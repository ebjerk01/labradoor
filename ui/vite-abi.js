// Build plugins for the shell (vite.config.js) and for module packages (vite.module.config.js).
//
// The module ABI: a module installed from a catalog is a prebuilt ES module bundle (deploy/make-module.sh) that imports
// `svelte`, `svelte/internal/client`, `$lab/sdk.js`, `$lab/Table.svelte` … as bare specifiers. The shell's build turns
// each of those into an entry of its own (a facade over the very chunks the shell itself uses, so there is ONE svelte
// runtime and ONE SDK in the page) and writes
//   * an import map into index.html (specifier → /assets/abi/<name>-<hash>.js), which the browser applies to every
//     module it loads afterwards, and
//   * ui/dist/abi.json: the svelte version (the ABI: compiled svelte code only runs on the runtime it was built for)
//     and the names each specifier exports — the module helper refuses a package that imports anything else.
// $lab/lab.svelte.js (the shell's own state) is not part of the ABI: modules reach the shell only through ctx.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const LIB = path.join(ROOT, 'ui', 'src', 'lib');
const MODULES = path.join(ROOT, 'modules');

// the svelte entry points compiled components and module code may import (type-only ones are left out)
export const SVELTE_SPECIFIERS = [
  'svelte', 'svelte/internal/client', 'svelte/internal/disclose-version', 'svelte/internal/flags/legacy',
  'svelte/internal/flags/async', 'svelte/internal/flags/tracing', 'svelte/store', 'svelte/reactivity',
  'svelte/reactivity/window', 'svelte/transition', 'svelte/animate', 'svelte/easing', 'svelte/motion', 'svelte/events',
  'svelte/attachments', 'svelte/legacy',
];
const NOT_ABI = new Set(['lab.svelte.js', 'modules.js']);

// every shared file in ui/src/lib, plus one level of subfolders for shared families of modules ($lab/arr/…: the *arr UI)
export function labSpecifiers() {
  const files = (dir, pre) => fs.readdirSync(dir)
    .filter((f) => /\.(js|svelte)$/.test(f) && !NOT_ABI.has(pre + f) && !f.endsWith('.test.mjs'))
    .map((f) => pre + f);
  const subs = fs.readdirSync(LIB, { withFileTypes: true })
    .filter((d) => d.isDirectory() && /^[a-z][a-z0-9-]{0,30}$/.test(d.name))
    .flatMap((d) => files(path.join(LIB, d.name), `${d.name}/`));
  return [...files(LIB, ''), ...subs].sort().map((f) => `$lab/${f}`);
}

export function svelteVersion() {
  return JSON.parse(fs.readFileSync(path.join(ROOT, 'node_modules', 'svelte', 'package.json'), 'utf8')).version;
}

// shared $lab components carry their CSS in their JS: a module bundle that imports one through the ABI gets its styles
// without the shell's CSS chunk bookkeeping (module bundles are compiled the same way, vite.module.config.js)
export function libCss({ filename }) {
  if (filename && filename.startsWith(LIB + path.sep)) return { css: 'injected' };
}

// `virtual:lab-modules`: {id: () => import(modules/<id>/ui/index.js)} for the modules this build bundles —
// every modules/<id>/ui/index.js except _* and the ids in LAB_EXCLUDE_MODULES (a slim core release whose other modules
// come from a catalog: deploy/make-release.sh --exclude-modules)
export function bundledIds() {
  const skip = new Set((process.env.LAB_EXCLUDE_MODULES || '').split(',').map((s) => s.trim()).filter(Boolean));
  return fs.readdirSync(MODULES)
    .filter((id) => !id.startsWith('_') && !id.startsWith('.') && !skip.has(id)
      && fs.existsSync(path.join(MODULES, id, 'ui', 'index.js')))
    .sort();
}

export function labModules() {
  const ID = 'virtual:lab-modules';
  return {
    name: 'lab-modules',
    resolveId(id) { return id === ID ? '\0' + ID : null; },
    load(id) {
      if (id !== '\0' + ID) return null;
      const lines = bundledIds().map((m) =>
        `  ${JSON.stringify(m)}: () => import(${JSON.stringify(path.join(MODULES, m, 'ui', 'index.js'))}),`);
      return `export default {\n${lines.join('\n')}\n};\n`;
    },
  };
}

const PREFIX = 'lab-abi:';
const entryName = (spec) => 'abi/' + spec.replace(/^\$/, '').replace(/[^A-Za-z0-9]+/g, '-').replace(/-+$/, '');

