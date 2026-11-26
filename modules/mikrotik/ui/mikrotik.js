// Pure helpers for the MikroTik module (RouterOS REST answers everything as strings).
export const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : 0; };

// RouterOS duration "23w4d2h28m57s" → seconds
export function uptimeSecs(s) {
  const u = { w: 604800, d: 86400, h: 3600, m: 60, s: 1 };
  let t = 0;
  for (const [, n, k] of String(s || '').matchAll(/(\d+)([wdhms])/g)) t += Number(n) * u[k];
  return t;
}

// "1Gbps" / "100Mbps" / "10Gbps" → Mbit/s (0 when unknown)
export function rateMbps(s) {
  const m = /^([\d.]+)\s*([GMK])bps$/i.exec(String(s || ''));
  if (!m) return 0;
  return Math.round(Number(m[1]) * { G: 1000, M: 1, K: 0.001 }[m[2].toUpperCase()]);
}
export const speedText = (mbps) => (!mbps ? '–' : mbps >= 1000 ? `${mbps / 1000}G` : `${mbps}M`);

// /system/health → {temp, boardTemp, poeW, fan, psu}
export function health(list) {
  const h = Object.fromEntries((Array.isArray(list) ? list : []).map((x) => [x.name, x.value]));
  const v = (k) => (h[k] === undefined || h[k] === '' ? null : num(h[k]));
  return { temp: v('cpu-temperature') ?? v('temperature'), boardTemp: v('board-temperature1'), poeW: v('poe-out-consumption'),
    fan: h['fan-state'] || null, psu1: v('psu1-voltage'), psu2: v('psu2-voltage') };
}

const byName = (xs) => Object.fromEntries((Array.isArray(xs) ? xs : []).map((x) => [x.name, x]));

// Joins /interface, /interface/ethernet, the PoE settings and the two monitor calls into one row per port.
// `prev` is {name: {rx, tx, t, fcs0}} from the last call (traffic rates, error growth); returns {ports, next}.
export function buildPorts({ ifaces, eth, poe, mon, poemon }, prev = {}, now = Date.now() / 1000) {
  const E = byName(eth), P = byName(poe), M = byName(mon), PM = byName(poemon);
  const ports = [], next = {};
  for (const i of Array.isArray(ifaces) ? ifaces : []) {
    if (i.type !== 'ether' || !E[i.name]) continue;
    const e = E[i.name], m = M[i.name] || {}, p = P[i.name], pm = PM[i.name] || {};
    const rx = num(i['rx-byte']), tx = num(i['tx-byte']);
    const old = prev[i.name];
    const dt = old ? now - old.t : 0;
    const rate = (a, b) => (dt >= 1 && a >= b ? (a - b) / dt : 0);
    const fcs = num(e['rx-fcs-error']);
    const running = i.running === 'true', disabled = i.disabled === 'true';
    next[i.name] = { rx, tx, t: now, fcs0: old ? old.fcs0 : fcs };
    ports.push({
      name: i.name, comment: i.comment || '', running, disabled,
      speed: running ? rateMbps(m.rate) : 0, duplex: m['full-duplex'] === 'false' ? 'half' : 'full',
      rx, tx, rxRate: rate(rx, old?.rx ?? Infinity), txRate: rate(tx, old?.tx ?? Infinity),
      linkDowns: num(i['link-downs']), fcs, fcsGrowth: fcs - next[i.name].fcs0, txDrop: num(e['tx-drop']),
      rxErr: num(e['rx-error-events']), lastUp: i['last-link-up-time'] || '',
      poe: p ? { mode: p['poe-out'], status: pm['poe-out-status'] || '', priority: num(p['poe-priority']),
        watts: num(pm['poe-out-power']), ma: num(pm['poe-out-current']), volts: num(pm['poe-out-voltage']) } : null,
    });
  }
  return { ports, next };
}

// PoE port states that mean trouble. "short-circuit" on a port with a non-PoE device is just how RouterOS reports it.
export const poeBad = (s) => /overload|voltage-too|current-too|hardware|error/i.test(s || '');
export const poeOn = (p) => !!p.poe && /powered/i.test(p.poe.status);

// what is wrong right now → [{key, status, title, detail?, port?}]
export function problems(d, st = {}) {
  const out = [];
  const ign = new Set(st.ignore_ports || []);
  const warnT = st.temp_warn ?? 70;
  if (d.health?.temp != null && d.health.temp >= warnT) out.push({ key: 'mikrotik:temp', status: d.health.temp >= warnT + 10 ? 'bad' : 'warn', title: `switch CPU at ${d.health.temp}°C` });
  if (d.sys?.cpu >= 90) out.push({ key: 'mikrotik:cpu', status: 'warn', title: `switch CPU load ${d.sys.cpu}%` });
  if (d.health?.fan && d.health.fan !== 'ok') out.push({ key: 'mikrotik:fan', status: 'warn', title: `switch fan: ${d.health.fan}` });
  for (const p of d.ports || []) {
    if (ign.has(p.name)) continue;
    if (p.poe && poeBad(p.poe.status)) out.push({ key: `mikrotik:poe:${p.name}`, status: 'warn', title: `${p.name} PoE ${p.poe.status}`, port: p.name });
    if (p.running && st.slow_warn !== false && p.speed && p.speed < 1000 && !p.name.startsWith('sfp'))
      out.push({ key: `mikrotik:slow:${p.name}`, status: 'warn', title: `${p.name} links at ${speedText(p.speed)}`, detail: p.comment || undefined, port: p.name });
    if (p.fcsGrowth > 0) out.push({ key: `mikrotik:fcs:${p.name}`, status: 'warn', title: `${p.name} receiving bad frames (+${p.fcsGrowth} CRC)`, port: p.name });
  }
  return out;
}

const expand = (s) => String(s || '').split(',').filter(Boolean).flatMap((x) => {
  const m = /^(\d+)-(\d+)$/.exec(x);
  return m && Number(m[2]) - Number(m[1]) < 100 ? Array.from({ length: m[2] - m[1] + 1 }, (_, k) => String(Number(m[1]) + k)) : [x];
});

// bridge vlan entries (+ bridge ports for PVIDs) → [{vlan, bridge, tagged:[], untagged:[], pvid:[]}] by VLAN id
export function vlanTable(vlans, bports = []) {
  const rows = new Map();
  for (const v of Array.isArray(vlans) ? vlans : []) {
    if (v.disabled === 'true') continue;
    for (const id of expand(v['vlan-ids'])) {
      const key = `${v.bridge}/${id}`;
      const r = rows.get(key) || { vlan: id, bridge: v.bridge, tagged: new Set(), untagged: new Set(), pvid: [] };
      const cur = (a, b) => (v[a] !== undefined ? v[a] : v[b]);
      for (const p of String(cur('current-tagged', 'tagged') || '').split(',').filter(Boolean)) r.tagged.add(p);
      for (const p of String(cur('current-untagged', 'untagged') || '').split(',').filter(Boolean)) r.untagged.add(p);
      rows.set(key, r);
    }
  }
  for (const b of Array.isArray(bports) ? bports : []) {
    const r = rows.get(`${b.bridge}/${b.pvid}`);
    if (r && b.interface) r.pvid.push(b.interface);
  }
  return [...rows.values()].map((r) => ({ ...r, tagged: [...r.tagged].sort(portCmp), untagged: [...r.untagged].sort(portCmp), pvid: r.pvid.sort(portCmp) }))
    .sort((a, b) => num(a.vlan) - num(b.vlan));
}
export const portCmp = (a, b) => String(a).localeCompare(String(b), undefined, { numeric: true });
