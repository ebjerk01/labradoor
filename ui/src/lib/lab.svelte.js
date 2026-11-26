// The shell's state. Modules plug in through hooks on their ui/index.js default export:
//   load(ctx)                 → data (called every refresh)
//   objects(data, ctx)        → [{id, type, name, kind, status, parent?, cpu?, mem?, disk?, upd?, backup?, meta?}]
//   kpis(data) / alerts(data) / ticker(data) / search(data)
//   tiles: [{id, label, w, h, component, min?}]          facets: {objectType: Component}
//   views: [{id, label, icon, component, min?}]  → own pages, grouped under the module's own section in the rail
//          (props {data, ctx}; ids are global: prefix them with the module id when they could collide)
//   ctx.api: get/text/post/patch/del/put/upload(path, blob); manifest route "audit": false skips the audit row (upload chunks)
//   actions(object, data, ctx) → [{label, icon, method, path, body, confirm?} | {label, icon, url}]   status(data, ref) → ok|warn|bad|null
//   search(data, ctx) → [{label, sub, status?, object?, url?, run?}] (static, for Ctrl-K)   lookup: async (q, ctx) → same (q ≥ 3 chars)
//   (picked: run() if given — e.g. ai's "? question" — else open object, else url; see palette.js)
//   ctx also carries what modules used to take from this singleton (now, me, go, open, objects, alerts, prefs …) and
//   ctx.peer(id) / ctx.via(id) for modules listed in the manifest's "requires". Modules use ctx + $lab/sdk.js only
//   (docs/sdk.md); "manifest": 2 modules must not import this file (tests/module_isolation.test.mjs).
// Objects with the same id from several modules merge into one, so a machine collects every module's facets.
import { api, moduleApi } from './api.js';
import { loadUi, uiSource } from './modules.js';
import { verdict, buildNav, allowedViews } from './routes.js';
import { worst, RANK, safeUrl } from './fmt.js';
import { peerGuard, readonly, changeTracker } from './sdk-core.js';

const REFRESH_MS = 15000;

function localGet(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } }
function localSet(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }

class Lab {
  me = $state(null);
  sso = $state(false);
  ssoName = $state('');
  roleGroups = $state(null);  // the SSO groups that make owner / admin (LAB_OWNER_GROUP / LAB_ADMIN_GROUP)
  brand = $state('labradoor');  // LAB_BRAND (the user's instance calls itself 'lab')
  setup = $state(false);  // first run: no owner yet (the login page points at the setup link)
  booted = $state(false);
  registry = $state(null);
  data = $state({});
  errors = $state({});
  denied = $state({});  // module id → time when its backend says "nothing for you" (403, or its own 401: no account there)
  loading = $state(false);
  topology = $state({ zones: [], nodes: [], links: [] });
  audit = $state([]);
  approvals = $state([]);
  prefs = $state({});
  view = $state('overview');
  sel = $state(null);
  panelOpen = $state(false);
  lens = $state('status');
  palette = $state(false);
  drawer = $state(null);
  toast = $state(null);
  theme = $state(localGet('lab.theme', 'auto'));
  now = $state(Date.now() / 1000);
  hist = $state({}); // object id -> last ~40 cpu samples (one per refresh), for sparklines
  lastRefresh = $state(0);

