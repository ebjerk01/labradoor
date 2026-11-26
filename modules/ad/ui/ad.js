// Helpers shared by the ad module's components.

export const enc = encodeURIComponent;
export const UP = (sam) => `/api/users/${enc(sam)}`;
export const DAY = 86400;

export const lockIcon = (v) => (v === 'ask' ? 'lock' : 'check');
export const verbLabel = (v, yes) => (v === 'ask' ? 'ask owner' : yes);

// Password expiry: seconds left (null = never expires; 0/negative = expired or must change)
export function pwLeft(u, now = Date.now() / 1000) {
  if (u.pwdNeverExpires || u.pwdExpires == null) return null;
  return u.pwdExpires - now;
}

export function pwState(u, days = 7, now = Date.now() / 1000) {
  if (u.mustChange) return { s: 'warn', t: 'must change at next logon' };
  const left = pwLeft(u, now);
  if (left == null) return { s: null, t: 'never expires' };
  if (left <= 0 || u.pwdExpired) return { s: 'bad', t: 'expired' };
  const d = left / DAY;
  return { s: d < days ? 'warn' : null, t: d < 1 ? `expires in ${Math.round(left / 3600)}h` : `expires in ${Math.floor(d)}d` };
}

export function userStatus(u, days = 7) {
  if (!u.enabled) return 'off';
  if (u.locked) return 'bad';
  const p = pwState(u, days);
  return p.s === 'bad' ? 'bad' : p.s === 'warn' ? 'warn' : 'ok';
}

// built-in = not ours: CN=Users/CN=Builtin accounts and groups (Administrator, krbtgt, Domain Admins, …)
export const isBuiltin = (x, data) => !x.dn.toLowerCase().endsWith(`,${data.managedOu}`.toLowerCase());

export const expiryDays = (ctx) => Number(ctx?.settings?.expiry_days) || 7;

// Every lab object id of a machine from the modules that own machines (drift, proxmox, manage), keyed by lower-case
// name, so an AD computer joins the existing object (WINSRV → winsrv) instead of making a twin.
export function machineIds(ctx) {
  const ids = new Map();
  const add = (id) => { if (id && !ids.has(String(id).toLowerCase())) ids.set(String(id).toLowerCase(), String(id)); };
  const o = ctx.peer('drift')?.overview;
  for (const g of o?.guests || []) add(g.name);
  for (const h of o?.hosts || []) add(h.name);
  for (const r of ctx.peer('proxmox')?.resources || []) if (r.type === 'qemu' || r.type === 'lxc') add(r.name);
  for (const id of Object.keys(ctx.peer('manage')?.byOid || {})) add(id);
  return ids;
}

export function computerId(c, ctx, ids = machineIds(ctx)) {
  const m = ids.get(c.name.toLowerCase()) || ids.get((c.dns || '').split('.')[0].toLowerCase());
  return m ? { id: m, merged: true } : { id: `adcomputer:${c.name.toLowerCase()}`, merged: false };
}

// The lab Authentik user for an AD account: Authentik's LDAP source (username_link) keys on the username, and
// records the AD DN in attributes.distinguishedName once it has synced.
export function authentikUser(u, ctx) {
  const users = ctx.peer('authentik')?.users || [];
  const dn = u.dn.toLowerCase();
  const hit = users.find((x) => (x.attributes?.distinguishedName || '').toLowerCase() === dn)
    || users.find((x) => x.username.toLowerCase() === u.sam.toLowerCase());
  if (!hit) return null;
  return { id: `user:${hit.username}`, username: hit.username, linked: (hit.attributes?.distinguishedName || '').toLowerCase() === dn };
}

export const authentikLoaded = (ctx) => !!ctx.peer('authentik')?.users;

// the Authentik LDAP source that syncs this domain (installation setting; '' = unknown)
export const akSource = (ctx) => String(ctx.settings?.authentik_source || '').trim();

// the last OU of a DN as text: "OU=Brukere,OU=Homelab,DC=…" → "OU=Brukere"
export const ouName = (dn) => String(dn || '').split(/(?<!\\),/)[0];

export const ouPath = (dn, base) => dn.slice(0, Math.max(0, dn.length - base.length - 1)).split(/(?<!\\),/)
  .map((p) => p.split('=').slice(1).join('=')).reverse().join(' / ') || '(domain root)';

// Most recently changed objects across the directory (whenChanged), newest first.
export function recent(d, n = 8) {
  const all = [
    ...d.users.map((u) => ({ t: u.changed, k: 'user', name: u.sam, id: `aduser:${u.sam}` })),
    ...d.groups.filter((g) => !g.system || g.managed).map((g) => ({ t: g.changed, k: 'group', name: g.name, id: `adgroup:${g.name}` })),
    ...d.computers.map((c) => ({ t: c.changed, k: 'computer', name: c.name, id: null, c })),
    ...d.ous.map((o) => ({ t: o.changed, k: o.container ? 'container' : 'ou', name: o.name, id: null })),
  ];
  return all.filter((x) => x.t).sort((a, b) => b.t - a.t).slice(0, n);
}
