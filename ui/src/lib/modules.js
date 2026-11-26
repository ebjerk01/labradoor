// Every module's UI half is its own chunk, loaded when the gateway's registry says this user has the module
// (/api/registry) — a guest downloads only their few modules, and a deploy that changes one module only invalidates
// that module's chunk in the browser cache. Code is not secret, data is.
//   * bundled modules (shipped in the release): modules/<id>/ui/index.js, compiled into this build (virtual:lab-modules,
//     ui/vite-abi.js);
//   * installed modules (from a signed catalog, docs/catalog.md): a prebuilt ES module the gateway serves at
//     /modules/<id>/<version>/ui.js (registry entry `bundle`). Its `svelte` and `$lab/…` imports resolve through the
//     import map in index.html to this build's own chunks (one svelte runtime, one SDK).
import bundled from 'virtual:lab-modules';

export const knownModules = Object.keys(bundled);

// where a registry entry's UI comes from: its installed bundle URL, else the bundled chunk ('' = none in this build)
export const uiSource = (m) => m.bundle || (bundled[m.id] ? 'bundled' : '');

// {id: ui object} for the given registry entries ({id, bundle?}; a bare id = bundled); a module whose code fails to
// load (or whose bundle exports another id) is left out (logged)
export async function loadUi(entries) {
  const out = {};
  await Promise.all(entries.map((e) => (typeof e === 'string' ? { id: e } : e)).map(async ({ id, bundle }) => {
    const load = bundle ? () => import(/* @vite-ignore */ bundle) : bundled[id];
    if (!load) return;
    try {
      const m = (await load()).default;
      if (m && m.id === id) out[id] = m;
      else console.error(`module ${id}: its UI says it is ${m?.id ?? 'nothing'}`);
    } catch (e) { console.error(`module ${id}: UI failed to load`, e); }
  }));
  return out;
}
