// What a Ctrl-K result from a module's search()/lookup() does when picked: its own run() if it has one (e.g. the
// assistant's "? question" item), else open its object, else open its http(s) url (never another scheme).
import { safeUrl } from './fmt.js';
import { CATEGORIES } from './routes.js';

export function itemAction(x, lab, open = (u) => window.open(u, '_blank', 'noopener')) {
  return () => {
    if (typeof x.run === 'function') return x.run();
    if (x.object) return lab.open(x.object);
    const u = x.url ? safeUrl(x.url) : undefined;
    if (u) open(u);
    return null;
  };
}

// --- ranking (pure: tests/palette.test.mjs) ---------------------------------------------------------------------------
// Ctrl-K understands tasks ("restart workstation", "reboot", "console lab", "new record", "approve"), dedupes the same thing
// seen by several modules (one row per object, other sources as badges), and keeps noisy lookups (file and part
// searches) from flooding: at most CAP rows per module, ranked below infrastructure.
// first word → the action labels it means (an action matches when its label starts with one of them)
export const VERBS = {
  restart: ['restart', 'reboot'], reboot: ['reboot', 'restart'], start: ['start'], boot: ['start'],
  stop: ['shutdown', 'stop'], shutdown: ['shutdown', 'stop'], halt: ['shutdown', 'stop'],
  snapshot: ['snapshot', 'backup'], backup: ['backup', 'snapshot'],
  console: ['console', 'shell', 'ssh'], shell: ['console', 'shell', 'ssh'], ssh: ['console', 'shell', 'ssh'], terminal: ['console', 'shell'],
  upgrade: ['upgrade', 'update'], update: ['update', 'upgrade', 'check updates'], patch: ['upgrade', 'update'],
  check: ['check', 'run check', 'test'], scan: ['scan', 're-index', 'rebuild'], snooze: ['snooze'], unlock: ['unlock'],
  logs: ['logs', 'grep logs'], open: ['open', 'console'], purge: ['purge'], sync: ['sync'], migrate: ['migrate'],
};
// words that point at a PAGE rather than an object; a view matches when its label/id/module contains one of the stems
export const TOPICS = {
  record: ['dns', 'record', 'zone', 'resolver', 'edge', 'cloudflare'], dns: ['dns', 'resolver', 'edge', 'zone'], zone: ['dns', 'zone', 'edge'],
  domain: ['domain', 'dns'], host: ['proxy', 'host'], proxy: ['proxy'], cert: ['proxy', 'cert'], certificate: ['proxy', 'cert'],
  user: ['user', 'identity', 'directory', 'people'], group: ['group', 'identity', 'directory'], account: ['user', 'identity', 'directory'],
  service: ['wizard', 'new service', 'service'], machine: ['fleet', 'machine'], vm: ['fleet', 'guest'], ct: ['fleet', 'guest'],
  request: ['request', 'discover'], movie: ['media', 'discover'], show: ['media', 'discover'], torrent: ['torrent'],
  backup: ['backup'], key: ['key'], policy: ['polic'], cve: ['cve'], alert: ['alert'], log: ['log'], check: ['check'],
  deploy: ['deploy', 'task sequence'], ring: ['ring'], vpn: ['vpn'], app: ['store', 'app'], client: ['network'],
};
const PAGE_VERBS = new Set(['new', 'add', 'create', 'find', 'show', 'list', 'manage', 'edit']);
export const CAP = 4;          // rows per module from search()/lookup()
const LIMIT = 16;

const norm = (s) => String(s ?? '').toLowerCase().trim();
// "lab (CT 132)" and "lab" are the same machine to a human
export const sameName = (s) => norm(s).replace(/\s*\([^)]*\)\s*$/, '').trim();
const catRank = (c) => { const i = CATEGORIES.indexOf(c); return i < 0 ? CATEGORIES.length : i; };
const TYPE_W = { machine: 0, service: 0.15, external: 0.4 };

