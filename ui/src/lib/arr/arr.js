// The module object for one *arr app (Sonarr or Radarr, v3 API): modules/sonarr/ui/index.js and modules/radarr/ui/index.js
// are `export default createArr('<app>')` over this shared SDK file ($lab/arr/arr.js). Backend = the app's own API
// through the gateway with its API key (never in the browser).
import { cached, soft, ts, worstOf, clip } from '../sdk.js';
import ArrFacet from './ArrFacet.svelte';
import LibraryView from './LibraryView.svelte';
import { A, APPS, PROBLEM_STATES, groupQueue, calendarItems, disks, healthStatus, healthAlerts } from './logic.js';

export async function loadArr(ctx, app) {
  const days = Number(ctx.settings?.calendar_days) || 7;
  const now = Date.now() / 1000;
  // whole days, so the cache key and the window stay stable between refreshes
  const start = Math.floor(now / 86400) * 86400 - 86400, end = start + (days + 2) * 86400;
  const iso = (t) => new Date(t * 1000).toISOString();
  const calQ = { start: iso(start), end: iso(end), unmonitored: 'false', ...(app === 'sonarr' ? { includeSeries: 'true' } : {}) };
  const problemsQ = [['pageSize', '250'], ['includeUnknownSeriesItems', 'true'], ...PROBLEM_STATES.map((s) => ['status', s])];
  const k = (key) => `${ctx.id}:${key}`;
  const [status, health, qs, problems, missing, cutoff, cal, disk, cmds] = await Promise.all([
    cached(k('status'), 600000, () => ctx.api.get(`${A}/system/status`)),
    ctx.api.get(`${A}/health`),
    ctx.api.get(`${A}/queue/status`),
    cached(k('problems'), 45000, () => ctx.api.get(`${A}/queue`, problemsQ)),
    soft(cached(k('missing'), 300000, () => ctx.api.get(`${A}/wanted/missing`, { pageSize: 1, monitored: 'true' }))),
    soft(cached(k('cutoff'), 300000, () => ctx.api.get(`${A}/wanted/cutoff`, { pageSize: 1, monitored: 'true' }))),
    soft(cached(k(`cal${days}`), 300000, () => ctx.api.get(`${A}/calendar`, calQ))),
    soft(cached(k('disk'), 300000, () => ctx.api.get(`${A}/diskspace`))),
    soft(cached(k('cmds'), 20000, () => ctx.api.get(`${A}/command`))),
  ]);
  const groups = groupQueue(problems?.records);
  const probs = groups.filter((g) => g.level);
  return {
    app, version: status?.version, health: health || [],
    queue: { total: qs?.totalCount ?? 0, errors: qs?.errors, warnings: qs?.warnings, problems: probs, imports: groups.filter((g) => g.needsImport),
      bad: probs.filter((g) => g.level === 'bad').length, blocked: probs.filter((g) => g.level === 'warn').length },
    missing: missing?.totalRecords ?? null, cutoff: cutoff?.totalRecords ?? null,
    upcoming: calendarItems(app, cal, start, end).filter((x) => x.at).sort((a, b) => a.at - b.at),
    disks: disks(disk),
    running: (cmds || []).filter((c) => c.status === 'started' || c.status === 'queued').map((c) => ({ name: c.name, status: c.status, started: ts(c.started) })),
    at: now,
  };
}

export function arrStatus(d, settings = {}) {
  const h = d.health.map(healthStatus);
  if (d.queue.bad) h.push('warn');
  if (d.queue.blocked && settings.alert_blocked !== false) h.push('warn');
  return worstOf(h);
}

const SEARCH_CONFIRM = (a, d) => `Search for every missing ${a.noun} in ${a.name}${d.missing != null ? ` (${d.missing})` : ''}? This hits the indexers hard.`;

export function arrActions(app, d) {
  const a = APPS[app];
  return [
    { label: `search missing ${a.noun}`, icon: 'search', method: 'POST', path: `${A}/command`, body: { name: a.missingCmd }, confirm: SEARCH_CONFIRM(a, d) },
    { label: `refresh ${a.item}`, icon: 'restart', method: 'POST', path: `${A}/command`, body: { name: a.refreshCmd } },
    { label: 'rescan downloads', icon: 'download', method: 'POST', path: `${A}/command`, body: { name: 'RefreshMonitoredDownloads' } },
    { label: 'check health', icon: 'check', method: 'POST', path: `${A}/command`, body: { name: 'CheckHealth' } },
  ];
}

export function createArr(app) {
  const a = APPS[app];
  return {
    id: app,
    load: (ctx) => loadArr(ctx, app),

    objects(d, ctx) {
      const meta = [d.version && `v${d.version}`, `${d.queue.total} queued`, d.queue.bad + d.queue.blocked ? `${d.queue.bad + d.queue.blocked} stuck` : null,
        d.missing != null ? `${d.missing} missing` : null].filter(Boolean).join(' · ');
      return [{ id: app, type: 'service', name: app, kind: a.label, parent: ctx?.settings?.parent || undefined, status: arrStatus(d, ctx?.settings), meta }];
    },

    alerts(d, ctx) {
      const out = healthAlerts(app, a.name, d.health);
      if (d.queue.bad) out.push({ key: `${app}:queue:failed`, status: 'warn', title: `${a.name}: ${d.queue.bad} failed download${d.queue.bad > 1 ? 's' : ''}`,
        detail: d.queue.problems.filter((g) => g.level === 'bad').slice(0, 3).map((g) => clip(g.title, 50)).join(', '), since: null, object: app });
      if (d.queue.blocked && ctx?.settings?.alert_blocked !== false) out.push({ key: `${app}:queue:blocked`, status: 'warn',
        title: `${a.name}: ${d.queue.blocked} download${d.queue.blocked > 1 ? 's' : ''} blocked from import`, detail: clip(d.queue.problems.find((g) => g.level === 'warn')?.reason, 120), since: null, object: app });
      return out;
    },

    kpis(d) {
      const stuck = d.queue.bad + d.queue.blocked;
      return [{ label: a.label, value: `${d.queue.total}`, sub: `${stuck} stuck · ${d.missing ?? '–'} missing`,
        status: d.queue.bad ? 'warn' : null, open: app }];
    },

    ticker(d) {
      const out = d.running.slice(0, 2).map((c) => ({ g: '●', c: 'var(--sig)', s: app, m: `running ${c.name}`, object: app }));
      const now = Date.now() / 1000;
      for (const u of d.upcoming.filter((x) => x.at > now - 3600 && x.at < now + 86400).slice(0, 3)) {
        out.push({ g: u.hasFile ? '●' : '○', c: u.hasFile ? 'var(--ok)' : 'var(--dim)', s: app, m: `${u.title} · ${u.sub}`, object: app });
      }
      return out;
    },

    actions: (obj, d) => (obj.id === app ? arrActions(app, d) : []),

    facets: { service: ArrFacet },
    views: [{ id: a.view, label: a.viewLabel, icon: 'play', component: LibraryView, min: 'admin' }],
  };
}
