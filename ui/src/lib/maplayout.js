// Deterministic, data-driven layout for the Map view (pure JS, no DOM: tests/map_layout.test.mjs runs it in node).
//
// Picture, top to bottom:
//   external band   zones (~/cloud, ~/remote, …) side by side, their nodes in a row (+ their machines as a tree)
//        │ │ │      every external node drops ONE short vertical line …
//   ════◉═════════  … onto the internet bus (the topology node with "bus": true, drawn as a badge on the line)
//        │     │    home nodes on the top home row that talk to the internet rise straight up to it
//   ~/home          a tidy tree from the gateway (the home node linked to the bus): children "below" hang from an
//                   orthogonal connector, children with "place": "left"|"right" sit beside their parent on the same
//                   row (short straight link), and each node's machines hang under it as a `tree`-style list
//                   (trunk + branches, split into columns with their own trunk when long).
// Every line is axis-aligned and lives in its own channel, so nothing crosses and nothing runs through a box.
// The only hints read from topology.json are order (array order of zones/nodes/links), zone, place and bus.

const F = 0.62;                                    // Geist Mono advance = .6em, a hair of slack
export const tw = (s, px) => Math.ceil(String(s ?? '').length * px * F);

export const K = {
  margin: 20, labelPx: 11.5, metaPx: 10, guestPx: 9.5, edgePx: 9.5, zonePx: 11,
  metaMax: 26, guestMax: 18, rowH: 22, colGap: 16, nodeGap: 26, zonePad: 18, zoneGap: 24,
  packM: 22, dropH: 48, riseGap: 50, homeTop: 36, badge: 34, legendH: 52, edgeLblH: 14,
};

// ---- geometry helpers ---------------------------------------------------------------------------------------
const R = (x1, y1, x2, y2, owner, kind) => ({ x1, y1, x2, y2, owner, kind });
const mk = () => ({ hubs: [], guests: [], edges: [], rects: [] });
function shift(b, dx, dy) {
  for (const h of b.hubs) { h.x += dx; h.y += dy; }
  for (const g of b.guests) { g.x += dx; g.y += dy; g.lx += dx; }
  for (const e of b.edges) { e.pts = e.pts.map(([x, y]) => [x + dx, y + dy]); if (e.lx != null) { e.lx += dx; e.ly += dy; }
    if (e.lrect) { e.lrect.x1 += dx; e.lrect.x2 += dx; e.lrect.y1 += dy; e.lrect.y2 += dy; } }
  for (const r of b.rects) { r.x1 += dx; r.x2 += dx; r.y1 += dy; r.y2 += dy; }
  return b;
}
function merge(a, b) { for (const k of ['hubs', 'guests', 'edges', 'rects']) a[k].push(...b[k]); return a; }
// everything that occupies space: boxes, edge labels and (thin) edge segments
function occupied(b) {
  const out = [...b.rects, ...b.edges.filter((e) => e.lrect).map((e) => e.lrect)];
  for (const e of b.edges) for (let i = 1; i < e.pts.length; i++) {
    const [x1, y1] = e.pts[i - 1], [x2, y2] = e.pts[i];
    out.push(R(Math.min(x1, x2) - 1, Math.min(y1, y2) - 1, Math.max(x1, x2) + 1, Math.max(y1, y2) + 1, 'seg'));
  }
  return out;
}
function bbox(rects) {
  const b = { x1: Infinity, y1: Infinity, x2: -Infinity, y2: -Infinity };
  for (const r of rects) { b.x1 = Math.min(b.x1, r.x1); b.y1 = Math.min(b.y1, r.y1); b.x2 = Math.max(b.x2, r.x2); b.y2 = Math.max(b.y2, r.y2); }
  return b;
}
function edgeLabel(e, x, y) {
  if (!e.label) return;
  const w = tw(e.label, K.edgePx) + 8;
  e.lx = x; e.ly = y;
  e.lrect = R(x - w / 2, y - K.edgeLblH / 2, x + w / 2, y + K.edgeLblH / 2, e.id, 'elabel');
}

