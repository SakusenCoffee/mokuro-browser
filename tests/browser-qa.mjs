// Run against the isolated QA Chromium instance on port 9235.
import assert from "node:assert/strict";
import {createServer} from "node:http";
import {readFile, writeFile} from "node:fs/promises";
import {setTimeout as sleep} from "node:timers/promises";
import path from "node:path";
import os from "node:os";

class Cdp {
  constructor(url) {
    this.socket = new WebSocket(url); this.counter = 0; this.pending = new Map();
    this.opened = new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve); this.socket.addEventListener("error", reject);
    });
    this.socket.addEventListener("message", event => {
      const message = JSON.parse(event.data);
      const item = this.pending.get(message.id);
      if (!item) return;
      this.pending.delete(message.id);
      message.error ? item.reject(new Error(JSON.stringify(message.error))) : item.resolve(message.result);
    });
  }
  async send(method, params = {}) {
    await this.opened;
    const id = ++this.counter;
    const result = new Promise((resolve, reject) => this.pending.set(id, {resolve, reject}));
    this.socket.send(JSON.stringify({id, method, params}));
    return result;
  }
  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {expression: `(async()=>(${expression}))()`, awaitPromise: true, returnByValue: true});
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
  close() { this.socket.close(); }
}

if (process.argv.includes("--close-browser")) {
  const version = await (await fetch("http://127.0.0.1:9235/json/version")).json();
  const browser = new Cdp(version.webSocketDebuggerUrl);
  await browser.send("Browser.close");
  browser.close();
  process.exit(0);
}

assert(process.env.MOKURO_QA_IMAGE && process.env.YOMITAN_ROOT && process.env.MOKURO_QA_TOKEN_FILE,
  "Set MOKURO_QA_IMAGE (Centuria vol. 3 page 005), YOMITAN_ROOT and MOKURO_QA_TOKEN_FILE for private local QA.");
const image = await readFile(process.env.MOKURO_QA_IMAGE);
// Read the user's installed scanner code without touching its profile/settings.
const yomitanRoot = process.env.YOMITAN_ROOT;
const site = createServer(async (request, response) => {
  const pathname = new URL(request.url, "http://localhost").pathname;
  if (pathname.startsWith("/yomitan/js/")) {
    const filename = path.resolve(yomitanRoot, pathname.slice("/yomitan/".length));
    if (!filename.startsWith(`${path.resolve(yomitanRoot)}/js/`)) { response.writeHead(403); response.end(); return; }
    try { response.writeHead(200, {"Content-Type": "text/javascript"}); response.end(await readFile(filename)); }
    catch { response.end("throw new Error('Yomitan scanner fixture missing')"); }
  } else if (pathname === "/page.jpg" || pathname === "/photo.jpg") {
    response.writeHead(200, {"Content-Type": "image/jpeg"}); response.end(image);
  } else {
    response.writeHead(200, {"Content-Type": "text/html"});
    const photos = pathname === "/photos";
    response.end(`<!doctype html><meta charset="utf-8"><title>${photos ? "Landscape photographs" : "Manga reader: Centuria chapter 1"}</title><style>body{margin:0;background:#dfded9}img{display:block;width:720px;margin:20px auto}p{font-size:99px;color:red;pointer-events:none}</style><img id="${photos ? "photo" : "manga"}" src="${photos ? "/photo.jpg" : pathname.includes("chapter-") ? `/page.jpg?${pathname.split("/").pop()}` : "/page.jpg"}">`);
  }
});
await new Promise(resolve => site.listen(0, "127.0.0.1", resolve));
const port = site.address().port;
const targets = await (await fetch("http://127.0.0.1:9235/json/list")).json();
const workerTarget = targets.find(target => target.type === "service_worker" && target.url.endsWith("/background.js"));
assert(workerTarget, "The real extension must be loaded");
const worker = new Cdp(workerTarget.webSocketDebuggerUrl);
const tab = targets.find(target => target.type === "page" && !target.url.startsWith("chrome-extension:"));
assert(tab, "QA needs a regular page tab");
const page = new Cdp(tab.webSocketDebuggerUrl);
const version = await (await fetch("http://127.0.0.1:9235/json/version")).json();
const browser = new Cdp(version.webSocketDebuggerUrl);

