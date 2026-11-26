// UniFi helpers shared by the module's hooks and components.

// a reservation that is not what the client actually has right now (DHCP lease from before the reservation, static IP, …)
export const mismatch = (c) => c.online && c.reserved && c.fixedIp && c.ip && c.ip !== c.fixedIp;

const toInt = (ip) => ip.split('.').reduce((a, b) => a * 256 + Number(b), 0);
const toIp = (n) => [24, 16, 8, 0].map((s) => Math.floor(n / 2 ** s) % 256).join('.');

// first address in `net` (from .50 up — servers live there) that no reservation, active client or 24 h lease uses.
// The connector re-checks on save; a ping is not enough.
export function freeIp(net, clients, from = 50) {
  if (!net?.subnet) return '';
  const [gw, bits] = net.subnet.split('/');
  const size = 2 ** (32 - Number(bits));
  const base = toInt(gw) - (toInt(gw) % size);
  const day = Date.now() / 1000 - 86400;
  const used = new Set([gw]);
  for (const c of clients) {
    if (c.fixedIp && c.reserved) used.add(c.fixedIp);
    if (c.ip && (c.online || (c.lastSeen || 0) > day)) used.add(c.ip);
  }
  for (let i = Math.min(from, size - 2); i < size - 1; i++) if (!used.has(toIp(base + i))) return toIp(base + i);
  return '';
}

export const label = (c) => c.name || c.hostname || c.mac;

// first word of a client name ("npmplus (CT 101, port forwards)" → "npmplus")
const firstWord = (s) => (s || '').toLowerCase().split(/[\s(]/)[0];

// the UniFi client that is this machine (by reservation/client name or hostname)
export function clientFor(unifi, id) {
  const cs = unifi?.clients || [];
  return cs.find((c) => c.reserved && firstWord(c.name) === id) || cs.find((c) => firstWord(c.name) === id)
    // hostname only for clients without a UniFi name (a nspawn container announces a DHCP hostname that is not its name)
    || cs.find((c) => !c.name && (c.hostname || '').toLowerCase() === id) || null;
}
