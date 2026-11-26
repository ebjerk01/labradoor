// ad — Active Directory in lab. Backend = the lab connector connectors/ad (:8115 on the lab CT), LDAPS to the DC as a
// delegated service account (domain, OUs and account names live in the connector's env and arrive in the data).
// Reading: admin; every change is identity → owner only (an admin's click asks the owner). Objects: aduser:<sam>,
// adgroup:<name>, and computers — merged into the existing machine object when the hostname matches, else
// adcomputer:<name>. Authentik's LDAP source syncs the users OU into Authentik (username_link); the facets show that
// link and its pitfalls.
import DirectoryView from './DirectoryView.svelte';
import UserFacet from './UserFacet.svelte';
import GroupFacet from './GroupFacet.svelte';
import ComputerFacet from './ComputerFacet.svelte';
import LockedTile from './LockedTile.svelte';
import ExpiringTile from './ExpiringTile.svelte';
import ChangesTile from './ChangesTile.svelte';
import { UP, DAY, pwLeft, pwState, userStatus, isBuiltin, expiryDays, machineIds, computerId, recent } from './ad.js';
import { ago } from '$lab/sdk.js';

const day = (s) => (s < DAY ? `${Math.max(1, Math.round(s / 3600))}h` : `${Math.floor(s / DAY)}d`);

