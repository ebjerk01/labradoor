// graylog helpers: source → object id mapping, query building, the two search calls, level styling.
// Log lines are data from every host in the lab: they are only ever rendered as text, never interpreted.
// Everything installation-specific comes from the module settings (cfgOf).

export const DEFAULT_STREAM = '000000000000000000000001';   // Graylog's own "All messages" stream

const list = (v) => (Array.isArray(v) ? v.map((x) => String(x).trim()).filter(Boolean) : []);

// the settings as the helpers use them; it travels in the module's data (data.cfg) so components need no ctx for it
export function cfgOf(ctx) {
  const s = ctx?.settings || {};
  const alias = {};
  for (const a of list(s.host_aliases)) {
    const [k, v] = a.split('=').map((x) => x.trim());
    if (k && v) alias[k.toLowerCase()] = v;
  }
  return { web: String(s.web_url || '').replace(/\/+$/, ''), alias, domains: list(s.strip_domains).map((d) => d.replace(/^\./, '').toLowerCase()),
    prefixes: list(s.strip_prefixes).map((p) => p.toLowerCase()), self: s.self_object || 'graylog', syslog: s.syslog_target || '',
    security: s.security_object || '' };
}

// hostname → normalised: lower case, no domain, no configured prefix
export function norm(src, cfg) {
  let n = String(src || '').toLowerCase().trim().replace(/\.(lan|localdomain|local|home\.arpa)$/, '');
  for (const d of cfg?.domains || []) if (n.endsWith(`.${d}`)) { n = n.slice(0, -d.length - 1); break; }
  for (const p of cfg?.prefixes || []) if (n.startsWith(p)) { n = n.slice(p.length); break; }
  return n;
}

// source → {id, known}: an existing lab object id when one matches (id, then name, case-insensitive), else the alias.
export function idOf(src, cfg, objects) {
  const n = norm(src, cfg);
  const cand = [cfg?.alias?.[n], n, String(src)].filter(Boolean);
  for (const c of cand) if (objects?.has?.(c)) return { id: c, known: true };
  if (objects?.size) {
    const lc = new Set(cand.map((c) => c.toLowerCase()));
    for (const [id, o] of objects) if (lc.has(id.toLowerCase()) || lc.has(String(o.name || '').toLowerCase())) return { id, known: true };
  }
  return { id: cfg?.alias?.[n] || n, known: false };
}

// Lucene: quote a value
export const quote = (v) => `"${String(v).replace(/[\\"]/g, '\\$&')}"`;
export const anyOf = (field, vals) => (vals.length === 1 ? `${field}:${quote(vals[0])}` : `${field}:(${vals.map(quote).join(' OR ')})`);

