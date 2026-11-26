// Module SDK (ui/src/lib/sdk*.js, docs/sdk.md) against a mock ctx; no browser. The reactive half (sdk.svelte.js) and
// the shared components + module template are compiled with the Svelte compiler (they are not in the bundle until a
// module uses them), and lazy()/poll() run for real in an effect root.
// Usage: node tests/sdk.test.mjs  (exit 1 on failure)
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { compile, compileModule } from 'svelte/compiler';

const root = fileURLToPath(new URL('..', import.meta.url));
const sdk = await import('../ui/src/lib/sdk-core.js');
const fmt = await import('../ui/src/lib/fmt.js');
const { act, errText, cached, forget, qs, withQuery, getOrDenied, soft, ts, rel, duration, worstOf, siteStatus, level,
  clip, sortRows, readonly, peerGuard, loader, watchTask, startPoll, changeTracker } = sdk;
const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));
const err = (status, body) => Object.assign(new Error(body?.error || `HTTP ${status}`), { status, body: body || {} });

// a ctx like the shell's: routes → verdict, records every call, toast and refresh
function mockCtx(verdicts = {}, answers = {}) {
  const log = [];
  const call = (m) => async (path, a) => {
    log.push([m, path, a]);
    const ans = answers[`${m} ${path.split('?')[0]}`];
    if (ans instanceof Error) throw ans;
    return typeof ans === 'function' ? ans(path, a) : ans;
  };
  return {
    id: 'mod', log, toasts: [], refreshes: 0, asks: [], changes: 0,
    changed() { this.changes++; },
    can(method, path) { return verdicts[`${method} ${String(path).split('?')[0]}`] || 'no'; },
    api: { get: call('GET'), post: call('POST'), put: call('PUT'), patch: call('PATCH'), del: call('DELETE') },
    notify(msg, kind = 'ok') { this.toasts.push([kind, msg]); },
    refresh() { this.refreshes++; },
    async ask(method, path, body, label, reason) { this.asks.push({ method, path, body, label, reason }); return { id: 1, label }; },
  };
}

