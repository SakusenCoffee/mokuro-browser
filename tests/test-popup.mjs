import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../extension/popup.js', import.meta.url), 'utf8');

async function popupWithHealth(health) {
  const elements = new Map();
  let tick;
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      textContent: '', disabled: false, open: false, value: '', parentElement: {hidden: false},
      attributes: {}, setAttribute(name, value) { this.attributes[name] = value; },
      querySelector: element,
      addEventListener(name, callback) { this[name] = callback; },
      getAttribute(name) { return this.attributes[name] ?? 'false'; }
    });
    return elements.get(selector);
  };
  const context = vm.createContext({
    setInterval(callback) { tick = callback; },
    document: {querySelector: element, getElementById: element},
    chrome: {
      storage: {onChanged: {addListener() {}}, local: {get: async () => ({autoScan: false, pairingToken: 'saved-code'})}},
      runtime: {sendMessage: async message => {
        if (message.type === 'SERVER_STATUS') return {ok: false, error: 'Specified native messaging host not found.'};
        if (message.type === 'HEALTH') return health;
        if (message.type === 'AUTO_PAIR') return {ok: false, error: 'Automatic pairing is unavailable.'};
        throw new Error(`Unexpected message: ${message.type}`);
      }}
    }
  });
  vm.runInContext(source, context);
  await new Promise(resolve => setImmediate(resolve));
  element.tick = () => tick();
  return element;
}

const connected = await popupWithHealth({ok: true, data: {model: 'ready'}});
assert.match(connected('#status').textContent, /Local server ready/);
assert.equal(connected('#server').textContent, 'Server: On');
assert.equal(connected('#server').getAttribute('data-connected'), 'true');
assert.equal(connected('#server').disabled, true);
assert.equal(connected('#pairing').open, false);
assert.equal(connected('#pairing-code').value, 'saved-code');
assert.equal(connected('#gpu-load').parentElement.hidden, true);

const legacy = await popupWithHealth({ok: true, data: {model: 'loaded'}});
assert.match(legacy('#status').textContent, /update the Mokuro Browser launcher/);
assert.doesNotMatch(legacy('#status').textContent, /loading/);
const loading = await popupWithHealth({ok: true, data: {model: 'loading', usage: {cpu: 12.4, gpu: 0}}});
assert.match(loading('#status').textContent, /loading OCR/);
assert.equal(loading('#cpu-load').textContent, '12%');
assert.equal(loading('#gpu-load').textContent, '0%');
assert.equal(loading('#gpu-load').parentElement.hidden, false);

const unpaired = await popupWithHealth({ok: false, error: 'Automatic pairing is unavailable.'});
assert.match(unpaired('#status').textContent, /Paste the connect code/);
assert.equal(unpaired('#pairing').open, true);
unpaired('summary').click();
unpaired('#pairing').open = false;
await unpaired.tick();
await unpaired.tick();
assert.equal(unpaired('#pairing').open, false, 'health polling must respect a collapsed pairing section');

console.log('PASS: popup checks server health without native control and highlights manual pairing');
