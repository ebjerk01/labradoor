// The module ABI (step 16, ui/vite-abi.js, docs/catalog.md): the shell's build exposes its svelte runtime and $lab files
// through an import map + ui/dist/abi.json, and a module built as a package (vite.module.config.js) imports nothing
// else. Usage: node tests/module_abi.test.mjs (after npm run build; the deploy gate runs it after the build).
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { SVELTE_SPECIFIERS, labSpecifiers, svelteVersion } from '../ui/vite-abi.js';

const root = fileURLToPath(new URL('..', import.meta.url));
const dist = path.join(root, 'ui', 'dist');
assert.ok(existsSync(path.join(dist, 'abi.json')), 'ui/dist/abi.json missing: run npm run build first');
const abi = JSON.parse(readFileSync(path.join(dist, 'abi.json'), 'utf8'));
const html = readFileSync(path.join(dist, 'index.html'), 'utf8');

// 1. the ABI: every svelte entry point + every shared $lab file, never the shell's own state
assert.equal(abi.svelte, svelteVersion(), 'abi.json records the svelte the shell was built with');
const want = [...SVELTE_SPECIFIERS, ...labSpecifiers()].sort();
assert.deepEqual(Object.keys(abi.specifiers).sort(), want);
assert.ok(!('$lab/lab.svelte.js' in abi.specifiers) && !('$lab/modules.js' in abi.specifiers), 'the shell state is not ABI');
assert.ok(abi.specifiers['$lab/sdk.js'].exports.includes('act'), '$lab/sdk.js exports the SDK');
assert.ok(abi.specifiers['$lab/Table.svelte'].exports.includes('default'), 'a component is a default export');
// a shared family of modules in a subfolder (the *arr UI): $lab/arr/<file>
assert.ok(abi.specifiers['$lab/arr/arr.js'].exports.includes('createArr'), '$lab/arr/arr.js is ABI');
assert.ok(abi.specifiers['$lab/arr/Problems.svelte'].exports.includes('default'), '$lab/arr/Problems.svelte is ABI');
assert.ok(abi.specifiers['svelte/internal/client'].exports.length > 50, 'the whole svelte client runtime is exported');
for (const [spec, v] of Object.entries(abi.specifiers)) {
  assert.ok(existsSync(path.join(dist, v.file)), `${spec}: ${v.file} is in the build`);
}

// 2. index.html: the import map maps exactly those files, and comes before the first module script
const m = html.match(/<script type="importmap">([\s\S]*?)<\/script>/);
assert.ok(m, 'index.html has an import map');
const map = JSON.parse(m[1]).imports;
assert.deepEqual(map, Object.fromEntries(Object.entries(abi.specifiers).map(([s, v]) => [s, v.file])));
assert.ok(html.indexOf('type="importmap"') < html.indexOf('type="module"'), 'the import map comes before any module script');

// 3. modules built as packages import only what the shell exports (a plain one, one with .svelte.js state, a connector)
const tmp = mkdtempSync(path.join(tmpdir(), 'lababi-'));
try {
  for (const id of ['dns', 'ai', 'unifi']) {
    const out = path.join(tmp, id);
    execFileSync(path.join(root, 'node_modules', '.bin', 'vite'), ['build', '-c', 'vite.module.config.js'],
      { cwd: root, env: { ...process.env, LAB_MODULE_ID: id, LAB_MODULE_OUT: out }, stdio: 'pipe' });
    const imports = JSON.parse(readFileSync(path.join(out, 'imports.json'), 'utf8'));
    const code = readFileSync(path.join(out, 'ui.js'), 'utf8');
    assert.ok(imports['svelte/internal/client']?.length > 5, `${id}: the svelte runtime names it uses are recorded`);
    for (const [spec, names] of Object.entries(imports)) {
      assert.ok(abi.specifiers[spec], `${id} imports ${spec}, which the shell does not provide`);
      const missing = names.filter((n) => n !== '*' && !abi.specifiers[spec].exports.includes(n));
      assert.deepEqual(missing, [], `${id}: ${spec} does not export ${missing.join(', ')}`);
    }
    assert.ok(!/from\s*["']\.{1,2}\//.test(code) && !/import\(\s*["']\.{1,2}\//.test(code), `${id}: one file, no relative imports`);
    assert.ok(!code.includes('lab.svelte.js'), `${id}: never the shell state`);
    assert.match(code, new RegExp(`id: ["']${id}["']`), `${id}: the bundle is the module`);
  }
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
console.log('module ABI ok:', Object.keys(abi.specifiers).length, 'specifiers, svelte', abi.svelte);
