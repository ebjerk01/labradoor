// Module isolation check (module SDK, docs/sdk.md). A module whose manifest says "manifest": 2 talks to the shell only
// through ctx + $lab/* shared code, never through the shell singleton or another module's files:
//   lab-singleton  imports $lab/lab.svelte.js (or reaches ui/src/lib/lab.svelte.js by a relative path)
//   cross-module   a relative import that leaves modules/<id>/ (another module's files, or the shell's by path)
//   undeclared-peer ctx.peer('x') / ctx.via('x') with x not in the manifest's "requires" (and no "*")
// v1 modules are not checked (phase 3 moves them). Used by tests/module_isolation.test.mjs (deploy gate).
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, resolve, relative, dirname, sep } from 'node:path';

const SRC = /\.(js|mjs|ts|svelte)$/;
const IMPORTS = [
  /\b(?:import|export)\s+(?:[^'"`;]*?\s+from\s+)?['"]([^'"]+)['"]/g,  // import x from '…', import '…', export … from '…'
  /\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g,                          // import('…')
];
const PEER = /\b(peer|via)\s*\(\s*(['"`])([^'"`$]+)\2\s*\)/g;

function files(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) { if (name !== 'node_modules') out.push(...files(p)); } else if (SRC.test(name)) out.push(p);
  }
  return out;
}

// comments out (so a comment that mentions an import is no violation); strings and code stay where they were
function strip(src) {
  return src.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
    .replace(/([;{}),])\s*\/\/.*$/gm, '$1');
}

const lineOf = (src, i) => src.slice(0, i).split('\n').length;

export function checkModule(dir, { root } = {}) {
  const manifestPath = join(dir, 'manifest.json');
  if (!existsSync(manifestPath)) return { checked: false, problems: [] };
  const m = JSON.parse(readFileSync(manifestPath, 'utf8'));
  if (m.manifest !== 2) return { checked: false, problems: [] };
  const id = m.id;
  const req = new Set((m.requires || []).map((r) => (typeof r === 'string' ? r : r?.id)));
  const uiDir = join(dir, 'ui');
  const shellFile = root ? resolve(root, 'ui/src/lib/lab.svelte.js') : null;
  const problems = [];
  const add = (file, line, rule, detail) => problems.push({ module: id, file: relative(root || dir, file), line, rule, detail });
  for (const f of existsSync(uiDir) ? files(uiDir) : []) {
    const src = strip(readFileSync(f, 'utf8'));
    for (const re of IMPORTS) {
      for (const hit of src.matchAll(re)) {
        const spec = hit[1], line = lineOf(src, hit.index);
        if (/^\$lab\/lab\.svelte(\.js)?$/.test(spec)) { add(f, line, 'lab-singleton', `imports ${spec}: use ctx (docs/sdk.md)`); continue; }
        if (!spec.startsWith('.')) continue;
        const target = resolve(dirname(f), spec);
        if (shellFile && (target === shellFile || target === shellFile.replace(/\.js$/, ''))) {
          add(f, line, 'lab-singleton', `imports the shell singleton by path (${spec}): use ctx`);
        } else if (target !== resolve(dir) && !target.startsWith(resolve(dir) + sep)) {
          add(f, line, 'cross-module', `imports ${spec}, outside modules/${id}/: use $lab/sdk.js or ctx.peer/ctx.via`);
        }
      }
    }
    for (const hit of src.matchAll(PEER)) {
      const peer = hit[3];
      if (!req.has(peer) && !req.has('*')) {
        add(f, lineOf(src, hit.index), 'undeclared-peer', `${hit[1]}('${peer}') but "${peer}" is not in requires`);
      }
    }
  }
  return { checked: true, problems };
}

// every module folder under modulesDir (the _template too: new modules start from it)
export function checkModules(modulesDir, { root } = {}) {
  const out = { checked: [], problems: [] };
  for (const name of readdirSync(modulesDir).sort()) {
    const dir = join(modulesDir, name);
    if (!statSync(dir).isDirectory()) continue;
    const r = checkModule(dir, { root });
    if (r.checked) out.checked.push(name);
    out.problems.push(...r.problems);
  }
  return out;
}
