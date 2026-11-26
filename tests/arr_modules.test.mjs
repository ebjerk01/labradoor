// The shared *arr UI ($lab/arr/, docs/sdk.md) without a browser: sonarr and radarr are thin modules over it, the hub and
// prowlarr use its helpers, and the manual-import / release / library / queue / health shaping does what the UI relies on.
// Usage: node tests/arr_modules.test.mjs  (exit 1 on failure)
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, writeFileSync, rmSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const read = (p) => readFileSync(join(root, p), 'utf8');

// 1. no copies any more: sonarr/radarr are `createArr('<app>')` over $lab/arr/arr.js; nothing *arr-shared lives in a module
for (const app of ['sonarr', 'radarr']) {
  assert.deepEqual(readdirSync(join(root, `modules/${app}/ui`)), ['index.js'], `${app}: only index.js (the rest is $lab/arr/)`);
  assert.match(read(`modules/${app}/ui/index.js`), new RegExp(`import \\{ createArr \\} from '\\$lab/arr/arr\\.js';[\\s\\S]*export default createArr\\('${app}'\\);`));
}
for (const f of ['Problems.svelte', 'Upcoming.svelte']) assert.ok(!readdirSync(join(root, 'modules/arr/ui')).includes(f), `arr: ${f} comes from $lab/arr/`);
for (const f of readdirSync(join(root, 'ui/src/lib/arr'))) {
  for (const [, spec] of read(`ui/src/lib/arr/${f}`).matchAll(/^\s*import\b[^'"]*['"]([^'"]+)['"]/gm)) {
    assert.ok(/^\.\.?\/[A-Za-z]/.test(spec) && !/lab\.svelte\.js|modules\.js/.test(spec), `$lab/arr/${f} imports ${spec}: the SDK's own files only, never shell state`);
  }
}

// 2. logic.js with ../sdk.js pointed at the SDK's plain-JS half
const dir = mkdtempSync(join(tmpdir(), 'arr-logic-'));
try {
  const sdk = pathToFileURL(join(root, 'ui/src/lib/sdk-core.js')).href;
  writeFileSync(join(dir, 'logic.mjs'), read('ui/src/lib/arr/logic.js').replace("'../sdk.js'", `'${sdk}'`));
  const L = await import(pathToFileURL(join(dir, 'logic.mjs')).href);

  // health: status, panel line, alerts (only warnings/errors)
  const hs = [{ source: 'A', type: 'error', message: 'x' }, { source: 'B', type: 'warning', message: 'y' }, { source: 'C', type: 'notice', message: 'z' }];
  assert.deepEqual(hs.map(L.healthStatus), ['bad', 'warn', 'ok']);
  assert.deepEqual(L.healthLine(hs[1], 'sonarr'), { p: '▲', s: 'warn', t: 'sonarr · y' });
  assert.deepEqual(L.healthLine(hs[2]), { p: '●', s: 'ok', t: 'z' });
  assert.deepEqual(L.healthAlerts('prowlarr', 'Prowlarr', hs).map((a) => [a.key, a.status, a.title, a.object]),
    [['prowlarr:health:A', 'bad', 'Prowlarr: x', 'prowlarr'], ['prowlarr:health:B', 'warn', 'Prowlarr: y', 'prowlarr']]);
  assert.deepEqual(L.healthAlerts('x', 'X', null), []);

  // queue: one row per download, import states kept even without a level
  const rec = (o) => ({ id: 1, title: 'T', downloadId: 'D1', status: 'completed', trackedDownloadState: 'downloading', trackedDownloadStatus: 'ok', added: '2026-11-01T10:00:00Z', ...o });
  const g = L.groupQueue([
    rec({ id: 1, trackedDownloadState: 'importBlocked', trackedDownloadStatus: 'warning', statusMessages: [{ title: 'x', messages: ['No files found are eligible'] }] }),
    rec({ id: 2, trackedDownloadState: 'importBlocked', trackedDownloadStatus: 'warning' }),
    rec({ id: 3, downloadId: 'D2', trackedDownloadState: 'importPending' }),
    rec({ id: 4, downloadId: 'D3', status: 'failed', trackedDownloadState: 'failedPending' }),
    rec({ id: 5, downloadId: 'D4', trackedDownloadState: 'downloading' }),
  ]);
  assert.deepEqual(g.map((x) => [x.key, x.level, x.n, x.needsImport]), [['D3', 'bad', 1, false], ['D1', 'warn', 2, true], ['D2', null, 1, true]]);
  assert.equal(g.find((x) => x.key === 'D1').reason, 'No files found are eligible');
  assert.deepEqual(g.filter((x) => x.level).map((x) => x.key), ['D3', 'D1']);

  // manual import: only candidates the app can place, exactly the fields the command needs
  const ep = (id, s, e) => ({ id, seasonNumber: s, episodeNumber: e });
  const sc = [
    { path: '/dl/a/S01E01.mkv', series: { id: 7, title: 'Show' }, episodes: [ep(71, 1, 1)], quality: { quality: { id: 7 } }, languages: [{ id: 1 }], releaseGroup: 'G', downloadId: 'D1', indexerFlags: 0, releaseType: 'singleEpisode', rejections: [] },
    { path: '/dl/a/sample.mkv', series: null, episodes: [], quality: { quality: { id: 0 } }, rejections: [{ reason: 'Unknown Series' }] },
    { path: '/dl/a/S01E02.mkv', series: { id: 7, title: 'Show' }, episodes: [], quality: {} },
  ];
  assert.deepEqual(sc.map((c) => L.importable('sonarr', c)), [true, false, false]);
  assert.equal(L.targetOf('sonarr', sc[0]), 'Show S01E01');
  const p = L.importPayload('sonarr', sc);
  assert.equal(p.name, 'ManualImport');
  assert.equal(p.importMode, 'auto');
  assert.deepEqual(p.files, [{ path: '/dl/a/S01E01.mkv', seriesId: 7, episodeIds: [71], releaseType: 'singleEpisode', quality: { quality: { id: 7 } }, languages: [{ id: 1 }], releaseGroup: 'G', indexerFlags: 0, downloadId: 'D1' }]);
  const mc = [{ path: 'C:\\dl\\M.2026.mkv', movie: { id: 3, title: 'Movie', year: 2026 }, quality: { quality: { id: 9 } }, languages: [], releaseGroup: '', downloadId: 'D9' }, { path: '/x.mkv', movie: null }];
  assert.deepEqual(L.importPayload('radarr', mc).files, [{ path: 'C:\\dl\\M.2026.mkv', movieId: 3, quality: { quality: { id: 9 } }, languages: [], releaseGroup: '', indexerFlags: 0, downloadId: 'D9' }]);
  assert.equal(L.fileName('C:\\dl\\M.2026.mkv'), 'M.2026.mkv');
  assert.deepEqual(L.importPayload('radarr', []).files, []);

  // releases: allowed first, then by score and seeders; the grab body carries only what the route allows
  const rows = L.releaseRows([
    { guid: 'a', indexerId: 1, title: 'A', rejected: true, rejections: ['Not an upgrade'], customFormatScore: 50, seeders: 99, quality: { quality: { name: 'WEBDL-1080p' } }, ageHours: 48, size: 1 },
    { guid: 'b', indexerId: 2, title: 'B', rejected: false, customFormatScore: 0, seeders: 5, quality: { quality: { name: 'HDTV-720p' } }, age: 3, size: 2 },
    { guid: 'c', indexerId: 2, title: 'C', rejected: false, customFormatScore: 10, seeders: 1, quality: { quality: { name: 'x' } }, size: 3 },
  ]);
  assert.deepEqual(rows.map((r) => r.guid), ['c', 'b', 'a']);
  assert.equal(rows[2].why, 'Not an upgrade');
  assert.equal(rows[2].age, 2);
  assert.deepEqual(L.releaseQuery('sonarr', 'episode', { id: 4 }), { episodeId: 4 });
  assert.deepEqual(L.releaseQuery('sonarr', 'season', { seriesId: 1, seasonNumber: 2 }), { seriesId: 1, seasonNumber: 2 });
  assert.deepEqual(L.releaseQuery('radarr', 'movie', { id: 5 }), { movieId: 5 });

  // library rows and episodes
  const s = L.slimSeries({ id: 1, title: 'S', year: 2020, monitored: true, path: '/tv/S', qualityProfileId: 4, statistics: { sizeOnDisk: 10, episodeFileCount: 3, episodeCount: 5 }, images: [1, 2, 3], overview: 'long' });
  assert.deepEqual(Object.keys(s).sort(), ['have', 'id', 'monitored', 'network', 'path', 'qualityProfileId', 'size', 'status', 'title', 'total', 'year']);
  assert.equal(L.libStatus('sonarr', s), 'warn');
  assert.equal(L.libStatus('sonarr', { ...s, have: 5 }), 'ok');
  assert.equal(L.libStatus('sonarr', { ...s, monitored: false }), 'off');
  const m = L.slimMovie({ id: 2, title: 'M', monitored: true, hasFile: true, sizeOnDisk: 9, movieFile: { quality: { quality: { name: 'Bluray-1080p' } } } });
  assert.equal(m.quality, 'Bluray-1080p');
  assert.equal(L.libStatus('radarr', m), 'ok');
  assert.deepEqual(L.slimLibrary('radarr', null), []);
  const seasons = L.bySeason([{ id: 1, seasonNumber: 1, episodeNumber: 2, hasFile: true }, { id: 2, seasonNumber: 1, episodeNumber: 1 }, { id: 3, seasonNumber: 2, episodeNumber: 1 }]);
  assert.deepEqual(seasons.map((x) => [x.n, x.have, x.eps.map((e) => e.n)]), [[2, 0, [1]], [1, 1, [1, 2]]]);
} finally { rmSync(dir, { recursive: true, force: true }); }

// 3. the hub reads other modules only through ctx.peer / ctx.via, and every one of them is declared
const mf = JSON.parse(read('modules/arr/manifest.json'));
assert.equal(mf.manifest, 2);
const declared = mf.requires.map((r) => r.id);
for (const f of readdirSync(join(root, 'modules/arr/ui')).filter((x) => /\.(js|svelte)$/.test(x))) {
  const src = read(`modules/arr/ui/${f}`);
  assert.ok(!/\$lab\/lab\.svelte\.js|\.\.\/\.\.\//.test(src), `${f} imports shell state or another module`);
  for (const [, id] of src.matchAll(/(?:peer|via|get)\((?:ctx, )?'([a-z]+)'\)/g)) assert.ok(declared.includes(id), `${f} uses ${id} without requires`);
}
console.log('arr modules ok');
