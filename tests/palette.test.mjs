// Ctrl-K item actions (ui/src/lib/palette.js): run() wins, then object, then only http(s) urls.
// Usage: node tests/palette.test.mjs  (exit 1 on failure)
import assert from 'node:assert/strict';
globalThis.location = { origin: 'https://lab.example.com' };
const { itemAction } = await import('../ui/src/lib/palette.js');

const log = [];
const lab = { open: (id) => log.push(['open', id]) };
const open = (u) => log.push(['url', u]);

itemAction({ run: () => log.push(['run']), object: 'x', url: 'https://a' }, lab, open)();
itemAction({ object: 'workstation', url: 'https://a' }, lab, open)();
itemAction({ url: 'https://example.org/x' }, lab, open)();
itemAction({ url: 'javascript:alert(1)' }, lab, open)();
itemAction({ label: 'nothing' }, lab, open)();
assert.deepEqual(log, [['run'], ['open', 'workstation'], ['url', 'https://example.org/x']]);
console.log('palette ok');

// --- ranking: tasks, dedupe, caps (rankPalette) ---------------------------------------------------------------------
const { rankPalette, parseTask, dedupeObjects, CAP } = await import('../ui/src/lib/palette.js');
const cats = { hyper: 'infrastructure', monitor: 'monitoring', wifi: 'network', files: 'apps', movies: 'media', dnsmod: 'network' };
const catOf = (m) => cats[m] || '';
const objects = [
  { id: 'web1', name: 'web1', type: 'machine', kind: 'ct', status: 'ok', sources: ['monitor', 'hyper'] },
  { id: 'client:aa', name: 'web1 (CT 101)', type: 'client', kind: 'wired', status: 'ok', sources: ['wifi'] },
  { id: 'check:web1', name: 'web1', type: 'service', kind: 'http', status: 'ok', sources: ['monitor'] },
  { id: 'db1', name: 'db1', type: 'machine', kind: 'vm', status: 'bad', sources: ['hyper'] },
  { id: 'restart-show', name: 'Restart (2009)', type: 'item', sources: ['movies'] },
];
const actions = {
  web1: [{ label: 'reboot', module: 'hyper', verdict: 'yes', method: 'POST' }, { label: 'console', module: 'hyper', verdict: 'ask', url: 'https://x' }],
  db1: [{ label: 'start', module: 'hyper', verdict: 'yes', method: 'POST' }, { label: 'backup now', module: 'hyper', verdict: 'ask', method: 'POST' }],
};
const views = [
  { id: 'overview', label: 'Overview' },
  { id: 'edge', label: 'Edge CDN', hint: 'zones', module: 'dnsmod', moduleName: 'Edge CDN', category: 'network' },
  { id: 'resolver', label: 'Resolver DNS', module: 'dnsmod2', moduleName: 'Resolver DNS', category: 'network' },
  { id: 'mod-files', label: 'Files', module: 'files', category: 'apps' },
];
const commands = [{ label: 'approvals', keys: 'approve approval deny request ask owner', run: () => {} }];
const lookups = [...Array.from({ length: 10 }, (_, n) => ({ label: `web1-backup-${n}.bin`, sub: 'file', module: 'files' })),
  // a film search answers every word: it must never beat a task, a page or a command
  { label: 'New Record (2018)', sub: 'movie', module: 'movies' }, { label: 'Approved (2006)', sub: 'movie', module: 'movies' },
  { label: 'Restart (2009)', sub: 'movie', module: 'movies' }];
const search = [{ label: 'web1', sub: 'site', object: 'web1', module: 'monitor' }, { label: 'restart', sub: 'film', module: 'movies' }];
const rank = (q) => rankPalette({ q, views, objects, search, lookups, commands, catOf, actionsFor: (o) => actions[o.id] || [] });

assert.equal(parseTask('restart web1').verb, 'restart');
assert.equal(parseTask('new record').match, null);
assert.equal(parseTask('web1'), null);

// "restart web1" → the reboot action on web1 first, with its verdict
let r = rank('restart web1');
assert.equal(r[0].kind, 'task');
assert.equal(r[0].label, 'reboot · web1');
assert.equal(r[0].verdict, 'yes');
assert.equal(r[0].pick.action.label, 'reboot');
// "restart" alone: tasks first — not the film called Restart
r = rank('restart');
assert.equal(r[0].kind, 'task');
assert.ok(r.findIndex((x) => x.label === 'restart') > r.findIndex((x) => x.kind === 'task'));
// "console web1" shows the verdict: ask owner
r = rank('console web1');
assert.equal(r[0].label, 'console · web1');
assert.equal(r[0].verdict, 'ask');
// "snapshot db1" → its backup action (snapshot ≈ backup)
assert.equal(rank('snapshot db1')[0].label, 'backup now · db1');
// a verb the object has no action for → its panel, not nothing
r = rank('snooze db1');
assert.equal(r[0].kind, 'obj');
assert.equal(r[0].pick.object, 'db1');
// "new record" / "dns record" → the DNS pages
r = rank('new record');
assert.ok(r.slice(0, 2).every((x) => x.kind === 'view'), JSON.stringify(r.slice(0, 2)));
assert.deepEqual(new Set(r.slice(0, 2).map((x) => x.pick.view)), new Set(['edge', 'resolver']));
assert.ok(rank('dns record').some((x) => x.pick.view === 'resolver'));
// "approve" → the approvals command
assert.equal(rank('approve')[0].label, 'approvals');
assert.equal(rank('approval')[0].label, 'approvals');
r = rank('new record');
assert.ok(r.findIndex((x) => x.label === 'New Record (2018)') > 1);
assert.equal(rank('restart')[0].kind, 'task');

// one row per machine: the CT, its wifi client "web1 (CT 101)" and the check "web1" collapse; module rows naming
// the object become badges
r = rank('web1');
const webRows = r.filter((x) => x.kind === 'obj' && /^web1/i.test(x.label));
assert.equal(webRows.length, 1, JSON.stringify(webRows));
assert.equal(webRows[0].pick.object, 'web1');
assert.deepEqual(webRows[0].badges.map((b) => b.label).sort(), ['hyper', 'monitor', 'wifi']);
// noisy lookups are capped per module and rank below the machine
const files = r.filter((x) => x.kind === 'mod' && x.sub.endsWith('files'));
assert.equal(files.length, CAP);
assert.ok(r.indexOf(webRows[0]) < r.indexOf(files[0]));
// dedupe picks the machine over the client and the check
const d = dedupeObjects(objects, catOf);
assert.equal(d.find((o) => o.id === 'web1').alts.length, 2);
// empty query: views (and machines with problems first)
r = rank('');
assert.equal(r[0].pick.object, 'db1');
assert.ok(r.some((x) => x.kind === 'view'));
console.log('palette ranking ok');
