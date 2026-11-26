// Seerr request → one status (shape + colour) + a short word. Download progress comes from Seerr's own *arr sync.
export function stateOf(r) {
  if (r.status === 'failed') return { s: 'bad', t: 'failed' };
  if (r.status === 'declined') return { s: 'off', t: 'declined' };
  if (r.status === 'pending') return { s: 'warn', t: 'waiting for approval' };
  if (r.media === 'available') return { s: 'ok', t: 'available' };
  const dl = progress(r);
  if (dl) return { s: 'ok', t: dl.pct != null ? `downloading ${dl.pct}%` : 'queued for download' };
  if (r.media === 'partial') return { s: 'ok', t: 'partly available' };
  if (r.media === 'deleted') return { s: 'off', t: 'deleted' };
  return { s: 'off', t: 'searching' };
}

// Average progress over the request's active downloads (a season = many episodes).
export function progress(r) {
  const ds = r.downloads || [];
  if (!ds.length) return null;
  const known = ds.filter((d) => d.progress != null);
  const pct = known.length ? Math.floor((100 * known.reduce((a, d) => a + d.progress, 0)) / known.length) : null;
  const etas = ds.map((d) => (d.eta ? Date.parse(d.eta) / 1000 : null)).filter(Boolean);
  return { pct, n: ds.length, eta: etas.length ? Math.max(...etas) : null };
}

// Media (library) status → status + word, for cards and seasons.
export const MEDIA = {
  available: { s: 'ok', t: 'available' }, partial: { s: 'ok', t: 'partly available' }, processing: { s: 'ok', t: 'processing' },
  pending: { s: 'warn', t: 'requested' }, blocklisted: { s: 'bad', t: 'blocklisted' }, deleted: { s: 'off', t: 'deleted' },
  unknown: { s: 'unknown', t: '' },
};
export const mediaState = (st) => MEDIA[st] || MEDIA.unknown;

export const name = (r) => `${r.title}${r.year ? ` (${r.year})` : ''}`;
export const seasons = (r) => (r.type === 'tv' && r.seasons?.length ? `S${r.seasons.map((s) => s.n ?? s).join(',')}` : '');

// Seerr permission bits, grouped for the editor. "identity" bits are owner-only (the connector enforces it too).
export const PERM_GROUPS = [
  { label: 'request', bits: [['REQUEST', 'all'], ['REQUEST_MOVIE', 'movies'], ['REQUEST_TV', 'series'], ['REQUEST_4K', '4K'],
    ['REQUEST_4K_MOVIE', '4K movies'], ['REQUEST_4K_TV', '4K series'], ['REQUEST_ADVANCED', 'advanced'], ['REQUEST_VIEW', 'see all requests']] },
  { label: 'auto-approve', bits: [['AUTO_APPROVE', 'all'], ['AUTO_APPROVE_MOVIE', 'movies'], ['AUTO_APPROVE_TV', 'series'],
    ['AUTO_APPROVE_4K', '4K'], ['AUTO_APPROVE_4K_MOVIE', '4K movies'], ['AUTO_APPROVE_4K_TV', '4K series']] },
  { label: 'auto-request (watchlist)', bits: [['AUTO_REQUEST', 'all'], ['AUTO_REQUEST_MOVIE', 'movies'], ['AUTO_REQUEST_TV', 'series']] },
  { label: 'issues', bits: [['VIEW_ISSUES', 'view'], ['CREATE_ISSUES', 'report'], ['MANAGE_ISSUES', 'manage']] },
  { label: 'manage', bits: [['MANAGE_REQUESTS', 'requests'], ['RECENT_VIEW', 'recently added'], ['WATCHLIST_VIEW', 'watchlists'],
    ['VIEW_BLOCKLIST', 'see blocklist'], ['MANAGE_BLOCKLIST', 'blocklist']] },
  { label: 'identity · owner', owner: true, bits: [['ADMIN', 'admin (everything)'], ['MANAGE_USERS', 'manage users'], ['MANAGE_SETTINGS', 'settings']] },
];

// Short summary of a permission mask: "admin" or "req · auto · 4K · issues".
export function permSummary(p, P) {
  if (!P) return '';
  if (p & P.ADMIN) return 'admin';
  const has = (k) => (p & P[k]) !== 0;
  const out = [];
  if (has('REQUEST')) out.push('request');
  else if (has('REQUEST_MOVIE') || has('REQUEST_TV')) out.push(`request ${has('REQUEST_MOVIE') ? 'mv' : ''}${has('REQUEST_TV') ? 'tv' : ''}`);
  if (has('AUTO_APPROVE')) out.push('auto');
  else if (has('AUTO_APPROVE_MOVIE') || has('AUTO_APPROVE_TV')) out.push(`auto ${has('AUTO_APPROVE_MOVIE') ? 'mv' : ''}${has('AUTO_APPROVE_TV') ? 'tv' : ''}`);
  if (has('REQUEST_4K') || has('REQUEST_4K_MOVIE') || has('REQUEST_4K_TV')) out.push('4K');
  if (has('MANAGE_REQUESTS')) out.push('manage');
  if (has('MANAGE_USERS')) out.push('users');
  if (has('MANAGE_SETTINGS')) out.push('settings');
  return out.join(' · ') || 'none';
}

export function quotaText(q) {
  if (!q) return '–';
  const one = (x, n) => (x?.limit ? `${n} ${x.used}/${x.limit}${x.days ? ` per ${x.days}d` : ''}` : `${n} ∞`);
  return `${one(q.movie, 'mv')} · ${one(q.tv, 'tv')}`;
}

// Ctrl-K: TMDB answers every word with films, so keep only titles that really match what was typed: every typed word must
// start a word of the title (or sit inside it for 4+ letters). Best first: exact title, title starts with the query, then
// popularity.
const fold = (t) => String(t || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
export function rankTitles(q, items) {
  const query = fold(q), words = query.split(' ').filter(Boolean);
  if (!words.length) return [];
  const score = (x) => {
    const title = fold(x.title);
    if (title === query) return 4;
    if (title.startsWith(query)) return 3;
    const tw = title.split(' ');
    return words.every((w) => tw.some((t) => t.startsWith(w)) || (w.length >= 4 && title.includes(w))) ? 2 : 0;
  };
  return items.map((x) => ({ x, s: score(x) })).filter((r) => r.s > 0)
    .sort((a, b) => b.s - a.s || (b.x.pop || 0) - (a.x.pop || 0)).map((r) => r.x);
}
