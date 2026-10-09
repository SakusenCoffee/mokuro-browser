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
  assert.equal(await evaluate(`document.querySelector('.orb')`), null);
  assert.equal(await evaluate(`document.querySelector('.toolbar')`), null);
  await page('Input.dispatchMouseEvent', {type:'mouseMoved', x:160, y:130});
  await sleep(350);
  const metrics = await evaluate(`(()=>{
    const line=document.querySelectorAll('.line')[2], span=line.querySelector('.digits');
    const a=document.createRange(), b=document.createRange();
    a.setStart(span.firstChild,0);a.setEnd(span.firstChild,1);
    b.setStart(span.firstChild,1);b.setEnd(span.firstChild,2);
    const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();
    return {text:line.textContent,topDifference:Math.abs(x.top-y.top),leftDifference:Math.abs(x.left-y.left),
      glyph:getComputedStyle(line).opacity,
      maskWidth:parseFloat(document.querySelector('.ink-mask').style.width)};
  })()`);
  assert.equal(metrics.text, '１４年…');
  assert(metrics.topDifference < 2 && metrics.leftDifference > 0, JSON.stringify(metrics));
  assert.equal(metrics.glyph, '1');
  assert(metrics.maskWidth > 30 && metrics.maskWidth < 60);
  assert.equal(await evaluate(`document.querySelectorAll('.backdrop').length`), 0);
  assert(await evaluate(`(()=>{
    const surface=document.querySelector('.text-surface').getBoundingClientRect();
    const lines=[...document.querySelectorAll('.line')].map(line=>line.getBoundingClientRect());
    for(let y=surface.top+1;y<surface.bottom;y+=2)for(let x=surface.left+1;x<surface.right;x+=2){
      if(!lines.some(line=>x>=line.left&&x<=line.right&&y>=line.top&&y<=line.bottom)
        &&document.elementFromPoint(x,y)?.id==='manga')return true;
    }
    return false;
  })()`),'background gaps must pass page-turn clicks through');
  if (process.env.MOKURO_OVERLAY_SCREENSHOT) {
    const shot = await page('Page.captureScreenshot', {format:'png'});
    await writeFile(process.env.MOKURO_OVERLAY_SCREENSHOT, Buffer.from(shot.data,'base64'));
  }
  const measure = () => evaluate(`document.querySelector('.line').getBoundingClientRect().width`);
  const width = await measure();
  const maskWidth = await evaluate(`document.querySelector('.ink-mask').getBoundingClientRect().width`);
  await evaluate(`storageChanged({hoverFontPercent:{newValue:150}},'local')`);
  assert(Math.abs(await measure() / width - 1.5) < .01);
  assert.equal(await evaluate(`document.querySelector('.ink-mask').getBoundingClientRect().width`), maskWidth);
  await evaluate(`storageChanged({hoverFontPercent:{newValue:50}},'local')`);
  await sleep(50);
  assert(Math.abs(await measure() / width - .5) < .01);
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.ink-mask')).opacity`), '1');
  const panelReply = await evaluate(`deliver({type:'SHOW_TEXT'})`);
  assert(!panelReply.error, JSON.stringify(panelReply));
  assert.equal(await evaluate(`document.querySelector('.panel pre').textContent`), result.blocks[0].lines.join('\n'));
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.panel')).backgroundColor`), 'rgba(8, 12, 18, 0.88)');
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.panel pre')).color`), 'rgb(237, 243, 251)');
  await evaluate(`deliver({type:'SHOW_TEXT'})`);
  assert.equal(await evaluate(`document.querySelector('.panel')`), null);
  await evaluate(`deliver({type:'SHOW_TEXT'});document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))`);
  assert.equal(await evaluate(`document.querySelector('.panel')`), null);
  // Mixed font sizes, a very narrow ellipsis, a wide region box and horizontal
  // lines: every glyph gets the page median while masks remain source-sized.
  const mixed = {img_width:235, img_height:284, blocks:[
    {box:[0,0,235,260],font_size:30,vertical:true,lines:['それじゃあ','……','瓜二つの','人間か…'],
      lines_coords:[[[180,20],[210,20],[210,170],[180,170]],[[160,20],[165,20],[165,100],[160,100]],
        [[125,20],[145,20],[145,120],[125,120]],[[95,20],[115,20],[115,120],[95,120]]]},
    {box:[10,185,90,275],font_size:15,vertical:true,lines:['小さい文字'],
      lines_coords:[[[55,190],[70,190],[70,273],[55,273]]]},
    {box:[100,190,230,270],font_size:40,vertical:false,lines:['大きい文字','次の行'],
      lines_coords:[[[105,190],[228,190],[228,230],[105,230]],[[105,235],[228,235],[228,265],[105,265]]]},
    {box:[0,0,10,100],font_size:3,vertical:true,lines:['……'],
      lines_coords:[[[1,1],[4,1],[4,99],[1,99]]]}]};
  await evaluate(`storageChanged({hoverFontPercent:{newValue:100}},'local')`);
  const mixedReply = await evaluate(`deliver(${JSON.stringify({type:'RENDER',target:reply,result:mixed})})`);
  assert(!mixedReply.error, JSON.stringify(mixedReply));
  assert.deepEqual(await evaluate(`[...new Set([...document.querySelectorAll('.line')].map(line=>line.style.fontSize))]`), ['30px']);
  assert.equal(await evaluate(`MokuroResults.pageFont(${JSON.stringify(mixed)})`),30);
  const evenlySpaced = await evaluate(`(()=>{
    return [...document.querySelectorAll('.text-surface')].every(surface=>{
      const lines=[...surface.querySelectorAll('.line')],rect=surface.getBoundingClientRect();
      const vertical=surface.classList.contains('vertical');
      const bounds=lines.map(line=>line.getBoundingClientRect()).sort((a,b)=>vertical?a.left-b.left:a.top-b.top);
      const expectedGap=parseFloat(getComputedStyle(surface).gap)*2;
      const spaced=bounds.slice(1).every((current,index)=>Math.abs((vertical?
        current.left-bounds[index].right:current.top-bounds[index].bottom)-expectedGap)<1);
      const fitted=bounds.every(line=>line.left>=rect.left&&line.top>=rect.top&&line.right<=rect.right+.1&&line.bottom<=rect.bottom+.1);
      return spaced&&fitted;
    });
  })()`);
  assert(evenlySpaced,'rows/columns need equal gaps and backgrounds must fit all glyphs');
  const mixedMasks = await evaluate(`[...document.querySelectorAll('.ink-mask')].map(mask=>[mask.style.width,mask.style.height])`);
  await evaluate(`storageChanged({hoverFontPercent:{newValue:150}},'local')`);
  assert.deepEqual(await evaluate(`[...new Set([...document.querySelectorAll('.line')].map(line=>line.style.fontSize))]`), ['45px']);
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('.ink-mask')].map(mask=>[mask.style.width,mask.style.height])`),mixedMasks);
  assert.equal(await evaluate(`(()=>{
    const blocks=[...document.querySelectorAll('.block')];
    return blocks.every(block=>getComputedStyle(block).backgroundColor==='rgba(0, 0, 0, 0)');
  })()`),true,'entire region boxes must never become white backdrops');
  if (process.env.MOKURO_BUBBLE_IMAGE) {
    const bubble = `data:image/png;base64,${(await readFile(process.env.MOKURO_BUBBLE_IMAGE)).toString('base64')}`;
    await evaluate(`new Promise(resolve=>{const img=document.querySelector('#manga');img.style.width='386px';img.style.height='415px';img.onload=resolve;img.src=${JSON.stringify(bubble)}})`);
    const target = await evaluate(`deliver({type:'LARGEST'})`);
    const bubbleResult={img_width:386,img_height:415,blocks:[{box:[78,42,285,398],font_size:34,vertical:true,
      lines:['それじゃあ','……','瓜二つの','人間か…'],lines_coords:[
        [[247,48],[280,48],[280,235],[247,235]],[[207,48],[222,48],[222,132],[207,132]],
        [[143,48],[176,48],[176,192],[143,192]],[[84,48],[117,48],[117,194],[84,194]]]}]};
    await evaluate(`storageChanged({hoverFontPercent:{newValue:100}},'local')`);
    const rendered=await evaluate(`deliver(${JSON.stringify({type:'RENDER',target,result:bubbleResult})})`);
    assert(!rendered.error,JSON.stringify(rendered));
    await evaluate(`document.querySelector('.layer').classList.add('pinned')`);
    const shot=await page('Page.captureScreenshot',{format:'png'});
    await writeFile('/tmp/mokuro-normalized-bubble.png',Buffer.from(shot.data,'base64'));
  }
  console.log('PASS: page-wide normalization, equal gaps, fitted backgrounds, paired digits and text panel');
} finally {
  socket?.close();
  browser.kill();
  await new Promise(resolve=>browser.exitCode!==null?resolve():browser.once('exit',resolve));
  await rm(profile,{recursive:true,force:true});
}
