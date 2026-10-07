// Keep unsent pages across browser restarts. The local app owns the editable
// archive, so editing/deleting a saved line cannot be undone by a restored tab.
const historyDatabase = new Promise((resolve, reject) => {
  const request = indexedDB.open("mokuro-reading-history", 1);
  request.onupgradeneeded = () => request.result.createObjectStore("pending", {keyPath: "page_id"});
  request.onsuccess = () => resolve(request.result);
  request.onerror = () => reject(request.error);
});
let historySending = false;

// Wake the worker to retry durable saves even when the popup is closed.
chrome.alarms.create("mokuro-history-sync", {periodInMinutes: 1});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === "mokuro-history-sync") void flushReadingLog();
});

async function historyTransaction(mode, action) {
  const database = await historyDatabase;
  return new Promise((resolve, reject) => {
    const transaction = database.transaction("pending", mode);
    let value;
    transaction.oncomplete = () => resolve(value);
    transaction.onerror = transaction.onabort = () => reject(transaction.error || new Error("Reading log could not be saved."));
    action(transaction.objectStore("pending"), result => { value = result; });
  });
}

async function queueReadingPage(tabId, target, result, pageId) {
  const tab = await chrome.tabs.get(tabId).catch(() => ({}));
  const source = /^https?:/.test(target.src || "") ? target.src : tab.url || "local-image";
  const record = {page_id: pageId || await resultDigest(result),
    source_key: await resultDigest(source), title: tab.title || "Manga page",
    lines: MokuroResults.lines(result)};
  await historyTransaction("readwrite", store => store.put(record));
  void flushReadingLog();
}

async function flushReadingLog() {
  if (historySending) return;
  historySending = true;
  try {
    const pending = await historyTransaction("readonly", (store, done) => {
      const request = store.getAll(undefined, 30);
      request.onsuccess = () => done(request.result);
    });
    for (const page of pending) {
      await api("/history", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(page)});
      await historyTransaction("readwrite", store => store.delete(page.page_id));
    }
  } catch (error) {
    console.warn("Reading history will retry when the local app is available:", error.message);
  } finally { historySending = false; }
}
