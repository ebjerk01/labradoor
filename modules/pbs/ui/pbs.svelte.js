// pbs — shared helpers: datastore paths, task watching, guest <-> backup group, job/usage status.
import { watch, forget } from '$lab/sdk.js';

export const STALE_S = 36 * 3600;
export const DAY = 86400;

// the datastore lab shows (setting `store`) and its route prefix
export const storeOf = (ctx) => ctx?.settings?.store || 'homelab';
export const dsOf = (store) => `/admin/datastore/${encodeURIComponent(store)}`;

// "CT 104" / "VM 103" (the kind drift and proxmox give guests) → {type: 'ct'|'vm', id: '104'}
export function guestRef(obj, ctx) {
  const m = /^(CT|VM) (\d+)$/.exec(obj?.kind || '');
  if (m) return { type: m[1] === 'CT' ? 'ct' : 'vm', id: m[2] };
  const g = (ctx.peer('proxmox')?.resources || []).find((r) => (r.type === 'lxc' || r.type === 'qemu') && r.name === obj?.id);
  return g ? { type: g.type === 'lxc' ? 'ct' : 'vm', id: String(g.vmid) } : null;
}

// backup group → the lab object (guest name) if Proxmox/drift know the vmid; else null
export function groupObject(type, id, ctx) {
  const pt = type === 'ct' ? 'lxc' : 'qemu';
  const g = (ctx.peer('proxmox')?.resources || []).find((r) => r.type === pt && String(r.vmid) === String(id));
  if (g) return g.name;
  const kind = `${type === 'ct' ? 'CT' : 'VM'} ${id}`;
  for (const o of ctx.objects().values()) if (o.kind === kind) return o.id;
  return null;
}

export const snapQuery = (s) => ({ 'backup-type': s['backup-type'], 'backup-id': s['backup-id'], 'backup-time': s['backup-time'] });
export const iso = (t) => new Date(t * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z');
export const volid = (s, storage) => `${storage}:backup/${s['backup-type']}/${s['backup-id']}/${iso(s['backup-time'])}`;
export const jobOk = (j) => !j['last-run-state'] || j['last-run-state'] === 'OK';
export const taskOk = (t) => !t.status || t.status === 'OK' || String(t.status).startsWith('WARNINGS');

// done: for ActionButton/act. A PBS write that starts a task answers {data: "UPID:…"}: follow it until it stops, then
// toast + refresh (the cached job list is dropped first so the refresh shows the new state).
export const watchUpid = (label) => (r, ctx) => {
  const upid = r?.data;
  if (typeof upid !== 'string' || !upid.startsWith('UPID:')) return false;
  watch(ctx, {
    label, id: upid, every: 3000, first: 1500, timeout: 6 * 3600e3, refresh: [0, 5000],
    check: async () => {
      const st = (await ctx.api.get(`/nodes/localhost/tasks/${encodeURIComponent(upid)}/status`)).data;
      if (st?.status !== 'stopped') return null;
      forget(`${ctx.id}:*`);
      const ok = st.exitstatus === 'OK' || String(st.exitstatus || '').startsWith('WARNINGS');
      return { ok, text: ok ? undefined : st.exitstatus };
    },
  });
  return true;
};

export function usageLevel(u) {
  return u >= 0.95 ? 'bad' : u >= 0.85 ? 'warn' : 'ok';
}
export const fullSoon = (s, now) => s['estimated-full-date'] > 0 && s['estimated-full-date'] - now < 14 * DAY;

// Bytes/day the datastore grows, from PBS's week RRD: the MEDIAN of the daily changes, so a one-off jump (moving
// every backup to PBS) doesn't count. PBS's own "estimated-full-date" is a straight line over the month and can say
// "full in 4 days" at 51 % used. null = not enough data.
export function growthPerDay(rrd) {
  const pts = (rrd || []).filter((x) => x && x.used > 0).sort((a, b) => a.time - b.time);
  const days = new Map();
  for (const x of pts) days.set(Math.floor(x.time / DAY), x.used);  // last value of each day
  const v = [...days.values()];
  if (v.length < 3) return null;
  const deltas = v.slice(1).map((x, i) => x - v[i]).sort((a, b) => a - b);
  return deltas[Math.floor(deltas.length / 2)];
}

// all jobs as one list: [{kind, id, store, state, last, next, upid, schedule, raw}]
export function jobsOf(d) {
  const j = [];
  for (const g of d.gc || []) j.push({ kind: 'gc', id: `gc-${g.store}`, store: g.store, schedule: g.schedule, raw: g });
  for (const x of d.prune || []) j.push({ kind: 'prune', id: x.id, store: x.store, schedule: x.schedule, raw: x });
  for (const x of d.verify || []) j.push({ kind: 'verify', id: x.id, store: x.store, schedule: x.schedule, raw: x });
  for (const x of d.sync || []) j.push({ kind: 'sync', id: x.id, store: x.store, schedule: x.schedule || '', raw: x, remote: `${x.remote}/${x['remote-store']}`, dir: x['sync-direction'] });
  return j.map((x) => ({ ...x, state: x.raw['last-run-state'] || '', last: x.raw['last-run-endtime'] || 0, next: x.raw['next-run'] || 0,
    upid: x.raw['last-run-upid'] || x.raw.upid || '' }));
}

export const hostOf = (d) => d.usage.find((s) => s.store === d.store);

// the pbs object's status: datastore missing → bad; ≥95 % → bad; ≥85 %, a failed GC/prune/verify or full within 14 d → warn
export function pbsStatus(d) {
  const h = hostOf(d);
  if (!h) return 'bad';
  const u = h.total ? h.used / h.total : 0;
  const bad = jobsOf(d).filter((j) => j.kind !== 'sync' && !jobOk(j.raw));
  return usageLevel(u) === 'bad' ? 'bad' : usageLevel(u) === 'warn' || bad.length || fullSoon(h, d.at) ? 'warn' : 'ok';
}
