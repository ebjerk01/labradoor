// pbs — Proxmox Backup Server. Backend = PBS's own API with the API token from the module config (system audit,
// DatastoreAdmin on the datastore: GC/prune/verify, forget + protect snapshots; RemoteSyncPushOperator for the
// owner-only "run sync job"). The encryption key is client-side on the PVE nodes: nothing here can reach it.
// Objects: "pbs" (service, under settings.host_object). Facets: pbs → datastore + jobs + tasks; a guest → its backups.
// Load: the summary (usage, tasks) every refresh; the job lists, backup groups and the week RRD are cached.
import { ago, bytes, cached, soft } from '$lab/sdk.js';
import ServiceFacet from './ServiceFacet.svelte';
import GuestBackups from './GuestBackups.svelte';
import BackupsView from './BackupsView.svelte';
import PbsTile from './PbsTile.svelte';
import { DAY, storeOf, dsOf, jobOk, jobsOf, usageLevel, fullSoon, pbsStatus, growthPerDay, taskOk, hostOf } from './pbs.svelte.js';

export default {
  id: 'pbs',

  async load(ctx) {
    const store = storeOf(ctx);
    const since = Math.floor(Date.now() / 1000) - DAY;
    const [usage, tasks, jobs, groups, growth] = await Promise.all([
      ctx.api.get('/status/datastore-usage'),
      ctx.api.get('/nodes/localhost/tasks', { since, limit: 200 }),
      cached(`${ctx.id}:jobs`, 120000, async () => {
        const [gc, prune, verify, sync] = await Promise.all([
          ctx.api.get('/admin/gc'), ctx.api.get('/admin/prune'), ctx.api.get('/admin/verify'),
          ctx.api.get('/admin/sync', { 'sync-direction': 'all' }),
        ]);
        return { gc: gc.data, prune: prune.data, verify: verify.data, sync: sync.data };
      }),
      soft(cached(`${ctx.id}:groups:${store}`, 120000, async () => (await ctx.api.get(`${dsOf(store)}/groups`)).data), []),
      soft(cached(`${ctx.id}:growth:${store}`, 300000, async () =>
        growthPerDay((await ctx.api.get(`${dsOf(store)}/rrd`, { timeframe: 'week', cf: 'AVERAGE' })).data)), null),
    ]);
    // lab's own full-date estimate replaces PBS's (see growthPerDay); PBS's stays as pbs-estimated-full-date
    const now = Date.now() / 1000;
    const stores = (usage.data || []).map((s) => (s.store !== store ? s : {
      ...s, 'pbs-estimated-full-date': s['estimated-full-date'],
      'estimated-full-date': growth > 0 ? Math.round(now + (s.avail / growth) * DAY) : 0, 'growth-per-day': growth,
    }));
    return { store, usage: stores, ...jobs, tasks: tasks.data, groups, at: now };
  },

  objects(d, ctx) {
    const h = hostOf(d);
    const u = h?.total ? h.used / h.total : 0;
    return [{ id: 'pbs', type: 'service', name: 'pbs', kind: 'backup server', parent: ctx.settings?.host_object || undefined, status: pbsStatus(d),
      meta: h ? `${d.store} ${Math.round(u * 100)}% · ${d.groups.length} guests · ${bytes(h.avail, 0)} free` : `${d.store} missing` }];
  },

  alerts(d) {
    const out = [];
    for (const s of d.usage) {
      const u = s.total ? s.used / s.total : 0;
      if (usageLevel(u) !== 'ok') out.push({ key: `pbs:usage:${s.store}`, status: usageLevel(u), title: `PBS ${s.store} ${Math.round(u * 100)}% full`, detail: `${bytes(s.avail, 0)} free`, since: d.at, object: 'pbs' });
      else if (s.store === d.store && fullSoon(s, d.at)) out.push({ key: `pbs:full:${s.store}`, status: 'warn', title: `PBS ${s.store} full in ~${Math.max(0, Math.round((s['estimated-full-date'] - d.at) / DAY))} d (estimate)`, detail: `${Math.round(u * 100)}% used · ${bytes(s.avail, 0)} free`, since: d.at, object: 'pbs' });
    }
    for (const j of jobsOf(d)) {
      if (jobOk(j.raw) || (j.kind === 'sync' && !j.schedule)) continue; // a manual sync job is the owner's call
      out.push({ key: `pbs:job:${j.id}`, status: 'warn', title: `PBS ${j.kind} ${j.id}: ${j.state}`, detail: j.store, since: j.last, object: 'pbs' });
    }
    return out;
  },

  kpis(d) {
    const h = hostOf(d);
    if (!h) return [];
    const u = h.used / h.total;
    const left = h['estimated-full-date'] > 0 ? Math.round((h['estimated-full-date'] - d.at) / DAY) : null;
    return [{ label: 'pbs', value: `${Math.round(u * 100)}%`, sub: left != null ? `full ~${left}d` : `${bytes(h.avail, 0)} free`, open: 'pbs',
      status: usageLevel(u) !== 'ok' ? usageLevel(u) : fullSoon(h, d.at) ? 'warn' : null }];
  },

  ticker(d) {
    return d.tasks.filter((t) => t.endtime && t.worker_type !== 'logrotate' && t.worker_type !== 'aptupdate').slice(0, 5).map((t) => ({
      g: taskOk(t) ? '●' : '■', c: taskOk(t) ? 'var(--ok)' : 'var(--bad)', s: 'pbs', m: `${t.worker_type} ${t.worker_id || ''} · ${ago(t.endtime)} ago`, object: 'pbs' }));
  },

  status(d, ref) {
    return ref === 'pbs' || ref === d.store ? pbsStatus(d) : null;
  },

  facets: { service: ServiceFacet, machine: GuestBackups },
  views: [{ id: 'pbs-backups', label: 'Backups', icon: 'archive', component: BackupsView, min: 'admin' }],
  tiles: [{ id: 'pbs', label: 'backup datastore', w: 4, h: 1, component: PbsTile }],
};