async function inspect(fn) {
  const handle = await page.send("Runtime.evaluate", {expression: "document.querySelector('#local-mokuro-overlay')"});
  const objectId = handle.result.objectId;
  if (!objectId) return null;
  const result = await page.send("Runtime.callFunctionOn", {objectId, functionDeclaration: fn, returnByValue: true, awaitPromise: true});
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function waitFor(check, label, milliseconds = 120000) {
  const deadline = Date.now() + milliseconds;
  while (Date.now() < deadline) { if (await check()) return; await sleep(500); }
  throw new Error(`Timeout: ${label}`);
}

try {
  const token = (await readFile(process.env.MOKURO_QA_TOKEN_FILE, "utf8")).trim();
  await worker.evaluate(`launch({type:'PAIR',token:${JSON.stringify(token)}}, {})`);
  const health = await worker.evaluate("api('/health')");
  assert.equal(health.ocr_backend, "bundled");
  assert.equal(await worker.evaluate("typeof getPageResult"), "function", "Start QA with a fresh browser profile so Chromium loads the updated worker");
  await worker.evaluate("chrome.storage.local.set({autoScan:false})");
  await page.send("Page.navigate", {url: `http://127.0.0.1:${port}/`});
  await waitFor(() => page.evaluate("document.querySelector('#manga')?.naturalWidth > 0"), "image load");
  const tabId = await worker.evaluate(`(await chrome.tabs.query({})).find(tab=>tab.url==='http://127.0.0.1:${port}/').id`);
  await worker.evaluate(`launch({type:'SCAN_LARGEST',tabId:${tabId}}, {})`);
  await waitFor(() => inspect("function(){return this.querySelectorAll('.line').length>0}"), "real image OCR and overlay");
  const text = await inspect("function(){return [...this.querySelectorAll('.line')].map(x=>x.textContent)}");
  for (const ending of ["活な少女。", "の存在。", "有する。"]) assert(text.includes(ending), `Recovered ending: ${ending}`);
  const initial = await inspect("function(){return {left:parseFloat(this.querySelector('.layer').style.left),width:parseFloat(this.querySelector('.layer').style.width)}}");
  assert.equal(initial.width, 720);
  const normalized = await inspect(`function(){
    return new Set([...this.querySelectorAll('.line')].map(line=>line.style.fontSize)).size===1;
  }`);
  assert(normalized, 'All text regions use the same page-wide base font before resizing');
  await page.evaluate("document.querySelector('#manga').style.width='560px'");
  await waitFor(async () => (await inspect("function(){return parseFloat(this.querySelector('.layer').style.width)}")) === 560, "responsive overlay");
  await inspect("function(){this.querySelector('.layer').classList.add('pinned');return true}");
  assert.equal(await inspect("function(){return this.querySelector('.layer').classList.contains('pinned')}"), true);
  // Exercise the actual installed Yomitan caret scanner against ordinary DOM
  // OCR text. No dictionaries or production profile writes are required.
  const scanned = await page.evaluate(`(async()=>{
    const {TextSourceGenerator}=await import('/yomitan/js/dom/text-source-generator.js');
    window.qaScanner=new TextSourceGenerator();
    const line=[...document.querySelectorAll('#local-mokuro-overlay .line')].find(line=>{
      const r=line.getBoundingClientRect();return r.top>0&&r.bottom<innerHeight;
    });
    const range=document.createRange();range.setStart(line.firstChild,0);range.setEnd(line.firstChild,1);
    const rect=range.getBoundingClientRect();
    const source=qaScanner.getRangeFromPoint(rect.x+rect.width/2,rect.y+rect.height/2,
      {deepContentScan:false,normalizeCssZoom:true,language:'ja',browser:'chrome'});
    if(!source)return null;
    source.setEndOffset(12);return {text:source.text(),expected:line.textContent,
      x:rect.x+rect.width/2,y:rect.y+rect.height/2};
  })()`);
  assert(scanned?.text && scanned.text.startsWith(scanned.expected.slice(0, 1)), `Yomitan extracts OCR text from a screen coordinate: ${JSON.stringify(scanned)}`);
  await inspect("function(){this.querySelector('.layer').classList.remove('pinned');return true}");
  await page.send("Input.dispatchMouseEvent", {type: "mouseMoved", x: scanned.x, y: scanned.y});
  const hoverScan = await page.evaluate(`(()=>{
    const source=qaScanner.getRangeFromPoint(${scanned.x},${scanned.y},
      {deepContentScan:false,normalizeCssZoom:true,language:'ja',browser:'chrome'});
    if(!source)return null;source.setEndOffset(12);return source.text();
  })()`);
  assert.equal(hoverScan?.trim(), scanned.text.trim(), "Yomitan can also scan unpinned hover text");
  // Full-image wrappers and paragraph gaps must pass clicks through to the
  // reader. Invisible per-line hit areas still reveal text for Yomitan.
  const clickAreas = await page.evaluate(`(()=>{
    const root=document.querySelector('#local-mokuro-overlay'),image=document.querySelector('#manga');
    const lines=[...root.querySelectorAll('.line')].map(line=>line.getBoundingClientRect());
    const insideLine=(x,y)=>lines.some(r=>x>=r.left&&x<=r.right&&y>=r.top&&y<=r.bottom);
    function blank(rect){
      for(let y=Math.max(1,rect.top+1);y<Math.min(innerHeight-1,rect.bottom-1);y+=2)
        for(let x=Math.max(1,rect.left+1);x<Math.min(innerWidth-1,rect.right-1);x+=2)
          if(!insideLine(x,y)&&document.elementFromPoint(x,y)===image)return {x,y};
      return null;
    }
    window.qaPageTurns=0;
    image.addEventListener('click',()=>qaPageTurns++);
    return {page:blank(image.getBoundingClientRect()),
      gap:[...root.querySelectorAll('.block')].map(block=>blank(block.getBoundingClientRect())).find(Boolean),
      borderless:[...root.querySelectorAll('.block,.line')].every(node=>{
        const css=getComputedStyle(node);return css.outlineStyle==='none'&&css.borderTopStyle==='none';
      })};
  })()`);
  assert(clickAreas.page, "image artwork outside text is clickable");
  assert(clickAreas.gap, "gaps inside paragraph boxes are clickable");
  assert(clickAreas.borderless, "OCR text has no borders or outlines");
  for (const point of [clickAreas.page, clickAreas.gap]) {
    await page.send("Input.dispatchMouseEvent", {type:"mouseMoved", ...point});
    await page.send("Input.dispatchMouseEvent", {type:"mousePressed", button:"left", clickCount:1, ...point});
    await page.send("Input.dispatchMouseEvent", {type:"mouseReleased", button:"left", clickCount:1, ...point});
  }
  assert.equal(await page.evaluate("qaPageTurns"), 2, "real clicks reach the reader's page-turn handler");
  await worker.evaluate(`tell(${tabId},'SHOW_TEXT')`);
  assert((await inspect("function(){return this.querySelector('.panel pre').textContent}")).includes("活な少女。"));
  await worker.evaluate(`tell(${tabId},'SHOW_TEXT')`);
  const screenshot = await page.send("Page.captureScreenshot", {format: "png"});
  await writeFile(path.join(os.tmpdir(), "mokuro-browser-extension-qa.png"), Buffer.from(screenshot.data, "base64"));
  await worker.evaluate(`launch({type:'CLEAR',tabId:${tabId}}, {})`);
  assert.equal(await inspect("function(){return this.querySelectorAll('.layer').length}"), 0);

  // Grant activeTab via the real toolbar action, then use the actual popup.
  const tabTargets = await browser.send("Target.getTargets", {filter: [{type: "tab", exclude: false}]});
  const actionTab = tabTargets.targetInfos.find(target => target.url === `http://127.0.0.1:${port}/`);
  assert(actionTab, "Browser exposes the toolbar's tab target");
  await browser.send("Extensions.triggerAction", {id: new URL(workerTarget.url).host, targetId: actionTab.targetId});
  await waitFor(async () => (await (await fetch("http://127.0.0.1:9235/json/list")).json()).some(t => t.url.endsWith("/popup.html")), "extension toolbar popup");
  const popupTarget = (await (await fetch("http://127.0.0.1:9235/json/list")).json()).find(t => t.url.endsWith("/popup.html"));
  const popup = new Cdp(popupTarget.webSocketDebuggerUrl);
  await waitFor(() => popup.evaluate("document.querySelector('#status')?.textContent.includes('server ready')"), "popup authenticated health");
  await popup.evaluate("document.querySelector('#visible').click()");
  popup.close();
  await waitFor(() => inspect("function(){return this.querySelectorAll('.line').length>0}"), "visible-tab screenshot OCR");
  assert.equal(await inspect("function(){return parseFloat(this.querySelector('.layer').style.width)}"), await page.evaluate("innerWidth"));
  await worker.evaluate(`launch({type:'CLEAR',tabId:${tabId}}, {})`);

  // Verify the page-owned blob: URL transfer fallback, using the same image.
  await page.evaluate("(async()=>{const image=document.querySelector('#manga');const bytes=await (await fetch('/page.jpg')).blob();image.src=URL.createObjectURL(bytes)})()");
  await waitFor(() => page.evaluate("document.querySelector('#manga').src.startsWith('blob:') && document.querySelector('#manga').naturalWidth>0"), "blob image load");
  await worker.evaluate(`launch({type:'SCAN_LARGEST',tabId:${tabId}}, {})`);
  await waitFor(() => inspect("function(){return this.querySelectorAll('.line').length>0}"), "blob image OCR");
  assert((await inspect("function(){return [...this.querySelectorAll('.line')].map(x=>x.textContent)}")).includes("活な少女。"));

  // A late result must never be attached to a replaced image.
  const target = await worker.evaluate(`tell(${tabId},'LARGEST')`);
  await page.evaluate("document.querySelector('#manga').src='/page.jpg?changed'");
  const stale = await worker.evaluate(`tell(${tabId},'RENDER',{target:${JSON.stringify(target)},result:{img_width:1,img_height:1,blocks:[]}})`);
  assert.match(stale.error, /changed/);

  // Count actual uploads and exercise the saved toggle through the real popup.
  await worker.evaluate("(()=>{const original=api;globalThis.qaUploads=0;api=async(...args)=>{if(args[0].split('?')[0]==='/jobs')qaUploads++;return original(...args)}})()");
  await browser.send("Extensions.triggerAction", {id: new URL(workerTarget.url).host, targetId: actionTab.targetId});
  await waitFor(async () => (await (await fetch("http://127.0.0.1:9235/json/list")).json()).some(t => t.url.endsWith("/popup.html")), "auto-scan popup");
  const autoPopupTarget = (await (await fetch("http://127.0.0.1:9235/json/list")).json()).find(t => t.url.endsWith("/popup.html"));
  const autoPopup = new Cdp(autoPopupTarget.webSocketDebuggerUrl);
  await waitFor(() => autoPopup.evaluate("document.querySelector('#auto')?.disabled===false"), "toggle loads saved preference");
  assert.equal(await autoPopup.evaluate("document.querySelector('#auto').getAttribute('aria-pressed')"), "false");
  await autoPopup.evaluate("document.querySelector('#auto').click()");
  await waitFor(() => autoPopup.evaluate("document.querySelector('#auto').getAttribute('aria-pressed')==='true'"), "auto-scan toggled on");
  await autoPopup.evaluate("window.close()"); autoPopup.close();
  await waitFor(() => worker.evaluate(`!busy.has(${tabId})`), "previous page's scan finishes");
  await page.send("Page.navigate", {url: `http://127.0.0.1:${port}/photos`});
  await waitFor(() => page.evaluate("document.querySelector('#photo')?.naturalWidth>0"), "unrelated large image loads");
  const before = await worker.evaluate("qaUploads");
  await sleep(3500);
  assert.equal(await worker.evaluate("qaUploads"), before, "unrelated photos are not auto-scanned");
  assert.equal(await inspect("function(){return this.querySelectorAll('.layer').length}"), 0);
  await page.send("Page.navigate", {url: `http://127.0.0.1:${port}/reader/chapter-1`});
  await waitFor(() => inspect("function(){return this.querySelectorAll('.line').length>0}"), "automatic manga OCR after navigation");
  assert.equal(await worker.evaluate("qaUploads"), before + 1);
  await waitFor(() => worker.evaluate(`!busy.has(${tabId})`), "auto job finishes");
  await page.evaluate("document.querySelector('#manga').src='/page.jpg?next-page'");
  await waitFor(async () => await worker.evaluate("qaUploads") === before + 2 && await worker.evaluate(`!busy.has(${tabId})`), "automatic next-image OCR");
  await page.evaluate("(()=>{window.dispatchEvent(new Event('scroll'));window.dispatchEvent(new Event('resize'))})()");
  await sleep(3500);
  assert.equal(await worker.evaluate("qaUploads"), before + 2, "unchanged image is not scanned repeatedly");
  await worker.evaluate(`launch({type:'CLEAR',tabId:${tabId}}, {})`);
  await sleep(2500);
  assert.equal(await worker.evaluate("qaUploads"), before + 2, "Clear does not immediately re-scan the same page");
  assert.equal(await inspect("function(){return this.querySelectorAll('.layer').length}"), 0);

  // Change pages while the earlier result is pending. The newest visible page
  // must eventually scan instead of being dropped because the tab was busy.
  await worker.evaluate("(()=>{const original=api;api=async(...args)=>{if(args[0].startsWith('/jobs/'))await pause(1800);return original(...args)}})()");
  await page.evaluate("document.querySelector('#manga').src='/page.jpg?turn-1'");
  await waitFor(async () => await worker.evaluate("qaUploads") === before + 3, "scan starts before second page turn");
  await page.evaluate("document.querySelector('#manga').src='/page.jpg?turn-2'");
  await waitFor(async () => await worker.evaluate("qaUploads") === before + 4 && await worker.evaluate(`!busy.has(${tabId})`), "latest page scans after pending result");
  assert((await inspect("function(){return [...this.querySelectorAll('.line')].map(x=>x.textContent)}")).includes("活な少女。"));
  await worker.evaluate(`launch({type:'SET_AUTO',enabled:false,tabId:${tabId}}, {})`);
  await page.evaluate("document.querySelector('#manga').src='/page.jpg?auto-off'");
  await sleep(2500);
  assert.equal(await worker.evaluate("qaUploads"), before + 4, "toggle off stops automatic uploads");
  assert.equal(await worker.evaluate("(await chrome.storage.local.get('autoScan')).autoScan"), false);

  const completePage = id => worker.evaluate(`(async()=>{
    const target=await tell(${id},'LARGEST').catch(()=>({error:true}));if(target.error)return false;
    const saved=await getPageResult(${id},target);
    return !!saved.result&&(await tell(${id},'VERIFY_OVERLAY',{target,result:saved.result})).complete;
  })()`);
  const cachedUploads = await worker.evaluate("qaUploads");
  // Returning rapidly to earlier pages restores OCR, even with auto-scan off.
  for (const source of ["/page.jpg?turn-1", "/page.jpg?turn-2", "/page.jpg?chapter-1", "/page.jpg?turn-1"]) {
    await page.evaluate(`document.querySelector('#manga').src=${JSON.stringify(source)}`);
    await sleep(150);
  }
  await waitFor(() => completePage(tabId), "rapid page-return restores completed OCR");
  assert.equal(await worker.evaluate("qaUploads"), cachedUploads, "returning to saved pages does not upload or OCR again");
  const savedRows = await inspect("function(){return this.querySelectorAll('.line').length}");
  await inspect("function(){this.querySelector('.line').remove();return true}");
  await waitFor(async () => await inspect("function(){return this.querySelectorAll('.line').length}") === savedRows, "automatic repair of a missing overlay row");
  assert.equal(await worker.evaluate("qaUploads"), cachedUploads);

  // Full document navigation creates a new content script but keeps this
  // tab's cached results. Cache corruption must trigger genuine fresh OCR.
  await page.send("Page.navigate", {url:`http://127.0.0.1:${port}/reader/chapter-1`});
  await waitFor(() => completePage(tabId), "cache survives document navigation");
  assert.equal(await worker.evaluate("qaUploads"), cachedUploads);
  const pageTarget = await worker.evaluate(`tell(${tabId},'LARGEST')`);
  await worker.evaluate(`cacheTransaction('readwrite',store=>{
    const request=store.get([${tabId},MokuroResults.key(${JSON.stringify(pageTarget)})]);
    request.onsuccess=()=>{const record=request.result;record.result.blocks.pop();store.put(record)};
  })`);
  const repaired = await worker.evaluate(`launch({type:'CHECK_PAGE',tabId:${tabId}}, {})`);
  assert.equal(repaired.started, true, "invalid cache triggers OCR instead of restoring truncated data");
  await waitFor(async () => await completePage(tabId) && await worker.evaluate(`!busy.has(${tabId})`), "incomplete cached page rescanned");
  assert.equal(await worker.evaluate("qaUploads"), cachedUploads + 1);
  const intactCheck = await worker.evaluate(`launch({type:'CHECK_PAGE',tabId:${tabId}}, {})`);
  assert.equal(intactCheck.complete, true);
  assert.equal(await worker.evaluate("qaUploads"), cachedUploads + 1, "Check on intact OCR does not rescan");

  // Each tab gets its own records, and closing one deletes just those records.
  const secondTab = await worker.evaluate(`chrome.tabs.create({url:'http://127.0.0.1:${port}/reader/chapter-2',active:true})`);
  await waitFor(async () => (await worker.evaluate(`tell(${secondTab.id},'LARGEST').catch(()=>({error:true}))`)).src?.includes('chapter-2'), "second reader tab loads");
  await worker.evaluate(`launch({type:'CHECK_PAGE',tabId:${secondTab.id}}, {})`);
  await waitFor(() => completePage(secondTab.id), "second tab independently caches and renders OCR");
  const counts = await worker.evaluate(`cacheTransaction('readonly',(store,done)=>{
    const request=store.getAll();request.onsuccess=()=>done(request.result.map(record=>record.tabId));
  })`);
  assert(counts.includes(tabId) && counts.includes(secondTab.id), "both tabs retain their page data");
  const secondTarget = await worker.evaluate(`tell(${secondTab.id},'LARGEST')`);
  const secondSaved = await worker.evaluate(`getPageResult(${secondTab.id},${JSON.stringify(secondTarget)})`);
  await worker.evaluate(`chrome.tabs.remove(${secondTab.id})`);
  await waitFor(async () => {
    const ids = await worker.evaluate("cacheTransaction('readonly',(store,done)=>{const r=store.getAll();r.onsuccess=()=>done(r.result.map(x=>x.tabId))})");
    return !ids.includes(secondTab.id) && ids.includes(tabId);
  }, "closing a tab removes only its cache");
  await worker.evaluate(`savePageResult(${secondTab.id},${JSON.stringify(secondTarget)},${JSON.stringify(secondSaved.result)})`);
  assert.equal((await worker.evaluate(`getPageResult(${secondTab.id},${JSON.stringify(secondTarget)})`)).result, undefined, "late completion cannot recreate a closed tab's cache");
  console.log("PASS: real extension -> authenticated local server -> patched GPU OCR -> selectable text overlay");
  console.log("PASS: short paragraph endings, image resize, pinned text, transcript, clear, real popup, visible-tab scan, blob transfer, stale-image rejection");
  console.log("PASS: installed Yomitan scanner on pinned and hover text; auto toggle, manga navigation, page replacement, deduplication, photo exclusion, toggle off");
  console.log("PASS: real page-turn clicks through image and paragraph gaps, borderless OCR text");
  console.log("PASS: rapid cached page returns, partial overlay repair, full navigation, corrupt-cache rescan, integrity check, independent tab caches and closure cleanup");
  console.log(`Screenshot: ${path.join(os.tmpdir(), "mokuro-browser-extension-qa.png")}`);
} finally {
  // This script owns only the isolated QA profile. Closing it also ends any
  // debug sockets belonging to the popup that closed itself after a scan.
  await browser.send("Browser.close").catch(() => {});
  page.close(); worker.close(); browser.close(); site.close(); site.closeAllConnections();
}
