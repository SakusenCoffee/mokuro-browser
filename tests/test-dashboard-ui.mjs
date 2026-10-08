// Isolated Chromium check; no real archive, installed browser profile or OCR.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as sleep} from 'node:timers/promises';

const source = await readFile(new URL('../src/mokuro_browser/dashboard.py', import.meta.url), 'utf8');
const html = source.match(/DASHBOARD = """([\s\S]*?)"""/)[1];
const fixture = {totals:{characters:9, kanji:3, hiragana:2, katakana:4, pages:1},
  pages:[{id:'a', title:'Test manga page', characters:9, text:'日本語。\nかな カタカナ！'}]};
let offline = false;
const requests = [];
const app = createServer((request, response) => {
  requests.push(request.url);
  if (request.url === '/dashboard') {
    response.writeHead(200, {'Content-Type':'text/html; charset=utf-8'}).end(html);
  } else if (offline || request.headers.authorization !== 'Bearer test-token') {
    response.writeHead(401).end('{}');
  } else {
    response.writeHead(200, {'Content-Type':'application/json'}).end(JSON.stringify(
      request.url.startsWith('/history') ? fixture : {model:'ready', device:'CPU'}));
  }
});
await new Promise((resolve, reject) => {app.once('error', reject); app.listen(0, '127.0.0.1', resolve);});

const profile = await mkdtemp(join(tmpdir(), 'mokuro-dashboard-'));
const browser = spawn(process.env.CHROMIUM || 'chromium-browser', [
  '--headless=new', '--no-sandbox', '--disable-gpu', '--no-first-run',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'
], {stdio:['ignore', 'ignore', 'pipe']});
let socket;
try {
  const endpoint = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(Error('Chromium did not start')), 20000);
    let log = '';
    browser.stderr.on('data', chunk => {
      log += chunk;
      const match = log.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) {clearTimeout(timeout); resolve(match[1]);}
    });
    browser.on('error', reject);
    browser.on('exit', code => {clearTimeout(timeout); reject(Error(`Chromium exited: ${code}`));});
  });
  const pending = new Map();
  let sequence = 0;
  socket = new WebSocket(endpoint);
  await new Promise((resolve, reject) => {socket.onopen = resolve; socket.onerror = reject;});
  socket.onmessage = event => {
    const value = JSON.parse(event.data), item = pending.get(value.id);
    if (!item) return;
    pending.delete(value.id);
    value.error ? item.reject(Error(JSON.stringify(value.error))) : item.resolve(value.result);
  };
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, method, params, sessionId}));
  });
  const target = (await send('Target.getTargets')).targetInfos.find(item => item.type === 'page');
  const {sessionId} = await send('Target.attachToTarget', {targetId:target.targetId, flatten:true});
  const page = (method, params) => send(method, params, sessionId);
  const evaluate = async expression => {
    const result = await page('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true});
    if (result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  await page('Emulation.setDeviceMetricsOverride', {width:1200, height:900, deviceScaleFactor:1, mobile:false});
  await page('Page.navigate', {url:`http://127.0.0.1:${app.address().port}/dashboard#test-token`});
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await evaluate('typeof refresh === "function"')) break;
    await sleep(20);
  }
  await evaluate('refresh()');
  assert.equal(await evaluate(`document.querySelectorAll('article').length`), 1);
  assert.equal(await evaluate(`document.querySelector('article p').textContent`), '日本語。\nかな カタカナ！');
  assert.equal(await evaluate(`document.getElementById('hiragana').textContent`), '2');
  assert.equal(await evaluate(`document.getElementById('katakana').textContent`), '4');
  assert.equal(await evaluate(`document.getElementById('words')`), null);
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('article p')).whiteSpace`), 'pre-wrap');
  await writeFile('/tmp/mokuro-live-reader.png', Buffer.from((await page('Page.captureScreenshot', {format:'png'})).data, 'base64'));
  fixture.pages[0].text = '猫！\nネコ';
  fixture.pages[0].characters = 3;
  fixture.totals.characters = 3;
  await evaluate('refresh()');
  assert.equal(await evaluate(`document.querySelector('article p').textContent`), '猫！\nネコ', 'Edit must refresh with the same page ID');
  assert.equal(await evaluate(`document.getElementById('characters').textContent`), '3');
  fixture.pages = [];
  fixture.totals.pages = 0;
  await evaluate('refresh()');
  assert.equal(await evaluate(`document.querySelectorAll('article').length`), 0);
  assert.equal(await evaluate(`document.getElementById('pages').textContent`), '0');
  offline = true;
  await evaluate('refresh()');
  assert.match(await evaluate(`document.getElementById('status').textContent`), /Cannot reach/);
  assert(requests.includes('/dashboard'));
  assert(requests.every(url => !url.includes('test-token')), 'Fragment token must not be sent in request URLs');
  console.log('PASS: live reader page grouping, script counts, edits, deletions, authentication and offline message');
} finally {
  socket?.close();
  const exited = new Promise(resolve => browser.once('exit', resolve));
  if (browser.exitCode === null) {browser.kill(); await exited;}
  app.closeAllConnections();
  await new Promise(resolve => app.close(resolve));
  await rm(profile, {recursive:true, force:true});
}
