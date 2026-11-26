// __NAME__ — UI half of the module. Everything here is optional; delete what you don't use.
// A module talks to the shell only through `ctx` and imports shared code only from `$lab/…` (docs/sdk.md). It never
// imports $lab/lab.svelte.js or another module's files; the deploy gate checks that for "manifest": 2 modules.
// The hooks the shell calls are listed in docs/sdk.md ("Module hooks").
import { cached, soft, siteStatus } from '$lab/sdk.js';
import Facet from './Facet.svelte';
import Tile from './Tile.svelte';
import ItemsView from './ItemsView.svelte';

// what is wrong right now: feeds alerts() and the object's status
function problems(data) {
  const out = [];
  if (!data.status?.ok) out.push({ key: '__ID__:down', status: 'bad', title: '__NAME__ is down', detail: data.status?.error || '', object: '__ID__' });
  return out;
}

export default {
  id: '__ID__',

  // Called on every shell refresh (15 s). ctx.api talks to this module's backend through the gateway (only manifest
  // routes work). Slow-changing calls go through cached() (prefix the key with ctx.id); soft() makes a part optional.
  async load(ctx) {
    const [status, items] = await Promise.all([
      ctx.api.get('/api/status'),
      soft(cached(`${ctx.id}:items`, 5 * 60000, () => ctx.api.get('/api/items')), []),
    ]);
    return { status, count: Array.isArray(items) ? items.length : 0, at: Date.now() / 1000 };
  },

  // Objects this module knows about. Same id as another module's object → they merge (facets stack up).
  objects(data) {
    return [{ id: '__ID__', type: 'service', name: '__NAME__', kind: 'service', status: siteStatus(problems(data)), meta: `${data.count} items` }];
  },

  alerts: (data) => problems(data),
  kpis: (data) => [{ label: '__ID__', value: data.count, sub: 'items', status: siteStatus(problems(data)) }],

  // Optional extras for the shell:
  // ticker(data)  → [{g: '●', c: 'var(--ok)', s: '__ID__', m: 'text'}]
  // status(data, ref) → 'ok'|'warn'|'bad'|null   (for a topology node's "status": {"module": "__ID__", "ref": "..."})
  // actions(object, data, ctx) → [{label, icon, method, path, body, confirm?}]   (object panel; locked/ask from the manifest)
  // search(data, ctx) / lookup(q, ctx) → Ctrl-K entries

  facets: { service: Facet },                                                     // props {object, data, ctx}
  tiles: [{ id: 'status', label: '__ID__', w: 2, h: 1, component: Tile }],        // props {data, ctx}
  views: [{ id: '__ID__', label: '__NAME__', icon: 'node', component: ItemsView }], // props {data, ctx}; ids are global
};
