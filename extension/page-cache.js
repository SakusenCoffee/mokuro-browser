// IndexedDB avoids storage.session's fixed 10 MB limit for long volumes in
// several tabs. Only OCR JSON is stored; tab closure/startup removes it.
const closedTabs = new Set();
const cacheDatabase = new Promise((resolve, reject) => {
  const request = indexedDB.open("mokuro-tab-pages", 1);
  request.onupgradeneeded = () => {
    const store = request.result.createObjectStore("pages", {keyPath: ["tabId", "key"]});
    store.createIndex("tabId", "tabId");
  };
  request.onsuccess = () => resolve(request.result);
  request.onerror = () => reject(request.error);
});

async function cacheTransaction(mode, action) {
  const db = await cacheDatabase;
  return new Promise((resolve, reject) => {
    const transaction = db.transaction("pages", mode);
    let value;
    transaction.oncomplete = () => resolve(value);
    transaction.onerror = transaction.onabort = () => reject(transaction.error || new Error("Page cache transaction failed."));
    action(transaction.objectStore("pages"), result => { value = result; });
  });
}

async function removeTabPages(tabId) {
  return cacheTransaction("readwrite", store => {
    const request = store.index("tabId").openKeyCursor(IDBKeyRange.only(tabId));
    request.onsuccess = () => {
      const cursor = request.result;
      if (cursor) { store.delete(cursor.primaryKey); cursor.continue(); }
    };
  });
}

const cacheReady = (async () => {
  const alive = new Set((await chrome.tabs.query({})).map(tab => tab.id));
  await cacheTransaction("readwrite", store => {
    const request = store.openCursor();
    request.onsuccess = () => {
      const cursor = request.result;
      if (cursor) { if (!alive.has(cursor.value.tabId)) cursor.delete(); cursor.continue(); }
    };
  });
})();

async function resultDigest(result) {
  const bytes = new TextEncoder().encode(JSON.stringify(result));
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

async function getPageResult(tabId, target) {
  await cacheReady;
  const key = MokuroResults.key(target);
  if (!key || closedTabs.has(tabId)) return {};
  const record = await cacheTransaction("readonly", (store, done) => {
    const request = store.get([tabId, key]); request.onsuccess = () => done(request.result);
  });
  if (!record) return {};
  if (record.version !== 3 || !MokuroResults.valid(record.result)
      || record.result.img_width !== target.width || record.result.img_height !== target.height
      || record.digest !== await resultDigest(record.result)) {
    await cacheTransaction("readwrite", store => store.delete([tabId, key]));
    return {invalid: true};
  }
  return {result: record.result};
}

async function savePageResult(tabId, target, result) {
  const key = MokuroResults.key(target);
  if (!key || !MokuroResults.valid(result)) return;
  const digest = await resultDigest(result);
  await cacheReady;
  // A completed job must not recreate data after its tab was closed.
  if (closedTabs.has(tabId)) return;
  await chrome.tabs.get(tabId);
  await cacheTransaction("readwrite", store => {
    if (!closedTabs.has(tabId)) store.put({tabId, key, version: 3, result, digest});
  });
}

chrome.tabs.onRemoved.addListener(tabId => {
  closedTabs.add(tabId);
  removeTabPages(tabId).catch(() => {});
});
chrome.runtime.onStartup.addListener(() => {
  cacheTransaction("readwrite", store => store.clear()).catch(() => {});
});
