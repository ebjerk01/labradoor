import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { moduleImports } from './ui/vite-abi.js';

// One installable module's UI as ONE ES module (deploy/make-module.sh): LAB_MODULE_ID=<id> [LAB_MODULE_SRC=<dir>]
// LAB_MODULE_OUT=<dir> vite build -c vite.module.config.js → <dir>/ui.js + <dir>/imports.json.
// `svelte…` and `$lab/…` stay imports (the shell's import map resolves them to its own runtime and SDK, ui/vite-abi.js);
// the CSS of its components is carried in the JS (no extra files); dynamic imports are inlined.
const ROOT = path.dirname(fileURLToPath(import.meta.url));
const id = process.env.LAB_MODULE_ID || '';
if (!/^[a-z][a-z0-9-]{1,30}$/.test(id)) throw new Error('LAB_MODULE_ID: a module id');
const src = path.resolve(process.env.LAB_MODULE_SRC || path.join(ROOT, 'modules', id));
const out = path.resolve(process.env.LAB_MODULE_OUT || path.join(ROOT, 'module-out', id));
const external = (s) => s === 'svelte' || s.startsWith('svelte/') || s.startsWith('$lab/');

export default defineConfig({
  root: src,
  logLevel: 'warn',
  publicDir: false,
  plugins: [svelte({ emitCss: false, compilerOptions: { css: 'injected', discloseVersion: false } }), moduleImports(out)],
  build: {
    outDir: out,
    emptyOutDir: true,
    minify: true,
    assetsInlineLimit: 1 << 20,   // images a module imports become data: URLs inside ui.js
    copyPublicDir: false,
    lib: { entry: path.join(src, 'ui', 'index.js'), formats: ['es'], fileName: () => 'ui.js' },
    rollupOptions: { external, output: { codeSplitting: false } },
  },
});
