// A small, isolated Chromium layout check. No OCR models or installed profile.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as sleep} from 'node:timers/promises';

const profile = await mkdtemp(join(tmpdir(), 'mokuro-overlay-'));
const browser = spawn(process.env.CHROMIUM || 'chromium-browser', [
  '--headless=new', '--no-sandbox', '--disable-gpu', '--no-first-run',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'
], {stdio: ['ignore', 'ignore', 'pipe']});
let socket;
try {
  const endpoint = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Chromium did not start')), 20000);
    let log = '';
    browser.stderr.on('data', chunk => {
      log += chunk;
      const match = log.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) { clearTimeout(timeout); resolve(match[1]); }
    });
    browser.on('error', reject);
    browser.on('exit', code => { clearTimeout(timeout); reject(new Error(`Chromium exited: ${code}\n${log}`)); });
  });
  const pending = new Map(); let sequence = 0;
  socket = new WebSocket(endpoint);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  socket.onmessage = event => {
    const value = JSON.parse(event.data), item = pending.get(value.id);
    if (!item) return;
    pending.delete(value.id);
    value.error ? item.reject(new Error(JSON.stringify(value.error))) : item.resolve(value.result);
  };
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++sequence; pending.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, method, params, sessionId}));
  });
  const target = (await send('Target.getTargets')).targetInfos.find(value => value.type === 'page');
  const {sessionId} = await send('Target.attachToTarget', {targetId: target.targetId, flatten: true});
  const page = (method, params) => send(method, params, sessionId);
  const evaluate = async expression => {
    const value = await page('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    if (value.exceptionDetails) throw new Error(JSON.stringify(value.exceptionDetails));
    return value.result.value;
  };
  await page('Emulation.setDeviceMetricsOverride', {width: 700, height: 600, deviceScaleFactor: 1, mobile: false});
  await evaluate(`document.body.innerHTML = '<style>body{margin:0;background:#eee}img{width:470px;height:568px}</style><img id="manga">';
    let fixtureId=0; crypto.randomUUID=()=> 'overlay-qa-'+(++fixtureId);
    window.chrome={storage:{local:{get:async defaults=>defaults},onChanged:{addListener:fn=>window.storageChanged=fn}},
      runtime:{onMessage:{addListener:fn=>window.receive=fn},sendMessage:async()=>({ok:true,data:{}})}};
    window.deliver=message=>new Promise(resolve=>receive(message,{},resolve));`);
  const fixture = process.env.MOKURO_OVERLAY_IMAGE;
  const source = fixture ? `data:image/png;base64,${(await readFile(fixture)).toString('base64')}`
    : 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="235" height="284"><rect width="235" height="284" fill="white"/></svg>');
  await evaluate(`new Promise(resolve=>{const img=document.querySelector('#manga');img.onload=resolve;img.src=${JSON.stringify(source)}})`);
  for (const file of ['ocr-result.js', 'content.js']) {
    await evaluate(await readFile(new URL(`../extension/${file}`, import.meta.url), 'utf8'));
  }
  const reply = await evaluate(`deliver({type:'LARGEST'})`);
  assert.equal(reply.kind, 'image');
  // Representative geometry for the reported bubble; no recognition changes.
  const result = {img_width: 235, img_height: 284, blocks: [{box: [72, 51, 209, 252],
    font_size: 29, vertical: true, lines: ['ハラルド王の', '死から', '１４年…'],
    lines_coords: [ [[178,54],[208,54],[208,251],[178,251]],
      [[123,52],[153,52],[153,149],[123,149]], [[73,53],[103,53],[103,149],[73,149]] ]}]};
  const rendered = await evaluate(`deliver(${JSON.stringify({type:'RENDER',target:reply,result})})`);
  assert(!rendered.error, JSON.stringify(rendered));
  assert.deepEqual(await evaluate(`MokuroResults.verticalParts('１４年…')`), ['１４', '年', '…']);
  assert.deepEqual(await evaluate(`MokuroResults.verticalParts('123年')`), ['1','2','3','年']);
  const orbOpacity = () => evaluate(`getComputedStyle(document.querySelector('.orb')).opacity`);
  assert.equal(await orbOpacity(), '0');
  await page('Input.dispatchMouseEvent', {type:'mouseMoved', x:160, y:130});
  await sleep(250);
  assert.equal(await orbOpacity(), '0.35');
  const metrics = await evaluate(`(()=>{
    const line=document.querySelectorAll('.line')[2], span=line.querySelector('.digits');
    const a=document.createRange(), b=document.createRange();
    a.setStart(span.firstChild,0);a.setEnd(span.firstChild,1);
    b.setStart(span.firstChild,1);b.setEnd(span.firstChild,2);
    const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();
    return {text:line.textContent,topDifference:Math.abs(x.top-y.top),leftDifference:Math.abs(x.left-y.left),
      surface:getComputedStyle(document.querySelector('.text-surface')).opacity,
      mask:getComputedStyle(document.querySelector('.text-surface'),'::before').right};
  })()`);
  assert.equal(metrics.text, '１４年…');
  assert(metrics.topDifference < 2 && metrics.leftDifference > 0, JSON.stringify(metrics));
  assert.equal(metrics.surface, '1');
  assert(parseFloat(metrics.mask) < -5);
  assert.equal(await evaluate(`document.elementFromPoint(220,180).id`), 'manga', 'gaps must pass page-turn clicks through');
  if (process.env.MOKURO_OVERLAY_SCREENSHOT) {
    const shot = await page('Page.captureScreenshot', {format:'png'});
    await writeFile(process.env.MOKURO_OVERLAY_SCREENSHOT, Buffer.from(shot.data,'base64'));
  }
  const measure = () => evaluate(`document.querySelector('.line').getBoundingClientRect().width`);
  const width = await measure();
  await evaluate(`storageChanged({hoverFontPercent:{newValue:150}},'local')`);
  assert(Math.abs(await measure() / width - 1.5) < .01);
  await evaluate(`storageChanged({hoverFontPercent:{newValue:50}},'local')`);
  await sleep(50);
  assert(Math.abs(await measure() / width - .5) < .01);
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.backdrop')).opacity`), '1');
  await page('Input.dispatchMouseEvent', {type:'mouseMoved', x:650, y:550});
  await sleep(250);
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.toolbar-actions')).visibility`), 'visible');
  await page('Input.dispatchMouseEvent', {type:'mouseMoved', x:500, y:300});
  await sleep(250);
  assert.equal(await orbOpacity(), '0');
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.toolbar-actions')).visibility`), 'hidden');
  await evaluate(`(()=>{const range=document.createRange();range.selectNodeContents(document.querySelector('.line'));
    const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range)})()`);
  await sleep(250);
  assert.equal(await orbOpacity(), '0.35', 'selecting OCR text reveals the orb');
  console.log('PASS: vertical paired digits, hover masks, live size changes, stable hover targets and contextual orb');
} finally {
  socket?.close();
  browser.kill();
  await new Promise(resolve=>browser.exitCode!==null?resolve():browser.once('exit',resolve));
  await rm(profile,{recursive:true,force:true});
}