export default {
  id: 'ad',

  async load(ctx) {
    return ctx.api.get('/api/directory');
  },

  objects(d, ctx) {
    const days = expiryDays(ctx);
    const out = [];
    for (const u of d.users) {
      const p = pwState(u, days);
      out.push({ id: `aduser:${u.sam}`, type: 'aduser', name: u.name || u.sam, kind: u.service ? 'AD service account' : isBuiltin(u, d) ? 'AD built-in' : 'AD user',
        status: userStatus(u, days), sam: u.sam, ownerOnly: 'identity · active directory',
        meta: `${u.sam} · ${u.enabled ? '' : 'disabled · '}${u.locked ? 'LOCKED · ' : ''}${p.t} · ${u.lastLogon ? 'logon ' + ago(u.lastLogon, ctx.now) + ' ago' : 'never logged on'}` });
    }
    for (const g of d.groups) {
      if (!g.managed && isBuiltin(g, d) && !(ctx?.settings?.builtin)) continue;
      out.push({ id: `adgroup:${g.name}`, type: 'adgroup', name: g.name, kind: `AD ${g.scope} ${g.kind}`, status: 'ok',
        meta: `${g.members.length} members${g.description ? ' · ' + g.description : ''}`, ownerOnly: 'identity · active directory' });
    }
    const ids = machineIds(ctx);
    for (const c of d.computers) {
      const { id, merged } = computerId(c, ctx, ids);
      // merged: only add the AD facet's handle; drift/proxmox/manage own name, kind, status and metrics
      out.push(merged ? { id, type: 'machine', adComputer: c.name }
        : { id, type: 'adcomputer', name: c.name, kind: c.dc ? 'domain controller' : 'AD computer', adComputer: c.name,
          status: c.enabled ? 'ok' : 'off', meta: `${c.os || 'no OS reported'} · ${c.lastLogon ? 'logon ' + ago(c.lastLogon, ctx.now) + ' ago' : 'never logged on'}` });
    }
    return out;
  },

  alerts(d, ctx) {
    const days = expiryDays(ctx);
    const out = [];
    for (const u of d.users.filter((x) => x.enabled)) {
      if (u.locked) {
        out.push({ key: `ad:locked:${u.sam}`, status: 'bad', title: `AD account ${u.sam} is locked out`,
          detail: `${u.badPwdCount || 0} bad passwords${u.badPasswordTime ? ', last ' + ago(u.badPasswordTime, ctx.now) + ' ago' : ''} · unlock in its panel`,
          since: u.lockoutTime, object: `aduser:${u.sam}` });
      }
      if (u.mustChange) continue; // a fresh/reset account waiting for its first logon is not "expiring"
      const left = pwLeft(u);
      if (left == null) continue;
      if (left <= 0) out.push({ key: `ad:pwexpired:${u.sam}`, status: 'warn', title: `AD password of ${u.sam} has expired`,
        detail: `expired ${ago(u.pwdExpires, ctx.now)} ago${u.service ? ' — a service account: whatever binds with it now fails' : ''}`, since: u.pwdExpires, object: `aduser:${u.sam}` });
      else if (left < days * DAY) out.push({ key: `ad:pwexpiry:${u.sam}`, status: 'warn', title: `AD password of ${u.sam} expires in ${day(left)}`,
        detail: `set ${u.pwdLastSet ? ago(u.pwdLastSet, ctx.now) + ' ago' : '–'} · the user changes it (Authentik writes it back) or reset it here`, since: null, object: `aduser:${u.sam}` });
    }
    return out;
  },

  kpis(d, ctx) {
    const days = expiryDays(ctx);
    const en = d.users.filter((u) => u.enabled);
    const locked = en.filter((u) => u.locked).length;
    const exp = en.filter((u) => { const l = pwLeft(u); return !u.mustChange && l != null && l < days * DAY; }).length;
    const first = en.find((u) => u.locked) || en.find((u) => { const l = pwLeft(u); return !u.mustChange && l != null && l < days * DAY; });
    return [{ label: 'AD', value: `${en.length}`, sub: `${locked ? locked + ' locked · ' : ''}${exp ? exp + ' pw expiring · ' : ''}${d.computers.length} computers`,
      ...(first ? { open: `aduser:${first.sam}` } : { view: 'ad-directory' }) }];
  },

  ticker(d, ctx) {
    const hour = Date.now() / 1000 - 3600;
    return recent(d, 5).filter((x) => x.t > hour).map((x) => ({ g: '●', c: 'var(--sig)', s: 'ad', object: x.id || undefined, m: `${x.k} ${x.name} changed · ${ago(x.t, ctx.now)} ago` }));
  },

  search(d) {
    return [
      ...d.users.map((u) => ({ label: `AD ${u.sam}`, sub: `${u.name} · ${u.enabled ? 'enabled' : 'disabled'}${u.locked ? ' · LOCKED' : ''}`, object: `aduser:${u.sam}`, status: userStatus(u) })),
      ...d.groups.filter((g) => g.managed).map((g) => ({ label: `AD group ${g.name}`, sub: `${g.members.length} members`, object: `adgroup:${g.name}` })),
    ];
  },

  actions(obj, d) {
    if (obj.type !== 'aduser') return [];
    const u = d.users.find((x) => x.sam === obj.sam);
    if (!u || !u.managed) return [];
    const out = [];
    if (u.locked) out.push({ label: 'unlock AD account', icon: 'lock', method: 'POST', path: `${UP(u.sam)}/unlock`, body: {} });
    if (u.enabled && !u.undeletable) out.push({ label: 'disable AD account', icon: 'close', method: 'POST', path: `${UP(u.sam)}/disable`, body: {},
      confirm: `Disable AD account ${u.sam}? It can no longer log on (Authentik logins with the AD password fail too).` });
    if (!u.enabled) out.push({ label: 'enable AD account', icon: 'check', method: 'POST', path: `${UP(u.sam)}/enable`, body: {} });
    return out;
  },

  views: [{ id: 'ad-directory', label: 'Directory', icon: 'user', component: DirectoryView, min: 'admin' }],
  facets: { aduser: UserFacet, adgroup: GroupFacet, adcomputer: ComputerFacet, machine: ComputerFacet },
  tiles: [
    { id: 'locked', label: 'AD locked', w: 2, h: 1, component: LockedTile, min: 'admin' },
    { id: 'expiring', label: 'AD passwords', w: 4, h: 2, component: ExpiringTile, min: 'admin' },
    { id: 'changes', label: 'AD changes', w: 4, h: 2, component: ChangesTile, min: 'admin' },
  ],
};
