// The module SDK's plain half: no runes, so node tests import it directly. Modules import everything from
// `$lab/sdk.js`, which re-exports this file, fmt.js and the reactive helpers in sdk.svelte.js. Reference: docs/sdk.md.
import { RANK, worst } from './fmt.js';

// Dates and times in module UIs use one locale.
export const LOCALE = 'nb-NO';

// --- errors ---------------------------------------------------------------------------------------------------------

const text = (v) => (typeof v === 'string' && v.trim() ? v.trim() : '');

// One line of text for a failed request, whatever shape the backend's error has: {error}, {error: {message}},
// {message}, {detail}, {errorMessage}, {title}, {errors: [{message}]}, a field map {errors: {field: text}} (appended),
// or a bare body. Capped at `max` characters.
export function errText(e, max = 220) {
  if (e == null) return 'failed';
  if (typeof e === 'string') return e.slice(0, max) || 'failed';
  const b = e.body && typeof e.body === 'object' ? e.body : {};
  const list = Array.isArray(b.errors) ? b.errors : null;
  let main = text(b.error?.message) || text(b.message) || text(b.error) || text(b.detail) || text(b.errorMessage)
    || text(b.title) || text(list?.[0]?.message) || text(list?.[0]);
  const fields = b.errors && !list && typeof b.errors === 'object'
    ? Object.entries(b.errors).map(([k, v]) => `${k}: ${String(v).trim()}`).join('; ') : '';
  if (!main && !fields) {
    const rest = Object.keys(b).length ? JSON.stringify(b) : '';
    main = rest && rest !== '{}' ? rest : text(e.message) || 'failed';
  }
  return [main, fields].filter(Boolean).join(' · ').slice(0, max);
}

// --- paths + query strings ------------------------------------------------------------------------------------------

// {a: 1, b: null, c: [1, 2]} → "a=1&c=1&c=2" (null/undefined dropped, arrays repeat the key)
export function qs(query) {
  if (query == null) return '';
  if (typeof query === 'string') return query.replace(/^\?/, '');
  const p = new URLSearchParams();
  for (const [k, v] of query instanceof URLSearchParams ? query : Object.entries(query)) {
    if (v == null) continue;
    for (const x of Array.isArray(v) ? v : [v]) if (x != null) p.append(k, String(x));
  }
  return p.toString();
}

// path + query (object or string), merged with a query the path already carries
export function withQuery(path, query) {
  const q = qs(query);
  if (!q) return path;
  return path + (String(path).includes('?') ? '&' : '?') + q;
}

export const barePath = (path) => String(path ?? '').split('?')[0];

// --- requests -------------------------------------------------------------------------------------------------------

function send(ctx, method, path, body) {
  switch (method) {
    case 'GET': return ctx.api.get(path);
    case 'DELETE': return ctx.api.del(path);
    case 'PUT': return ctx.api.put(path, body ?? {});
    case 'PATCH': return ctx.api.patch(path, body ?? {});
    default: return ctx.api.post(path, body ?? {});
  }
}

function confirmed(q) {
  const f = globalThis.confirm;
  return typeof f !== 'function' || f(q);
}

// Run one of this module's routes the way the manifest allows it for this user:
//   'yes' → call it, toast "<label> ✓" (or `ok`), refresh;  'ask' → a one-time approval request to the owner;
//   'no' → refuse with a toast. A call the gateway turns into an approval (403 {approval}) is asked for too.
// Options: method (POST), path (may carry ?query), body, query (object or string), label (required for writes),
//   confirm (true or a question: a browser confirm() first), ok (text or (result) => text for the success toast),
//   quiet (no toast, no refresh: a read made with POST), reason (shown on the approval request),
//   done(result, ctx): runs after success; return true when it handled the follow-up itself (no toast/refresh), e.g.
//   watch() on a background task.
// Returns the backend's answer ({} when empty), or null when nothing ran (refused, cancelled, asked, failed).
export async function act(ctx, opts) {
  const { method = 'POST', path, body, query, quiet = false, ok, done, check, reason = '' } = opts || {};
  const label = opts?.label || `${method} ${barePath(path)}`;
  const full = withQuery(path, query);
  const v = ctx.can(method, full);
  if (v !== 'yes' && v !== 'ask') { ctx.notify(`${label}: not allowed`, 'bad'); return null; }
  if (opts?.confirm && !confirmed(typeof opts.confirm === 'string' ? opts.confirm : `${label}?`)) return null;
  if (v === 'ask') { await ctx.ask(method, full, body, label, reason); return null; }
  let r;
  try {
    r = (await send(ctx, method, full, body)) ?? {};
  } catch (e) {
    if (e?.body?.approval) { await ctx.ask(method, full, body, label, reason); return null; }
    ctx.notify(`${label}: ${errText(e)}`, 'bad');
    return null;
  }
  // check(r): for APIs that report errors inside a 2xx answer (Technitium: {status: "error"}) — throw to fail the action
  // before anything says ✓; it may also return the unwrapped value, which `done` and the caller then get.
  if (typeof check === 'function') {
    try {
      const c = check(r);
      if (c !== undefined) r = c;
    } catch (e) {
      ctx.notify(`${label}: ${errText(e)}`, 'bad');
      return null;
    }
  }
  // a write went through: this module's cached() values and its open lazy() loads (the object panel's facets, a view's
  // lists) refresh now, not when their ttl or the next poll comes round (the shell's ctx.changed(), see changeTracker)
  if (!quiet) ctx.changed?.();
  let handled = false;
  if (typeof done === 'function') {
    try { handled = (await done(r, ctx)) === true; } catch (e) { console.error(ctx.id, label, e); }
  }
  if (!handled && !quiet) {
    // a backend that only queued the work (a machine that checks in later) answers {queued: true}
    ctx.notify(typeof ok === 'function' ? ok(r) : ok || `${label} ✓${r?.queued === true ? ' (queued: runs at the next check-in)' : ''}`);
    ctx.refresh();
  }
  return r;
}