export function labAbi() {
  const specs = [...SVELTE_SPECIFIERS, ...labSpecifiers()];
  let root = '';
  return {
    name: 'lab-abi',
    apply: 'build',
    config(cfg) {
      const input = { index: path.join(ROOT, 'ui', 'index.html') };
      specs.forEach((s, i) => { input[entryName(s)] = PREFIX + i; });   // ids by number: none may end in .svelte
      return {
        build: {
          rollupOptions: {
            input,
            preserveEntrySignatures: 'strict',
            output: { entryFileNames: 'assets/[name]-[hash].js' },
          },
        },
      };
    },
    configResolved(c) { root = c.root; },
    resolveId(id) { return id.startsWith(PREFIX) ? '\0' + id : null; },
    load(id) {
      if (!id.startsWith('\0' + PREFIX)) return null;
      const spec = specs[Number(id.slice(PREFIX.length + 1))];
      if (!spec.startsWith('$lab/')) return `export * from ${JSON.stringify(spec)};\n`;
      const file = path.join(LIB, spec.slice(5));
      const src = fs.readFileSync(file, 'utf8');
      const out = [];
      const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');   // not a mention in a comment
      if (file.endsWith('.svelte') || /\bexport\s+default\b/.test(code)) out.push(`export { default } from ${JSON.stringify(file)};`);
      if (!file.endsWith('.svelte')) out.push(`export * from ${JSON.stringify(file)};`);
      return out.join('\n') + '\n';
    },
    // ui/dist/abi.json — what the module helper checks a package against
    generateBundle(_, bundle) {
      const map = abiFromBundle(bundle, specs);
      this.emitFile({
        type: 'asset', fileName: 'abi.json',
        source: JSON.stringify({ format: 1, svelte: svelteVersion(), specifiers: map }, null, 1) + '\n',
      });
    },
    transformIndexHtml: {
      order: 'post',
      handler(html, ctx) {
        if (!ctx.bundle) return html;
        const imports = {};
        for (const [spec, v] of Object.entries(abiFromBundle(ctx.bundle, specs))) imports[spec] = v.file;
        // before every other script: an import map must be in place before the first module loads
        return [{ tag: 'script', attrs: { type: 'importmap' }, children: JSON.stringify({ imports }), injectTo: 'head-prepend' }];
      },
    },
  };
}

function abiFromBundle(bundle, specs) {
  const map = {};
  for (const c of Object.values(bundle)) {
    if (c.type !== 'chunk' || !c.isEntry || !c.name.startsWith('abi/')) continue;
    const spec = specs.find((s) => entryName(s) === c.name);
    if (spec) map[spec] = { file: '/' + c.fileName, exports: [...c.exports].sort() };
  }
  const missing = specs.filter((s) => !map[s]);
  if (missing.length) throw new Error(`module ABI: no entry for ${missing.join(', ')}`);
  return map;
}

// What a module bundle imports from the ABI, for the package's package.json (`imports`): {specifier: [names]}, "*" when
// it takes a whole namespace. Svelte's compiled code reaches its runtime as `$.name` through `import * as $ from
// 'svelte/internal/client'` ($ is reserved in Svelte 5: user code can't shadow it), so those names are collected from
// each compiled file before bundling renames `$`; everything else from the bundle's own import statements.
export function moduleImports(out) {
  const internal = new Set();
  return {
    name: 'lab-module-imports',
    transform: {
      order: 'post',
      handler(code) {
        if (/import \* as \$ from ['"]svelte\/internal\/client['"]/.test(code)) {
          for (const m of code.matchAll(/(?<![\w$.])\$\.([A-Za-z_][\w$]*)/g)) internal.add(m[1]);
        }
        return null;
      },
    },
    generateBundle(_, bundle) {
      const chunks = Object.values(bundle).filter((c) => c.type === 'chunk');
      if (chunks.length !== 1) this.error(`a module bundle is ONE file (got ${chunks.map((c) => c.fileName).join(', ')})`);
      const code = chunks[0].code;
      const imports = {};
      const add = (spec, name) => { (imports[spec] ||= new Set()).add(name); };
      for (const m of code.matchAll(/^\s*import\s+(?:([\s\S]*?)\s+from\s*)?["']([^"']+)["'];?\s*$/gm)) {
        const [, what, spec] = m;
        if (!(spec === 'svelte' || spec.startsWith('svelte/') || spec.startsWith('$lab/'))) {
          this.error(`a module bundle may import only svelte and $lab/… (got ${spec})`);
        }
        imports[spec] ||= new Set();
        if (!what) continue;   // side effect only (a svelte flag)
        let rest = what.trim();
        const ns = rest.match(/^(?:([\w$]+)\s*,\s*)?\*\s+as\s+[\w$]+$/);
        if (ns) {
          if (ns[1]) add(spec, 'default');
          if (spec === 'svelte/internal/client') internal.forEach((n) => add(spec, n));
          else add(spec, '*');
          continue;
        }
        const def = rest.match(/^([\w$]+)\s*(?:,\s*(\{[\s\S]*\}))?$/);
        if (def) { add(spec, 'default'); rest = def[2] || ''; }
        const named = rest.match(/^\{([\s\S]*)\}$/);
        if (named) for (const part of named[1].split(',').map((x) => x.trim()).filter(Boolean)) add(spec, part.split(/\s+as\s+/)[0].replace(/^["']|["']$/g, ''));
        else if (rest) this.error(`can't read the import of ${spec}: ${rest.slice(0, 80)}`);
      }
      for (const m of code.matchAll(/\bimport\(\s*["']([^"']+)["']\s*\)/g)) add(m[1], '*');
      if (/\bimport\(\s*[^"'\s]/.test(code)) this.error('a module bundle may not import() computed URLs');
      const outObj = Object.fromEntries(Object.entries(imports).sort().map(([k, v]) => [k, [...v].sort()]));
      this.emitFile({ type: 'asset', fileName: 'imports.json', source: JSON.stringify(outObj, null, 1) + '\n' });
    },
  };
}
