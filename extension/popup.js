const status = document.querySelector("#status");
const error = document.querySelector("#error");
const auto = document.querySelector("#auto");
const server = document.querySelector("#server");
const serverHint = document.querySelector("#server-hint");
const pairing = document.querySelector("#pairing");
const pairingCode = document.querySelector("#pairing-code");
let controlAvailable = false;
let healthPending = false;
let pairingPromptShown = false;
let pairingTouched = false;
pairing.querySelector("summary").addEventListener("click", () => { pairingTouched = true; });
function showAuto(enabled) {
  auto.setAttribute("aria-pressed", String(enabled));
  auto.textContent = `Auto-scan manga: ${enabled ? "On" : "Off"}`;
}
auto.disabled = true;
chrome.storage.local.get({autoScan: false, pairingToken: ""}).then(settings => {
  showAuto(settings.autoScan);
  pairingCode.value = settings.pairingToken || "";
  auto.disabled = false;
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.pairingToken) pairingCode.value = changes.pairingToken.newValue || "";
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
  showServer({running: reply.ok});
  status.textContent = reply.ok
    ? (reply.data.model === "ready" ? "● Local server ready · models loaded"
      : reply.data.model === "error" ? "● Connected · models could not load: " + reply.data.model_error
      : reply.data.model === "loading" ? "● Connected · loading OCR models…"
      : "● Connected · update the Mokuro Browser launcher for model status and reading history.")
    : (reply.error?.includes("Automatic pairing is unavailable")
      ? "Paste the connect code below to check the local server."
      : reply.error);
  for (const name of ["cpu", "gpu"]) {
    const meter = document.querySelector(`#${name}-load`);
    const value = reply.data?.usage?.[name];
    meter.parentElement.hidden = !reply.ok || !Number.isFinite(value);
    meter.textContent = Number.isFinite(value) ? `${Math.round(value)}%` : "";
  }
  if (!reply.ok && !pairingPromptShown && !pairingTouched) pairing.open = true;
  if (!reply.ok) pairingPromptShown = true;
}
function showServer(data) {
  const running = data.running === true;
  server.setAttribute("aria-pressed", String(running));
  server.setAttribute("data-connected", String(running));
  server.textContent = `Server: ${running ? "On" : "Off"}`;
  if (!running) status.textContent = "● Local server is off";
}
async function refreshHealth() {
  if (healthPending) return;
  healthPending = true;
  try {
    showHealth(await chrome.runtime.sendMessage({type: "HEALTH"}));
  } catch (failure) { showHealth({ok: false, error: failure.message}); }
  finally { healthPending = false; }
}
async function refreshServer() {
  server.disabled = true;
  try {
    const reply = await chrome.runtime.sendMessage({type: "SERVER_STATUS"});
    if (!reply.ok) throw new Error(reply.error);
    showServer(reply.data);
    controlAvailable = true;
    serverHint.textContent = "Starts and stops the local OCR server. It stays off until you turn it on.";
    server.disabled = false;
  } catch (failure) {
    controlAvailable = false;
    serverHint.textContent = "Open the Mokuro Browser app to start or stop the server. Scanning still works when connected.";
  }
  await refreshHealth();
  server.disabled = !controlAvailable;
}
server.onclick = async () => {
  if (!controlAvailable) return;
  error.textContent = "";
  server.disabled = true;
  try {
    const action = server.getAttribute("aria-pressed") === "true" ? "stop" : "start";
    const reply = await chrome.runtime.sendMessage({type: "SERVER_CONTROL", action});
    if (!reply.ok) throw new Error(reply.error);
    showServer(reply.data);
    if (reply.data.running) {
      await refreshHealth();
    }
  } catch (failure) { error.textContent = failure.message; }
  finally { server.disabled = !controlAvailable; }
};
refreshServer();
setInterval(refreshHealth, 2000);
document.querySelector("#pair").onclick = async () => {
  error.textContent = "";
  const button = document.querySelector("#pair");
  button.disabled = true;
  try {
    const reply = await chrome.runtime.sendMessage({type: "PAIR", token: document.querySelector("#pairing-code").value});
    if (!reply.ok) throw new Error(reply.error);
    showHealth(reply);
    pairingCode.value = pairingCode.value.trim();
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