  role = $derived(this.me?.role || 'guest');
  #uiSrc = {};               // module id → where its loaded UI came from (modules.js uiSource)
  uiMods = $state.raw({});  // module id → its UI half, loaded per user from the registry (modules.js)
  live = $state(false);     // the push stream (/api/events) is connected
  rev = $state({});          // module id → change counter (ctx.rev; lazy() loads follow it): changeTracker in sdk-core.js
  #changed = changeTracker(this.rev);
  #lastLoad = {};           // module id → when its load() last ran
  active = $derived((this.registry?.modules || []).filter((m) => this.uiMods[m.id]).map((m) => ({ ...m, ui: this.uiMods[m.id] })));
  moduleViews = $derived(this.active.flatMap((m) => (m.ui.views || [])
    .filter((v) => allowedViews([v], this.role).length)
    .map((v) => ({ ...v, module: m.id, moduleName: m.name, moduleIcon: m.icon }))));
  sections = $derived(this.active.filter((m) => this.moduleViews.some((v) => v.module === m.id))
    .map((m) => ({ id: m.id, name: m.name, icon: m.icon || 'node', views: this.moduleViews.filter((v) => v.module === m.id) })));
  // the rail / start page / Ctrl-K / router model: modules grouped by category, unique labels, module pages (routes.js)
  nav = $derived(buildNav(this.active.map((m) => ({ id: m.id, name: m.name, icon: m.icon, category: m.category, views: m.ui.views })),
    this.role, this.role === 'guest' ? ['wall', 'settings'] : ['overview', 'wall', 'map', 'log', 'people', 'settings']));
  views = $derived([...this.nav.top, ...this.nav.entries, ...this.nav.bottom].map((e) => e.id));
  objects = $derived(this.#buildObjects());
  alerts = $derived(this.#collect('alerts').sort((a, b) => RANK[b.status] - RANK[a.status] || (a.since || 0) - (b.since || 0)));
  kpis = $derived(this.#collect('kpis'));
  ticker = $derived(this.prefs.ticker === false ? [] : [...this.#collect('ticker'), ...this.audit.slice(0, 8).map((a) => ({
    g: '●', c: 'var(--sig)', s: a.module || 'lab', m: `${a.username || '-'} · ${a.action}${a.target ? ' ' + a.target : ''}`,
    audit: true, open: a.target || undefined,  // the ticker opens the target object (or the log)
  }))]);
  tiles = $derived(this.#buildTiles());

  ctx(mid) {
    const mod = this.active.find((m) => m.id === mid);
    const lab = this;
    const dev = !!import.meta.env?.DEV;  // dev: an undeclared peer or a write to read-only data throws; production: null / ignored
    const may = peerGuard(mid, mod?.requires, dev);
    const live = (id) => this.active.some((m) => m.id === id);
    return {
      id: mid,
      role: this.role,
      settings: mod?.settings || {},
      api: moduleApi(mid),
      can: (method, path) => verdict(mod, method, path),
      // path may carry a ?query: the approval stores it and the approved run gets it back
      ask: (method, path, body, label, reason) => this.ask(mid, method, path, body, label, reason),
      open: (id) => this.open(id),
      notify: (msg, kind) => this.notify(msg, kind),
      data: () => this.data[mid],
      refresh: () => this.refresh(),
      // a write went through (act() calls it): drop this module's cached() values, reload its open lazy() data
      changed: () => this.changed(mid),
      get rev() { return lab.rev[mid] || 0; },
      // module SDK (docs/sdk.md): the shell state a module may use, so it never imports this file
      get now() { return lab.now; },
      get me() { return readonly(lab.me, dev, 'ctx.me'); },
      go: (view) => this.go(view),
      canGo: (view) => this.views.includes(view),
      close: () => this.close(),
      selected: () => this.sel,
      object: (id) => readonly(this.objects.get(id) ?? null, dev, 'a lab object'),
      objects: () => this.objects,
      alerts: () => readonly(this.alerts, dev, 'the alert list'),
      topology: () => readonly(this.topology || {}, dev, 'the topology'),  // the map's nodes/links/zones (read-only)
      prefs: {
        get: (key, dflt) => this.prefs[`${mid}.${key}`] ?? dflt,
        set: (key, value) => this.savePref(`${mid}.${key}`, value),
      },
      // another module's loaded data (read-only) / its ctx to act through its routes: only for modules this one's
      // manifest lists in "requires"; null when that module is not active for this user or has no data yet
      peer: (id) => (may(id, 'peer') && live(id) && this.data[id] != null ? readonly(this.data[id], dev, `${id}'s data`) : null),
      via: (id) => (may(id, 'via') && live(id) ? this.ctx(id) : null),
    };
  }

  // owner's per-module switches (Settings → ~/modules): _ticker, _overview (also kpis), _alerts, _tiles
  on(m, sw) { return (m.settings || {})[sw] !== false; }

  #collect(hook) {
    const sw = { ticker: '_ticker', alerts: '_alerts', kpis: '_overview' }[hook];
    const out = [];
    for (const m of this.active) {
      if (sw && !this.on(m, sw)) continue;
      const d = this.data[m.id];
      if (d == null || typeof m.ui[hook] !== 'function') continue;
      try { for (const x of m.ui[hook](d, this.ctx(m.id)) || []) out.push({ ...x, module: m.id }); } catch (e) { console.error(m.id, hook, e); }
    }
    return out;
  }