// A GET for a backend that answers per user: {data} on success, {denied: text} on 403 (this user has no account or
// no rights there: show it, it is not an error). A 401 from the backend itself (not lab's own "not logged in") means
// it refused the gateway's signature; it is rethrown without the status so the shell does not log the user out.
export async function getOrDenied(ctx, path, query) {
  try {
    return { data: await ctx.api.get(path, query) };
  } catch (e) {
    if (e?.status === 403) return { denied: text(e.body?.error) || 'no access' };
    if (e?.status === 401 && e.body?.error !== 'not logged in') throw new Error('backend refused the lab signature');
    throw e;
  }
}

// An optional part of a load: a failure becomes `fallback` instead of failing the whole module.
export const soft = (p, fallback = null) => Promise.resolve(p).catch(() => fallback);

// --- caching --------------------------------------------------------------------------------------------------------

const cache = new Map(); // key → {has, at, val, p}

// fn()'s value, reused for `ttl` ms. Calls made while one runs share it. A failed refresh keeps the last good value
// (and throws only when there is none yet). Prefix keys with ctx.id: the cache is shared by every module.
export function cached(key, ttl, fn) {
  const hit = cache.get(key);
  if (hit?.has && Date.now() - hit.at < ttl) return Promise.resolve(hit.val);
  if (hit?.p) return hit.p;
  const p = Promise.resolve().then(fn).then(
    (val) => {
      if (cache.get(key)?.p === p) cache.set(key, { has: true, at: Date.now(), val });
      return val;
    },
    (e) => {
      const cur = cache.get(key);
      if (cur?.p === p) {
        if (cur.has) { cache.set(key, { has: true, at: cur.at, val: cur.val }); return cur.val; }
        cache.delete(key);
      }
      throw e;
    });
  cache.set(key, { ...(hit || {}), p });
  return p;
}

// Drop a cached value (after a write that changes it). "prefix*" drops every key that starts with prefix.
export function forget(key) {
  if (key.endsWith('*')) {
    const pre = key.slice(0, -1);
    for (const k of [...cache.keys()]) if (k.startsWith(pre)) cache.delete(k);
  } else cache.delete(key);
}

// The shell's "module X changed" bookkeeping (lab.svelte.js): after a write — this tab's own (act(), a panel action) or
// another tab's/user's (the gateway's SSE "invalidate") — drop X's cached() values ("X:*") and bump rev[X], which every
// lazy() load made with X's ctx follows (ctx.rev), so an open object panel shows the new state at once. The gateway's echo
// of this tab's own write (remote, within `window` ms) is skipped: the local change already did it.
// rev: a (reactive) object {moduleId: n}. Returns changed(mid, remote = false) → true when it dropped/bumped.
export function changeTracker(rev, { now = () => Date.now(), window = 2000 } = {}) {
  const local = {};
  return function changed(mid, remote = false) {
    if (!mid) return false;
    const t = now();
    if (remote && t - (local[mid] ?? -Infinity) < window) return false;
    if (!remote) local[mid] = t;
    forget(`${mid}:*`);
    rev[mid] = (rev[mid] || 0) + 1;
    return true;
  };
}

// --- background loops (the reactive wrappers in sdk.svelte.js stop them when the component goes away) --------------

