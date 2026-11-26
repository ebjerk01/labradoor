// guacamole — connection → lab object matching, and opening a console (shared by the hooks and components).
// connection names that don't say which object they are: setting `aliases` ("name=object", lower case on the left)
const aliasMap = (ctx) => Object.fromEntries((ctx.settings?.aliases || []).map((a) => String(a).split('=').map((x) => x.trim())).filter((p) => p.length === 2 && p[0] && p[1]).map(([k, v]) => [k.toLowerCase(), v]));

function guestName(vmid, ctx) {
  const r = (ctx.peer('proxmox')?.resources || []).find((x) => (x.type === 'lxc' || x.type === 'qemu') && x.vmid === vmid);
  if (r) return r.name;
  const g = (ctx.peer('drift')?.overview?.guests || []).find((x) => Number(x.vmid) === vmid);
  return g ? g.name : null;
}

// the lab object id a connection belongs to
export function objectFor(c, ctx) {
  if (c.vmid) {
    const n = guestName(c.vmid, ctx);
    if (n) return n;
  }
  return aliasMap(ctx)[c.label.toLowerCase()] || c.label;
}

export const connsFor = (d, obj, ctx) => (d?.connections || []).filter((c) => objectFor(c, ctx).toLowerCase() === obj.id.toLowerCase());

// --- consoles ---------------------------------------------------------------------------------------------------------
// The client URL only comes from POST /api/open/<connection>/<object> (gateway: role + _protect + audit; connector:
// owner, or an admin with a grant). The window then signs in to Guacamole with the viewer's OWN account.
export const openPath = (c, obj) => `/api/open/${encodeURIComponent(c.id)}/${encodeURIComponent(obj.id)}`;
export const grantPath = (c, obj) => `/api/grant/${encodeURIComponent(c.id)}/${encodeURIComponent(obj.id)}`;
export const kindOf = (c) => (c.terminal ? 'terminal' : 'console');
const FEATURES = 'popup,width=1100,height=700';
const winName = (c) => `lab-console-${c.id}`;

// _protect entries ("/api/open/19/**", "POST /api/open/19/workstation") that cover this connection's open route. The
// gateway enforces them (admins: owner approval, which can't hand over a window → no button); for the owner the UI
// only asks once more before opening a protected machine.
function segRe(pattern) {
  const segs = pattern.replace(/^\/|\/$/g, '').split('/').filter(Boolean);
  let re = '';
  for (const s of segs) {
    if (s === '**') { re += '(?:/.*)?'; break; }
    re += '/' + (s === '*' ? '[^/]+' : s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  }
  return new RegExp('^' + re + '/?$', 'i');
}
export function isProtected(c, obj, ctx) {
  const path = openPath(c, obj);
  return (ctx.settings?._protect || []).some((e) => {
    const parts = String(e).trim().split(/\s+/);
    const methods = parts[0]?.startsWith('/') ? ['POST'] : (parts.shift() || '').toUpperCase().split(',');
    return parts.length === 1 && methods.includes('POST') && segRe(parts[0]).test(path);
  });
}

// the admin's live grant for this connection (from /api/sessions), or null
export const grantFor = (d, c, ctx) => (d?.sessions?.grants || []).find((g) => g.id === c.id && g.user === ctx.me?.username && g.until > ctx.now) || null;

// What this user can do with a connection on this object:
//   'open' (owner; admin with a grant) · 'ask' (admin may ask the owner for a grant) · null (nothing)
export function mode(d, c, obj, ctx) {
  if (ctx.role === 'owner') return ctx.can('POST', openPath(c, obj)) === 'yes' ? 'open' : null;
  if (ctx.role !== 'admin' || !d?.admins) return null;
  if (ctx.can('POST', openPath(c, obj)) !== 'yes') return null;  // protected here: owner only
  if (grantFor(d, c, ctx)) return 'open';
  return ctx.can('POST', grantPath(c, obj)) === 'ask' ? 'ask' : null;
}

// Show the client in its own window: re-use `pre` (opened synchronously on the click, so no pop-up blocker objects),
// else open one now. The opener link is cut before Guacamole loads.
export function show(r, ctx, pre = null) {
  let w = pre && !pre.closed ? pre : null;
  if (!w) {
    w = window.open('', r.window, FEATURES);
    try { if (w) w.opener = null; } catch { /* already showing Guacamole: cross-origin */ }
  }
  if (!w) {
    ctx.notify('pop-up blocked: allow pop-ups for lab and try again', 'bad');
    return true;
  }
  try { w.location.replace(r.url); } catch { w.location = r.url; }
  try { w.focus(); } catch { /* ignore */ }
  ctx.notify(`${r.terminal ? 'terminal' : 'console'} on ${r.object} opened (${r.protocol})`);
  ctx.refresh();
  return true;
}

// a blank window for this connection, opened while the click still counts as a user gesture
export function preOpen(c) {
  const w = window.open('', winName(c), FEATURES);
  try { if (w) w.opener = null; } catch { /* an existing cross-origin window */ }
  return w;
}

// close a window preOpen() made when nothing was opened after all — never one already showing a console
export function dropPre(w) {
  if (!w || w.closed) return;
  try { if (w.location.href === 'about:blank') w.close(); } catch { /* cross-origin: a live console, keep it */ }
}

export const protectQuestion = (c, obj) => `${obj.id} is protected in this lab (owner only). Open a ${kindOf(c)} (${c.protocol}) on it?`;