// ---- weighted pool-adjacent-violators: x[i] >= x[i-1] + sep[i], minimise sum w (x - ideal)^2 ----------------------
export function placeInOrder(ideal, sep, weight) {
  const n = ideal.length, c = [0];
  for (let i = 1; i < n; i++) c[i] = c[i - 1] + sep[i];
  const blocks = []; // {sum w*q, w, from, to}
  for (let i = 0; i < n; i++) {
    blocks.push({ s: weight[i] * (ideal[i] - c[i]), w: weight[i], from: i, to: i });
    while (blocks.length > 1) {
      const b = blocks[blocks.length - 1], a = blocks[blocks.length - 2];
      if (a.s / a.w <= b.s / b.w) break;
      blocks.splice(-2, 2, { s: a.s + b.s, w: a.w + b.w, from: a.from, to: b.to });
    }
  }
  const x = new Array(n);
  for (const b of blocks) for (let i = b.from; i <= b.to; i++) x[i] = b.s / b.w + c[i];
  return x;
}

// ---- the layout -----------------------------------------------------------------------------------------------
// topo: {zones:[{id,label,tone}], nodes:[{id,label,size,round,zone,place,bus,meta}], links:[{from,to,kind,label,rev}]}
// guests: {nodeId: [{id, name}]} (already ordered), metaOf(id) → meta text shown under a hub (or '').
export function layoutMap(topo, guests = {}, { width = 1200, metaOf = () => '' } = {}) {
  let best = null;
  for (let rows = 6; rows <= 10; rows++) {
    const L = layoutOnce(topo, guests, width, metaOf, rows);
    if (!best || L.need < best.need) best = L;
    if (L.need <= width) return L;
  }
  return best;
}

