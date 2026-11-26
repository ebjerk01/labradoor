// prowlarr — indexer health in lab. Stats + back-off status are readable by admins; the indexer config itself
// (/api/v1/indexer: private trackers keep credentials in its fields) is owner-only, so admins see names from the stats.
import { cached, soft, ts, worstOf } from '$lab/sdk.js';
import { healthStatus, healthAlerts } from '$lab/arr/logic.js';
import Facet from './Facet.svelte';
import IndexersTile from './IndexersTile.svelte';

const P = '/api/v1';

export function merge(cfg, stats, status, now) {
  const by = new Map();
  for (const c of cfg || []) by.set(c.id, { id: c.id, name: c.name, enable: c.enable, priority: c.priority, privacy: c.privacy });
  for (const s of stats?.indexers || []) {
    const x = by.get(s.indexerId) || { id: s.indexerId, name: s.indexerName };
    const q = s.numberOfQueries + s.numberOfRssQueries, f = s.numberOfFailedQueries + s.numberOfFailedRssQueries;
    Object.assign(x, { queries: q, grabs: s.numberOfGrabs, failed: f + s.numberOfFailedGrabs, failPct: q ? (100 * f) / q : 0, ms: s.averageResponseTime });
    by.set(x.id, x);
  }
  for (const s of status || []) {
    const x = by.get(s.indexerId) || { id: s.indexerId, name: `#${s.indexerId}` };
    Object.assign(x, { disabledTill: ts(s.disabledTill), failingSince: ts(s.initialFailure), lastFailure: ts(s.mostRecentFailure) });
    by.set(x.id, x);
  }
  return [...by.values()].map((x) => ({
    ...x,
    status: x.enable === false ? 'off' : x.disabledTill && x.disabledTill > now ? 'bad' : x.failPct > 20 ? 'warn' : 'ok',
  })).sort((a, b) => (a.priority ?? 50) - (b.priority ?? 50) || a.name.localeCompare(b.name));
}

export default {
  id: 'prowlarr',

  async load(ctx) {
    const now = Date.now() / 1000;
    const since = new Date((Math.floor(now / 3600) * 3600 - 7 * 86400) * 1000).toISOString();
    const owner = ctx.can('GET', `${P}/indexer`) === 'yes';
    const k = (key) => `${ctx.id}:${key}`;
    const [status, health, stats, ixs, cfg] = await Promise.all([
      cached(k('status'), 600000, () => ctx.api.get(`${P}/system/status`)),
      ctx.api.get(`${P}/health`),
      soft(cached(k('stats'), 300000, () => ctx.api.get(`${P}/indexerstats`, { startDate: since }))),
      soft(cached(k('ixstatus'), 60000, () => ctx.api.get(`${P}/indexerstatus`))),
      owner ? soft(cached(k('cfg'), 600000, () => ctx.api.get(`${P}/indexer`))) : null,
    ]);
    const indexers = merge(cfg, stats, ixs, now);
    return { version: status?.version, health: health || [], indexers, full: !!cfg, apps: stats?.userAgents || [], at: now };
  },

  objects(d, ctx) {
    const down = d.indexers.filter((x) => x.status === 'bad').length;
    const st = worstOf([...d.health.map(healthStatus),
      ...d.indexers.map((x) => (x.status === 'bad' ? 'warn' : 'ok'))]);
    return [{ id: 'prowlarr', type: 'service', name: 'prowlarr', kind: 'indexers', parent: ctx?.settings?.parent || undefined, status: st,
      meta: [d.version && `v${d.version}`, `${d.indexers.filter((x) => x.status !== 'off').length} indexers`, down ? `${down} backed off` : null].filter(Boolean).join(' · ') }];
  },

  alerts: (d) => healthAlerts('prowlarr', 'Prowlarr', d.health),

  kpis(d) {
    const on = d.indexers.filter((x) => x.status !== 'off'), bad = on.filter((x) => x.status === 'bad').length;
    return [{ label: 'indexers', value: `${on.length - bad}/${on.length}`, sub: bad ? `${bad} backed off` : 'all answering', status: bad ? 'warn' : null, open: 'prowlarr' }];
  },

  actions(obj) {
    if (obj.id !== 'prowlarr') return [];
    return [
      { label: 'test all indexers', icon: 'check', method: 'POST', path: `${P}/indexer/testall`, body: {} },
      { label: 'sync indexers to apps', icon: 'restart', method: 'POST', path: `${P}/command`, body: { name: 'ApplicationIndexerSync' } },
      { label: 'check health', icon: 'activity', method: 'POST', path: `${P}/command`, body: { name: 'CheckHealth' } },
    ];
  },

  facets: { service: Facet },
  tiles: [{ id: 'indexers', label: 'indexers', w: 4, h: 1, component: IndexersTile, min: 'admin' }],
};
