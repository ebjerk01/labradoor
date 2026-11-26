// Formatting + status helpers shared by the shell and modules.
export const GLYPH = { ok: '●', warn: '▲', bad: '■', off: '○', unknown: '·' };
export const RANK = { unknown: 0, off: 1, ok: 2, warn: 3, bad: 4 };
export const worst = (...s) => s.filter(Boolean).reduce((a, b) => (RANK[b] > RANK[a] ? b : a), 'unknown');
export const statusVar = (s) => ({ ok: 'var(--ok)', warn: 'var(--warn)', bad: 'var(--bad)', off: 'var(--faint)' }[s] || 'var(--faint)');

export function bytes(n, digits = 1) {
  if (n == null || isNaN(n)) return '–';
  const u = ['B', 'K', 'M', 'G', 'T', 'P'];
  let i = 0;
  while (Math.abs(n) >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i && n < 100 ? digits : 0)}${u[i]}`;
}
export const rate = (n) => (n == null ? '–' : `${bytes(n)}/s`);
export const bits = (bytesPerSec) => {
  if (bytesPerSec == null) return '–';
  const b = bytesPerSec * 8;
  return b >= 1e9 ? `${(b / 1e9).toFixed(1)}G` : b >= 1e6 ? `${(b / 1e6).toFixed(b >= 1e8 ? 0 : 1)}M` : `${(b / 1e3).toFixed(0)}k`;
};
export const pct = (v, d = 0) => (v == null || isNaN(v) ? '–' : `${Number(v).toFixed(d)}%`);
export const num = (v, d = 0) => (v == null || isNaN(v) ? '–' : Number(v).toFixed(d));

export function ago(ts, now = Date.now() / 1000) {
  if (!ts) return '–';
  const s = Math.max(0, now - ts);
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}
export const dur = (s) => ago(Date.now() / 1000 - s);
export const clock = (ts) => (ts ? new Date(ts * 1000).toLocaleTimeString('nb-NO', { hour: '2-digit', minute: '2-digit' }) : '–');

// SVG polyline points for a 80×18 sparkline from values (any range; scaled to min..max or to 0..100 for %).
export function sparkPoints(values, { fixed100 = false, w = 80, h = 18 } = {}) {
  const v = (values || []).filter((x) => x != null && !isNaN(x));
  if (v.length < 2) return '';
  const lo = fixed100 ? 0 : Math.min(...v), hi = fixed100 ? 100 : Math.max(...v);
  const span = hi - lo || 1;
  return v.map((x, i) => `${((i * w) / (v.length - 1)).toFixed(1)},${(h - 1 - ((x - lo) / span) * (h - 2)).toFixed(1)}`).join(' ');
}
export const memLevel = (v) => (v >= 90 ? 'bad' : v >= 80 ? 'warn' : 'ok');

// Links built from backend data (torrent/firmware source URLs, carrier links, profiles ...) are hostile input:
// only http(s) may become an href / window.open target (a `javascript:` URL would run on lab's origin).
export function safeUrl(u) {
  if (u == null || u === '') return undefined;
  try {
    const x = new URL(String(u), location.origin);
    return x.protocol === 'https:' || x.protocol === 'http:' ? x.href : undefined;
  } catch { return undefined; }
}
