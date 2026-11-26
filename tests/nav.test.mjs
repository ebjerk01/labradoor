// Rail grouping, label disambiguation, short routes, role filtering and action dedupe (ui/src/lib/routes.js).
// Usage: node tests/nav.test.mjs  (exit 1 on failure)
import assert from 'node:assert/strict';
const { buildNav, filterNav, allowedViews, dedupeActions, homeId, CATEGORIES } = await import('../ui/src/lib/routes.js');

const mods = [
  { id: 'monitor', name: 'Monitor', category: 'monitoring', views: [
    { id: 'alerts', label: 'Alerts', min: 'admin' }, { id: 'checks', label: 'Checks', min: 'admin' }] },
  { id: 'fleet', name: 'fleet', category: 'infrastructure', views: [
    { id: 'fleet-alerts', label: 'Alerts', min: 'admin' }, { id: 'fleet-jobs', label: 'Jobs', min: 'admin' }, { id: 'fleet-keys', label: 'Keys', min: 'owner' }] },
  { id: 'deploy', name: 'Deploy', category: 'infrastructure', views: [
    { id: 'deploy-jobs', label: 'Jobs', min: 'admin' }, { id: 'deploy-ts', label: 'Task sequences', min: 'admin' }] },
  { id: 'edgecdn', name: 'Edge CDN', category: 'network', views: [{ id: 'edge', label: 'Zones', min: 'admin' }] },
  { id: 'requests', name: 'Requests', category: 'media', views: [{ id: 'req-discover', label: 'Discover' }, { id: 'req-settings', label: 'Settings', min: 'admin' }] },
  { id: 'files', name: 'Files', category: 'apps' },                // no views → generated module page
  { id: 'parcels', name: 'Parcels', category: 'apps', views: [] },
  { id: 'odd', name: 'Odd', category: 'nonsense' },                   // unknown category → "other", last
];
const owner = buildNav(mods, 'owner');

// grouped by category, in the fixed order, modules sorted by name, unknown category last
assert.deepEqual(owner.groups.map((g) => g.key), ['infrastructure', 'network', 'monitoring', 'media', 'apps', 'other']);
assert.deepEqual(owner.groups[0].modules.map((m) => m.id), ['deploy', 'fleet']);
assert.ok(CATEGORIES.indexOf('infrastructure') < CATEGORIES.indexOf('apps'));

// every module appears; one without views gets the generated page
const ids = owner.entries.map((e) => e.id);
for (const m of mods) assert.ok(owner.entries.some((e) => e.module === m.id), `${m.id} missing from the rail`);
assert.ok(ids.includes(homeId('files')) && ids.includes(homeId('parcels')));
assert.equal(owner.byId.get(homeId('files')).home, true);

// labels are unique across the whole app (core views included): two "Alerts", two "Jobs", "Settings" vs core Settings
const labels = [...owner.top, ...owner.entries, ...owner.bottom].map((e) => e.label.toLowerCase());
assert.equal(new Set(labels).size, labels.length, `duplicate labels: ${labels}`);
assert.equal(owner.byId.get('alerts').label, 'Alerts · Monitor');
assert.equal(owner.byId.get('fleet-jobs').label, 'Jobs · fleet');
assert.equal(owner.byId.get('req-settings').label, 'Settings · Requests');
assert.equal(owner.byId.get('checks').label, 'Checks');  // unique ones stay short

// a module with one view is listed under its own name, and its url is the module id; old ids still resolve
const edge = owner.byId.get('edge');
assert.equal(edge.label, 'Edge CDN');
assert.equal(edge.hint, 'zones');
assert.equal(owner.route('edge'), 'edgecdn');
assert.equal(owner.resolve('edgecdn'), 'edge');
assert.equal(owner.resolve('edge'), 'edge');
assert.equal(owner.route(homeId('files')), 'files');
assert.equal(owner.resolve('files'), homeId('files'));
assert.equal(owner.resolve('fleet'), 'fleet-alerts');     // a module id opens its first page
assert.equal(owner.resolve('overview'), 'overview');
assert.equal(owner.resolve('nope'), undefined);

// roles: admin loses owner-only views; guest gets only views without `min` + module pages + wall/settings
const admin = buildNav(mods, 'admin');
assert.ok(!admin.byId.has('fleet-keys') && owner.byId.has('fleet-keys'));
const guest = buildNav(mods, 'guest', ['wall', 'settings']);
assert.deepEqual(guest.top.map((e) => e.id), ['wall']);
assert.deepEqual(guest.bottom.map((e) => e.id), ['settings']);
assert.ok(!guest.byId.has('alerts') && !guest.byId.has('req-settings') && !guest.byId.has('overview'));
assert.ok(guest.byId.has('req-discover'));
// a module whose every view is admin-only still shows up for a guest who may use it: as its module page
assert.ok(guest.byId.has(homeId('monitor')));
assert.equal(guest.byId.get('req-discover').label, 'Requests');  // its only remaining view → module name
assert.deepEqual(allowedViews([{ id: 'a' }, { id: 'b', min: 'admin' }, { id: 'c', min: 'owner' }], 'admin').map((v) => v.id), ['a', 'b']);

// the $ grep box
const f = filterNav(owner.groups, 'jobs');
assert.deepEqual(f.flatMap((g) => g.modules.flatMap((m) => m.entries.map((e) => e.id))), ['deploy-jobs', 'fleet-jobs']);
assert.deepEqual(filterNav(owner.groups, 'fleet alerts').flatMap((g) => g.modules.flatMap((m) => m.entries.map((e) => e.id))), ['fleet-alerts']);
assert.equal(filterNav(owner.groups, 'media')[0].modules[0].entries.length, 2);  // category name keeps the module
assert.equal(filterNav(owner.groups, 'zones')[0].modules[0].id, 'edgecdn');       // hint (the view's own label)
assert.equal(filterNav(owner.groups, '').length, owner.groups.length);

// object panel: one button per verb; the module the object came from wins, then the most specific one
const acts = [
  { label: 'reboot', module: 'monitor', verdict: 'yes', method: 'POST' },
  { label: 'reboot', module: 'hyper', verdict: 'yes', method: 'POST' },
  { label: 'upgrade 3', module: 'fleet', verdict: 'yes', method: 'POST' },
  { label: 'upgrade 5', module: 'other', verdict: 'ask', method: 'POST' },
  { label: 'open site', module: 'monitor', url: 'https://a.example' },
  { label: 'open site', module: 'web', url: 'https://b.example' },
];
const size = (m) => ({ monitor: 400, hyper: 40, fleet: 50, other: 10 }[m]);
const d = dedupeActions(acts, { sources: ['monitor', 'hyper', 'fleet'] }, size);
assert.deepEqual(d.map((a) => `${a.label}@${a.module}`), ['reboot@hyper', 'upgrade 3@fleet', 'open site@monitor', 'open site@web']);
assert.deepEqual(d[0].also, ['monitor']);
assert.deepEqual(d[1].also, ['other']);
console.log('nav ok');
