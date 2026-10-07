const status = document.querySelector("#status");
const error = document.querySelector("#error");
const auto = document.querySelector("#auto");
const server = document.querySelector("#server");
function showAuto(enabled) {
  auto.setAttribute("aria-pressed", String(enabled));
  auto.textContent = `Auto-scan manga: ${enabled ? "On" : "Off"}`;
}
auto.disabled = true;
chrome.storage.local.get({autoScan: false}).then(settings => {
  showAuto(settings.autoScan);
  auto.disabled = false;
});
auto.onclick = async () => {
  error.textContent = "";
  auto.disabled = true;
  try {
    const enabled = auto.getAttribute("aria-pressed") !== "true";
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const reply = await chrome.runtime.sendMessage({type: "SET_AUTO", enabled, tabId: tab.id});
    if (!reply.ok) throw new Error(reply.error);
    showAuto(enabled);
  } catch (failure) { error.textContent = failure.message; }
  finally { auto.disabled = false; }
};
function showHealth(reply) {
  status.textContent = reply.ok
    ? (reply.data.model === "ready" ? "● Local server ready · models loaded" : "● Local server ready · first scan loads models")
    : reply.error;
  if (!reply.ok) document.querySelector("#pairing").open = true;
}
function showServer(data) {
  const running = data.running === true;
  server.setAttribute("aria-pressed", String(running));
  server.textContent = `Server: ${running ? "On" : "Off"}`;
  if (!running) status.textContent = "● Local server is off";
}
async function refreshServer() {
  server.disabled = true;
  try {
    const reply = await chrome.runtime.sendMessage({type: "SERVER_STATUS"});
    if (!reply.ok) throw new Error(reply.error);
    showServer(reply.data);
    if (reply.data.running) {
      const health = await chrome.runtime.sendMessage({type: "HEALTH"});
      showHealth(health);
    }
  } catch (failure) {
    status.textContent = failure.message;
    server.textContent = "Server: unavailable";
  } finally { server.disabled = false; }
}
server.onclick = async () => {
  error.textContent = "";
  server.disabled = true;
  try {
    const action = server.getAttribute("aria-pressed") === "true" ? "stop" : "start";
    const reply = await chrome.runtime.sendMessage({type: "SERVER_CONTROL", action});
    if (!reply.ok) throw new Error(reply.error);
    showServer(reply.data);
    if (reply.data.running) showHealth(await chrome.runtime.sendMessage({type: "HEALTH"}));
  } catch (failure) { error.textContent = failure.message; }
  finally { server.disabled = false; }
};
refreshServer();
document.querySelector("#pair").onclick = async () => {
  error.textContent = "";
  const button = document.querySelector("#pair");
  button.disabled = true;
  try {
    const reply = await chrome.runtime.sendMessage({type: "PAIR", token: document.querySelector("#pairing-code").value});
    if (!reply.ok) throw new Error(reply.error);
    showHealth(reply);
    document.querySelector("#pairing-code").value = "";
    document.querySelector("#pairing").open = false;
  } catch (failure) { error.textContent = failure.message; }
  finally { button.disabled = false; }
};
for (const [id, type] of [["largest", "SCAN_LARGEST"], ["check", "CHECK_PAGE"], ["pick", "PICK_IMAGE"], ["visible", "SCAN_VISIBLE"], ["clear", "CLEAR"]]) {
  document.getElementById(id).onclick = async () => {
    error.textContent = "";
    try {
      const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
      const reply = await chrome.runtime.sendMessage({type, tabId: tab.id});
      if (!reply.ok) throw new Error(reply.error);
      window.close();
    } catch (failure) { error.textContent = failure.message; }
  };
}
