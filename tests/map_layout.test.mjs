// Map layout check: no two lines cross or touch (except inside one bundle: a tree, a below-connector, the bus),
// no line runs through a box (hub icon/label, machine row, edge label, zone label) that is not its own endpoint,
// no two boxes overlap, every line is orthogonal. Runs on deploy/topology.json with a set of machines derived
// from its own host nodes, and on bigger synthetic labs, at phone, laptop and wide widths. No installation
// names, so it runs the same on any Labradoor tree.  Usage: node tests/map_layout.test.mjs  (exit 1 on failure)
import { readFileSync } from 'node:fs';
import { layoutMap } from '../ui/src/lib/maplayout.js';

const topo = JSON.parse(readFileSync(new URL('../deploy/topology.json', import.meta.url), 'utf8'));
const g = (names) => names.map((n) => ({ id: n, name: n }));

// Host nodes = home-zone boxes that carry a tree of guests: no zone (home), not the internet bus, no switch/
// router icon, not a left/right neighbour. The gateway/switch/neighbours are derived the same way, by role.
const hosts = topo.nodes.filter((n) => !n.zone && !n.bus && !n.icon && !n.place).map((n) => n.id);
const anchor = topo.nodes.find((n) => n.icon === 'switch')?.id
  || topo.nodes.find((n) => n.icon === 'router')?.id || hosts[0] || topo.nodes[0]?.id;

// a spread of guests under the first few hosts
const today = {};
hosts.slice(0, 5).forEach((id, k) => { today[id] = g(Array.from({ length: 4 + k * 3 }, (_, i) => `${id}-m${i}`)); });
const live = () => '';

// a bigger lab: load the hosts heavily, hang extra hubs off the anchor, add a side switch with neighbours and a
// node in a non-home zone
function synthetic(seed) {
  const t = JSON.parse(JSON.stringify(topo));
  let s = seed;
  const rnd = (n) => { s = (s * 1103515245 + 12345) % 2147483648; return s % n; };
  const name = (p, i) => `${p}-${'abcdefghijklmnopqrstuvwxyz'.slice(0, 3 + rnd(14))}${i}`;
  const gs = {};
  hosts.forEach((id, k) => { gs[id] = Array.from({ length: (k === 0 ? 30 : 3) + rnd(k === 0 ? 15 : 12) }, (_, i) => ({ id: `${id}-${i}`, name: name(id, i) })); });
  for (let i = 0; i < 2 + rnd(3); i++) {
    const id = `hub-x${i}`;
    t.nodes.push({ id, label: id, size: 48 });
    if (anchor) t.links.push({ from: anchor, to: id, kind: 'flow' });
    gs[id] = Array.from({ length: 1 + rnd(9) }, (_, j) => ({ id: `${id}-${j}`, name: name('x', j) }));
  }
  if (anchor) {
    t.nodes.push({ id: 'sw2', label: 'sw2', icon: 'switch' }, { id: 'nas9', label: 'nas9', place: 'left' }, { id: 'ap1', label: 'ap1', place: 'right' });
    t.links.push({ from: anchor, to: 'sw2', kind: 'flow', label: '10g' }, { from: 'sw2', to: 'nas9', kind: 'dashed', label: 'iscsi' }, { from: 'sw2', to: 'ap1', kind: 'dashed' });
    gs.sw2 = g(['sw2-a', 'sw2-b', 'sw2-c']);
  }
  const zone = t.zones.find((z) => !z.home);
  if (zone && anchor) {
    t.nodes.push({ id: 'site2', label: 'site2', zone: zone.id, meta: 'vpn' });
    t.links.push({ from: 'site2', to: anchor, kind: 'sig', label: 'vpn' });
  }
  return { t, gs };
}

const EPS = 0.01;
const segs = (e) => e.pts.slice(1).map((p, i) => [e.pts[i], p]);
const box = ([a, b]) => ({ x1: Math.min(a[0], b[0]), y1: Math.min(a[1], b[1]), x2: Math.max(a[0], b[0]), y2: Math.max(a[1], b[1]) });
const touch = (p, q, pad = 0) => p.x1 <= q.x2 + pad && q.x1 <= p.x2 + pad && p.y1 <= q.y2 + pad && q.y1 <= p.y2 + pad;
const inside = (p, q) => p.x1 < q.x2 - 0.5 && q.x1 < p.x2 - 0.5 && p.y1 < q.y2 - 0.5 && q.y1 < p.y2 - 0.5;

function check(L, what) {
  const errs = [];
  const S = L.edges.flatMap((e) => segs(e).map((s) => ({ e, s, b: box(s) })));
  for (const { e, s } of S) if (Math.abs(s[0][0] - s[1][0]) > EPS && Math.abs(s[0][1] - s[1][1]) > EPS) errs.push(`diagonal ${e.id} ${e.group}`);
  for (let i = 0; i < S.length; i++) for (let j = i + 1; j < S.length; j++) {
    const A = S[i], B = S[j];
    if (A.e.group === B.e.group) continue;
    if (touch(A.b, B.b, 1)) errs.push(`lines touch: ${A.e.group}[${A.e.ends}] × ${B.e.group}[${B.e.ends}] at ${A.b.x1},${A.b.y1}`);
  }
  const owners = (e) => new Set([...(e.ends || []), e.id]);
  for (const { e, b } of S) for (const r of L.rects) {
    if (owners(e).has(r.owner)) continue;
    if (inside(b, { x1: r.x1 + 1, y1: r.y1 + 1, x2: r.x2 - 1, y2: r.y2 - 1 })) errs.push(`line ${e.group}[${e.ends}] through ${r.kind} ${r.owner}`);
  }
  for (let i = 0; i < L.rects.length; i++) for (let j = i + 1; j < L.rects.length; j++) {
    const a = L.rects[i], b = L.rects[j];
    if (a.owner === b.owner) continue;
    if (inside(a, b)) errs.push(`overlap ${a.kind} ${a.owner} × ${b.kind} ${b.owner}`);
  }
  for (const r of L.rects) if (r.x1 < 0 || r.x2 > L.W || r.y1 < 0 || r.y2 > L.H) errs.push(`outside canvas ${r.kind} ${r.owner}`);
  const zs = L.zones;
  for (let i = 0; i < zs.length; i++) for (let j = i + 1; j < zs.length; j++) {
    const a = zs[i], b = zs[j];
    if (inside({ x1: a.x, y1: a.y, x2: a.x + a.w, y2: a.y + a.h }, { x1: b.x, y1: b.y, x2: b.x + b.w, y2: b.y + b.h })) errs.push(`zones overlap ${a.id} × ${b.id}`);
  }
  if (errs.length) { console.error(`FAIL ${what}:\n  ${[...new Set(errs)].slice(0, 25).join('\n  ')}`); return false; }
  console.log(`ok   ${what}  (${L.W}×${L.H}, ${L.edges.length} lines, ${L.hubs.length} hubs, ${L.guests.length} machines, rows≤${L.maxRows})`);
  return true;
}

let ok = true;
for (const w of [390, 1280, 1900]) ok = check(layoutMap(topo, today, { width: w, metaOf: live }), `base @${w}`) && ok;
for (const seed of [1, 7, 42, 99, 2026]) {
  const { t, gs } = synthetic(seed);
  for (const w of [390, 1600]) ok = check(layoutMap(t, gs, { width: w, metaOf: live }), `synthetic#${seed} @${w}`) && ok;
}
process.exit(ok ? 0 : 1);