// --- act ------------------------------------------------------------------------------------------------------------
{
  const ctx = mockCtx({ 'POST /restart': 'yes' }, { 'POST /restart': { done: 1 } });
  assert.deepEqual(await act(ctx, { path: '/restart', label: 'restart', body: { a: 1 } }), { done: 1 });
  assert.deepEqual(ctx.log, [['POST', '/restart', { a: 1 }]]);
  assert.deepEqual(ctx.toasts, [['ok', 'restart ✓']]);
  assert.equal(ctx.refreshes, 1);
}
{ // every method, query merged into the path, the verdict checked on the bare path, empty answers become {}
  const ctx = mockCtx({ 'GET /a': 'yes', 'PUT /a': 'yes', 'PATCH /a': 'yes', 'DELETE /a': 'yes' });
  await act(ctx, { method: 'GET', path: '/a?x=1', query: { y: 2, z: null }, label: 'get', quiet: true });
  await act(ctx, { method: 'PUT', path: '/a', body: { k: 1 }, label: 'put' });
  await act(ctx, { method: 'PATCH', path: '/a', label: 'patch' });
  assert.deepEqual(await act(ctx, { method: 'DELETE', path: '/a', query: 'purge=1', label: 'delete' }), {});
  assert.deepEqual(ctx.log, [['GET', '/a?x=1&y=2', undefined], ['PUT', '/a', { k: 1 }], ['PATCH', '/a', {}], ['DELETE', '/a?purge=1', undefined]]);
  assert.equal(ctx.toasts.length, 3); // quiet: no toast
}
{ // not allowed: nothing sent
  const ctx = mockCtx({});
  assert.equal(await act(ctx, { path: '/x', label: 'x' }), null);
  assert.deepEqual([ctx.log, ctx.toasts], [[], [['bad', 'x: not allowed']]]);
}
{ // ask: an approval with the query kept; the route is not called
  const ctx = mockCtx({ 'POST /zones/add': 'ask' });
  assert.equal(await act(ctx, { path: '/zones/add?zone=a', query: { ttl: 60 }, body: { b: 1 }, label: 'add', reason: 'why' }), null);
  assert.deepEqual(ctx.asks, [{ method: 'POST', path: '/zones/add?zone=a&ttl=60', body: { b: 1 }, label: 'add', reason: 'why' }]);
  assert.deepEqual(ctx.log, []);
}
{ // the gateway turns it into an approval (403 {approval}) → asked
  const ctx = mockCtx({ 'POST /x': 'yes' }, { 'POST /x': err(403, { error: 'owner only', approval: true }) });
  assert.equal(await act(ctx, { path: '/x', label: 'x' }), null);
  assert.equal(ctx.asks.length, 1);
}
{ // failure → toast with the backend's text, no refresh
  const ctx = mockCtx({ 'POST /x': 'yes' }, { 'POST /x': err(400, { message: 'bad input', errors: { name: 'required ' } }) });
  assert.equal(await act(ctx, { path: '/x', label: 'save' }), null);
  assert.deepEqual(ctx.toasts, [['bad', 'save: bad input · name: required']]);
  assert.equal(ctx.refreshes, 0);
}
{ // check(): an error inside a 2xx answer fails the action before any ✓; its return value replaces the answer
  const unwrap = (r) => { if (r.status !== 'ok') throw new Error(`server: ${r.errorMessage}`); return r.response; };
  const bad = mockCtx({ 'POST /rec': 'yes' }, { 'POST /rec': { status: 'error', errorMessage: 'zone not found' } });
  assert.equal(await act(bad, { path: '/rec', label: 'add record', check: unwrap }), null);
  assert.deepEqual(bad.toasts, [['bad', 'add record: server: zone not found']]);
  assert.equal(bad.refreshes, 0);
  const good = mockCtx({ 'POST /rec': 'yes' }, { 'POST /rec': { status: 'ok', response: { id: 7 } } });
  let seen;
  assert.deepEqual(await act(good, { path: '/rec', label: 'add record', check: unwrap, done: (r) => { seen = r; } }), { id: 7 });
  assert.deepEqual(seen, { id: 7 });
  assert.deepEqual(good.toasts, [['ok', 'add record ✓']]);
}
{ // confirm: cancelled → nothing; ok text/function; done() returning true takes over the follow-up
  const ctx = mockCtx({ 'POST /x': 'yes' }, { 'POST /x': { message: 'queued' } });
  globalThis.confirm = () => false;
  assert.equal(await act(ctx, { path: '/x', label: 'wipe', confirm: 'really?' }), null);
  globalThis.confirm = (q) => { ctx.asked = q; return true; };
  await act(ctx, { path: '/x', label: 'wipe', confirm: true, ok: (r) => `wipe: ${r.message}` });
  assert.equal(ctx.asked, 'wipe?');
  let seen = null;
  await act(ctx, { path: '/x', label: 'job', done: (r, c) => { seen = [r, c.id]; return true; } });
  await act(ctx, { path: '/x', label: 'job2', done: () => undefined });
  assert.deepEqual(seen, [{ message: 'queued' }, 'mod']);
  assert.deepEqual(ctx.toasts, [['ok', 'wipe: queued'], ['ok', 'job2 ✓']]);
  delete globalThis.confirm;
}

// --- errText ----------------------------------------------------------------------------------------------------------
assert.equal(errText(err(500, { error: 'boom' })), 'boom');
assert.equal(errText(err(400, { error: { message: 'nested' } })), 'nested');
assert.equal(errText(err(400, { detail: 'drf detail' })), 'drf detail');
assert.equal(errText(err(400, { errors: [{ message: 'first' }, { message: 'second' }] })), 'first');
assert.equal(errText(err(400, { errorMessage: 'tech' })), 'tech');
assert.equal(errText(err(400, { username: ['taken'] })), '{"username":["taken"]}');
assert.equal(errText(err(502, {})), 'HTTP 502');
assert.equal(errText(new Error('plain')), 'plain');
assert.equal(errText(null), 'failed');
assert.equal(errText('x'.repeat(300)).length, 220);

// --- query strings ----------------------------------------------------------------------------------------------------
assert.equal(qs({ a: 1, b: null, c: [1, 2], d: undefined, e: 'x y' }), 'a=1&c=1&c=2&e=x+y');
assert.equal(qs('?a=1'), 'a=1');
assert.equal(withQuery('/p', {}), '/p');
assert.equal(withQuery('/p?a=1', { b: 2 }), '/p?a=1&b=2');