function layoutOnce(topo, guests, width, metaOf, maxRows) {
  const nodes = (topo.nodes || []).filter((n) => n && n.id);
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const zones = (topo.zones || []).filter((z) => z && z.id);
  const homeZone = zones.find((z) => z.home) || { id: 'home', label: '~/home', home: true };
  const zoneOf = (n) => (n.bus ? 'bus' : !n.zone || n.zone === homeZone.id ? 'home' : n.zone);
  const bus = nodes.find((n) => n.bus) || null;
  const ext = nodes.filter((n) => !['bus', 'home'].includes(zoneOf(n)));
  const home = nodes.filter((n) => zoneOf(n) === 'home');
  const links = (topo.links || []).map((l, i) => ({ ...l, i })).filter((l) => byId[l.from] && byId[l.to] && l.from !== l.to);
  let eid = 0;
  const newEdge = (o) => ({ id: `e${eid++}`, ...o });
  const dirCls = (l, forward) => (['flow', 'sig', 'bad'].includes(l.kind) ? ((!!l.rev) !== !forward ? 'flowr' : 'flow') : '');

  // hub geometry, relative to the icon centre
  const hubOf = (n) => {
    const s = n.bus ? K.badge : n.size || 40;
    const meta = String(metaOf(n.id) || n.meta || '').slice(0, K.metaMax);
    const tW = Math.max(tw(n.label || n.id, K.labelPx), meta ? tw(meta.padEnd(16), K.metaPx) : 0) + 8;
    const tTop = s / 2 + 4, tBot = tTop + (meta ? 28 : 17);
    return { s, tW, tTop, tBot, by: tBot + 3 };
  };
  const hubBlock = (n) => {
    const g = hubOf(n), b = mk();
    b.hubs.push({ id: n.id, x: 0, y: 0, s: g.s, tW: g.tW });
    b.rects.push(R(-g.s / 2, -g.s / 2, g.s / 2, g.s / 2, n.id, 'icon'), R(-g.tW / 2, g.tTop, g.tW / 2, g.tBot, n.id, 'text'));
    return { b, g };
  };

  // machines under a node as a `tree` listing; attach point (trunk top) at (0,0)
  const treeBlock = (nid, list) => {
    const b = mk(), cols = Math.ceil(list.length / maxRows), per = Math.ceil(list.length / cols);
    const columns = Array.from({ length: cols }, (_, c) => list.slice(c * per, (c + 1) * per));
    const lw = (g) => tw(String(g.name || g.id).slice(0, K.guestMax), K.guestPx) + 4;
    const widths = columns.map((col) => 36 + Math.max(...col.map(lw)) + K.colGap);
    const trunks = []; let acc = 0;
    for (const w of widths) { trunks.push(acc); acc += w; }
    const mid = (trunks[0] + trunks[cols - 1]) / 2;
    const T = trunks.map((t) => t - mid), group = `tree:${nid}`;
    let y0 = 0;
    if (cols > 1) {
      y0 = 12;
      b.edges.push(newEdge({ pts: [[0, 0], [0, y0]], kind: 'tree', group, ends: [nid] }));
      b.edges.push(newEdge({ pts: [[T[0], y0], [T[cols - 1], y0]], kind: 'tree', group, ends: [nid] }));
    }
    columns.forEach((col, c) => {
      const t = T[c], first = y0 + 18, last = first + (col.length - 1) * K.rowH;
      b.edges.push(newEdge({ pts: [[t, y0], [t, last]], kind: 'tree', group, ends: [nid] }));
      col.forEach((g, r) => {
        const y = first + r * K.rowH, w = lw(g);
        b.edges.push(newEdge({ pts: [[t, y], [t + 13, y]], kind: 'tree', group, ends: [nid, g.id] }));
        b.guests.push({ id: g.id, node: nid, x: t + 22, y, lx: t + 36, w });
        b.rects.push(R(t + 12, y - 10, t + 36 + w, y + 10, g.id, 'guest'));
      });
    });
    return b;
  };

  // ---- home: spanning tree from the gateway over home↔home links ----
  const homeIds = new Set(home.map((n) => n.id));
  const busLinks = links.filter((l) => bus && (l.from === bus.id || l.to === bus.id));
  const rootLink = busLinks.find((l) => homeIds.has(l.from) || homeIds.has(l.to));
  const roots = [];
  if (rootLink) roots.push(homeIds.has(rootLink.from) ? rootLink.from : rootLink.to);
  const kids = {}, seen = new Set(roots), linkTo = {};
  const grow = (start) => {
    const q = [start];
    while (q.length) {
      const id = q.shift();
      kids[id] = [];
      for (const l of links) {
        const other = l.from === id ? l.to : l.to === id ? l.from : null;
        if (!other || !homeIds.has(other) || seen.has(other)) continue;
        seen.add(other); kids[id].push(other); linkTo[other] = l; q.push(other);
      }
    }
  };
  for (const r of roots) grow(r);
  for (const n of home) if (!seen.has(n.id)) { roots.push(n.id); seen.add(n.id); grow(n.id); }

  const block = (id) => {
    const n = byId[id], { b, g } = hubBlock(n);
    const side = { left: null, right: null }, below = [];
    for (const k of kids[id] || []) {
      const p = byId[k].place;
      if ((p === 'left' || p === 'right') && !side[p]) side[p] = k; else below.push(k);
    }
    const gl = guests[id] || [];
    const row = below.map((k) => ({ id: k, link: linkTo[k], b: block(k), top: -hubOf(byId[k]).s / 2 }));
    if (gl.length && !row.length) merge(b, shift(treeBlock(id, gl), 0, g.by));
    else {
      if (gl.length) row.unshift({ id: null, link: null, b: treeBlock(id, gl), top: 0 });
      if (row.length) {
        let cursor = 0;
        for (const it of row) { const bb = bbox(occupied(it.b)); it.x = cursor - bb.x1; shift(it.b, it.x, 0); cursor = bb.x2 + it.x + K.nodeGap; }
        const mid = (row[0].x + row[row.length - 1].x) / 2;
        const labeled = row.some((it) => it.link?.label);
        const top = g.by + (labeled ? 54 : 34), yc = g.by + 14;
        for (const it of row) {
          it.x -= mid; shift(it.b, -mid, top - it.top); merge(b, it.b);
          const x = Math.round(it.x * 2) / 2;
          const pts = Math.abs(x) < 0.5 ? [[0, g.by], [0, top]] : [[0, g.by], [0, yc], [x, yc], [x, top]];
          const l = it.link || {};
          const e = newEdge({ pts, kind: it.id ? l.kind : 'tree', cls: it.id ? dirCls(l, l.from === id) : '', label: l.label,
            group: `below:${id}`, ends: it.id ? [id, it.id] : [id] });
          edgeLabel(e, x, Math.abs(x) < 0.5 ? (g.by + top) / 2 : (yc + top) / 2 + 1);
          b.edges.push(e);
        }
      }
    }
    for (const dir of ['right', 'left']) {
      const k = side[dir];
      if (!k) continue;
      const sb = block(k), l = linkTo[k], sk = hubOf(byId[k]).s / 2, nk = g.s / 2, sg = dir === 'right' ? 1 : -1;
      const minLen = l.label ? tw(l.label, K.edgePx) + 8 + 32 : 40;
      const cur = occupied(b), other = occupied(sb);
      let dx = nk + minLen + sk;
      for (const a of cur) for (const c of other) {
        if (a.y1 - K.packM >= c.y2 || c.y1 >= a.y2 + K.packM) continue;
        dx = Math.max(dx, sg > 0 ? a.x2 + K.packM - c.x1 : c.x2 + K.packM - a.x1);
      }
      shift(sb, sg * dx, 0); merge(b, sb);
      const e = newEdge({ pts: [[sg * nk, 0], [sg * (dx - sk), 0]], kind: l.kind, cls: dirCls(l, l.from === id), label: l.label,
        group: `side:${id}:${k}`, ends: [id, k] });
      edgeLabel(e, sg * (nk + dx - sk) / 2, 0);
      b.edges.push(e);
    }
    return b;
  };

  const H = mk();
  let cursor = null;
  for (const r of roots) {
    const rb = block(r), bb = bbox(occupied(rb));
    if (cursor != null) shift(rb, cursor - bb.x1, 0);
    cursor = bbox(occupied(rb)).x2 + K.nodeGap * 2;
    merge(H, rb);
  }
  const homeHub = Object.fromEntries(H.hubs.map((h) => [h.id, h]));
  const topRow = new Set(H.hubs.filter((h) => Math.abs(h.y) < 0.01).map((h) => h.id));

  // ---- internet: drops (external → bus) and rises (home top row → bus) ----
  const drops = new Map(), rises = new Map();
  const addDrop = (id, l, withLabel, suffix = '') => {
    const lbl = withLabel && l.label ? l.label + suffix : withLabel && suffix ? suffix.replace(/^ · /, '') : '';
    const d = drops.get(id);
    if (d) { if (lbl) d.label = d.label ? `${d.label} / ${lbl}` : lbl; return; }
    drops.set(id, { l, forward: l.from === id, label: lbl });
  };
  const addRise = (id, l, label = '') => { if (!rises.has(id)) rises.set(id, { l, forward: l.from === id, label }); };
  for (const l of links) {
    const za = zoneOf(byId[l.from]), zb = zoneOf(byId[l.to]);
    if (za === 'home' && zb === 'home') continue;               // drawn by the tree (non-tree home links are not drawn)
    if (za === 'bus' || zb === 'bus') {
      const o = za === 'bus' ? l.to : l.from, zo = za === 'bus' ? zb : za;
      if (zo === 'bus') continue;
      if (zo === 'home') { if (topRow.has(o)) addRise(o, l, l.label); } else addDrop(o, l, true);
    } else if (za === 'home' || zb === 'home') {
      const e = za === 'home' ? l.to : l.from, h = za === 'home' ? l.from : l.to;
      if (topRow.has(h)) { addDrop(e, l, true); addRise(h, l); } else addDrop(e, l, true, ` · ${byId[h].label || h}`);
    } else { addDrop(l.from, l, true); addDrop(l.to, l, false); }
  }

  // ---- external band: one element per external node (+ the bus badge), in zone order ----
  const zoneList = [...zones.filter((z) => !z.home && ext.some((n) => zoneOf(n) === z.id))];
  for (const n of ext) if (!zoneList.some((z) => z.id === zoneOf(n))) zoneList.push({ id: zoneOf(n), label: `~/${zoneOf(n)}` });
  const elems = [];
  for (const z of zoneList) {
    const members = ext.filter((n) => zoneOf(n) === z.id);
    members.forEach((n, i) => {
      const { b, g } = hubBlock(n);
      const gl = guests[n.id] || [];
      if (gl.length) merge(b, shift(treeBlock(n.id, gl), 0, g.by));
      const bb = bbox(occupied(b)), d = drops.get(n.id);
      const dx = d ? (gl.length ? bb.x1 - 10 : 0) : null;
      const half = d?.label ? (tw(d.label, K.edgePx) + 8) / 2 : 0;
      let L = Math.max(-bb.x1, dx != null ? half - dx : 0), Rr = Math.max(bb.x2, dx != null ? dx + half : 0);
      if (members.length === 1) { const need = (tw(z.label, K.zonePx) + 40) / 2 - K.zonePad; L = Math.max(L, need); Rr = Math.max(Rr, need); }
      // ideal x: above the home node the link lands on, else above the gateway
      let ideal = 0;
      for (const l of links) {
        const o = l.from === n.id ? l.to : l.to === n.id ? l.from : null;
        if (o && homeHub[o] && roots.length) { ideal = homeHub[o].x - homeHub[roots[0]].x; break; }
      }
      elems.push({ n, b, g, gl, zone: z.id, first: i === 0, L, R: Rr, ideal, w: 1, dropX: dx, bb });
    });
  }
  const badgeText = bus ? Math.max(tw(bus.label || bus.id, K.labelPx), tw(String(metaOf(bus.id) || bus.meta || ''), K.metaPx)) + 8 : 0;
  // badge text goes under the bus on the side with no rising line nearby (else above it, and the band makes room)
  const riseRel = [...rises.keys()].map((id) => homeHub[id].x - homeHub[roots[0]].x).filter((x) => Math.abs(x) > 0.5);
  const span = K.badge / 2 + 6 + badgeText + 14;
  const badgeSide = !bus ? null : !riseRel.some((x) => x > 0 && x < span) ? 'right' : !riseRel.some((x) => x < 0 && -x < span) ? 'left' : 'above';
  const badgeEl = bus ? { badge: true, L: K.badge / 2 + 8, R: K.badge / 2 + 8 + (badgeSide === 'above' ? badgeText + 6 : 0), ideal: 0, w: 50 } : null;
  const sepOf = (a, b) => a.R + b.L + (a.badge || b.badge ? K.zonePad + 16 : a.zone !== b.zone ? K.zoneGap + 2 * K.zonePad : K.nodeGap);
  let seq = elems, best = null;
  if (badgeEl) {
    const bounds = [0];
    elems.forEach((e, i) => { if (i > 0 && e.first) bounds.push(i); });
    bounds.push(elems.length);
    for (const at of bounds) {
      const s = [...elems.slice(0, at), badgeEl, ...elems.slice(at)];
      const x = placeInOrder(s.map((e) => e.ideal), s.map((e, i) => (i ? sepOf(s[i - 1], e) : 0)), s.map((e) => e.w));
      const xb = x[at];
      const cost = s.reduce((acc, e, i) => acc + (e.badge ? 0 : (x[i] - xb - e.ideal) ** 2), 0) + Math.abs(at - bounds.length / 2) * 1e-3;
      if (!best || cost < best.cost) best = { cost, s, x };
    }
    seq = best.s;
  }
  const xs = best ? best.x : placeInOrder(seq.map((e) => e.ideal), seq.map((e, i) => (i ? sepOf(seq[i - 1], e) : 0)), seq.map((e) => e.w));

  // vertical band geometry
  const maxS = Math.max(40, ...elems.map((e) => e.g.s));
  const zoneTop = K.margin + 10, headY = zoneTop + 30 + maxS / 2;
  const out = mk(), zoneBoxes = [];
  let zoneBot = headY;
  seq.forEach((e, i) => { if (!e.badge) { shift(e.b, xs[i], headY); e.x = xs[i]; zoneBot = Math.max(zoneBot, bbox(occupied(e.b)).y2); } });
  zoneBot += 14;
  const busY = elems.length || bus ? zoneBot + K.dropH : null;
  for (const e of elems) {
    merge(out, e.b);
    const d = drops.get(e.n.id);
    if (!d) continue;
    const x = e.x + e.dropX;
    const pts = e.gl.length ? [[e.x - e.g.s / 2, headY], [x, headY], [x, busY]] : [[x, headY + e.g.by], [x, busY]];
    const edge = newEdge({ pts: d.forward ? pts : [...pts].reverse(), kind: d.l.kind, cls: dirCls(d.l, true), label: d.label,
      group: 'bus', ends: [e.n.id, bus?.id].filter(Boolean) });
    edgeLabel(edge, x, zoneBot + (busY - zoneBot) / 2 - 4);
    out.edges.push(edge);
  }
  for (const z of zoneList) {
    const mem = elems.filter((e) => e.zone === z.id);
    if (!mem.length) continue;
    const bb = bbox(mem.flatMap((e) => e.b.rects));
    let x1 = bb.x1 - K.zonePad, x2 = bb.x2 + K.zonePad;
    const need = tw(z.label, K.zonePx) + 40;
    if (x2 - x1 < need) { const pad = (need - (x2 - x1)) / 2; x1 -= pad; x2 += pad; }
    zoneBoxes.push({ id: z.id, label: z.label, tone: z.tone, x: x1, y: zoneTop, w: x2 - x1, h: zoneBot - zoneTop });
  }

  // home placed so the gateway sits right under the badge
  const bi = seq.indexOf(badgeEl);
  const badgeX = bi >= 0 ? xs[bi] : 0;
  const homeZoneTop = busY != null ? busY + K.riseGap : zoneTop;
  const maxTopS = Math.max(40, ...H.hubs.filter((h) => topRow.has(h.id)).map((h) => h.s));
  const homeHeadY = homeZoneTop + K.homeTop + maxTopS / 2;
  shift(H, roots.length ? badgeX - homeHub[roots[0]].x : badgeX, homeHeadY);
  merge(out, H);
  for (const [id, r] of rises) {
    const h = homeHub[id], pts = [[h.x, h.y - h.s / 2], [h.x, busY]];
    const e = newEdge({ pts: r.forward ? pts : [...pts].reverse(), kind: r.l.kind, cls: dirCls(r.l, true), label: r.label,
      group: 'bus', ends: [id, bus?.id].filter(Boolean) });
    edgeLabel(e, h.x, (busY + homeZoneTop) / 2);
    out.edges.push(e);
  }
  const hb = bbox(H.rects.length ? occupied(H) : [R(badgeX, homeHeadY, badgeX, homeHeadY)]);
  const homeBox = { id: homeZone.id, label: homeZone.label, tone: homeZone.tone, home: true,
    x: hb.x1 - 24, y: homeZoneTop, w: hb.x2 - hb.x1 + 48, h: hb.y2 + 24 - homeZoneTop };
  zoneBoxes.push(homeBox);

  // the bus itself + its badge
  let badge = null;
  if (busY != null) {
    const xsOnBus = out.edges.filter((e) => e.group === 'bus').flatMap((e) => e.pts.filter(([, y]) => y === busY).map(([x]) => x));
    if (bus) {
      xsOnBus.push(badgeX - K.badge / 2);
      badge = { id: bus.id, x: badgeX, y: busY, s: K.badge, tW: badgeText, side: badgeSide };
      const tx1 = badgeSide === 'left' ? badgeX - K.badge / 2 - 6 - badgeText : badgeX + K.badge / 2 + 6;
      const ty1 = badgeSide === 'above' ? busY - 33 : busY + 4;
      out.rects.push(R(badgeX - K.badge / 2, busY - K.badge / 2, badgeX + K.badge / 2, busY + K.badge / 2, bus.id, 'icon'),
        R(tx1, ty1, tx1 + badgeText, ty1 + 29, bus.id, 'text'));
    }
    if (xsOnBus.length) {
      const l = bus && busLinks.find((x) => x.from === bus.id || x.to === bus.id);
      out.edges.push(newEdge({ pts: [[Math.min(...xsOnBus), busY], [Math.max(...xsOnBus, badgeX + K.badge / 2), busY]],
        kind: 'bus', cls: '', group: 'bus', ends: [bus?.id].filter(Boolean), link: l?.kind }));
    }
  }

  // zone labels sit on the top border; move a label right if a line crosses it there
  for (const z of zoneBoxes) {
    const w = tw(z.label, K.zonePx) + 12;
    const vert = out.edges.flatMap((e) => e.pts.slice(1).map((p, i) => [e.pts[i], p])).filter(([a, b]) => a[0] === b[0]
      && Math.min(a[1], b[1]) <= z.y + 9 && Math.max(a[1], b[1]) >= z.y - 9).map(([a]) => a[0]);
    let lx = z.x + 10;
    for (const x of [...vert].sort((a, b) => a - b)) if (x >= lx - 6 && x <= lx + w + 6) lx = x + 10;
    z.lx = lx - z.x;
    z.lw = w;
    out.rects.push(R(lx, z.y - 9, lx + w, z.y + 9, `zone:${z.id}`, 'zlabel'));
  }

  // normalise into the canvas (centred when there is room)
  const all = bbox([...occupied(out), ...zoneBoxes.map((z) => R(z.x, z.y, z.x + z.w, z.y + z.h))]);
  const need = Math.ceil(all.x2 - all.x1 + 2 * K.margin);
  const W = Math.max(width, need);
  const dx = K.margin - all.x1 + (W - need) / 2;
  shift(out, dx, 0);
  for (const z of zoneBoxes) z.x += dx;
  if (badge) badge.x += dx;
  const Hh = Math.ceil(homeBox.y + homeBox.h + K.legendH);
  for (const e of out.edges) if (e.lrect) out.rects.push(e.lrect);
  return { W, H: Hh, need, maxRows, zones: zoneBoxes, hubs: out.hubs, guests: out.guests, edges: out.edges, rects: out.rects,
    badge, busY, legend: { x: homeBox.x, y: homeBox.y + homeBox.h + 14 } };
}

// SVG path for an orthogonal polyline with small rounded corners
export function roundedPath(pts, r = 6) {
  if (!pts.length) return '';
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [ax, ay] = pts[i - 1], [px, py] = pts[i], [bx, by] = pts[i + 1];
    const l1 = Math.hypot(px - ax, py - ay), l2 = Math.hypot(bx - px, by - py);
    const k = Math.min(r, l1 / 2, l2 / 2);
    if (!k) { d += ` L${px},${py}`; continue; }
    d += ` L${px - (px - ax) / l1 * k},${py - (py - ay) / l1 * k} Q${px},${py} ${px + (bx - px) / l2 * k},${py + (by - py) / l2 * k}`;
  }
  const [lx, ly] = pts[pts.length - 1];
  return `${d} L${lx},${ly}`;
}
