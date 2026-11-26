// Client copy of the gateway's route matcher, so buttons can show locked/ask states before a request is made.
// The gateway still checks everything; this is only for the UI.
function compile(pattern) {
  const segs = pattern.replace(/^\/|\/$/g, '').split('/').filter(Boolean);
  let re = '';
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    if (s === '**') { re += '(?:/.*)?'; break; }
    re += '/' + (s === '*' ? '[^/]+' : s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  }
  return new RegExp('^' + re + '/?$');
}
const cache = new Map();
export function verdict(module, method, path) {
  if (!module) return 'no';
  path = String(path || '').split('?')[0];
  for (const r of module.routes || []) {
    if (r.method !== method) continue;
    let re = cache.get(r.path);
    if (!re) cache.set(r.path, (re = compile(r.path)));
    if (re.test(path)) return r.allow;
  }
  return 'no';
}

// --- navigation model (pure: tested by tests/nav.test.mjs) -----------------------------------------------------------
// The rail, the start-page picker, Ctrl-K and the hash router all read the same entries, so a view has ONE label
// everywhere. Modules are grouped by their manifest `category`; a module's views sit under it; a module without views
// gets one entry that opens the shell's generated module page (objects + tiles + alerts), id `mod-<module>`.
export const CATEGORIES = ['infrastructure', 'network', 'monitoring', 'identity', 'media', 'apps', 'tools'];
export const CORE = {
  overview: { label: 'Overview', icon: 'overview' }, wall: { label: 'Wall', icon: 'wall' }, map: { label: 'Map', icon: 'map' },
  log: { label: 'Log', icon: 'log' }, people: { label: 'People', icon: 'people' }, settings: { label: 'Settings', icon: 'wrench' },
};
export const homeId = (mid) => `mod-${mid}`;
const RANK_ROLE = { guest: 0, admin: 1, owner: 2 };

// the views of one module this role may open (`min: 'admin' | 'owner'` on the view)
export function allowedViews(views, role) {
  return (views || []).filter((v) => RANK_ROLE[role || 'guest'] >= RANK_ROLE[v.min || 'guest']);
}