// --- getOrDenied / soft -------------------------------------------------------------------------------------------------
{
  const ok = mockCtx({}, { 'GET /o': { n: 1 } });
  assert.deepEqual(await getOrDenied(ok, '/o'), { data: { n: 1 } });
  assert.deepEqual(await getOrDenied(mockCtx({}, { 'GET /o': err(403, { error: 'no account' }) }), '/o'), { denied: 'no account' });
  await assert.rejects(getOrDenied(mockCtx({}, { 'GET /o': err(401, { error: 'bad signature' }) }), '/o'), /refused the lab signature/);
  await assert.rejects(getOrDenied(mockCtx({}, { 'GET /o': err(401, { error: 'not logged in' }) }), '/o'), (e) => e.status === 401);
  assert.equal(await soft(Promise.reject(new Error('x'))), null);
  assert.deepEqual(await soft(Promise.reject(new Error('x')), []), []);
}

// --- cached -------------------------------------------------------------------------------------------------------------
{
  let n = 0;
  const fn = async () => { n++; await tick(5); return n; };
  const [a, b] = await Promise.all([cached('t:a', 10000, fn), cached('t:a', 10000, fn)]);
  assert.deepEqual([a, b, n], [1, 1, 1]); // shared while running
  assert.equal(await cached('t:a', 10000, fn), 1); // fresh
  assert.equal(await cached('t:a', 0, fn), 2); // expired
  assert.equal(await cached('t:a', 0, () => Promise.reject(new Error('down'))), 2); // last good value kept
  await assert.rejects(cached('t:b', 1000, () => Promise.reject(new Error('down'))), /down/); // nothing to fall back on
  forget('t:*');
  assert.equal(await cached('t:a', 10000, async () => 'new'), 'new');
}

// --- time + status + text -------------------------------------------------------------------------------------------------
assert.equal(ts('2026-01-02T03:04:05Z'), 1767323045);
assert.equal(ts('2026-01-02 03:04:05'), 1767323045); // no zone = UTC
assert.equal(ts('2026-01-02 04:04:05+01:00'), 1767323045);
assert.equal(ts(1767323045000), 1767323045);
assert.equal(ts('1767323045'), 1767323045);
assert.equal(ts(new Date(1767323045000)), 1767323045);
assert.deepEqual([ts(null), ts(''), ts('nope')], [null, null, null]);
assert.equal(rel(1000 + 7200, 1000), 'in 2h');
assert.equal(rel(1000 - 120, 1000), '2m ago');
assert.equal(rel(null), '–');
assert.deepEqual([duration(3900), duration(420), duration(-1)], ['1h05', '7m', '–']);
assert.equal(worstOf(['ok', 'warn', 'off']), 'warn');
assert.equal(worstOf([]), 'ok');
assert.equal(siteStatus([]), 'ok');
assert.equal(siteStatus([{ title: 'x' }]), 'warn');
assert.equal(siteStatus([{ status: 'warn' }, { status: 'bad' }, 'ok']), 'bad');
assert.deepEqual([level(95, 80, 90), level(85, 80, 90), level(10, 80, 90), level(null, 80, 90)], ['bad', 'warn', 'ok', null]);
assert.deepEqual([level(0.5, 1.5, 0.75), level(1, 1.5, 0.75), level(5, 1.5, 0.75)], ['bad', 'warn', 'ok']);
assert.equal(clip('abcdef', 4), 'abc…');
assert.equal(clip(null), '');
assert.deepEqual(sortRows([{ n: 'node10' }, { n: null }, { n: 'node2' }, { n: 'Node1' }], 'n').map((r) => r.n), ['Node1', 'node2', 'node10', null]);
assert.deepEqual(sortRows([{ v: 3 }, { v: 10 }, { v: 1 }], (r) => r.v, -1).map((r) => r.v), [10, 3, 1]);
// fmt.js re-exports keep working
assert.equal(fmt.worst('ok', 'bad'), 'bad');

