// dns — Technitium DNS Server. Its HTTP API takes the token as `Authorization: Bearer` (v15+), so the gateway talks to
// it directly (backend.auth, token from the module config). Technitium answers HTTP 200 with
// {status: ok|error|invalid-token}: unwrap() turns anything but ok into an error.
import ResolverView from './ResolverView.svelte';
import MachineFacet from './MachineFacet.svelte';
import DnsTile from './DnsTile.svelte';
import { unwrap } from './tdns.js';
import { cached } from '$lab/sdk.js';

export default {
  id: 'dns',

  async load(ctx) {
    const s = unwrap(await ctx.api.get('/api/dashboard/stats/get', { type: 'LastDay', utc: 'true' }));
    const zones = await cached('dns:zones', 300000, async () => unwrap(await ctx.api.get('/api/zones/list')).zones || []);
    return { stats: s.stats || {}, topClients: s.topClients || [], topDomains: s.topDomains || [],
      topBlocked: s.topBlockedDomains || [], zones };
  },

  kpis(d) {
    const s = d.stats;
    const pct = s.totalQueries ? (100 * s.totalBlocked) / s.totalQueries : 0;
    return [{ label: 'dns 24h', value: `${s.totalQueries ?? '–'}`, sub: `${s.totalBlocked ?? 0} blocked (${pct.toFixed(0)}%) · ${s.totalClients ?? 0} clients` }];
  },

  // topology/status ref "server" → the API answered with stats
  status(d, ref) {
    return ref === 'server' ? (d.stats ? 'ok' : 'bad') : null;
  },

  views: [{ id: 'resolver', label: 'DNS', icon: 'search', component: ResolverView, min: 'admin' }],
  facets: { machine: MachineFacet },
  tiles: [{ id: 'dns', label: 'dns · technitium 24h', w: 2, h: 1, component: DnsTile, min: 'admin' }],
};