// modules: [{id, name, icon, category, views: [{id, label, icon, min?}]}] — the registry's modules this user may use.
// core: the core view ids this role has (guest: wall + settings). Returns {entries, groups, top, bottom, byId, resolve, route}.
export function buildNav(modules, role = 'guest', core = Object.keys(CORE)) {
  const entries = [];
  const mods = [];
  for (const m of modules || []) {
    const views = allowedViews(m.views, role);
    const cat = CATEGORIES.includes(m.category) ? m.category : 'other';
    const base = { module: m.id, moduleName: m.name || m.id, category: cat };
    let list;
    if (!views.length) list = [{ ...base, id: homeId(m.id), short: m.name || m.id, icon: m.icon || 'node', home: true }];
    else if (views.length === 1) {
      const v = views[0];  // one page: the module's name is the clearer label ("Cloudflare", not "edge")
      const hint = (v.label || '').toLowerCase() !== (m.name || m.id).toLowerCase() ? (v.label || '').toLowerCase() : '';
      list = [{ ...base, id: v.id, short: m.name || m.id, hint, icon: v.icon || m.icon || 'node', props: v.props }];
    } else list = views.map((v) => ({ ...base, id: v.id, short: v.label || v.id, icon: v.icon || 'node', props: v.props }));
    entries.push(...list);
    mods.push({ id: m.id, name: m.name || m.id, icon: m.icon || 'node', category: cat, entries: list, single: list.length === 1 });
  }
  // one label everywhere: two views called "Alerts" become "Alerts · Driftsstatus" and "Alerts · manage"
  const coreLabels = core.map((c) => (CORE[c]?.label || c).toLowerCase());
  const count = new Map();
  for (const l of [...coreLabels, ...entries.map((e) => e.short.toLowerCase())]) count.set(l, (count.get(l) || 0) + 1);
  for (const e of entries) e.label = count.get(e.short.toLowerCase()) > 1 ? `${e.short} · ${e.moduleName}` : e.short;
  // short, readable urls: a module with one page (or none) is reachable as #/<module id>; old view ids keep working
  const taken = new Set([...core, ...entries.map((e) => e.id)]);
  const alias = new Map();
  for (const m of mods) {
    const first = m.entries[0];
    if (!first) continue;
    if (m.single && !taken.has(m.id)) first.route = m.id;
    if (!taken.has(m.id)) alias.set(m.id, first.id);
  }
  for (const e of entries) e.route = e.route || e.id;
  const byId = new Map(entries.map((e) => [e.id, e]));
  for (const c of core) byId.set(c, { id: c, label: CORE[c]?.label || c, short: CORE[c]?.label || c, icon: CORE[c]?.icon || 'node', route: c, core: true, category: 'lab' });
  const byRoute = new Map([...byId.values()].map((e) => [e.route, e.id]));
  const order = (c) => { const i = CATEGORIES.indexOf(c); return i < 0 ? 99 : i; };
  const groups = [...new Set(mods.map((m) => m.category))].sort((a, b) => order(a) - order(b)).map((c) => ({
    key: c, label: c, modules: mods.filter((m) => m.category === c).sort((a, b) => a.name.localeCompare(b.name, 'en', { sensitivity: 'base' })),
  }));
  return {
    entries, groups, byId,
    top: ['overview', 'wall', 'map'].filter((c) => core.includes(c)).map((c) => byId.get(c)),
    bottom: ['log', 'people', 'settings'].filter((c) => core.includes(c)).map((c) => byId.get(c)),
    // hash segment → view id (view ids, short routes and module ids all work); undefined if unknown
    resolve: (seg) => (byId.has(seg) ? seg : byRoute.get(seg) || alias.get(seg)),
    route: (id) => byId.get(id)?.route || id,
  };
}

// the rail's `$ grep` box: keep entries whose label / module / category / hint matches every word; a module whose
// name matches keeps all its entries. Returns groups in the same shape (empty ones dropped).
export function filterNav(groups, q) {
  const words = String(q || '').toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return groups;
  const hit = (s) => words.every((w) => s.includes(w));
  return groups.map((g) => ({
    ...g,
    modules: g.modules.map((m) => {
      const mtext = `${m.id} ${m.name} ${g.key}`.toLowerCase();
      if (hit(mtext)) return m;
      return { ...m, entries: m.entries.filter((e) => hit(`${mtext} ${e.label} ${e.hint || ''} ${e.id}`.toLowerCase())) };
    }).filter((m) => m.entries.length),
  })).filter((g) => g.modules.length);
}

// One button per verb on an object. Two modules offering "reboot" (or "upgrade 3" and "upgrade 5") show one button:
// the most specific module's — one the object came from, then the one that knows the fewest objects (a hypervisor
// module beats a whole-fleet monitor) — and the button says which module runs it; the others are listed in `also`.
export const actionKey = (a) => String(a.label || '').toLowerCase().replace(/\s*(#?\d+[\w.-]*)$/, '').trim() + (a.url && !a.method ? ` ${a.url}` : '');
export function dedupeActions(actions, obj = {}, size = () => 0) {
  const src = obj.sources || [];
  const w = (a) => [src.includes(a.module) ? 0 : 1, size(a.module) || 1e9, a.verdict === 'yes' ? 0 : 1];
  const cmp = (a, b) => { const x = w(a), y = w(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] - y[i]; return 0; };
  const by = new Map();
  for (const a of actions || []) {
    const k = actionKey(a);
    const cur = by.get(k);
    if (!cur) by.set(k, { ...a, also: [] });
    else if (cmp(a, cur) < 0) by.set(k, { ...a, also: [cur.module, ...cur.also].filter((m) => m && m !== a.module) });
    else if (a.module && a.module !== cur.module && !cur.also.includes(a.module)) cur.also.push(a.module);
  }
  return [...by.values()];
}
