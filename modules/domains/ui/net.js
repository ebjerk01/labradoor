// Helpers for the hostname join: certificate maths, probe levels, IP → machine map, backend target parsing.

export const days = (unix) => (unix == null ? null : (unix - Date.now() / 1000) / 86400);
export const dayTxt = (d) => (d == null ? '–' : d < 1 ? `${Math.max(0, Math.round(d * 24))}h` : `${d.toFixed(d < 10 ? 1 : 0)}d`);
// NPMplus uses Let's Encrypt short-lived certs (~6.7 days), so 3–5 days left is normal; renewal failing shows < 1.5 d.
export const certLevel = (d) => (d == null ? null : d < 0.75 ? 'bad' : d < 1.5 ? 'warn' : 'ok');

export const probeLevel = (p) => (!p ? 'unknown' : p.state === 'up' ? 'ok' : p.state === 'timeout' ? 'warn' : 'bad');

// first word of a UniFi client name ("npmplus (CT 101, port forwards)" → "npmplus")
const firstWord = (s) => (s || '').toLowerCase().split(/[\s(]/)[0];

// IP → {name, machine} from UniFi clients (reservations + active), matched to drift machine ids where possible.
export function ipMap(unifi, drift) {
  const ids = new Set();
  for (const g of drift?.overview?.guests || []) ids.add(g.name);
  for (const h of drift?.overview?.hosts || []) ids.add(h.name);
  const out = {};
  for (const c of unifi?.clients || []) {
    const ip = c.fixedIp || c.ip;
    if (!ip || (!c.reserved && !c.online)) continue;
    const w = firstWord(c.name), hn = (c.hostname || '').toLowerCase();
    const machine = ids.has(w) ? w : ids.has(hn) ? hn : null;
    if (!c.name && !c.hostname && !machine) continue;
    if (!out[ip] || machine || c.reserved) out[ip] = { name: c.name || c.hostname, machine, mac: c.mac };
  }
  return out;
}

// the UniFi client that is this machine (by reservation/client name or hostname)
export function clientFor(unifi, id) {
  const cs = unifi?.clients || [];
  return cs.find((c) => c.reserved && firstWord(c.name) === id) || cs.find((c) => firstWord(c.name) === id)
    // hostname only for clients without a UniFi name: the PBS nspawn on media-host announces the DHCP hostname
    // "sdr-test" but is named "pbs (nspawn on media-host)", and must not become CT 116's client
    || cs.find((c) => !c.name && (c.hostname || '').toLowerCase() === id) || null;
}

export function hostPort(target) {
  if (!target) return null;
  try {
    const u = new URL(/^[a-z]+:\/\//i.test(target) ? target : `tcp://${target}`);
    const port = u.port || (u.protocol === 'https:' ? '443' : u.protocol === 'http:' ? '80' : '');
    return { host: u.hostname.toLowerCase(), port: port ? Number(port) : null, query: u.search };
  } catch { return null; }
}
