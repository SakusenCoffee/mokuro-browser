import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const settings = {};
const event = () => ({addListener() {}});
const token = 'test-pairing-code-with-at-least-32-characters';
let offline = false;
const context = vm.createContext({
  setTimeout, AbortSignal, importScripts() {},
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
    runtime: {onMessage: event(), onInstalled: event()},
    tabs: {onActivated: event(), onRemoved: event()},
    contextMenus: {onClicked: event()}, commands: {onCommand: event()}
  }
});
vm.runInContext(await readFile(new URL('../extension/background.js', import.meta.url), 'utf8'), context);
const evaluate = code => vm.runInContext(code, context);
await assert.rejects(evaluate("launch({type:'HEALTH'}, {})"), /pairing code/);
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
await assert.rejects(evaluate("launch({type:'HEALTH'}, {})"), /mokuro-browser serve/);
console.log('PASS: first-run pairing, authenticated health, bad codes, tab isolation, retry and portable offline message');
