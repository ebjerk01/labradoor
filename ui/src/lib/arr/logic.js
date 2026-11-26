// Pure helpers for the *arr modules (no shell state): health, queue grouping, calendar, disks, manual-import and
// release shaping, library rows. Shared through the SDK as `$lab/arr/logic.js` (docs/sdk.md: modules never import each
// other's files); sonarr, radarr, prowlarr and the arr hub use it. Tests: tests/arr_modules.test.mjs.
import { ts, clip } from '../sdk.js';

export const A = '/api/v3';
export const PROBLEM_STATES = ['completed', 'warning', 'failed', 'downloadClientUnavailable'];
export const IMPORT_STATES = ['importBlocked', 'importPending', 'importFailed'];

export const APPS = {
  sonarr: { name: 'Sonarr', noun: 'episodes', label: 'tv', missingCmd: 'MissingEpisodeSearch', refreshCmd: 'RefreshSeries', item: 'series',
    lib: '/api/v3/series', view: 'sonarr-series', viewLabel: 'Series' },
  radarr: { name: 'Radarr', noun: 'movies', label: 'movies', missingCmd: 'MissingMoviesSearch', refreshCmd: 'RefreshMovie', item: 'movie',
    lib: '/api/v3/movie', view: 'radarr-movies', viewLabel: 'Movies' },
};

// --- health (GET /api/v{1,3}/health → [{source, type: ok|notice|warning|error, message}]) ------------------------------
export const healthStatus = (h) => (h.type === 'error' ? 'bad' : h.type === 'warning' ? 'warn' : 'ok');
export const healthLine = (h, prefix = '') => ({ p: h.type === 'error' ? '■' : h.type === 'warning' ? '▲' : '●', s: healthStatus(h),
  t: prefix ? `${prefix} · ${h.message}` : h.message });
// the warnings/errors as lab alerts on the service object `id` ("Sonarr: …")
export const healthAlerts = (id, name, health) => (health || []).filter((h) => h.type === 'error' || h.type === 'warning').map((h) => ({
  key: `${id}:health:${h.source}`, status: h.type === 'error' ? 'bad' : 'warn', title: `${name}: ${clip(h.message, 120)}`,
  detail: h.source, since: null, object: id }));

// level: bad = failed / import failed; warn = import blocked, client warnings; null = fine (normal import pending etc.)
export function levelOf(r) {
  if (r.status === 'failed' || r.trackedDownloadStatus === 'error' || ['importFailed', 'failedPending', 'failed'].includes(r.trackedDownloadState)) return 'bad';
  if (r.status === 'warning' || r.status === 'downloadClientUnavailable' || r.trackedDownloadStatus === 'warning'
    || r.trackedDownloadState === 'importBlocked') return 'warn';
  return null;
}

export function reasonOf(r) {
  if (r.errorMessage) return r.errorMessage;
  for (const m of r.statusMessages || []) {
    if (m.messages?.length) return m.messages[0];
  }
  return r.statusMessages?.[0]?.title || r.trackedDownloadState || r.status || '';
}

// One row per download (a season pack is one torrent but one record per episode). Rows without a level are kept only
// when the download waits for an import (`needsImport`); `problems` below is the ones with a level.
export function groupQueue(records) {
  const by = new Map();
  for (const r of records || []) {
    const lvl = levelOf(r);
    const imp = IMPORT_STATES.includes(r.trackedDownloadState);
    if (!lvl && !imp) continue;
    const k = r.downloadId || `q${r.id}`;
    const g = by.get(k);
    if (g) {
      g.n += 1;
      if (lvl === 'bad') g.level = 'bad';
      else if (lvl === 'warn' && !g.level) g.level = 'warn';
      continue;
    }
    by.set(k, { key: k, id: r.id, downloadId: r.downloadId, title: r.title, n: 1, level: lvl, state: r.trackedDownloadState || r.status,
      reason: clip(reasonOf(r), 160), added: ts(r.added), indexer: r.indexer, size: r.size, client: r.downloadClient, needsImport: imp && !!r.downloadId });
  }
  const rank = (g) => (g.level === 'bad' ? 0 : g.level === 'warn' ? 1 : 2);
  return [...by.values()].sort((a, b) => rank(a) - rank(b) || (b.added || 0) - (a.added || 0));
}

export function calendarItems(app, list, start, end) {
  if (app === 'sonarr') {
    return (list || []).map((e) => ({ at: ts(e.airDateUtc), title: e.series?.title || '?', sub: `S${String(e.seasonNumber).padStart(2, '0')}E${String(e.episodeNumber).padStart(2, '0')} ${e.title || ''}`.trim(),
      hasFile: e.hasFile, kind: 'tv' }));
  }
  const inWin = (d) => d && ts(d) >= start && ts(d) <= end;
  return (list || []).map((m) => {
    const which = inWin(m.digitalRelease) ? ['digital', m.digitalRelease] : inWin(m.physicalRelease) ? ['disc', m.physicalRelease] : ['cinema', m.inCinemas];
    return { at: ts(which[1]), title: m.title, sub: `${m.year || ''} · ${which[0]}`, hasFile: m.hasFile, kind: 'movie' };
  });
}

