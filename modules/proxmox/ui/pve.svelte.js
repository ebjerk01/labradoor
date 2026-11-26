// proxmox — shared helpers: ids, requests the way the manifest allows them, task watching, lazy GETs.
// Proxmox answers {data: …}; errors {message, errors: {param: text}}.

import { act, errText, watch, watching } from '$lab/sdk.js';
export { errText, watching };

// Proxmox node name → the object id the rest of lab uses, from the module setting `node_names` ("pve=pve1"):
// some installations name a node differently in Proxmox and in their monitoring. Set by load().
let NODE_ID = {};
export function setNodeNames(list) {
  NODE_ID = Object.fromEntries((list || []).map((x) => String(x).split('=').map((y) => y.trim())).filter((x) => x.length === 2 && x[0] && x[1]));
}
export const nodeId = (n) => NODE_ID[n] || n;
export const isGuest = (r) => r.type === 'qemu' || r.type === 'lxc';
export const kindOf = (r) => `${r.type === 'lxc' ? 'CT' : 'VM'} ${r.vmid}`;
export const gpath = (g) => `/nodes/${g.node}/${g.type}/${g.vmid}`;

// the Proxmox guest / node behind a lab object (fresh from the latest data, not the merged object)
export const guestOf = (d, obj) => (d?.resources || []).find((r) => isGuest(r) && r.name === obj.id) || null;
export const nodeOf = (d, obj) => (d?.resources || []).find((r) => r.type === 'node' && nodeId(r.node) === obj.id) || null;
export const guestByVmid = (d, vmid) => (d?.resources || []).find((r) => isGuest(r) && String(r.vmid) === String(vmid)) || null;

// a Proxmox task (UPID) started from this browser: listed in `watching` (module proxmox) until Proxmox says it stopped
export const vmidOfTask = (t) => String(t.id || '').split(':')[6] || '';
export function watchTask(ctx, upid, label) {
  if (typeof upid !== 'string' || !upid.startsWith('UPID:')) return;
  const node = String(upid).split(':')[1] || '';
  const path = `/nodes/${node}/tasks/${encodeURIComponent(upid)}/status`;
  // /cluster/resources (guest status → which buttons show) lags pvestatd's 10 s cycle: refresh until it caught up
  watch(ctx, { id: upid, label, every: 2500, timeout: 3 * 3600e3, refresh: [0, 5000, 11000], check: async () => {
    const st = (await ctx.api.get(path)).data;
    if (!st || st.status !== 'stopped') return null;
    const ok = st.exitstatus === 'OK' || String(st.exitstatus || '').startsWith('WARNINGS');
    return { ok, text: ok ? '' : st.exitstatus };
  } });
}

// Proxmox answers {data: …}: the SDK act with that unwrapped; a UPID answer (async task) is watched until it stops
// instead of an immediate ✓. Returns Proxmox's data ({} if none), or null when nothing ran / it failed.
export const pveData = (r) => r?.data ?? {};
export function pveAct(ctx, method, path, body, label, { quiet = false, done = null } = {}) {
  return act(ctx, { method, path, body, label, quiet, check: pveData, done: (data) => {
    const upid = typeof data === 'string' && data.startsWith('UPID:') ? data : null;
    if (upid) { ctx.notify(`${label}: started`); watchTask(ctx, upid, label); }
    if (done) done(data);
    return !!upid;  // a task: the watcher toasts + refreshes when it ends
  } });
}

// disks in a guest config: [{key, vol, storage, size}] (no cd-roms, no efi/tpm state, no unused)
const DISK = /^(rootfs|mp\d+|scsi\d+|virtio\d+|sata\d+|ide\d+)$/;
export function disks(cfg) {
  const out = [];
  for (const [k, v] of Object.entries(cfg || {})) {
    if (!DISK.test(k) || typeof v !== 'string' || /media=cdrom/.test(v) || v.startsWith('none')) continue;
    const vol = v.split(',')[0];
    out.push({ key: k, vol, storage: vol.split(':')[0], size: (v.match(/size=([^,]+)/) || [])[1] || '?',
      mp: (v.match(/mp=([^,]+)/) || [])[1] || '' });
  }
  const order = (k) => (k === 'rootfs' ? '0' : k);
  return out.sort((a, b) => order(a.key).localeCompare(order(b.key), 'en', { numeric: true }));
}

export function nets(cfg) {
  return Object.entries(cfg || {}).filter(([k]) => /^net\d+$/.test(k)).map(([k, v]) => {
    const p = Object.fromEntries(String(v).split(',').map((x) => x.split('=')));
    const mac = p.hwaddr || Object.entries(p).find(([key]) => /^(virtio|e1000|e1000e|rtl8139|vmxnet3)$/.test(key))?.[1] || '';
    return { key: k, bridge: p.bridge || '', mac, ip: p.ip || '', tag: p.tag || '' };
  });
}

// backup jobs (cluster/backup) that include this guest
export function jobsFor(jobs, vmid) {
  const id = String(vmid);
  return (jobs || []).filter((j) => {
    if (j.enabled === 0 || j.enabled === '0') return false;
    if (j.all === 1 || j.all === '1') return !String(j.exclude || '').split(',').map((s) => s.trim()).includes(id);
    return String(j.vmid || '').split(',').map((s) => s.trim()).includes(id);
  });
}

// a guest/node object id for a task ("vzdump 104" → the guest's name)
export function taskObject(d, t) {
  const g = t.id && /^\d+$/.test(String(t.id)) ? guestByVmid(d, t.id) : null;
  return g ? g.name : nodeId(t.node);
}

export const taskOk = (t) => !t.status || t.status === 'OK' || String(t.status).startsWith('WARNINGS');

// which facet tab is open (survives switching objects)
export const ui = $state({ tab: 'cfg' });

// a snapshot name Proxmox accepts: letter first, then letters/digits/_/-, ≤ 40
export const SNAP_RE = /^[a-zA-Z][a-zA-Z0-9_-]{1,39}$/;
export const stamp = () => new Date().toISOString().slice(0, 16).replace(/[-:]/g, '').replace('T', '-');
