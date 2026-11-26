// graylog — logs everywhere. Backend = Graylog's own REST API through the gateway with a service account's access token
// from the module config (Reader + create streams: search all streams, read streams/views/event definitions). Graylog wants X-Requested-By on POST: manifest backend.headers.
// Every object (machine / service / external) gets a log section; the logs view searches, tails and lists streams.
import LogFacet from './LogFacet.svelte';
import LogsView from './LogsView.svelte';
import RateTile from './RateTile.svelte';
import NoisyTile from './NoisyTile.svelte';
import ErrorsTile from './ErrorsTile.svelte';
import { cached, soft } from '$lab/sdk.js';
import { searchLogs } from './state.svelte.js';
import { cfgOf, idOf, queryFor, webUrl, aggregate, series, messages, ts, one, short, ERRORS } from './gl.js';

const MIN = 60000;
// Slow-changing parts come from the shell's cache, not every refresh: sources last hour + events 1 min; the 24 h
// breakdown, streams, saved views, event definitions, index health 5 min; the error list 30 s. A failed call keeps
// the last good value.
const part = (ctx, key, ttl, fn, fallback) => soft(cached(`${ctx.id}:${key}`, ttl, fn), fallback);

// per source: 1h (5 min buckets) and 24h (hourly) counts, where it maps in lab
function sources(m, s, cfg, objects) {
  const by = new Map();
  const get = (src) => by.get(src) || by.set(src, { src, n1h: 0, m60: [], n24h: 0, h24: [], last: 0, lastH: 0 }).get(src);
  for (const [src, t, n] of m.recent || []) { const x = get(src); x.n1h += n; x.m60.push(n); if (n) x.last = Math.max(x.last, ts(t)); }
  for (const [src, t, n] of s.hourly || []) { const x = get(src); x.n24h += n; x.h24.push(n); if (n) x.lastH = Math.max(x.lastH, ts(t)); }
  // last = start of the newest bucket with lines (5 min precision in the last hour, else 1 h)
  return [...by.values()].map(({ lastH, ...x }) => ({ ...x, last: x.last || lastH || null, ...idOf(x.src, cfg, objects) }))
    .sort((a, b) => b.n1h - a.n1h || b.n24h - a.n24h);
}

// a source that sent in ≥20 of the last 23 full hours and nothing for the last 30 minutes
const silent = (x) => x.h24.slice(0, -1).filter(Boolean).length >= 20 && x.m60.slice(-6).every((n) => !n);

