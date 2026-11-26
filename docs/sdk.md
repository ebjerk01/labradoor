# Module SDK (browser side)

A module's UI half lives in `modules/<id>/ui/`. It gets **everything from the shell through `ctx`** and imports shared
code **only from `$lab/…`**:

```js
import { act, lazy, cached, errText, ago } from '$lab/sdk.js';   // functions
import Table from '$lab/Table.svelte';                             // components
```

Three rules keep modules independent of each other and of the shell's internals. The deploy gate enforces them for
every module whose manifest says `"manifest": 2` (see [Isolation](#isolation)):

1. never import `$lab/lab.svelte.js` (the shell's own state): use `ctx`;
2. never import another module's files (`../../other/ui/…`): shared code belongs in `$lab/`;
3. read another module's data only through `ctx.peer(id)`, and only when the manifest lists `id` in `requires`.

The manifest (routes, config, access) is described in [modules.md](modules.md).

## Module hooks

`ui/index.js` default-exports an object. Every hook is optional.

| hook | | |
|---|---|---|
| `id` | required | the module id (same as the folder and the manifest) |
| `load(ctx)` | → data | called on every shell refresh (default 15 s); the result is the `data` every other hook and component gets. Throwing marks the module as failing; a 403 means "nothing for this user" and is retried every 5 min |
| `objects(data, ctx)` | → `[{id, type, name, kind, status, parent?, meta?, cpu?, mem?, disk?}]` | objects with the same `id` from several modules merge into one, so one machine collects every module's facets |
| `alerts(data, ctx)` | → `[{key, status: 'warn'\|'bad', title, detail?, since?, object?}]` | |
| `kpis(data, ctx)` | → `[{label, value, sub?, status?}]` | overview numbers |
| `ticker(data, ctx)` | → `[{g, c, s, m}]` | glyph, colour, source, message |
| `status(data, ref)` | → `'ok'\|'warn'\|'bad'\|null` | for map nodes that point at this module |
| `actions(object, data, ctx)` | → `[{label, icon, method, path, body?, confirm?, done?} \| {label, icon, url}]` | buttons in the object panel; the shell hides/locks them from the manifest's verdict |
| `search(data, ctx)` | → `[{label, sub, status?, object?, url?, run?}]` | static Ctrl-K entries |
| `lookup(q, ctx)` | async → same | Ctrl-K entries looked up as the user types (q ≥ 3 characters) |
| `facets` | `{objectType: Component}` | the module's section in the object panel; props `{object, data, ctx}`; `'*'` = every object |
| `tiles` | `[{id, label, w, h, component, min?}]` | wall tiles; props `{data, ctx}` |
| `views` | `[{id, label, icon, component, min?}]` | pages of their own; props `{data, ctx}`. View ids are global: prefix them with the module id |

`min: 'admin'` or `'owner'` hides a tile or view from lower roles. That is for tidiness; the gateway decides what
anyone may read or change.

## `ctx`

Every hook and component gets a `ctx` bound to its module.

| member | |
|---|---|
| `id`, `role`, `settings` | the module id, the user's role (`owner`/`admin`/`guest`), the owner's settings for this module (manifest `settings`) |
| `me` | the signed-in user `{username, name, role, groups}` (read-only) |
| `now` | the shell's clock in unix seconds, updated every 5 s: use it for "3m ago" so text refreshes on its own |
| `api.get(path, query?)`, `api.text(path, query?)`, `api.post/put/patch(path, body)`, `api.del(path)`, `api.upload(path, blob, method?)` | this module's backend through the gateway; only manifest routes work (`text`: a plain-text answer such as a log file) |
| `can(method, path)` | `'yes'`, `'ask'` (owner approval needed) or `'no'`, from the manifest and the user's role; a `?query` is ignored |
| `ask(method, path, body, label, reason?)` | request a one-time owner approval; `path` may carry a `?query`, which the approved run gets back |
| `notify(text, kind?)`, `refresh()` | a toast (`ok`/`bad`), a shell refresh (every module's `load`; a push hint from the gateway already reloads the module after its own writes) |
| `changed()`, `rev` | mark this module changed after a write made without `act()`: its `cached()` values are dropped and its open `lazy()` loads run again (`act()`, panel actions and the gateway's push hint for other tabs' writes do this already); `rev` is the change counter `lazy()` follows |
| `data()` | this module's latest data |
| `open(objectId)`, `close()`, `selected()` | open/close the object panel, the selected object id |
| `go(viewId)`, `canGo(viewId)` | switch view; whether this user has that view |
| `object(id)`, `objects()`, `alerts()`, `topology()` | one merged object (read-only), the map of all objects, all open alerts, the map's topology (nodes, links, zones; read-only) |
| `prefs.get(key, default)`, `prefs.set(key, value)` | per-user preferences, stored server side and scoped to the module |
| `peer(id)` | another module's loaded data, **read-only**, or `null` (not active for this user, not loaded yet). Needs `id` in `requires` |
| `via(id)` | another module's `ctx`, to call **its** routes (the gateway checks them as usual). Needs `id` in `requires` |

Don't call `objects()`, `object()` or `alerts()` from inside the `objects`/`alerts` hooks: those lists are built from
the hooks, so it would go round in circles. Read your own `data` there, and `peer()` for other modules.

## Requests

### `act(ctx, opts)` — run a route the way the manifest allows

```js
await act(ctx, { path: '/api/restart', label: 'restart server', confirm: true });
await act(ctx, { method: 'DELETE', path: `/api/items/${id}`, label: `delete ${name}`, confirm: `delete ${name}?` });
await act(ctx, { method: 'POST', path: '/api/zones/records/add', query: { zone, type: 'A' }, label: 'add record' });
```

| verdict | what happens |
|---|---|
| `yes` | the call runs; on success the module is marked changed (`ctx.changed()`: its `cached()` values go, open `lazy()` loads such as the object panel's run again), a toast `<label> ✓` and a refresh |
| `ask` | a one-time approval request to the owner (toast "asked the owner: …"); the route is not called |
| `no` | nothing is sent; toast `<label>: not allowed` |

If the gateway answers that the call needs approval after all, it is asked for. A failure shows `<label>: <errText>`.

| option | |
|---|---|
| `method` | default `POST` |
| `path`, `query` | `query` (object or string) is added to the path; the verdict uses the bare path |
| `body` | JSON body (`{}` when left out on POST/PUT/PATCH) |
| `label` | what the user, the audit log and the approval request see (always give one for writes) |
| `confirm` | `true` or a question: the browser asks first |
| `ok` | the success toast: text or `(result) => text` |
| `quiet` | no toast, no refresh (a read made with POST) |
| `reason` | shown on an approval request |
| `check(result)` | for APIs that report errors inside a 2xx answer: throw to fail the action (error toast, no ✓, no refresh); a returned value replaces the result |
| `done(result, ctx)` | runs after success; return `true` when it takes over the follow-up (e.g. it watches a background task), else the toast and refresh still happen |

Returns the backend's answer (`{}` when empty), or `null` when nothing ran (refused, cancelled, asked, failed).

### `getOrDenied(ctx, path, query?)`

For backends that answer per user: `{data}` on success, `{denied: text}` on 403 (show it, it is not an error). A 401
from your own backend (not the gateway's "not logged in") means it refused the gateway's signature; it is rethrown
without the status so the shell does not sign the user out.

```js
async load(ctx) {
  const r = await getOrDenied(ctx, '/api/me/summary');
  return r.denied ? { denied: r.denied } : { summary: r.data };
}
```

### `soft(promise, fallback = null)`, `qs(query)`, `withQuery(path, query)`, `barePath(path)`

`soft` turns a failure into `fallback`, for the optional parts of a `load`. `qs({a: 1, b: null, c: [1, 2]})` →
`a=1&c=1&c=2` (null dropped, arrays repeat the key).

### `errText(error, max = 220)`

One line of text for a failed request, whatever the backend's error looks like: `{error}`, `{error: {message}}`,
`{message}`, `{detail}`, `{errorMessage}`, `{title}`, `{errors: [{message}]}`, a field map `{errors: {field: text}}`
(appended), or the raw body.

## Loading

### `lazy(getCtx, pathFn, opts?)` — a GET that follows its inputs

For data a view needs that the 15 s `load` should not fetch. Call it while the component initialises (top of `<script>`).

```js
let { ctx } = $props();
let page = $state(1);
const users = lazy(() => ctx, () => '/api/users', { query: () => ({ page }), pick: (r) => r.items });
```

It runs at once and again whenever `pathFn()` or `query()` change (a `null` path loads nothing), and again when the
module changes (`ctx.rev`: a write through `act()`, a panel action, another tab's write) — that reload keeps the data
shown until the new answer is in. Routes the user may not read are not sent. It returns:

| | |
|---|---|
| `data` | the whole JSON answer, or `pick(answer)` |
| `error` | one line of text, or `null` |
| `loading` | `true` until the first answer, and while reloading |
| `denied` | `'ask'` (owner only) or `'no'` when the user may not read it |
| `reload()` | fetch again (after a write) |

Options: `query: () => object`, `pick: (answer) => value`, `keep: true` (keep the old data while the path changes or a
reload fails), `follow: false` (do not load again on a module change: for expensive loads such as an interactive search).

### `cached(key, ttl, fn)`, `forget(key)`

`fn()`'s value, reused for `ttl` milliseconds: for slow-changing lists inside `load`. Calls made while one runs share
it, and a failed refresh keeps the last good value (it throws only when there is none yet). The cache is shared by all
modules: start keys with `ctx.id`. `forget('mod:jobs')` drops one key, `forget('mod:*')` every key with that prefix.

```js
async load(ctx) {
  const [status, jobs] = await Promise.all([
    ctx.api.get('/api/status'),
    soft(cached(`${ctx.id}:jobs`, 5 * 60000, () => ctx.api.get('/api/jobs')), []),
  ]);
  return { status, jobs };
}
```

### `poll(fn, ms, opts?)`

`fn()` now and every `ms` while the component is mounted; skipped while the browser tab is hidden (`hidden: true` runs
anyway), stopped when the component is destroyed. `immediate: false` waits `ms` first. Returns `{stop()}`. Prefer
`lazy` + the shell refresh; poll only what must be fresher (a live log, a progress bar).

### `watch(ctx, opts)`, `watching`

Follow a background task the module started until it ends, then toast and refresh. It is not tied to a component, so
it keeps going when the user leaves the view.

```js
await act(ctx, {
  path: `/nodes/${node}/backup`, body, label: 'backup',
  done: (r) => {
    if (!r.task) return false;
    watch(ctx, { label: 'backup', id: r.task, refresh: [0, 5000],
      check: async () => {
        const t = await ctx.api.get(`/tasks/${r.task}`);
        return t.state === 'running' ? null : { ok: t.state === 'ok', text: t.error };
      } });
    return true;
  },
});
```

`check()` returns `null` while the task runs and `{ok, text?}` when it ended; a thrown error is retried. Options:
`label`, `id`, `every` (ms, 3000), `first` (ms before the first check, 1500), `timeout` (ms, 1 hour), `refresh` (delays
in ms for refreshes after the end, `[0]`), `quiet`. `watching.list` (reactive) holds the running ones as
`{id, module, label, started}`; filter by `module` to show yours.

## Formatting and status

From `fmt.js` (also importable from `$lab/fmt.js`): `bytes(n)`, `rate(bytesPerSecond)`, `bits(bytesPerSecond)`,
`pct(v, digits)`, `num(v, digits)`, `ago(ts, now)`, `dur(seconds)`, `clock(ts)`, `sparkPoints`, `safeUrl(url)` (only
http(s) links may become an `href`), and the status set `GLYPH`, `RANK`, `worst(...statuses)`, `statusVar(status)`,
`memLevel(pct)`.

Statuses are `ok`, `warn`, `bad`, `off` and `unknown`, shown as shape + colour (● ▲ ■ ○ ·).

| | |
|---|---|
| `ts(value)` | unix seconds from an ISO string, `YYYY-MM-DD HH:MM:SS` (no zone = UTC), a `Date`, ms or seconds; `null` if missing/invalid |
| `rel(t, now)` | `in 3h` / `2d ago` |
| `duration(seconds)` | `1h05`, `7m` |
| `when(t)`, `day(t)`, `hhmm(t)` | date + time, weekday + date, time (locale `LOCALE`) |
| `worstOf(list, base = 'ok')` | the worst status in a list |
| `siteStatus(problems)` | a module's own health from its problems list (`[{status}]` or strings; no status = `warn`): none → `ok` |
| `level(v, warn, bad)` | thresholds: `level(disk, 80, 90)` (higher is worse), `level(daysLeft, 7, 2)` (lower is worse) |
| `clip(text, n = 80)` | cut with `…` |
| `sortRows(rows, keyOrFn, dir)` | numbers numerically, text naturally (`node2` before `node10`), empty last |
| `readonly(value)` | a deep read-only view of plain objects and arrays |

A common pattern: one `problems(data)` function feeds both `alerts()` and the object's status.

```js
const problems = (d) => [...(d.status.ok ? [] : [{ key: 'mod:down', status: 'bad', title: 'server is down' }])];
export default {
  alerts: (d) => problems(d),
  objects: (d) => [{ id: 'mod', type: 'service', name: 'Mod', status: siteStatus(problems(d)) }],
};
```

## Components

Styles use the theme's CSS variables (`--ink`, `--dim`, `--faint`, `--line`, `--raise`, `--sig`, `--ok`, `--warn`,
`--bad` …) and global classes (`btn`, `lnk`, `cap`, `mono`, `dim`, `spin`), so modules match the shell in both
themes.

### `Table.svelte`

```svelte
<Table rows={guests} key="vmid" {ctx} object={(g) => g.name} status={(g) => (g.running ? 'ok' : 'off')}
  bind:sort label="guests"
  columns={[
    { key: 'name', label: 'name' },
    { key: 'node', label: 'node', dim: true, phone: false },
    { key: 'mem', label: 'memory', align: 'right', desc: true, format: (v) => bytes(v) },
    { key: 'tags', label: 'tags', sort: false, render: tagCell },
  ]} />
{#snippet tagCell(g)}{#each g.tags as t}<span class="tag">{t}</span>{/each}{/snippet}
```

| prop | |
|---|---|
| `rows`, `key` | the rows; their key (`'id'` or `(row) => key`) |
| `columns` | `{key, label, get?, format?, render?, sort?, desc?, align?, dim?, phone?, title?}`: `get(row)` for a computed value, `format(value, row)` for text, `render` a snippet for markup, `sort: false` or `(row) => value`, `desc: true` sorts high → low on the first click, `phone: false` hides the column on narrow screens |
| `status` | `(row) => status`: a glyph column first |
| `object` + `ctx` | a row click (or Enter) opens that lab object |
| `onrow` | or your own row click handler |
| `muted` | `(row) => bool`: dimmed rows (stopped, disabled …) |
| `sort` | bindable `{key, dir: 1 \| -1}`, `null` = as given |
| `loading`, `error`, `empty` | the states shown instead of rows |
| `label`, `minWidth` | `aria-label`; a minimum width in px before the table scrolls sideways |

### `ActionButton.svelte`

A button for one route, with the verdict built in: hidden when the user may not call it (`showDenied` shows it
disabled instead), a lock and "ask owner" when the owner must approve, a spinner while it runs. With `confirm`, the
first click arms it and a second click within 4 s runs it, so no dialog interrupts. It runs through `act()` and takes
the same options (`method`, `path`, `body` (or a function read at click time), `query`, `label`, `ok`, `done`, `quiet`,
`reason`), plus `icon`, `primary`, `small`, `disabled`, `title` and optional children for the text.

```svelte
<ActionButton {ctx} path="/api/restart" label="restart" icon="restart" confirm="restart now?" small />
<ActionButton {ctx} method="DELETE" path={`/api/items/${it.id}`} label={`delete ${it.name}`} confirm />
```

### `Lazy.svelte`

The states of a `lazy()` result in one place: a spinner until the first answer, the error (or "owner only" / "not
allowed"), `empty` for `null` or `[]`, else its children with the data.

```svelte
<Lazy of={users} empty="no users">
  {#snippet children(list)}<Table rows={list} {columns} />{/snippet}
</Lazy>
```

### Also in `$lab/`

`Section` (a titled panel section), `Stats` (`[{n, v, s?}]` number row), `Glyph` (status shape), `Lines`
(terminal-style lines), `Bar`, `Gauge`, `Spark`, `Metric` (labelled sparkline), `Icon` (names in `icons.js`).

### `$lab/arr/` — the shared *arr UI

Modules for the same family of apps share their UI through a subfolder of the SDK instead of keeping copies (they may
not import each other). `$lab/arr/` holds the Sonarr/Radarr (v3 API) module and its parts:

| file | |
|---|---|
| `arr.js` | `createArr('sonarr' \| 'radarr')`: the whole module object (load, objects, alerts, kpis, ticker, actions, facet, library view); `modules/sonarr/ui/index.js` is `export default createArr('sonarr')` |
| `logic.js` | pure helpers: `healthStatus(h)`, `healthLine(h, prefix?)`, `healthAlerts(id, name, health)` (also for Prowlarr's v1 health list), `groupQueue`, `calendarItems`, `disks`, `importPayload`, `releaseRows`, `slimLibrary`, `bySeason` … |
| `Problems.svelte` | stuck downloads with "import files" + "remove + blocklist". Props `groups`, `ctx`, `limit`, `empty`, `imports` (show the import button). Rows with `app` (the media hub) act through `ctx.via(app)` |
| `Upcoming.svelte` | calendar lines `[{at, title, sub, hasFile, kind}]` grouped by day |
| `ArrFacet`, `LibraryView`, `ItemDetail`, `Releases`, `ManualImport` | the service facet, the library view, one series/movie (search, interactive search + grab, edit, delete), and a stuck download's manual import |

They get everything through the `ctx` you pass (the app module's own, or `ctx.via(app)`), so the app module's manifest
still decides every call. Files in a subfolder are part of the module ABI like every other `$lab` file
(`$lab/<folder>/<file>`, one level).

## Isolation

### `requires` and `ctx.peer` / `ctx.via`

A module that shows or acts on another module's data declares it in its manifest:

```json
"requires": ["hypervisor", { "id": "dhcp", "optional": true }]
```

```js
objects(data, ctx) {
  const hv = ctx.peer('hypervisor');            // read-only, or null
  return data.backups.map((b) => ({ id: hv?.guests.find((g) => g.id === b.guest)?.name ?? `backup:${b.id}`, … }));
}
// acting through another module's routes (its manifest and the user's role still apply):
const media = ctx.via('downloader');
if (media) await act(media, { path: `/api/torrents/${hash}/pause`, label: 'pause' });
```

- `peer()` returns `null` when the other module is not active for this user or has not loaded yet; always handle it.
  An `optional` dependency is one the module works without.
- The data is the other module's `load()` result: an interface between modules. Read only what you need, and expect
  it to change between that module's versions.
- An undeclared `peer('x')`/`via('x')` **throws in development** and returns `null` (with one console warning) in
  production. Writing to peer data throws in development and is ignored in production.
- `"*"` (any module) is accepted only together with `delegate: true` (an assistant that reads everything as the user).

### The deploy gate

`tests/module_isolation.test.mjs` (with the checker in `tests/isolation.mjs`) fails the deploy when a module with
`"manifest": 2`:

| rule | |
|---|---|
| `lab-singleton` | imports `$lab/lab.svelte.js`, or reaches `ui/src/lib/lab.svelte.js` by a relative path |
| `cross-module` | has a relative import that leaves `modules/<id>/` |
| `undeclared-peer` | calls `peer('x')` or `via('x')` with a literal `x` that is not in `requires` (and no `"*"`) |

A v2 module whose UI is still being ported can be listed in `tests/isolation-pending.json`: its problems are then
printed instead of failing the deploy, and the gate fails once the module is clean until the entry is removed, so the
list only shrinks. Run it locally with `node tests/module_isolation.test.mjs`. Comments are ignored. A `peer(id)` with a computed id
cannot be checked here; the runtime guard catches it.

## Moving a module to the SDK

1. Manifest: `"manifest": 2` (see [modules.md](modules.md)); list every module you read or act through in `requires`.
2. Replace `import { lab } from '$lab/lab.svelte.js'`: `lab.now` → `ctx.now`, `lab.open` → `ctx.open`, `lab.go` →
   `ctx.go`, `lab.views.includes(v)` → `ctx.canGo(v)`, `lab.data.x` → `ctx.peer('x')`, `lab.ctx('x')` → `ctx.via('x')`,
   `lab.objects.has/get` → `ctx.object(id)`, `lab.objects` → `ctx.objects()`, `lab.alerts` → `ctx.alerts()`,
   `lab.me` → `ctx.me`, `lab.role` → `ctx.role`, `lab.sel` → `ctx.selected()`, `lab.close` → `ctx.close`,
   `lab.prefs['mod.k']` / `lab.savePref('mod.k', v)` → `ctx.prefs.get('k')` / `ctx.prefs.set('k', v)`,
   `lab.ask(...)` → `ctx.ask(...)` or `ctx.via(id).ask(...)`.
3. Components that only get `data` and need `ctx` get it as a prop (facets, tiles and views already receive it).
4. Replace local copies of `act`, `lazy`, `errText`, `ts`, caches (`every`, `loadSlow`), task watchers and
   "overview" loaders with the SDK; move helpers other modules imported from you into `$lab/` (or have them use
   `ctx.peer`).
5. Use `Table`, `ActionButton` and `Lazy` where the module hand-built them.
6. `node tests/module_isolation.test.mjs`, `npm run build`, then click through the module.
