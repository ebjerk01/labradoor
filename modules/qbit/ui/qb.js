// qBittorrent state → group + status (shape + colour).
export const GROUPS = {
  downloading: ['downloading', 'forcedDL', 'metaDL', 'forcedMetaDL'],
  stalled: ['stalledDL'],
  queued: ['queuedDL', 'queuedUP'],
  seeding: ['uploading', 'stalledUP', 'forcedUP'],
  stopped: ['stoppedDL', 'stoppedUP', 'pausedDL', 'pausedUP'],
  checking: ['checkingDL', 'checkingUP', 'checkingResumeData', 'moving', 'allocating'],
  error: ['error', 'missingFiles', 'unknown'],
};
const BY = Object.fromEntries(Object.entries(GROUPS).flatMap(([g, ss]) => ss.map((s) => [s, g])));
export const groupOf = (t) => BY[t.state] || 'error';
export const STATUS = { downloading: 'ok', seeding: 'ok', checking: 'ok', stalled: 'warn', queued: 'off', stopped: 'off', error: 'bad' };
export const statusOf = (t) => STATUS[groupOf(t)];
export const isStopped = (t) => groupOf(t) === 'stopped';

export function summary(d) {
  const counts = Object.fromEntries(Object.keys(GROUPS).map((g) => [g, 0]));
  const cats = {};
  for (const t of d.torrents) {
    counts[groupOf(t)] += 1;
    const c = t.category || '—';
    cats[c] = cats[c] || { n: 0, size: 0, left: 0 };
    cats[c].n += 1;
    cats[c].size += Math.max(0, t.size || 0);
    cats[c].left += Math.max(0, t.amount_left || 0);
  }
  return { counts, cats };
}

export const eta = (s) => (s == null || s >= 8640000 ? '∞' : s < 3600 ? `${Math.round(s / 60)}m` : s < 86400 ? `${(s / 3600).toFixed(1)}h` : `${Math.round(s / 86400)}d`);