// 0 exact · 1 prefix · 2 word prefix · 3 substring · 3.5 every word starts a word of label+extra · 4 every word
// somewhere in label+extra · null no match
export function textScore(q, label, extra = '') {
  const s = norm(q), l = norm(label);
  if (!s) return 5;
  if (l === s) return 0;
  if (l.startsWith(s)) return 1;
  if (l.split(/[\s·:/._-]+/).some((w) => w.startsWith(s))) return 2;
  if (l.includes(s)) return 3;
  const hay = `${l} ${norm(extra)}`;
  const qw = s.split(/\s+/);
  const hw = hay.split(/[\s·:/._-]+/);
  if (qw.every((w) => hw.some((h) => h.startsWith(w) || w.startsWith(h) && h.length >= 4))) return 3.5;
  return qw.every((w) => hay.includes(w)) ? 4 : null;
}

export function parseTask(q) {
  const words = norm(q).split(/\s+/).filter(Boolean);
  if (!words.length) return null;
  if (VERBS[words[0]]) return { verb: words[0], match: VERBS[words[0]], rest: words.slice(1).join(' ') };
  if (PAGE_VERBS.has(words[0]) && words.length > 1) return { verb: words[0], match: null, rest: words.slice(1).join(' ') };
  return null;
}

const actionMatches = (a, match) => { const l = norm(a.label); return match.some((m) => l === m || l.startsWith(m + ' ') || l.startsWith(m)); };

// One row per object: objects with the same name (a CT, its unifi client, a drift check called the same) collapse
// into the most "infrastructure" one; the rest become badges. Returns [{...primary, alts: [{id, type, module}]}].
export function dedupeObjects(objects, catOf = () => '') {
  const by = new Map();
  const w = (o) => (TYPE_W[o.type] ?? 0.6) * 10 + catRank(catOf(o.sources?.[0])) - (o.sources?.length || 1) * 0.01;
  for (const o of objects) {
    const k = sameName(o.name || o.id);
    const cur = by.get(k);
    if (!cur) { by.set(k, { ...o, alts: [] }); continue; }
    const alt = (x) => ({ id: x.id, type: x.type || '', module: x.sources?.[0] || '' });
    if (w(o) < w(cur)) by.set(k, { ...o, alts: [alt(cur), ...cur.alts] });
    else cur.alts.push(alt(o));
  }
  return [...by.values()];
}

