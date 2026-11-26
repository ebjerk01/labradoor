// Deploy gate: "manifest": 2 modules use ctx + $lab/* only (tests/isolation.mjs, docs/sdk.md).
// Usage: node tests/module_isolation.test.mjs  (exit 1 on failure)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { checkModules } from './isolation.mjs';

const root = fileURLToPath(new URL('..', import.meta.url));

// 1. the real modules. isolation-pending.json lists v2 modules whose UI is not ported yet: reported, not fatal, and
//    an entry must go as soon as its module is clean (the list only shrinks).
const pending = Object.keys(JSON.parse(readFileSync(new URL('./isolation-pending.json', import.meta.url), 'utf8'))).filter((k) => k !== '_');
const real = checkModules(`${root}modules`, { root });
const fatal = real.problems.filter((p) => !pending.includes(p.module));
for (const p of real.problems.filter((x) => pending.includes(x.module))) console.log(`pending ${p.file}:${p.line} [${p.rule}]`);
if (fatal.length) {
  for (const p of fatal) console.error(`${p.file}:${p.line} [${p.rule}] ${p.detail}`);
  assert.fail(`${fatal.length} module isolation problem(s) in "manifest": 2 modules (docs/sdk.md#isolation)`);
}
for (const m of pending) {
  assert.ok(real.checked.includes(m), `isolation-pending.json lists ${m}, which is not a "manifest": 2 module`);
  assert.ok(real.problems.some((p) => p.module === m), `${m} is clean now: remove it from tests/isolation-pending.json`);
}
assert.ok(real.checked.includes('_template'), 'the module template is a v2 module and must be checked');

// 2. the checker catches each violation (fixtures), and leaves v1 modules alone
const fx = checkModules(fileURLToPath(new URL('./fixtures/isolation/modules', import.meta.url)), { root });
assert.deepEqual(fx.checked, ['badcross', 'badlab', 'badpeer', 'good']);
const got = fx.problems.map((p) => `${p.module} ${p.rule} ${p.file.split('/').slice(-1)[0]}:${p.line}`).sort();
assert.deepEqual(got, [
  'badcross cross-module index.js:1',
  'badcross cross-module index.js:2',
  'badlab lab-singleton View.svelte:2',
  'badlab lab-singleton index.js:1',
  'badpeer undeclared-peer index.js:1',
  'badpeer undeclared-peer index.js:1',
]);
assert.ok(fx.problems.some((p) => p.detail.includes("peer('other')")) && fx.problems.some((p) => p.detail.includes("via('stranger')")));
console.log(`module isolation ok (${real.checked.length} v2 module(s): ${real.checked.join(', ')}; pending port: ${pending.join(', ') || 'none'})`);
