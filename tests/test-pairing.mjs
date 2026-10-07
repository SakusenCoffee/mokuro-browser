import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const settings = {};
const event = () => ({addListener() {}});
const token = 'test-pairing-code-with-at-least-32-characters';
let offline = false;
const nativeActions = [];
const context = vm.createContext({
  setTimeout, AbortSignal, importScripts() {}, flushReadingLog: async () => {},
  fetch: async (url, options) => {
    if (offline) throw new Error('offline');
    assert.equal(url, 'http://127.0.0.1:8766/health');
    const ok = options.headers.Authorization === `Bearer ${token}`;
    return {ok, status: ok ? 200 : 401, json: async () => ok
      ? {status: 'ok', model: 'ready'} : {error: 'Extension pairing token does not match.'}};
  },
  chrome: {
    storage: {local: {
      get: async key => typeof key === 'object' ? {...key, ...settings} : {...settings},
      set: async values => Object.assign(settings, values)
    }},
    runtime: {onMessage: event(), onInstalled: event(), sendNativeMessage: async (host, message) => {
      assert.equal(host, 'com.sakusencoffee.mokuro_browser');
      nativeActions.push(message.action);
      if (message.action === 'pair') return {ok: true, pairing_code: token};
      return {ok: true, running: message.action !== 'stop', health: {model: 'not_loaded'}};
    }},
    tabs: {onActivated: event(), onRemoved: event()},
    contextMenus: {onClicked: event()}, commands: {onCommand: event()}
  }
});
vm.runInContext(await readFile(new URL('../extension/background.js', import.meta.url), 'utf8'), context);
const evaluate = code => vm.runInContext(code, context);
assert.equal((await evaluate("launch({type:'SERVER_STATUS'}, {})")).running, true);
assert.equal((await evaluate("launch({type:'SERVER_CONTROL',action:'stop'}, {})")).running, false);
await assert.rejects(evaluate("launch({type:'SERVER_CONTROL',action:'anything'}, {})"), /Unsupported local server action/);
assert.deepEqual(nativeActions, ['status', 'stop']);
assert.equal((await evaluate("launch({type:'HEALTH'}, {})")).model, 'ready', 'scan path pairs without opening popup');
assert.equal(settings.pairingToken, token);
settings.pairingToken = 'old-pairing-code-with-at-least-32-characters';
assert.equal((await evaluate("launch({type:'HEALTH'}, {})")).model, 'ready', 'stale code is refreshed');
assert.equal(settings.pairingToken, token);
assert.equal((await evaluate("launch({type:'AUTO_PAIR'}, {})")).model, 'ready');
assert.equal(settings.pairingToken, token);
delete settings.pairingToken;
await assert.rejects(evaluate("launch({type:'PAIR',token:'short'}, {})"), /complete pairing/);
await assert.rejects(evaluate("launch({type:'PAIR',token:'wrong-code-with-at-least-32-characters'}, {})"), /does not match/);
assert.equal(settings.pairingToken, undefined);
await assert.rejects(evaluate(`launch({type:'PAIR',token:'${token}'}, {tab:{id:1}})`), /popup/);
await evaluate(`launch({type:'PAIR',token:'${token}'}, {})`);
assert.equal(settings.pairingToken, token);
assert.equal((await evaluate("launch({type:'HEALTH'}, {})")).model, 'ready');
await assert.rejects(evaluate("launch({type:'PAIR',token:'wrong-code-with-at-least-32-characters'}, {})"), /does not match/);
assert.equal(settings.pairingToken, token, 'failed re-pair preserves the working code');
offline = true;
await assert.rejects(evaluate("launch({type:'HEALTH'}, {})"), /server is off/);
console.log('PASS: native server control, first-run pairing, authenticated health, bad codes, tab isolation, retry and popup server message');