// fn() now (or after ms) and then every ms, skipped while the tab is hidden. Returns stop().
export function startPoll(fn, ms, { immediate = true, hidden = false } = {}) {
  let stopped = false, t = null;
  const tick = async () => {
    if (stopped) return;
    if (hidden || !globalThis.document?.hidden) {
      try { await fn(); } catch (e) { console.error('poll', e); }
    }
    if (!stopped) t = setTimeout(tick, ms);
  };
  t = setTimeout(tick, immediate ? 0 : ms);
  return () => { stopped = true; clearTimeout(t); };
}

// Watch a background task the module started (a Proxmox UPID, a job id …) until it ends.
//   check() → null/undefined while it runs, or {ok: bool, text?} when it ended; a thrown error is retried.
//   Options: label, id, every (ms, 3000), first (ms before the first check, 1500), timeout (ms, 1 h),
//   refresh ([0]: refresh delays in ms after it ended, e.g. [0, 5000] for a backend whose lists lag), quiet.
// While it runs it is listed in store.list as {id, module, label, started}. Resolves to the result
// ({ok: null, text: 'timeout'} when it gave up).
export function watchTask(ctx, opts, store = { list: [] }) {
  const { check, label = 'task', every = 3000, first = 1500, timeout = 3600e3, refresh = [0], quiet = false } = opts;
  const id = opts.id ?? `${ctx.id}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
  store.list = [{ id, module: ctx.id, label, started: Date.now() / 1000 }, ...store.list.filter((t) => t.id !== id)].slice(0, 20);
  const drop = () => { store.list = store.list.filter((t) => t.id !== id); };
  const deadline = Date.now() + timeout;
  return new Promise((resolve) => {
    const tick = async () => {
      let res = null;
      try { res = await check(); } catch { /* transient: keep watching */ }
      if (res) {
        drop();
        if (!quiet) ctx.notify(`${label}: ${res.ok ? '✓' : res.text || 'failed'}${res.ok && res.text ? ` ${res.text}` : ''}`, res.ok ? 'ok' : 'bad');
        for (const ms of refresh) setTimeout(() => ctx.refresh(), ms);
        resolve(res);
        return;
      }
      if (Date.now() < deadline) setTimeout(tick, every);
      else { drop(); resolve({ ok: null, text: 'timeout' }); }
    };
    setTimeout(tick, first);
  });
}

// The non-reactive core of lazy(): returns reload(), which GETs pathFn() into `state` ({data, error, loading,
// denied}). A request that was overtaken by a newer one is dropped. Routes the user may not read are not sent.
export function loader(state, getCtx, pathFn, { query, pick, keep = false } = {}) {
  let seq = 0;
  return async function reload() {
    const path = pathFn();
    const n = ++seq;
    if (!path) { Object.assign(state, { data: null, error: null, denied: null, loading: false }); return; }
    const ctx = typeof getCtx === 'function' ? getCtx() : getCtx;
    const v = ctx.can('GET', path);
    if (v !== 'yes') {
      Object.assign(state, { data: null, denied: v, loading: false, error: v === 'ask' ? 'owner only' : 'not allowed' });
      return;
    }
    state.loading = true;
    state.denied = null;
    try {
      const r = await ctx.api.get(path, query?.());
      if (n === seq) { state.data = pick ? pick(r) : r; state.error = null; }
    } catch (e) {
      if (n === seq) { state.error = errText(e); if (!keep) state.data = null; }
    }
    if (n === seq) state.loading = false;
  };
}

// --- time -----------------------------------------------------------------------------------------------------------

// unix seconds from an ISO string, "YYYY-MM-DD HH:MM:SS" (no zone = UTC), a Date, ms or seconds; null if none/invalid
export function ts(v) {
  if (v == null || v === '') return null;
  if (typeof v === 'number') return Number.isFinite(v) ? (v > 1e12 ? v / 1000 : v) : null;
  if (v instanceof Date) { const t = v.getTime(); return Number.isNaN(t) ? null : t / 1000; }
  let s = String(v).trim();
  if (/^\d+(\.\d+)?$/.test(s)) return ts(Number(s));
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(s)) s = s.replace(' ', 'T') + (/(Z|[+-]\d{2}:?\d{2})$/i.test(s) ? '' : 'Z');
  const t = Date.parse(s);
  return Number.isNaN(t) ? null : t / 1000;
}

// "in 3h" / "2d ago" for a unix time in the future or past
export function rel(t, now = Date.now() / 1000) {
  if (t == null) return '–';
  const d = t - now, a = Math.abs(d);
  const v = a < 3600 ? `${Math.max(1, Math.round(a / 60))}m` : a < 86400 ? `${Math.round(a / 3600)}h` : `${Math.round(a / 86400)}d`;
  return d >= 0 ? `in ${v}` : `${v} ago`;
}

// seconds → "1h05" / "7m" (a duration, not a time ago)
export function duration(s) {
  if (s == null || !Number.isFinite(s) || s < 0) return '–';
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? `${h}h${String(m).padStart(2, '0')}` : `${m}m`;
}

export const when = (t) => (t ? new Date(t * 1000).toLocaleString(LOCALE, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '–');
export const day = (t) => (t ? new Date(t * 1000).toLocaleDateString(LOCALE, { weekday: 'short', day: '2-digit', month: '2-digit' }) : '–');
export const hhmm = (t) => (t ? new Date(t * 1000).toLocaleTimeString(LOCALE, { hour: '2-digit', minute: '2-digit' }) : '–');

// --- status ---------------------------------------------------------------------------------------------------------

// The worst status in a list, `base` when it is empty.
export const worstOf = (list, base = 'ok') => (list || []).reduce((a, b) => (RANK[b] > RANK[a] ? b : a), base);

// A module's own health from its list of problems ([{status}] or status strings; an item without one counts as warn):
// none → 'ok', else the worst.
export function siteStatus(problems) {
  const list = (problems || []).map((p) => (typeof p === 'string' ? p : p?.status || 'warn'));
  return list.length ? worst(...list) : 'ok';
}

// value → ok/warn/bad against two thresholds. warn < bad: higher is worse (disk %); warn > bad: lower is worse
// (days left). null → null.
export function level(v, warn, bad) {
  if (v == null || Number.isNaN(Number(v))) return null;
  if (warn <= bad) return v >= bad ? 'bad' : v >= warn ? 'warn' : 'ok';
  return v <= bad ? 'bad' : v <= warn ? 'warn' : 'ok';
}

// --- text + tables --------------------------------------------------------------------------------------------------

export const clip = (s, n = 80) => (s && s.length > n ? s.slice(0, n - 1) + '…' : s || '');

// Sort rows by a column: numbers numerically, text naturally ("node2" before "node10"); empty values always last.
export function sortRows(rows, get, dir = 1) {
  const val = typeof get === 'function' ? get : (r) => r?.[get];
  const empty = (x) => x == null || x === '' || (typeof x === 'number' && Number.isNaN(x));
  return [...(rows || [])].sort((a, b) => {
    const x = val(a), y = val(b);
    if (empty(x) || empty(y)) return empty(x) - empty(y);
    const c = typeof x === 'number' && typeof y === 'number' ? x - y
      : String(x).localeCompare(String(y), undefined, { numeric: true, sensitivity: 'base' });
    return c * dir;
  });
}

// --- module isolation (used by the shell's ctx; see ctx.peer / ctx.via) ---------------------------------------------

const RO = new WeakMap();
const plain = (v) => {
  if (Array.isArray(v)) return true;
  const p = v && typeof v === 'object' ? Object.getPrototypeOf(v) : undefined;
  return p === Object.prototype || p === null;
};

// A deep read-only view of plain objects/arrays (other values pass through). Writing throws when `strict`, else it
// is ignored with one console warning.
export function readonly(v, strict = true, what = 'another module\'s data') {
  if (!v || typeof v !== 'object' || !plain(v)) return v;
  const key = strict ? 's' : 'l';
  let byMode = RO.get(v);
  if (byMode?.[key]) return byMode[key];
  let warned = false;
  const refuse = () => {
    if (strict) throw new TypeError(`${what} is read-only`);
    if (!warned) { warned = true; console.warn(`${what} is read-only: write ignored`); }
    return true;
  };
  const view = new Proxy(v, {
    get(t, k, r) {
      const val = Reflect.get(t, k, r);
      const d = Object.getOwnPropertyDescriptor(t, k);
      if (d && !d.configurable && !d.writable) return val; // proxy invariant
      return readonly(val, strict, what);
    },
    set: refuse,
    deleteProperty: refuse,
    defineProperty: refuse,
    setPrototypeOf: refuse,
  });
  RO.set(v, { ...(byMode || {}), [key]: view });
  return view;
}

// May module `module` (manifest `requires`) read/act through `id`? Undeclared: throws in dev, false (+ one warning)
// in production.
export function peerGuard(module, requires, dev = false) {
  const ids = new Set((requires || []).map((r) => (typeof r === 'string' ? r : r?.id)).filter(Boolean));
  const warned = new Set();
  return (id, how = 'peer') => {
    if (ids.has(id) || ids.has('*')) return true;
    const msg = `module ${module}: ctx.${how}('${id}') needs "${id}" in its manifest's "requires"`;
    if (dev) throw new Error(msg);
    if (!warned.has(id)) { warned.add(id); console.warn(msg); }
    return false;
  };
}