// in: {q, views, objects, search, lookups, commands, catOf, actionsFor}
//   views:    [{id, label, hint?, module?, moduleName?, category?, route?}]
//   objects:  [{id, name, type, kind?, parent?, status?, sources: [moduleId]}] (lab.objects values)
//   search / lookups: module rows [{label, sub?, status?, object?, url?, run?, module}]
//   commands: [{label, keys?, run}]   catOf(moduleId) → category   actionsFor(object) → lab.actions(object)
// out: [{kind: task|view|obj|mod|cmd, key, label, sub, status?, verdict?, badges: [{label, id?}], pick}]
//   pick: {view: id} | {object: id} | {action} | {item} | {cmd}
export function rankPalette({ q = '', views = [], objects = [], search = [], lookups = [], commands = [], catOf = () => '', actionsFor = () => [] }) {
  const s = norm(q);
  const task = parseTask(s);
  const objs = dedupeObjects(objects, catOf);
  const byId = new Map();
  for (const o of objs) { byId.set(o.id, o); for (const a of o.alts) byId.set(a.id, o); }
  const out = [];
  const push = (score, item) => { if (score != null) out.push([score, item]); };
  const objItem = (o, extra = {}) => ({
    kind: 'obj', key: `o:${o.id}`, label: o.name || o.id, sub: [o.kind, o.parent].filter(Boolean).join(' · '), status: o.status,
    badges: [...new Set([...(o.sources || []), ...o.alts.map((a) => a.module)].filter(Boolean))].map((m) => ({ label: m })), pick: { object: o.id }, ...extra,
  });

  // 1. tasks: "<verb> [object]" → that object's matching actions, with the caller's verdict
  if (task?.match) {
    const cands = task.rest
      ? objs.map((o) => [textScore(task.rest, o.name, `${o.kind || ''} ${o.id}`), o]).filter(([n]) => n != null && n < 4)
        .sort((a, b) => a[0] - b[0] || (TYPE_W[a[1].type] ?? 0.6) - (TYPE_W[b[1].type] ?? 0.6)).slice(0, 8)
      : objs.filter((o) => o.type === 'machine' || o.type === 'service').slice(0, 200).map((o) => [1, o]);
    let n = 0;
    for (const [ts, o] of cands) {
      let acts = [];
      try { acts = (actionsFor(o) || []).filter((a) => actionMatches(a, task.match)); } catch { acts = []; }
      for (const a of acts) {
        push(ts * 0.1 + (a.verdict === 'yes' ? 0 : 0.05), {
          kind: 'task', key: `t:${o.id}:${a.module}:${a.label}`, label: `${a.label} · ${o.name || o.id}`, sub: a.module || '',
          status: o.status, verdict: a.verdict, badges: [], pick: { action: a },
        });
        n++;
      }
      if (n >= 24) break;
    }
    // nothing to run on the best match: offer its panel (the action may live in a facet), rather than nothing
    if (!n && task.rest && cands.length) push(0.5, objItem(cands[0][1], { sub: `no “${task.verb}” action here · open panel` }));
  }

  // 2. views (+ "new record" / "dns record": topic words → the pages that do it)
  const words = s.split(/\s+/).filter(Boolean);
  const topicStems = words.flatMap((w) => TOPICS[w] || TOPICS[w.replace(/s$/, '')] || []);
  for (const v of views) {
    const extra = `${v.hint || ''} ${v.id} ${v.module || ''} ${v.moduleName || ''} ${v.category || ''}`;
    let sc = textScore(task && !task.match ? task.rest : s, v.label, extra);
    // "new record": a page verb + a topic is a strong hint, a bare topic word a weaker one
    if (topicStems.length && topicStems.some((t) => norm(`${v.label} ${extra}`).includes(t))) sc = Math.min(sc ?? 9, task && !task.match ? 0.5 : 2.5);
    push(sc == null ? null : sc + 0.2, { kind: 'view', key: `v:${v.id}`, label: v.label, sub: ['view', v.category].filter(Boolean).join(' · '), badges: [], pick: { view: v.id } });
  }

  // 3. objects (deduped). With no query: the first few non-ok machines, then views, so the list is useful empty.
  if (s && !task?.match) {
    for (const o of objs) {
      const sc = textScore(s, o.name, `${o.kind || ''} ${o.parent || ''} ${o.alts.map((a) => a.type).join(' ')}`);
      push(sc == null ? null : sc + (TYPE_W[o.type] ?? 0.6) + catRank(catOf(o.sources?.[0])) * 0.05, objItem(o));
    }
  } else if (!s) {
    for (const o of objs.filter((x) => x.type === 'machine' && (x.status === 'bad' || x.status === 'warn')).slice(0, 4)) push(0.1, objItem(o));
  }

  // 4. module rows: those naming an object fold into it (badge); the rest are capped per module
  const per = new Map();
  for (const [list, w] of [[search, 0.9], [lookups, 1.4]]) {
    for (const x of list) {
      const sc = textScore(s, x.label, x.sub || '');
      if (sc == null) continue;
      const o = x.object && byId.get(x.object);
      if (o) {
        const have = out.find(([, it]) => it.kind === 'obj' && it.pick.object === o.id);
        if (have) { if (x.module && !have[1].badges.some((b) => b.label === x.module)) have[1].badges.push({ label: x.module }); continue; }
        if (s) push(sc + w, objItem(o, { label: o.name || x.label }));
        continue;
      }
      const c = (per.get(x.module) || 0) + 1;
      per.set(x.module, c);
      if (c > CAP) continue;
      push(sc + w + catRank(catOf(x.module)) * 0.08 + (task ? 2 : 0) + c * 0.01, {
        kind: 'mod', key: `m:${x.module}:${x.label}:${x.sub || ''}`, label: x.label, sub: [x.sub, x.module].filter(Boolean).join(' · '),
        status: x.status, badges: [], pick: { item: x },
      });
    }
  }

  // 5. commands
  // a command matches on its label or on one of its keywords ("approve" → approvals)
  const cmdScore = (c) => { const a = textScore(s, c.label), b = c.keys ? textScore(s, c.keys) : null; return a == null && b == null ? null : Math.min(a ?? 9, (b ?? 9) + 0.5) + 0.3; };
  for (const c of commands) push(cmdScore(c), { kind: 'cmd', key: `c:${c.label}`, label: c.label, sub: c.sub || 'command', badges: [], pick: { cmd: c } });

  // one row per key (an object found by name and again through a module row)
  const seen = new Set();
  return out.sort((a, b) => a[0] - b[0]).map(([, it]) => it).filter((it) => (seen.has(it.key) ? false : seen.add(it.key))).slice(0, task?.match ? 24 : LIMIT);
}
