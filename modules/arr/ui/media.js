// What the hub reads from the other media modules (each may be missing: module off, backend down, no access).
// Data comes through ctx.peer (read-only, null when absent); actions go through ctx.via(id), so every click is checked
// against THAT module's manifest.
import { healthLine } from '$lab/arr/logic.js';

export const MEDIA = ['sonarr', 'radarr', 'prowlarr', 'bazarr', 'qbit', 'jellyfin', 'seerr'];
export const get = (ctx, id) => ctx.peer(id);

export function upcoming(ctx) {
  return ['sonarr', 'radarr'].flatMap((id) => (get(ctx, id)?.upcoming || []).map((u) => ({ ...u, app: id }))).sort((a, b) => a.at - b.at);
}

export function healthLines(ctx) {
  const out = [];
  for (const id of ['sonarr', 'radarr', 'prowlarr']) {
    for (const h of get(ctx, id)?.health || []) out.push(healthLine(h, id));
  }
  for (const h of get(ctx, 'bazarr')?.health || []) out.push({ p: '▲', s: 'warn', t: `bazarr · ${h.object || ''} ${h.issue || ''}` });
  return out;
}

// qBittorrent state → group (the same grouping qbit's own view uses)
const GROUPS = {
  downloading: ['downloading', 'forcedDL', 'metaDL', 'forcedMetaDL'], stalled: ['stalledDL'],
  queued: ['queuedDL', 'queuedUP'], seeding: ['uploading', 'stalledUP', 'forcedUP'],
  stopped: ['stoppedDL', 'stoppedUP', 'pausedDL', 'pausedUP'], checking: ['checkingDL', 'checkingUP', 'checkingResumeData', 'moving', 'allocating'],
  error: ['error', 'missingFiles', 'unknown'],
};
const BY = Object.fromEntries(Object.entries(GROUPS).flatMap(([g, ss]) => ss.map((s) => [s, g])));
export const groupOf = (t) => BY[t.state] || 'error';
export const torrentStatus = (t) => ({ downloading: 'ok', seeding: 'ok', checking: 'ok', stalled: 'warn', queued: 'off', stopped: 'off', error: 'bad' })[groupOf(t)];

// a Seerr request → status + word
export function requestState(r) {
  if (r.status === 'failed') return { s: 'bad', t: 'failed' };
  if (r.status === 'declined') return { s: 'off', t: 'declined' };
  if (r.status === 'pending') return { s: 'warn', t: 'waiting for approval' };
  if (r.media === 'available') return { s: 'ok', t: 'available' };
  const ds = (r.downloads || []).filter((d) => d.progress != null);
  if (r.downloads?.length) return { s: 'ok', t: ds.length ? `downloading ${Math.floor(ds.reduce((a, d) => a + d.progress, 0) / ds.length)}%` : 'queued for download' };
  if (r.media === 'partial') return { s: 'ok', t: 'partly available' };
  if (r.media === 'deleted') return { s: 'off', t: 'deleted' };
  return { s: 'off', t: 'searching' };
}
export const requestName = (r) => `${r.title}${r.year ? ` (${r.year})` : ''}`;
export const playLabel = (p) => (p.type === 'Episode' ? `${p.series} S${String(p.s ?? 0).padStart(2, '0')}E${String(p.e ?? 0).padStart(2, '0')} ${p.name}` : `${p.name}${p.year ? ` (${p.year})` : ''}`);
export const stuckGroups = (ctx) => ['sonarr', 'radarr'].flatMap((id) => (get(ctx, id)?.queue.problems || []).map((g) => ({ ...g, app: id })));
