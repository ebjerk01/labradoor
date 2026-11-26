// proxmox — a Proxmox VE cluster. Backend = Proxmox's own API (any node) through the gateway with a privilege-separated
// API token from the module config (guests' power/snapshot/backup/migrate/resize/cpu-mem-options, read-only Sys/Datastore
// audit; no users, ACLs, firewall or storage config). Guests merge with other modules' objects by NAME, nodes by node name
// (setting node_names maps Proxmox names to the ids your monitoring uses).
import { ago, bytes, cached } from '$lab/sdk.js';
import MachineFacet from './MachineFacet.svelte';
import ClusterTile from './ClusterTile.svelte';
import TasksTile from './TasksTile.svelte';
import { nodeId, setNodeNames, isGuest, kindOf, gpath, guestOf, guestByVmid, taskOk, taskObject, watchTask } from './pve.svelte.js';

// slow-changing lists: every 5 min, not every 15 s (a failed call keeps the last good list)
const slow = (ctx, key, path) => cached(`proxmox:${key}`, 300000, async () => (await ctx.api.get(path)).data || []).catch(() => []);

const DAY = 86400;

export default {
  id: 'proxmox',

  async load(ctx) {
    setNodeNames(ctx.settings?.node_names);
    const [res, status, tasks, hastat, jobs, ha, repl] = await Promise.all([
      ctx.api.get('/cluster/resources'),
      ctx.api.get('/cluster/status'),
      ctx.api.get('/cluster/tasks'),
      ctx.api.get('/cluster/ha/status/current').catch(() => ({ data: [] })),
      slow(ctx, 'jobs', '/cluster/backup'), slow(ctx, 'ha', '/cluster/ha/resources'), slow(ctx, 'repl', '/cluster/replication'),
    ]);
    return { resources: res.data, cluster: status.data, tasks: tasks.data, haStatus: hastat.data, jobs, ha, repl,
      at: Date.now() / 1000, storage: ctx.settings?.backup_storage || '' };
  },

  objects(d, ctx) {
    const out = [];
    const drift = !!ctx?.peer('drift')?.overview; // a monitoring module with metrics: ours only when it's down
    const haBad = new Set((d.ha || []).filter((h) => h.state === 'error' || h.status === 'error').map((h) => h.sid));
    for (const r of d.resources) {
      if (r.type === 'node') {
        const up = r.status === 'online';
        const n = d.resources.filter((g) => isGuest(g) && g.node === r.node);
        out.push({ id: nodeId(r.node), type: 'machine', name: nodeId(r.node), kind: 'pve node', status: up ? 'ok' : 'bad',
          meta: up ? `${n.filter((g) => g.status === 'running').length}/${n.length} guests · ${r.maxcpu}c · ${bytes(r.maxmem, 0)}` : 'offline',
          cpu: !drift && up ? r.cpu * 100 : undefined, mem: !drift && up && r.maxmem ? (100 * r.mem) / r.maxmem : undefined });
      } else if (isGuest(r)) {
        const run = r.status === 'running';
        const st = r.template ? 'off' : haBad.has(`${r.type === 'lxc' ? 'ct' : 'vm'}:${r.vmid}`) ? 'bad' : run ? 'ok' : r.status === 'paused' ? 'warn' : 'off';
        out.push({ id: r.name, type: 'machine', name: r.name, kind: r.template ? 'template' : kindOf(r), parent: nodeId(r.node), status: st,
          meta: `${run ? `${r.maxcpu}c · ${bytes(r.maxmem, 0)}` : r.status}${r.lock ? ` · locked: ${r.lock}` : ''}`,
          cpu: !drift && run ? r.cpu * 100 : undefined, mem: !drift && run && r.maxmem ? (100 * r.mem) / r.maxmem : undefined });
      }
    }
    return out;
  },

  alerts(d) {
    const out = [];
    const c = d.cluster.find((x) => x.type === 'cluster');
    if (c && !c.quorate) out.push({ key: 'pve:quorum', status: 'bad', title: 'Proxmox cluster has no quorum', detail: `${d.cluster.filter((x) => x.type === 'node' && x.online).length}/${c.nodes} nodes`, since: d.at, object: null });
    for (const h of d.ha || []) {
      if (h.state === 'error') out.push({ key: `pve:ha:${h.sid}`, status: 'bad', title: `HA ${h.sid} in error`, detail: h.comment || '', since: d.at, object: guestByVmid(d, h.sid.split(':')[1])?.name || null });
    }
    const since = d.at - DAY;
    for (const t of d.tasks.filter((x) => x.endtime && x.endtime > since && !taskOk(x)).slice(0, 6)) {
      out.push({ key: `pve:task:${t.upid}`, status: 'warn', title: `${t.type} ${t.id || ''} failed on ${t.node}`.replace('  ', ' '),
        detail: String(t.status).slice(0, 160), since: t.endtime, object: taskObject(d, t) });
    }
    return out;
  },

  kpis(d) {
    const c = d.cluster.find((x) => x.type === 'cluster');
    const nodes = d.cluster.filter((x) => x.type === 'node');
    const on = nodes.filter((x) => x.online).length;
    const running = d.tasks.filter((t) => !t.endtime).length;
    return [{ label: 'cluster', value: `${on}/${nodes.length}`, sub: c?.quorate ? `quorate${running ? ` · ${running} tasks` : ''}` : 'NO QUORUM',
      status: !c?.quorate ? 'bad' : on < nodes.length ? 'warn' : null }];
  },

  ticker(d) {
    return d.tasks.filter((t) => t.endtime).slice(0, 5).map((t) => ({
      g: taskOk(t) ? '●' : '■', c: taskOk(t) ? 'var(--ok)' : 'var(--bad)', s: 'pve',
      m: `${t.type} ${t.id || ''} · ${nodeId(t.node)} · ${ago(t.endtime)} ago`,
    }));
  },

  // header buttons on a guest: power + backup now (snapshots/migrate/resize are in the facet: they need input).
  // Proxmox answers these with a task id at once: `done` watches the task (spinner in the facet, toast when it ends).
  actions(obj, d) {
    const g = guestOf(d, obj);
    if (!g || g.template) return [];
    const p = gpath(g);
    const out = [];
    const task = (what) => (r, ctx) => {
      const upid = r?.data;
      const label = `${what} ${g.name}`;
      if (typeof upid === 'string' && upid.startsWith('UPID:')) { ctx.notify(`${label}: started`); watchTask(ctx, upid, label); } else ctx.notify(`${label} ✓`);
      ctx.refresh();
    };
    if (g.status === 'running') {
      out.push({ label: 'shutdown', icon: 'close', method: 'POST', path: `${p}/status/shutdown`, confirm: `Shut down ${g.name} (${kindOf(g)})?`, done: task('shut down') });
      out.push({ label: 'reboot', icon: 'restart', method: 'POST', path: `${p}/status/reboot`, confirm: `Reboot ${g.name} (${kindOf(g)})?`, done: task('reboot') });
    } else if (g.status === 'stopped') {
      out.push({ label: 'start', icon: 'play', method: 'POST', path: `${p}/status/start`, done: task('start') });
    }
    if (d.storage) out.push({ label: 'backup now', icon: 'archive', method: 'POST', path: `/nodes/${g.node}/vzdump`, done: task('back up'),
      body: { vmid: String(g.vmid), storage: d.storage, mode: 'snapshot', 'notes-template': '{{guestname}} (lab)' } });
    return out;
  },

  status(d, ref) {
    const n = d.resources.find((r) => r.type === 'node' && (r.node === ref || nodeId(r.node) === ref));
    return n ? (n.status === 'online' ? 'ok' : 'bad') : null;
  },

  facets: { machine: MachineFacet },
  tiles: [
    { id: 'cluster', label: 'proxmox', w: 4, h: 1, component: ClusterTile },
    { id: 'tasks', label: 'pve tasks', w: 4, h: 2, component: TasksTile },
  ],
};
