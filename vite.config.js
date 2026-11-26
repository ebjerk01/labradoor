import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';
import { labModules, labAbi, libCss } from './ui/vite-abi.js';

// Root is ui/; modules/*/ui are compiled into the same bundle (each its own chunk) and import shared parts as "$lab/...".
// The build also exposes the shell's own svelte runtime and $lab files as the module ABI (ui/vite-abi.js): an import map in
// index.html + ui/dist/abi.json, so a module installed from a catalog (a prebuilt bundle, deploy/make-module.sh) runs
// on the very same svelte instance and SDK as the bundled ones.
export default defineConfig({
  root: 'ui',
  plugins: [svelte({ dynamicCompileOptions: libCss }), labModules(), labAbi()],
  resolve: { alias: { $lab: fileURLToPath(new URL('./ui/src/lib', import.meta.url)) } },
  build: { outDir: 'dist', emptyOutDir: true, assetsInlineLimit: 0, chunkSizeWarningLimit: 2000 },
  server: {
    fs: { allow: ['..'] },
    proxy: { '/api': 'http://127.0.0.1:8100', '/auth': 'http://127.0.0.1:8100' }
  }
});
