// Technitium helpers: response unwrapping and record value ↔ API parameter mapping.

export function unwrap(r) {
  if (r?.status === 'ok') return r.response || {};
  const e = new Error(r?.status === 'invalid-token' ? 'technitium: invalid API token' : `technitium: ${r?.errorMessage || r?.status || 'no answer'}`);
  e.body = r;
  throw e;
}

// rData → the parameter Technitium wants for add/delete of that type, and a display string
const PARAM = { A: 'ipAddress', AAAA: 'ipAddress', CNAME: 'cname', TXT: 'text', NS: 'nameServer', PTR: 'ptrName', MX: 'exchange' };
export const EDITABLE = ['A', 'AAAA', 'CNAME', 'TXT'];

export function value(r) {
  const d = r.rData || {};
  if (r.type === 'MX') return `${d.preference} ${d.exchange}`;
  if (r.type === 'SOA') return `${d.primaryNameServer} ${d.serial}`;
  if (r.type === 'SRV') return `${d.priority} ${d.weight} ${d.port} ${d.target}`;
  return d[PARAM[r.type]] ?? d.value ?? JSON.stringify(d).slice(0, 80);
}

export function recordQuery(zone, name, type, val, extra = {}) {
  const p = new URLSearchParams({ zone, domain: name, type, ...extra });
  if (PARAM[type] && val != null) p.set(PARAM[type], val);
  return p.toString();
}