// What to search for an object: {q, label} or null. machine/external: its sources. service: apps named like it.
export function queryFor(obj, d) {
  const cfg = d?.cfg;
  if (!obj || !d) return null;
  const srcs = d.sources.filter((s) => s.id === obj.id).map((s) => s.src);
  if (srcs.length) return { q: anyOf('source', srcs), label: srcs.join(' ') };
  if (obj.type !== 'service') return null;
  const raw = String(obj.name || obj.id).replace(/^check:/, '');
  const name = raw.toLowerCase();
  // drift checks are named like "Graylog (logs)": the first word is usually the host
  const first = name.split(/[\s(/:]+/)[0];
  const host = d.sources.filter((s) => s.id === first || norm(s.src, cfg) === first).map((s) => s.src);
  if (host.length && first !== name) return { q: anyOf('source', host), label: host.join(' ') };
  const apps = (d.apps || []).filter((a) => { const l = a.toLowerCase(); return l === name || l.startsWith(name + '-') || l === first; });
  if (apps.length) return { q: anyOf('application_name', apps), label: apps.join(' ') };
  if (host.length) return { q: anyOf('source', host), label: host.join(' ') };
  return null;
}

// links into Graylog's own UI; null when the web address setting is empty
export const webUrl = (cfg, q, range = 3600) => (!cfg?.web ? null : `${cfg.web}/search?q=${encodeURIComponent(q)}&` + (typeof range === 'object'
  ? `rangetype=absolute&from=${encodeURIComponent(range.from)}&to=${encodeURIComponent(range.to)}` : `rangetype=relative&from=${range}`));
export const msgUrl = (cfg, m) => (cfg?.web ? `${cfg.web}/messages/${encodeURIComponent(m.index)}/${encodeURIComponent(m._id)}` : null);

// --- levels: syslog 0..7. Status = shape + colour. -----------------------------------------------------------
export function lvl(level) {
  const n = level == null || level === '' ? null : Number(level);
  if (n == null || isNaN(n)) return { g: '·', c: 'var(--faint)', n: '-' };
  if (n <= 3) return { g: '■', c: 'var(--bad)', n: ['emerg', 'alert', 'crit', 'err'][n] };
  if (n === 4) return { g: '▲', c: 'var(--warn)', n: 'warn' };
  if (n === 5) return { g: '●', c: 'var(--sig)', n: 'notice' };
  if (n === 6) return { g: '●', c: 'var(--dim)', n: 'info' };
  return { g: '○', c: 'var(--faint)', n: 'debug' };
}
export const ERRORS = 'level:<=3';

// Graylog times: "2026-11-13T23:02:55.470Z" (messages) or "2026-11-13 23:03:08.303" (UTC, aggregate latest())
export const ts = (s) => (s ? Date.parse(String(s).includes('T') ? s : String(s).replace(' ', 'T') + 'Z') / 1000 : null);
export const hms = (s) => { const t = ts(s); return t ? new Date(t * 1000).toLocaleTimeString('nb-NO', { hour12: false }) : '--:--:--'; };
export const hm = (s) => { const t = ts(s); return t ? new Date(t * 1000).toLocaleTimeString('nb-NO', { hour: '2-digit', minute: '2-digit' }) : '--:--'; };
export const one = (s, max = 400) => String(s ?? '').replace(/\s+/g, ' ').slice(0, max);

// --- API ---------------------------------------------------------------------------------------------------
const FIELDS = 'timestamp,source,level,application_name,message,facility';

// newest-first messages. range = seconds (relative) or {from, to} ISO (absolute)
export async function messages(ctx, q, { range = 3600, limit = 30, stream = '', fields = FIELDS, offset = 0 } = {}) {
  const p = { query: q || '*', limit, offset, sort: 'timestamp:desc', decorate: 'false' };
  if (fields) p.fields = fields;
  if (stream) p.filter = `streams:${stream}`;
  const abs = typeof range === 'object';
  if (abs) Object.assign(p, { from: range.from, to: range.to }); else p.range = range;
  const r = await ctx.api.get(`/api/search/universal/${abs ? 'absolute' : 'relative'}`, p);
  return { total: r.total_results, list: (r.messages || []).map((m) => ({ ...m.message, index: m.index })) };
}

// aggregate (Graylog scripting API, POST → needs X-Requested-By, which the manifest's backend.headers adds)
export async function aggregate(ctx, q, range, groupBy, metrics = [{ function: 'count' }], stream = '') {
  const timerange = typeof range === 'object' ? { type: 'absolute', from: range.from, to: range.to } : { type: 'relative', range };
  const body = { query: q || '*', timerange, group_by: groupBy, metrics };
  if (stream) body.streams = [stream];
  const r = await ctx.api.post('/api/search/aggregate', body);
  return r.datarows || [];
}

// count per time bucket, oldest first (Graylog returns the empty buckets inside the range too)
export async function series(ctx, q, range, unit, stream = '') {
  const rows = await aggregate(ctx, q, range, [{ field: 'timestamp', timeunit: unit }], undefined, stream);
  return rows.map((r) => Number(r[1]) || 0);
}

// histogram bucket for a time range (seconds, or {from, to}): ~30..60 points
export const seconds = (r) => (typeof r === 'object' ? (Date.parse(r.to) - Date.parse(r.from)) / 1000 : r);
export function bucket(r) {
  const range = seconds(r);
  if (range <= 300) return '10s';
  if (range <= 900) return '30s';
  if (range <= 3600) return '1m';
  if (range <= 6 * 3600) return '10m';
  if (range <= 86400) return '30m';
  return '4h';
}

export const RANGES = [[300, '5m'], [900, '15m'], [3600, '1h'], [6 * 3600, '6h'], [86400, '24h'], [7 * 86400, '7d']];
export const short = (n) => (n == null ? '–' : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}k` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : `${n}`);

// security quick searches. Failed-login NUMBERS live in drift (security-metrics): we only offer the search + a link.
export const SECURITY = [
  { id: 'failed', label: 'failed logins', q: '("Failed password" OR "Invalid user" OR "authentication failure") AND NOT polkit AND NOT "invalid PVE ticket" AND NOT "no authentication credentials"', drift: true },
  { id: 'ssh', label: 'ssh logins', q: 'application_name:sshd* AND ("Accepted publickey" OR "Accepted password")', who: /Accepted \w+ for (\S+) from (\S+)/ },
  { id: 'sudo', label: 'sudo', q: 'application_name:sudo AND COMMAND', who: /^\s*(\S+) : .*?USER=(\S+)/ },
  { id: 'su', label: 'su / sessions', q: 'application_name:(su OR systemd-logind) AND ("session opened" OR "New session")' },
];