export default {
  id: 'graylog',

  async load(ctx) {
    const cfg = cfgOf(ctx);
    const [rate, journal, errors, recent, events, hourly, apps, streams, views, defs, indexer] = await Promise.all([
      series(ctx, '*', 3600, '1m'),
      ctx.api.get('/api/system/journal').catch(() => null),
      part(ctx, 'errors', 30000, async () => {
        const [by, lines] = await Promise.all([
          aggregate(ctx, ERRORS, 3600, [{ field: 'source', limit: 20 }]).catch(() => []),
          messages(ctx, ERRORS, { range: 3600, limit: 12 }).catch(() => ({ total: 0, list: [] })),
        ]);
        return { by, lines: lines.list };
      }, { by: [], lines: [] }),
      part(ctx, 'recent', MIN, () => aggregate(ctx, '*', 3600, [{ field: 'source', limit: 300 }, { field: 'timestamp', timeunit: '5m' }]), []),
      part(ctx, 'events', MIN, async () => (await ctx.api.post('/api/events/search', { query: '', page: 1, per_page: 30, sort_by: 'timestamp',
        sort_direction: 'desc', timerange: { type: 'relative', range: 7 * 86400 } })).events?.map((e) => e.event) || [], []),
      part(ctx, 'hourly', 5 * MIN, () => aggregate(ctx, '*', 86400, [{ field: 'source', limit: 300 }, { field: 'timestamp', timeunit: '1h' }]), []),
      part(ctx, 'apps', 5 * MIN, async () => (await aggregate(ctx, '*', 86400, [{ field: 'application_name', limit: 300 }])).map((r) => r[0]).filter((a) => a && !a.startsWith('(')), []),
      part(ctx, 'streams', 5 * MIN, async () => (await ctx.api.get('/api/streams')).streams || [], []),
      part(ctx, 'views', 5 * MIN, async () => (await ctx.api.get('/api/views', { per_page: 200 })).views || [], []),
      part(ctx, 'defs', 5 * MIN, async () => (await ctx.api.get('/api/events/definitions', { per_page: 200 })).event_definitions || [], []),
      part(ctx, 'indexer', 5 * MIN, async () => { const x = await ctx.api.get('/api/system/indexer/overview'); return {
        health: x.indexer_cluster?.health?.status, events: x.counts?.events,
        bytes: (x.indices || []).reduce((a, i) => a + (i.size?.bytes || 0), 0), indices: (x.indices || []).length }; }, null),
    ]);
    const src = sources({ recent }, { hourly }, cfg, ctx.objects());
    return {
      at: Date.now() / 1000, cfg, rate, perMin: rate.length > 1 ? rate.at(-2) : rate.at(-1) || 0,
      perHour: rate.reduce((a, b) => a + b, 0),
      errors: { total: errors.by.reduce((a, r) => a + r[1], 0), bySrc: errors.by, lines: errors.lines },
      journal: journal && { uncommitted: journal.uncommitted_journal_entries, size: journal.journal_size, limit: journal.journal_size_limit },
      sources: src, silent: src.filter(silent), apps, streams, views, defs, indexer, events,
    };
  },

  alerts(d) {
    const out = d.silent.map((x) => ({
      key: `graylog:silent:${x.src}`, status: 'warn', title: `no logs from ${x.src} for 30m+`,
      detail: `${short(x.n24h)} lines in 24h, now quiet: rsyslog/forwarding stopped?`, since: x.last || null, object: x.known ? x.id : null,
    }));
    if (d.journal?.uncommitted > 100000) out.push({ key: 'graylog:journal', status: 'warn', title: `Graylog journal backlog ${short(d.journal.uncommitted)}`,
      detail: 'messages wait to be indexed (OpenSearch/datanode slow or down)', object: d.cfg.self });
    if (d.indexer?.health && d.indexer.health !== 'green') out.push({ key: 'graylog:indexer', status: d.indexer.health === 'red' ? 'bad' : 'warn',
      title: `Graylog index cluster ${d.indexer.health}`, object: d.cfg.self });
    const alerting = new Set(d.defs.filter((x) => x.alert).map((x) => x.id));
    const hour = Date.now() / 1000 - 3600;
    for (const e of d.events.filter((x) => alerting.has(x.event_definition_id) && ts(x.timestamp) > hour)) {
      out.push({ key: `graylog:event:${e.event_definition_id}`, status: e.priority >= 3 ? 'bad' : 'warn', title: one(e.message, 120),
        detail: 'Graylog event', since: ts(e.timestamp), object: null });
    }
    return out.filter((a, i) => out.findIndex((b) => b.key === a.key) === i);
  },

  kpis(d) {
    return [{ label: 'logs', value: `${short(d.perMin)}/m`, sub: `${short(d.errors.total)} err 1h · ${d.sources.filter((x) => x.n1h).length} sources`,
      status: d.silent.length ? 'warn' : null, view: 'graylog-logs' }];
  },

  ticker(d) {
    return d.errors.lines.slice(0, 4).map((m) => ({ g: '■', c: 'var(--bad)', s: m.source, m: one(`${m.application_name || ''}: ${m.message}`, 140), view: 'graylog-logs' }));
  },

  // topology refs: the Graylog server's own object (ingest + index health)
  status(d, ref) {
    if (ref !== d.cfg.self) return null;
    if (d.indexer?.health === 'red') return 'bad';
    return d.indexer?.health === 'yellow' || d.journal?.uncommitted > 100000 || d.silent.length ? 'warn' : 'ok';
  },

  // "open in Graylog" only when the web address is set; the in-lab search is the facet's button
  actions(obj, d) {
    const qf = queryFor(obj, d);
    const url = qf && webUrl(d.cfg, qf.q);
    return url ? [{ label: 'open in graylog', icon: 'ext', url }] : [];
  },

  search(d) {
    return d.sources.slice(0, 40).map((x) => ({ label: `logs ${x.src}`, sub: `${short(x.n1h)} 1h${x.known ? '' : ' · no object'}`,
      ...(x.known ? { object: x.id } : webUrl(d.cfg, `source:"${x.src}"`) ? { url: webUrl(d.cfg, `source:"${x.src}"`) } : {}) }));
  },

  // Ctrl-K: "logs <text>", "grep <text>" or a Lucene query (field:value) → run that search in the logs view
  async lookup(q, ctx) {
    const m = /^(?:logs?|grep|search)\s+(\S.*)$/i.exec(q.trim());
    const query = m ? m[1] : /\w:\S|"/.test(q) ? q.trim() : null;
    return query ? [{ label: `grep logs: ${query}`, sub: 'graylog · last hour', run: () => searchLogs(ctx, { q: query }) }] : [];
  },

  views: [{ id: 'graylog-logs', label: 'Logs', icon: 'search', component: LogsView, min: 'admin' }],
  facets: { machine: LogFacet, service: LogFacet, external: LogFacet },
  tiles: [
    { id: 'rate', label: 'logs/min', w: 2, h: 1, component: RateTile, min: 'admin' },
    { id: 'noisy', label: 'noisiest sources 1h', w: 4, h: 2, component: NoisyTile, min: 'admin' },
    { id: 'errors', label: 'log errors 1h', w: 4, h: 2, component: ErrorsTile, min: 'admin' },
  ],
};