  #buildObjects() {
    const map = new Map();
    for (const m of this.active) {
      const d = this.data[m.id];
      if (d == null || typeof m.ui.objects !== 'function') continue;
      let list = [];
      try { list = m.ui.objects(d, this.ctx(m.id)) || []; } catch (e) { console.error(m.id, 'objects', e); }
      for (const o of list) {
        const cur = map.get(o.id);
        if (!cur) { map.set(o.id, { ...o, sources: [m.id], types: o.type ? [o.type] : [] }); continue; }
        const add = Object.fromEntries(Object.entries(o).filter(([k, v]) => v !== undefined && v !== null
          && !(['name', 'kind', 'parent', 'type', 'meta'].includes(k) && cur[k] != null)));
        // every source's type is kept, so each module's facet shows up on the merged object (npm host = bilinfo …)
        const types = o.type && !cur.types.includes(o.type) ? [...cur.types, o.type] : cur.types;
        map.set(o.id, { ...cur, ...add, status: worst(cur.status, o.status), sources: [...cur.sources, m.id], types });
      }
    }
    for (const n of this.topology.nodes || []) {
      const st = this.#topoStatus(n);
      const cur = map.get(n.id);
      if (cur) map.set(n.id, { ...cur, icon: n.icon || cur.icon, meta: cur.meta || n.meta, status: worst(cur.status, st) });
      else map.set(n.id, { id: n.id, type: n.type || 'external', name: n.label || n.id, kind: n.kind || '', icon: n.icon,
        meta: n.meta || '', status: st || 'unknown', about: n.about || '', sources: ['lab'] });
    }
    for (const [id, why] of Object.entries(this.topology.ownerOnly || {})) {
      const o = map.get(id);
      if (o) map.set(id, { ...o, ownerOnly: why });
    }
    // an object with open alerts is never shown greener than its worst alert (a down desktop that manage last saw
    // as "ok" stayed green while drift had 3 critical alerts on it)
    for (const a of this.alerts) {
      const o = a.object && map.get(a.object);
      if (!o) continue;
      o.alerts = (o.alerts || 0) + 1;
      if (a.status === 'bad' || a.status === 'warn') o.status = worst(o.status, a.status);
    }
    return map;
  }

  #topoStatus(n) {
    const refs = n.status ? (Array.isArray(n.status) ? n.status : [n.status]) : [];
    const res = [];
    for (const r of refs) {
      const m = this.active.find((x) => x.id === r.module);
      if (m && typeof m.ui.status === 'function' && this.data[m.id] != null) res.push(m.ui.status(this.data[m.id], r.ref));
    }
    return res.length ? worst(...res) : null;
  }

  #buildTiles() {
    const out = [];
    for (const m of this.active) {
      if (!this.on(m, '_tiles')) continue;
      for (const t of m.ui.tiles || []) {
        if (t.min === 'admin' && this.role === 'guest') continue;
        if (t.min === 'owner' && this.role !== 'owner') continue;
        out.push({ ...t, key: `${m.id}.${t.id}`, module: m.id });
      }
    }
    const order = this.prefs['wall.order'] || [];
    const idx = (k) => { const i = order.indexOf(k); return i < 0 ? 1e6 : i; };
    return out.sort((a, b) => idx(a.key) - idx(b.key));
  }

  facets(obj) {
    if (!obj) return [];
    const out = [];
    for (const m of this.active) {
      const f = m.ui.facets || {};
      const t = [obj.type, ...(obj.types || [])].find((x) => x && f[x]);
      const C = (t && f[t]) || f['*'];
      if (C && this.data[m.id] != null) out.push({ module: m.id, name: m.name, component: C });
    }
    return out;
  }

  actions(obj) {
    if (!obj) return [];
    const out = [];
    for (const m of this.active) {
      if (typeof m.ui.actions !== 'function' || this.data[m.id] == null) continue;
      const ctx = this.ctx(m.id);
      for (const a of m.ui.actions(obj, this.data[m.id], ctx) || []) {
        const v = a.url && !a.method ? 'yes' : ctx.can(a.method, a.path);
        if (v !== 'no') out.push({ ...a, module: m.id, verdict: v });
      }
    }
    return out;
  }

  // --- lifecycle ---------------------------------------------------------------------------------------------
  async boot() {
    this.applyTheme();
    this.#readHash();
    window.addEventListener('hashchange', () => this.#readHash());
    try {
      const me = await api.get('/api/me');
      this.me = me.user;
      this.sso = me.sso;
      this.ssoName = me.ssoName || '';
      if (me.brand) this.brand = me.brand;
      this.roleGroups = me.roleGroups || null;
      this.setup = !!me.setup;
    } catch { this.me = null; }
    this.booted = true;
    if (!this.me || this.me.mustEnrol) return;  // mustEnrol: only the 2FA enrolment screen until it is done
    await this.loadRegistry();
    const [prefs] = await Promise.allSettled([api.get('/api/prefs'),
      this.role !== 'guest' ? api.get('/api/topology').then((t) => (this.topology = t)) : null]);
    if (prefs.status === 'fulfilled') this.prefs = prefs.value.prefs || {};
    if (!location.hash && this.prefs.home && this.views.includes(this.prefs.home)) this.view = this.prefs.home;
    { const v = this.nav.resolve(this.view); this.view = v && this.views.includes(v) ? v : this.views[0]; }
    if (new URLSearchParams(location.search).get('approvals')) this.drawer = 'approvals';
    await this.refresh();
    this.#connectEvents();
    // a module loads when it is due: its own `poll` (seconds) or the base interval — the user's refresh pref, else 15 s,
    // or 30 s while the push stream is up (writes, settings, approvals and health changes then arrive at once).
    // pref 0 = no polling. Always a full refresh when the tab becomes visible again.
    const tick = () => setTimeout(() => {
      if (!document.hidden && Number(this.prefs.refresh) !== 0) this.refresh(false);
      tick();
    }, 5000);
    tick();
    document.addEventListener('visibilitychange', () => { if (!document.hidden && Date.now() / 1000 - this.lastRefresh > 5) this.refresh(); });
    $effect.root(() => { $effect(() => { const n = this.alerts.length; document.title = n ? `(${n}) ${this.brand}` : this.brand; }); });
    setInterval(() => { this.now = Date.now() / 1000; }, 5000);
    setInterval(() => { if (!document.hidden) this.loadRegistry(); }, 60000);
  }

  async loadRegistry() {
    try {
      const reg = await api.get('/api/registry');
      // (re)load a module's UI when it is new for this tab or its source changed (an installed module was updated,
      // rolled back, or replaced the bundled one); a removed module drops out of `active` with its registry entry
      const missing = (reg.modules || []).filter((m) => !this.uiMods[m.id] || this.#uiSrc[m.id] !== uiSource(m));
      if (missing.length) {
        const got = await loadUi(missing);
        for (const m of missing) if (got[m.id]) this.#uiSrc[m.id] = uiSource(m);
        this.uiMods = { ...this.uiMods, ...got };
      }
      this.registry = reg;
      if (this.registry.approvalsPending || this.drawer === 'approvals') this.loadApprovals();
    } catch (e) {
      if (e.status === 401) { this.me = null; }
    }
  }

  #again = false;
  baseSeconds() {
    const pref = Number(this.prefs.refresh);
    return pref > 0 ? Math.max(5, pref) : this.live ? 30 : REFRESH_MS / 1000;
  }

  // force (default): every module now (after an action, tab back in view). force=false: only modules that are due.
  async refresh(force = true) {
    // a refresh asked for while one runs (e.g. a module's task just ended) runs once more afterwards, not never
    if (this.loading) { if (force) this.#again = true; return; }
    const now = Date.now() / 1000;
    const base = this.baseSeconds();
    const due = this.active.filter((m) => force || now - (this.#lastLoad[m.id] || 0) >= Math.max(5, Number(m.ui.poll) || base) - 1);
    if (!due.length) return;
    this.loading = true;
    const jobs = due.map((m) => this.#loadModule(m, now));
    if (this.role !== 'guest' && (force || now - (this.#lastLoad._audit || 0) >= base - 1)) {
      this.#lastLoad._audit = now;
      jobs.push(api.get('/api/audit', { limit: 30 }).then((r) => (this.audit = r.audit)).catch(() => {}));
    }
    await Promise.all(jobs);
    this.loading = false;
    this.lastRefresh = Date.now() / 1000;
    if (this.#again) { this.#again = false; setTimeout(() => this.refresh(), 0); }
    for (const o of this.objects.values()) {
      if (o.cpu == null) continue;
      const h = this.hist[o.id] || [];
      h.push(o.cpu);
      this.hist[o.id] = h.slice(-40);
    }
  }

  // a write reached module mid (remote: the gateway's push hint): see changeTracker in sdk-core.js
  changed(mid, remote = false) { return this.#changed(mid, remote); }

  // one module now (a push hint said it changed)
  async refreshModule(id) {
    const m = this.active.find((x) => x.id === id);
    if (!m) return;
    await this.#loadModule(m, Date.now() / 1000);
    this.lastRefresh = Date.now() / 1000;
  }

  async #loadModule(m, now) {
    if (typeof m.ui.load !== 'function') return;
    if (this.denied[m.id] && now - this.denied[m.id] < 300) return;  // "no access" is asked again every 5 min, not every 15 s
    this.#lastLoad[m.id] = now;
    try {
      this.data[m.id] = await m.ui.load(this.ctx(m.id));
      delete this.errors[m.id];
      delete this.denied[m.id];
    } catch (e) {
      // the app itself says "nothing for you" (no account there): quiet, not an error, and tiles say so instead of
      // spinning forever. A 401 from lab's own gateway ("not logged in") is a real logout, handled below.
      if (e.status === 403 || (e.status === 401 && e.body?.error !== 'not logged in')) {
        delete this.data[m.id];
        delete this.errors[m.id];
        this.denied[m.id] = Date.now() / 1000;
        return;
      }
      this.errors[m.id] = e.message;
      if (e.status === 401 && e.body?.error === 'not logged in') this.me = null;
    }
  }

  // Push hints from the gateway (gateway/lab/events.py): which module to reload now. EventSource reconnects by itself;
  // while it is down the tabs simply poll at the normal pace.
  #events = null;
  #pending = {};
  #connectEvents() {
    if (typeof EventSource === 'undefined' || this.#events) return;
    const es = (this.#events = new EventSource('/api/events'));
    es.onopen = () => { this.live = true; };
    es.onerror = () => { this.live = false; };
    es.onmessage = (msg) => {
      let ev;
      try { ev = JSON.parse(msg.data); } catch { return; }
      if ((ev.t === 'invalidate' || ev.t === 'health') && ev.m) {
        if (ev.t === 'invalidate') this.changed(ev.m, true);  // someone's write: cached values + open panels too
        clearTimeout(this.#pending[ev.m]);  // a burst of writes → one reload
        this.#pending[ev.m] = setTimeout(() => this.refreshModule(ev.m), 300);
      } else if (ev.t === 'registry') {
        this.loadRegistry().then(() => this.refresh());
      } else if (ev.t === 'approvals') {
        this.loadRegistry();
        this.loadApprovals();
      }
    };
  }

  async loadApprovals() {
    try { this.approvals = (await api.get('/api/approvals')).approvals; } catch { /* ignore */ }
  }

  // --- navigation --------------------------------------------------------------------------------------------
  #readHash() {
    const h = location.hash.replace(/^#\/?/, '');
    const [view, obj] = h.split('/');
    if (/^[a-z][a-z0-9-]{0,30}$/.test(view || '')) {
      // a view this user doesn't have (a guest typing #/overview, an old bookmark) falls back to the first one
      const v = this.registry ? this.nav.resolve(view) : view;  // #/cloudflare, #/edge and #/mod-cdn style links
      this.view = !this.registry || this.views.includes(v) ? v : this.views[0];
    }
    if (obj) { this.sel = decodeURIComponent(obj); this.panelOpen = true; }
  }

  go(view) {
    view = this.nav.resolve(view) || view;  // a module id or short route works too (kpis, ticker items)
    if (!this.views.includes(view)) return;
    this.view = view;
    this.panelOpen = view === 'map' && !!this.sel;
    history.replaceState(null, '', `#/${this.nav.route(view)}`);
  }

  open(id) {
    this.sel = id;
    this.panelOpen = true;
    if (this.view === 'wall' && this.role !== 'guest') this.view = 'map';
    history.replaceState(null, '', `#/${this.nav.route(this.view)}/${encodeURIComponent(id)}`);
  }

  close() {
    this.panelOpen = false;
    history.replaceState(null, '', `#/${this.nav.route(this.view)}`);
  }

  setTheme(t) {
    this.theme = t;
    localSet('lab.theme', t);
    this.applyTheme();
  }

  applyTheme() {
    if (this.theme === 'auto') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = this.theme;
  }

  async savePref(key, value) {
    this.prefs[key] = value;
    try { await api.post('/api/prefs', { key, value }); } catch (e) { this.notify(e.message, 'bad'); }
  }

  notify(msg, kind = 'ok') {
    this.toast = { msg, kind, at: Date.now() };
    const at = this.toast.at;
    setTimeout(() => { if (this.toast?.at === at) this.toast = null; }, 4000);
  }

  // --- actions + approvals -------------------------------------------------------------------------------------
  async run(action) {
    if (action.url && !action.method) { const u = safeUrl(action.url); if (u) window.open(u, '_blank', 'noopener'); return; }
    if (action.confirm && !confirm(typeof action.confirm === 'string' ? action.confirm : `${action.label}?`)) return;
    const ctx = this.ctx(action.module);
    if (action.verdict === 'ask') return this.ask(action.module, action.method, action.path, action.body, action.label);
    try {
      const m = { GET: () => ctx.api.get(action.path), PATCH: () => ctx.api.patch(action.path, action.body || {}),
        PUT: () => ctx.api.put(action.path, action.body || {}),
        DELETE: () => ctx.api.del(action.path) }[action.method] || (() => ctx.api.post(action.path, action.body || {}));
      const r = await m();
      this.changed(action.module);  // the open panel's lazy() data and the module's cached() values reload now
      // a module may follow up itself (e.g. proxmox watches the async task it started and reports when it ends)
      if (typeof action.done === 'function') action.done(r, ctx);
      else { this.notify(`${action.label} ✓${r?.queued === true ? ' (queued: runs at the next check-in)' : ''}`); this.refresh(); }
    } catch (e) {
      if (e.body?.approval) return this.ask(action.module, action.method, action.path, action.body, action.label);
      this.notify(`${action.label}: ${e.message}`, 'bad');
    }
  }

  async ask(module, method, path, body, label, reason = '') {
    const [p, query = ''] = String(path).split('?');  // the gateway stores the query separately and replays it
    try {
      const r = await api.post('/api/approvals', { module, method, path: p, query, body, label, reason });
      this.notify(`asked the owner: ${r.approval.label}`);
      this.loadApprovals();
      this.loadRegistry();
      return r.approval;
    } catch (e) { this.notify(e.message, 'bad'); return null; }
  }

  async decide(id, verb) {
    try {
      const r = await api.post(`/api/approvals/${id}/${verb}`, {});
      this.notify(`#${id} ${r.approval.status}`, r.approval.status === 'failed' ? 'bad' : 'ok');
    } catch (e) { this.notify(e.message, 'bad'); }
    this.loadApprovals();
    this.loadRegistry();
  }

  async logout() {
    try { await api.post('/auth/logout'); } catch { /* ignore */ }
    location.href = '/';
  }
}

export const lab = new Lab();
