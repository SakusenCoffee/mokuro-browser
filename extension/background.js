// Chrome uses this file as an MV3 service worker. Firefox uses it as the last
// script in an MV3 background page, where importScripts does not exist.
if (typeof importScripts === "function") importScripts("ocr-result.js", "page-cache.js", "reading-history.js");
const SERVER_URL = "http://127.0.0.1:8766";
const NATIVE_HOST = "com.sakusencoffee.mokuro_browser";
const busy = new Set();
const generations = new Map();
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function nativePair() {
  const result = await chrome.runtime.sendNativeMessage(NATIVE_HOST, {action: "pair"});
  const token = result?.pairing_code;
  if (!result?.ok || !/^[A-Za-z0-9_-]{32,128}$/.test(token || "")) {
    throw new Error("Automatic pairing is unavailable. Copy the code from the Mokuro Browser window.");
  }
  return token;
}

async function api(path, options = {}, pairingCode) {
  let token = pairingCode || (await chrome.storage.local.get("pairingToken")).pairingToken;
  if (!token) token = await nativePair();
  const request = async value => {
    try {
      return await fetch(SERVER_URL + path, {
        ...options, headers: {...options.headers, Authorization: `Bearer ${value}`},
        signal: AbortSignal.timeout(25000)
      });
    } catch { throw new Error("Mokuro Browser server is off. Open the Mokuro Browser app."); }
  };
  let response = await request(token);
  if (response.status === 401 && !pairingCode) {
    token = await nativePair();
    response = await request(token);
  }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Server error ${response.status}`);
  if (!pairingCode && (await chrome.storage.local.get("pairingToken")).pairingToken !== token) {
    await chrome.storage.local.set({pairingToken: token});
  }
  return result;
}

async function inject(tabId) {
  try {
    await chrome.scripting.executeScript({target: {tabId}, files: ["ocr-result.js", "content.js"]});
  } catch { throw new Error("Open a normal manga webpage first. Browser settings and store pages cannot be scanned."); }
}

async function tell(tabId, type, data = {}) {
  return chrome.tabs.sendMessage(tabId, {type, ...data});
}

async function imageBytes(tabId, target) {
  // blob: URLs belong to the page, so read those in its content-script context.
  if (target.src.startsWith("blob:") || target.src.startsWith("data:")) {
    const reply = await tell(tabId, "READ_IMAGE", {target});
    if (reply.error) throw new Error(reply.error);
    return (await fetch(reply.data)).blob();
  }
  if (!/^https?:/.test(target.src)) throw new Error("Use Scan visible tab area for this image type.");
  const response = await fetch(target.src, {credentials: "include", signal: AbortSignal.timeout(20000)});
  if (!response.ok) throw new Error(`Image download returned ${response.status}. Try Scan visible tab area.`);
  const blob = await response.blob();
  if (blob.size > 32 * 1024 * 1024) throw new Error("Image exceeds the 32 MB upload limit.");
  return blob;
}

async function performScan(tabId, target, bytes, force = false) {
  if (busy.has(tabId)) throw new Error("A scan is already running in this tab.");
  busy.add(tabId);
  const generation = generations.get(tabId) || 0;
  let completed = false;
  let failed = false;
  try {
    await chrome.action.setBadgeText({tabId, text: "…"});
    await chrome.action.setBadgeBackgroundColor({tabId, color: "#225c50"});
    await tell(tabId, "NOTICE", {text: "Sending image to local Mokuro…", pageKey: target.pageKey});
    const image = bytes || await imageBytes(tabId, target);
    const job = await api(force ? "/jobs?rescan=1" : "/jobs", {method: "POST", body: image});
    for (let attempt = 0; attempt < 300; attempt++) {
      if ((generations.get(tabId) || 0) !== generation) return;
      const progress = await api(`/jobs/${job.id}`);
      if (progress.status === "error") throw new Error(progress.error);
      if (progress.status === "complete") {
        if (!MokuroResults.valid(progress.result)) throw new Error("Incomplete OCR result. Check the page again to retry.");
        await savePageResult(tabId, target, progress.result);
        await queueReadingPage(tabId, target, progress.result, progress.page_id);
        completed = true;
        if ((generations.get(tabId) || 0) !== generation) return;
        const reply = await tell(tabId, "RENDER", {target, result: progress.result});
        if (reply?.error) throw new Error(reply.error);
        await chrome.action.setBadgeText({tabId, text: String(progress.result.blocks.length)});
        return;
      }
      // Extension API calls and short job polls keep the service worker alive;
      // a long-running OCR fetch could exceed Chromium's fetch lifetime limit.
      await chrome.runtime.getPlatformInfo();
      await tell(tabId, "NOTICE", {text: progress.status === "queued" ? "Waiting for local Mokuro…" : "Scanning locally…", pageKey: target.pageKey}).catch(() => {});
      await pause(1000);
    }
    throw new Error("Scan timed out. Check the local server log and try again.");
  } catch (error) {
    failed = !completed;
    await chrome.action.setBadgeText({tabId, text: "!"}).catch(() => {});
    await tell(tabId, "NOTICE", {text: error.message, error: true, pageKey: target.pageKey}).catch(() => {});
  } finally {
    busy.delete(tabId);
    await tell(tabId, "SCAN_FINISHED", {pageKey: target.pageKey, target, failed}).catch(() => {});
  }
}

async function checkPage(tabId, target, scan = true) {
  const cached = await getPageResult(tabId, target);
  if (cached.result) {
    // Older extensions cached pages before the reading archive existed.
    await queueReadingPage(tabId, target, cached.result);
    const checked = await tell(tabId, "VERIFY_OVERLAY", {target, result: cached.result});
    if (!checked.complete) {
      const restored = await tell(tabId, "RENDER", {target, result: cached.result});
      if (restored?.error) return {started: false}; // Image changed again; check the newest page.
    }
    return {restored: true, complete: true};
  }
  if (!scan) return {missing: true};
  if (busy.has(tabId)) return {started: false};
  void performScan(tabId, target, undefined, cached.invalid === true).catch(() => {});
  return {started: true};
}

async function launch(message, sender) {
  if (message.type === "SERVER_STATUS" || message.type === "SERVER_CONTROL") {
    if (sender.tab) throw new Error("Control the server from the extension popup.");
    const action = message.type === "SERVER_STATUS" ? "status" : message.action;
    if (!["status", "start", "stop"].includes(action)) throw new Error("Unsupported local server action.");
    try {
      const result = await chrome.runtime.sendNativeMessage(NATIVE_HOST, {action});
      if (!result?.ok) throw new Error(result?.error || "The local server control did not respond.");
      return result;
    } catch (error) {
      throw new Error("Local server control is unavailable. Run Mokuro Browser again, then reload the extension. " + error.message);
    }
  }
  if (message.type === "AUTO_PAIR") {
    if (sender.tab) throw new Error("Pair from the extension popup.");
    const token = await nativePair();
    const health = await api("/health", {}, token);
    await chrome.storage.local.set({pairingToken: token});
    return health;
  }
  if (message.type === "PAIR") {
    if (sender.tab) throw new Error("Pair from the extension popup.");
    const token = String(message.token || "").trim();
    if (!/^[A-Za-z0-9_-]{32,128}$/.test(token)) throw new Error("Paste the complete pairing code from mokuro-browser setup.");
    const health = await api("/health", {}, token);
    await chrome.storage.local.set({pairingToken: token});
    return health;
  }
  if (message.type === "HEALTH") {
    const health = await api("/health");
    void flushReadingLog();
    return health;
  }
  const tabId = sender.tab?.id ?? message.tabId;
  if (tabId === undefined) throw new Error("No active tab.");
  if (message.type === "SET_AUTO") {
    await chrome.storage.local.set({autoScan: message.enabled === true});
    // Existing tabs may predate the newly installed content script.
    await inject(tabId).catch(() => {});
    return {};
  }
  if (message.type === "AUTO_SCAN" || message.type === "CHECK_CACHE") {
    if (!sender.tab) throw new Error("Auto-scan must originate in a manga tab.");
    const settings = await chrome.storage.local.get({autoScan: false});
    const tab = await chrome.tabs.get(tabId);
    if (!tab.active || (message.type === "AUTO_SCAN" && !settings.autoScan)) return {started: false};
    return checkPage(tabId, message.target, message.type === "AUTO_SCAN");
  }
  if (message.type === "CANCEL") {
    generations.set(tabId, (generations.get(tabId) || 0) + 1);
    await chrome.action.setBadgeText({tabId, text: ""});
    return {};
  }
  if (["SCAN_IMAGE", "SCAN_LARGEST", "SCAN_VISIBLE"].includes(message.type) && busy.has(tabId)) {
    throw new Error("A scan is already running in this tab. Clear it first to cancel.");
  }
  if (message.type === "SCAN_IMAGE") {
    if (!sender.tab) throw new Error("Choose an image in a tab first.");
    void performScan(tabId, message.target, undefined, true).catch(() => {});
    return {};
  }
  await inject(tabId);
  if (message.type === "CLEAR") {
    generations.set(tabId, (generations.get(tabId) || 0) + 1);
    await tell(tabId, "CLEAR");
    await chrome.action.setBadgeText({tabId, text: ""});
  } else if (message.type === "CHECK_PAGE") {
    const target = await tell(tabId, "LARGEST");
    if (target.error) throw new Error(target.error);
    const checked = await checkPage(tabId, target);
    await tell(tabId, "CHECK_STATUS", {target, checked});
    return checked;
  } else if (message.type === "PICK_IMAGE") {
    const reply = await tell(tabId, "PICK_IMAGE");
    if (reply?.error) throw new Error(reply.error);
  } else if (message.type === "SHOW_TEXT") {
    const reply = await tell(tabId, "SHOW_TEXT");
    if (reply?.error) throw new Error(reply.error);
  } else if (message.type === "SCAN_LARGEST") {
    const target = await tell(tabId, "LARGEST");
    if (target.error) throw new Error(target.error);
    void performScan(tabId, target, undefined, true).catch(() => {});
  } else if (message.type === "SCAN_VISIBLE") {
    const tab = await chrome.tabs.get(tabId);
    if (!tab.active) throw new Error("Keep the manga tab active while capturing it.");
    const target = await tell(tabId, "VIEWPORT");
    const screenshot = await chrome.tabs.captureVisibleTab(tab.windowId, {format: "png"});
    void performScan(tabId, target, await (await fetch(screenshot)).blob()).catch(() => {});
  } else { throw new Error("Unknown action."); }
  return {};
}

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  launch(message, sender).then(data => reply({ok: true, data}), error => reply({ok: false, error: error.message}));
  return true;
});
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({id: "mokuro-image", title: "Scan image with Mokuro Browser", contexts: ["image"]});
  });
});
chrome.tabs.onActivated.addListener(async ({tabId}) => {
  const settings = await chrome.storage.local.get({autoScan: false});
  if (settings.autoScan) await inject(tabId).catch(() => {});
});
chrome.tabs.onRemoved.addListener(tabId => {
  generations.delete(tabId);
});
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "mokuro-image") return;
  try {
    await inject(tab.id);
    const target = await tell(tab.id, "FIND_IMAGE", {src: info.srcUrl});
    if (target.error) throw new Error(target.error);
    void performScan(tab.id, target).catch(() => {});
  } catch (error) { await tell(tab.id, "NOTICE", {text: error.message, error: true}).catch(() => {}); }
});
chrome.commands.onCommand.addListener(async command => {
  if (command !== "scan-largest") return;
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  launch({type: "SCAN_LARGEST", tabId: tab.id}, {}).catch(async error => {
    await tell(tab.id, "NOTICE", {text: error.message, error: true}).catch(() => {});
  });
});
