import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../extension/content.js', import.meta.url), 'utf8');
const functions = ['mangaImage', 'scheduleAuto', 'setAuto'].map(name => {
  const start = source.indexOf(`  function ${name}(`);
  assert.notEqual(start, -1);
  const end = source.indexOf('\n  }', start);
  return source.slice(start, end + 4);
}).join('\n');
let images = [], scheduled = [], cancelled = [];
const context = vm.createContext({
  visibleImages: () => images,
  scanAuto() {},
  setTimeout(callback, delay) { scheduled.push({callback, delay}); return scheduled.length; },
  clearTimeout(id) { cancelled.push(id); }
});
vm.runInContext(`
  let autoEnabled = false, autoTimer, retryAfter = 99, clearedKey = 'old', missingKey = 'old';
  const attempted = new Map([['old', 99]]);
  ${functions}
`, context);
const image = (width, height, complete = true) => ({naturalWidth: width, naturalHeight: height, complete});
for (const [width, height] of [[800, 1200], [1600, 800], [800, 10000], [500, 500]]) {
  const page = image(width, height);
  images = [{image: page, area: 200000}];
  // No document title, URL, alt text or reader-specific markup is needed.
  assert.equal(vm.runInContext('mangaImage()', context), page);
}
const page = image(800, 1200);
images = [{image: image(100, 100), area: 60000},
  {image: image(800, 1200, false), area: 200000}, {image: page, area: 200000}];
assert.equal(vm.runInContext('mangaImage()', context), page);
images = [{image: page, area: 1000}];
assert.equal(vm.runInContext('mangaImage()', context), undefined);
vm.runInContext('scheduleAuto(); scheduleAuto(); scheduleAuto();', context);
assert.equal(scheduled.length, 1, 'DOM updates must not postpone a pending scan');
vm.runInContext('setAuto(true)', context);
assert.equal(scheduled.at(-1).delay, 0);
assert.equal(cancelled.at(-1), 1);
assert.equal(vm.runInContext('autoEnabled && retryAfter === 0 && clearedKey === null && missingKey === null && attempted.size === 0', context), true);
vm.runInContext('setAuto(false)', context);
assert.equal(vm.runInContext('autoEnabled', context), false);
console.log('Auto-scan checks passed');