// The disks the app sees, without duplicates of the same filesystem and without snap mounts.
export function disks(list) {
  const seen = new Map();
  for (const d of list || []) {
    if (!d.totalSpace || d.path.includes('/snap/')) continue;
    const k = `${d.freeSpace}:${d.totalSpace}`;
    const cur = seen.get(k);
    if (!cur || d.path.length < cur.path.length) seen.set(k, { path: d.path, free: d.freeSpace, total: d.totalSpace });
  }
  return [...seen.values()].sort((a, b) => a.path.localeCompare(b.path));
}

// --- manual import -----------------------------------------------------------------------------------------------
// GET /manualimport?downloadId= → candidates. A candidate can be imported when the app knows what it is.
export const targetOf = (app, c) => (app === 'sonarr'
  ? (c.series ? `${c.series.title}${c.episodes?.length ? ` ${c.episodes.map((e) => `S${String(e.seasonNumber).padStart(2, '0')}E${String(e.episodeNumber).padStart(2, '0')}`).join(' ')}` : ''}` : '')
  : (c.movie ? `${c.movie.title}${c.movie.year ? ` (${c.movie.year})` : ''}` : ''));
export const importable = (app, c) => (app === 'sonarr' ? !!(c.series?.id && c.episodes?.length) : !!c.movie?.id);
export const fileName = (p) => String(p || '').split(/[\\/]/).pop();

// The ManualImport command for the chosen candidates: exactly what the app returned, plus what it needs to place them.
export function importPayload(app, cands) {
  const files = cands.filter((c) => importable(app, c)).map((c) => ({
    path: c.path,
    ...(app === 'sonarr' ? { seriesId: c.series.id, episodeIds: c.episodes.map((e) => e.id), ...(c.releaseType ? { releaseType: c.releaseType } : {}) } : { movieId: c.movie.id }),
    quality: c.quality, languages: c.languages, releaseGroup: c.releaseGroup, indexerFlags: c.indexerFlags ?? 0,
    ...(c.downloadId ? { downloadId: c.downloadId } : {}),
  }));
  return { name: 'ManualImport', files, importMode: 'auto' };
}

// --- interactive search ------------------------------------------------------------------------------------------
export function releaseRows(list) {
  return (list || []).map((r) => ({
    guid: r.guid, indexerId: r.indexerId, title: r.title, indexer: r.indexer, size: r.size, seeders: r.seeders ?? null, leechers: r.leechers ?? null,
    quality: r.quality?.quality?.name || '', age: r.ageHours != null ? r.ageHours / 24 : r.age ?? null, protocol: r.protocol, score: r.customFormatScore ?? 0,
    rejected: !!r.rejected, why: (r.rejections || []).join(' · '),
  })).sort((a, b) => a.rejected - b.rejected || (b.score - a.score) || ((b.seeders ?? -1) - (a.seeders ?? -1)));
}
export const releaseQuery = (app, kind, o) => (app === 'radarr' ? { movieId: o.id }
  : kind === 'episode' ? { episodeId: o.id } : { seriesId: o.seriesId, seasonNumber: o.seasonNumber });

// --- library -----------------------------------------------------------------------------------------------------
export const slimSeries = (s) => ({ id: s.id, title: s.title, year: s.year, monitored: !!s.monitored, status: s.status, path: s.path,
  qualityProfileId: s.qualityProfileId, size: s.statistics?.sizeOnDisk ?? 0, have: s.statistics?.episodeFileCount ?? 0,
  total: s.statistics?.episodeCount ?? 0, network: s.network || '' });
export const slimMovie = (m) => ({ id: m.id, title: m.title, year: m.year, monitored: !!m.monitored, status: m.status, path: m.path,
  qualityProfileId: m.qualityProfileId, size: m.sizeOnDisk ?? 0, hasFile: !!m.hasFile, quality: m.movieFile?.quality?.quality?.name || '',
  minimumAvailability: m.minimumAvailability });
export const slimLibrary = (app, list) => (Array.isArray(list) ? list : []).map(app === 'sonarr' ? slimSeries : slimMovie);
export const libStatus = (app, x) => (!x.monitored ? 'off' : app === 'sonarr' ? (x.total && x.have >= x.total ? 'ok' : 'warn') : x.hasFile ? 'ok' : 'warn');

// Episodes of one series grouped by season, newest season first.
export function bySeason(eps) {
  const m = new Map();
  for (const e of eps || []) {
    const s = m.get(e.seasonNumber) || { n: e.seasonNumber, eps: [], have: 0 };
    s.eps.push({ id: e.id, n: e.episodeNumber, title: e.title, monitored: !!e.monitored, hasFile: !!e.hasFile, air: e.airDateUtc || e.airDate || null, seriesId: e.seriesId });
    if (e.hasFile) s.have += 1;
    m.set(e.seasonNumber, s);
  }
  return [...m.values()].map((s) => ({ ...s, eps: s.eps.sort((a, b) => a.n - b.n) })).sort((a, b) => b.n - a.n);
}