// --- isolation helpers ------------------------------------------------------------------------------------------------------
{
  const data = { list: [{ a: 1 }], m: new Map([[1, 2]]), d: new Date(0) };
  const ro = readonly(data, true, 'x');
  assert.equal(ro.list[0].a, 1);
  assert.equal(ro.list.map((x) => x.a)[0], 1);
  assert.equal(ro.m.get(1), 2); // non-plain values pass through
  assert.equal(readonly(data, true, 'x'), ro); // same view every time
  assert.throws(() => { ro.list[0].a = 2; }, /x is read-only/);
  assert.throws(() => { ro.list.push(1); }, /read-only/);
  assert.throws(() => { delete ro.list; }, /read-only/);
  const lax = readonly(data, false, 'y');
  const warn = console.warn; let warned = 0; console.warn = () => warned++;
  lax.list[0].a = 5; lax.list[0].b = 6;
  console.warn = warn;
  assert.deepEqual([data.list[0].a, data.list[0].b, warned >= 1], [1, undefined, true]);
  assert.equal(readonly(null), null);
  assert.equal(readonly(7), 7);
  const frozen = Object.freeze({ inner: { z: 1 } });
  assert.equal(readonly(frozen).inner.z, 1); // proxy invariants respected

  const may = peerGuard('hub', ['leaf', { id: 'opt', optional: true }], true);
  assert.equal(may('leaf'), true);
  assert.equal(may('opt'), true);
  assert.throws(() => may('other', 'via'), /module hub: ctx\.via\('other'\) needs "other" in its manifest's "requires"/);
  console.warn = () => {};
  assert.equal(peerGuard('hub', [], false)('other'), false); // production: no throw, just null upstream
  console.warn = warn;
  assert.equal(peerGuard('ai', ['*'], true)('anything'), true);
}

// --- the panel cache hook: a write marks its module changed (act → ctx.changed → the shell's changeTracker) ------------
{
  // act: only a write that went through counts (not refused, cancelled, asked for, failed, or a quiet read-by-POST)
  const ctx = mockCtx({ 'POST /ok': 'yes', 'POST /ask': 'ask', 'POST /bad': 'yes', 'POST /read': 'yes' },
    { 'POST /ok': {}, 'POST /bad': err(500, { error: 'down' }), 'POST /read': { rows: [] } });
  await act(ctx, { path: '/ok', label: 'ok' });
  assert.equal(ctx.changes, 1);
  await act(ctx, { path: '/ok', label: 'ok', done: () => true });   // done takes over the follow-up: still a change
  assert.equal(ctx.changes, 2);
  await act(ctx, { path: '/ask', label: 'a' });
  await act(ctx, { path: '/bad', label: 'b' });
  await act(ctx, { path: '/nope', label: 'n' });
  await act(ctx, { path: '/read', label: 'r', quiet: true });
  assert.equal(ctx.changes, 2);
  delete ctx.changed;                                              // a ctx without the hook (older shells) still works
  assert.deepEqual(await act(ctx, { path: '/ok', label: 'ok' }), {});

  // the "(queued …)" note is for a backend that says {queued: true}, not for an *arr command's `queued` timestamp
  const q = mockCtx({ 'POST /q': 'yes', 'POST /arr': 'yes' }, { 'POST /q': { queued: true }, 'POST /arr': { name: 'CheckHealth', queued: '2026-11-16T11:53:08Z' } });
  await act(q, { path: '/q', label: 'restart' });
  await act(q, { path: '/arr', label: 'check health' });
  assert.deepEqual(q.toasts, [['ok', 'restart ✓ (queued: runs at the next check-in)'], ['ok', 'check health ✓']]);

  // changeTracker: drops the module's cached() values (only its own), bumps rev; the gateway's echo of our own write
  // is skipped, another tab's write (remote, no local change) is not
  let t = 1000;
  const rev = {};
  const changed = changeTracker(rev, { now: () => t, window: 2000 });
  let calls = 0;
  const load = (k) => cached(k, 60000, async () => ++calls);
  await load('mod:list'); await load('mod2:list');
  assert.equal(changed('mod'), true);
  assert.deepEqual(rev, { mod: 1 });
  await load('mod:list'); await load('mod2:list');
  assert.equal(calls, 3, 'mod:list fetched again, mod2:list still cached');
  t += 300;
  assert.equal(changed('mod', true), false, 'the echo of our own write');
  assert.deepEqual(rev, { mod: 1 });
  t += 5000;
  assert.equal(changed('mod', true), true, 'a later write from elsewhere');
  assert.equal(changed('other', true), true);
  assert.deepEqual(rev, { mod: 2, other: 1 });
  assert.equal(changed(''), false);
  forget('mod2:*');
}

// --- loader (lazy's core), watchTask, startPoll -----------------------------------------------------------------------------
{
  const ctx = mockCtx({ 'GET /u': 'yes', 'GET /secret': 'ask' }, { 'GET /u': (p, q) => ({ items: [q?.page ?? 0] }) });
  const s = { data: null, error: null, loading: true, denied: null };
  let path = '/u', page = 1;
  const reload = loader(s, () => ctx, () => path, { query: () => ({ page }), pick: (r) => r.items });
  await reload();
  assert.deepEqual(s, { data: [1], error: null, loading: false, denied: null });
  path = '/secret'; await reload();
  assert.deepEqual(s, { data: null, error: 'owner only', loading: false, denied: 'ask' });
  assert.equal(ctx.log.filter((l) => l[1] === '/secret').length, 0); // not sent
  path = '/nope'; await reload();
  assert.equal(s.error, 'not allowed');
  path = null; await reload();
  assert.deepEqual(s, { data: null, error: null, loading: false, denied: null });
  // a slow answer overtaken by a newer one is dropped
  const ctx2 = mockCtx({ 'GET /v': 'yes' }, { 'GET /v': async (p, q) => { if (q.n === 1) await tick(20); return q.n; } });
  const s2 = { data: null };
  let n = 1;
  const r2 = loader(s2, ctx2, () => '/v', { query: () => ({ n }) });
  const first = r2(); n = 2; await r2(); await first;
  assert.equal(s2.data, 2);
  // an error clears the data (keep: true keeps it)
  const ctx3 = mockCtx({ 'GET /w': 'yes' }, { 'GET /w': err(500, { error: 'down' }) });
  const s3 = { data: 'old' };
  await loader(s3, ctx3, () => '/w', { keep: true })();
  assert.deepEqual([s3.data, s3.error], ['old', 'down']);
  await loader(s3, ctx3, () => '/w')();
  assert.equal(s3.data, null);
}
{
  const ctx = mockCtx();
  const store = { list: [] };
  let polls = 0;
  const res = watchTask(ctx, { label: 'backup', id: 'u1', first: 1, every: 1, refresh: [0, 5],
    check: async () => (++polls < 3 ? (polls === 1 ? Promise.reject(new Error('flaky')) : null) : { ok: false, text: 'exit 1' }) }, store);
  assert.deepEqual(store.list.map((t) => [t.id, t.module, t.label]), [['u1', 'mod', 'backup']]);
  assert.deepEqual(await res, { ok: false, text: 'exit 1' });
  await tick(20);
  assert.deepEqual([store.list, ctx.toasts, ctx.refreshes, polls], [[], [['bad', 'backup: exit 1']], 2, 3]);
  const gaveUp = await watchTask(ctx, { check: () => null, first: 1, every: 1, timeout: 5 }, store);
  assert.deepEqual([gaveUp, store.list], [{ ok: null, text: 'timeout' }, []]);
  const okRes = await watchTask(ctx, { label: 'job', check: () => ({ ok: true, text: 'done' }), first: 1, quiet: false }, store);
  assert.equal(okRes.ok, true);
  assert.deepEqual(ctx.toasts.at(-1), ['ok', 'job: ✓ done']);

  let runs = 0;
  const stop = startPoll(() => { runs++; }, 5);
  await tick(30); stop(); const at = runs; await tick(20);
  assert.ok(at >= 3 && runs === at, `poll ran ${at} then ${runs}`);
  globalThis.document = { hidden: true };
  let hiddenRuns = 0;
  const stop2 = startPoll(() => { hiddenRuns++; }, 2);
  await tick(15); stop2();
  delete globalThis.document;
  assert.equal(hiddenRuns, 0); // hidden tab: skipped
}

// --- the reactive half, compiled and run (lazy, poll) -----------------------------------------------------------------------
{
  const cacheDir = `${root}node_modules/.cache/lab-sdk-test`;
  mkdirSync(cacheDir, { recursive: true });
  const lib = pathToFileURL(`${root}ui/src/lib/`).href;
  const out = compileModule(readFileSync(`${root}ui/src/lib/sdk.svelte.js`, 'utf8'), { filename: 'sdk.svelte.js', generate: 'client' });
  const file = `${cacheDir}/sdk.svelte.${process.pid}.mjs`;
  writeFileSync(file, out.js.code.replace(/from '\.\/([^']+)'/g, (_, f) => `from '${lib}${f}'`));
  try {
    const { lazy, poll, watching } = await import(pathToFileURL(file).href);
    const $ = await import('svelte/internal/client');
    const ctx = mockCtx({ 'GET /a': 'yes', 'GET /b': 'yes' }, { 'GET /a': { v: 'a' }, 'GET /b': { v: 'b' } });
    const p = $.proxy({ path: '/a' });
    let l, runs = 0;
    const destroy = $.effect_root(() => {
      l = lazy(() => ctx, () => p.path, { pick: (r) => r.v });
      poll(() => { runs++; }, 5);
    });
    $.flush();
    await tick(10);
    assert.deepEqual([l.data, l.loading, l.error], ['a', false, null]);
    p.path = '/b';
    $.flush();
    await tick(10);
    assert.equal(l.data, 'b');
    assert.deepEqual(ctx.log.map((x) => x[1]), ['/a', '/b']);
    // a change in the module (ctx.rev) loads it again, and the shown data stays until the new answer is in
    const rc = mockCtx({ 'GET /p': 'yes' }, { 'GET /p': async () => { await tick(15); return { v: `n${rc.log.length}` }; } });
    const live = $.proxy({ rev: 0 });
    Object.defineProperty(rc, 'rev', { get: () => live.rev });
    let pl;
    const destroy2 = $.effect_root(() => { pl = lazy(() => rc, () => '/p', { pick: (r) => r.v }); });
    $.flush();
    await tick(30);
    assert.equal(pl.data, 'n1');
    live.rev++;
    $.flush();
    await tick(1);
    assert.deepEqual([pl.data, pl.loading], ['n1', true], 'old data kept while reloading');
    await tick(30);
    assert.deepEqual([pl.data, pl.loading, rc.log.length], ['n2', false, 2]);
    destroy2();
    // follow: false (an expensive search): a change does not run it again
    let fl;
    const destroy3 = $.effect_root(() => { fl = lazy(() => rc, () => '/p', { follow: false }); });
    $.flush();
    await tick(30);
    const before = rc.log.length;
    live.rev++;
    $.flush();
    await tick(30);
    assert.equal(rc.log.length, before, 'follow: false ignores ctx.rev');
    destroy3();
    destroy();
    const at = runs; await tick(20);
    assert.ok(at >= 1 && runs === at, 'poll stops when its component (effect root) goes away');
    assert.deepEqual(watching.list, []);
  } finally { rmSync(file, { force: true }); }
}

// --- every shared component and the module template compile (they are not bundled until a module imports them) -----------
{
  const svelteFiles = [
    ...['Table.svelte', 'ActionButton.svelte', 'Lazy.svelte'].map((f) => `ui/src/lib/${f}`),
    ...readdirSync(`${root}modules/_template/ui`).filter((f) => f.endsWith('.svelte')).map((f) => `modules/_template/ui/${f}`),
  ];
  for (const f of svelteFiles) {
    const r = compile(readFileSync(`${root}${f}`, 'utf8'), { filename: f, generate: 'client' });
    const warns = r.warnings;
    assert.deepEqual(warns.map((w) => `${f}: ${w.code} ${w.message}`), [], `${f} compiles without warnings`);
  }
  // the SDK entry only re-exports names that exist
  const entry = readFileSync(`${root}ui/src/lib/sdk.js`, 'utf8');
  const names = (from) => [...entry.matchAll(new RegExp(`export \\{([^}]*)\\} from '\\./${from.replace('.', '\\.')}'`, 'g'))]
    .flatMap((m) => m[1].split(',').map((s) => s.trim()).filter(Boolean));
  for (const n of names('fmt.js')) assert.ok(n in fmt, `fmt.js exports ${n}`);
  for (const n of names('sdk-core.js')) assert.ok(n in sdk, `sdk-core.js exports ${n}`);
  for (const n of names('sdk.svelte.js')) assert.ok(['lazy', 'poll', 'watch', 'watching'].includes(n), n);
}
console.log('sdk ok');
