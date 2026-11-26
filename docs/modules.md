# Writing a module (manifest v2)

A module is a folder `modules/<id>/` with two parts:

- `manifest.json` — read by the **gateway**: what the module needs from each installation (`config`), how to reach its
  backend, and **every** backend route the UI may call, with who may call it. The gateway refuses everything else.
- `ui/index.js` (+ Svelte components) — read by the **browser**: objects, facets, tiles, views, alerts …, built with
  `ctx` and the module SDK `$lab/sdk.js` ([sdk.md](sdk.md): hooks, `ctx`, helpers, components, isolation rules).

Scaffold one with `lab-admin new-module <id> --name "Name"`; it starts from `modules/_template`.

A module either ships with the core (**bundled**: `modules/<id>/` in the release) or is installed from a signed
**catalog** as a package of its own (`deploy/make-module.sh <id>`; [catalog.md](catalog.md)). The manifest and the UI
are the same either way; each module has its own `version` and is updated on its own.

## The manifest

```json
{
  "manifest": 2,
  "id": "technitium",
  "name": "Technitium DNS",
  "version": "1.0.0",
  "kind": "community",
  "category": "network",
  "icon": "globe",
  "description": "Zones, records, cache and blocking for a Technitium DNS server.",
  "min_core": "0.1.0",
  "requires": [{ "id": "unifi", "optional": true }],
  "config": {
    "fields": [
      { "key": "url", "type": "url", "label": "Server URL", "required": true, "placeholder": "http://dns:5380" },
      { "key": "token", "type": "secret", "label": "API token", "required": true,
        "help": "Administration → Sessions → Create Token (a dedicated user with the least rights you need)" },
      { "key": "verify_tls", "type": "bool", "label": "Verify TLS certificate", "default": true }
    ],
    "validate": { "method": "GET", "path": "/api/user/session/get", "expect": [200] }
  },
  "backend": {
    "url": "{url}", "health": "/api/dashboard/stats/get", "timeout": 20, "tls_verify": "{verify_tls}",
    "auth": { "type": "header", "name": "Authorization", "prefix": "Bearer ", "secret": "token" }
  },
  "access": { "roles": ["owner", "admin"], "groups": [] },
  "routes": [
    { "method": "GET",  "path": "/api/zones/list" },
    { "method": "POST", "path": "/api/zones/records/add", "min": "admin", "label": "add DNS record",
      "query_keys": ["zone", "domain", "type", "ipAddress", "ttl"] },
    { "method": "POST", "path": "/api/cache/flush", "owner_only": true, "label": "flush DNS cache" }
  ],
  "settings": [
    { "key": "top_n", "type": "int", "default": 10, "min": 5, "max": 50, "label": "rows in top lists" }
  ]
}
```

Unknown keys are an **error** at every level. A misspelt `owner-only` must fail loudly, not quietly grant access.

### Top level

| key | | |
|---|---|---|
| `manifest` | required | `2` |
| `id` | required | `[a-z][a-z0-9-]{1,30}`, the same as the folder name |
| `name`, `version` | required | `version` is semver; each module is versioned and updated on its own |
| `kind` | required | `community` (any installation can use it) or `private` (talks to your own app) |
| `category` | required | `infrastructure`, `network`, `media`, `identity`, `monitoring`, `apps`, `tools` (groups the menu) |
| `icon`, `description` | | an icon name from `ui/src/lib/icons.js`; one line of text |
| `min_core` | | the oldest core version the module works with (a package with a newer `min_core` is refused: [catalog.md](catalog.md)) |
| `requires` | | other modules whose data it reads (`ctx.peer`) or whose routes it calls (`ctx.via`): `"id"` or `{"id", "optional": true}`; anything else is refused in the browser and by the deploy gate ([sdk.md](sdk.md#isolation)). `"*"` only with `delegate` |
| `access` | | `roles` that may use the module (default owner + admin) and `groups` that let a guest in |
| `guest_safe` | | `true` only if the backend filters per user (see below) |
| `delegate` | | `true`: a connector on 127.0.0.1 that may read other modules *as the calling user* (the AI module) |
| `connector` | | `{}` or `{"uses_credentials_of": [ids]}`: the backend is a connector Labradoor runs as its own user and configures from this module's `config` ([connectors/README.md](../connectors/README.md)); `backend.url` must be `http://127.0.0.1:<port>`; each id in `uses_credentials_of` must be in `requires` |

### `config`: what each installation fills in

No addresses, hostnames or credentials belong in a manifest. Each installation enters them in
**Settings → `~/modules` → (expand the module) → connection** (or `lab-admin config <id> key=value key=@file`).

Each entry in `fields` has a `key`, a `type` and a `label`, plus optional `help`, `required`, `default`, `placeholder`,
`options` (enum), `min`/`max` (int) and `multiline: true` (text/secret only: a PEM certificate, an ssh key). The types are:

- `url`: http(s) only, with no credentials or query string, and the trailing slash trimmed
- `secret`: stored **encrypted** with the gateway's master key and never sent to a browser; the UI only learns
  whether it is set
- `text`, `bool`, `int`, `enum`, `list`

`validate` is one call the gateway makes **with the values as typed, before saving them** (e.g. "who am I").
`expect` lists the status codes that mean success (default `[200]`). If the test fails, nothing is saved unless the
owner chooses *save anyway*. For a `connector` module the connector answers it: `{"method": "POST", "path":
"/api/_validate"}` gets the candidate values and tries its upstream login with them.

A module with missing required fields is **not set up**. Nobody can use it, and Settings shows what is missing.

### `backend`: a template filled from `config`

| key | |
|---|---|
| `url` | may use `{field}` placeholders of url/text/int/enum fields: `"{url}/api/v3"` |
| route paths | a whole path segment may be `{key}` (a config field or setting), e.g. `/admin/datastore/{store}/snapshots`: the route then only matches this installation's value (one safe segment; unset = the route matches nothing) |
| `tls_verify` | `true`/`false`, or a bool field: `"{verify_tls}"` |
| `auth` | `{"type": "bearer", "secret": "<secret field>"}`, `{"type": "header", "name": "X-Api-Key", "prefix": "", "secret": …}` or `{"type": "basic", "username": "<text field>", "secret": …}`; when an API logs in with a token as the user and a fixed password (Graylog: `<token>:token`): `{"type": "basic", "secret": "<secret field>", "password": "token"}` |
| `health`, `timeout`, `headers`, `decodes_slashes` | health path (401/403 counts as up), request timeout in seconds, a few static non-credential headers, and `decodes_slashes: true` if the backend turns `%2F` into `/` before routing (Proxmox does) |

Without `auth`, the module talks to **your own backend**, which verifies the signed `X-Lab-Auth` header (HMAC-SHA256,
60 s, bound to the module; see `sdk/python/labauth.py`). Create its key with `lab-admin keygen <id>`.

With `auth`, the gateway holds one credential for everyone, and the backend can't tell users apart. That is why guest
groups are refused on such modules unless `guest_safe: true` (the backend filters by user itself).

### `routes`: the allow-list

Each route has a `method` and a `path`. In the path, `*` matches exactly one segment and `**` (last only) matches the rest.

| key | |
|---|---|
| `min` | `guest`, `admin` or `owner`: the lowest role that may call it |
| `owner_only` | owner yes; admin only through a one-time **owner approval**; guest never. An admin may *read* an owner-only GET unless it is also `secret: true` |
| `secret` | the answer contains secret material (with `owner_only`); reads are audited too |
| `label` | what the audit log and approval requests show; **required on writes** |
| `body_keys` | the JSON body may only carry these fields |
| `body_allow` | `{"field": [allowed values]}`, e.g. which *arr commands may be run |
| `body_list` | the body is an array of such objects |
| `body_schema` | nested rules instead of the three above: every field at every level, with types, lengths, allowed values and allowed folders — see below |
| `query_keys` | the query string may only carry these parameters (`[]` = none) |
| `max_body` | bytes |
| `audit` | `false` for read-only POSTs (searches): they are neither audited nor logged at info level |
| `timeout` | seconds (1–300) for this route instead of `backend.timeout`: a slow search (the *arr interactive search waits for every indexer). Behind Cloudflare keep it under 100 s, or Cloudflare cuts the request first (524) |
| `cache` | GET only, 0–300 s: how long the gateway may answer this route from its cache. Default: 5 s for modules with a shared credential (`backend.auth`; one entry for all users, each caller's permission still checked), none for the rest (`cache` there means per user). Secret routes are never cached; a write through the gateway clears the module's entries |

**Writes must say who may call them** (`min` or `owner_only`). A GET defaults to everyone who may use the module.

#### `body_schema`: nested bodies

`body_keys`/`body_allow` see only the top level. When fields further down matter — the *arr `ManualImport` command
sends `files: [{path, seriesId, episodeIds, quality: {…}}]`, and `path` decides which file on the server is imported —
describe the whole body:

```json
"body_schema": {"type": "object", "by": "name", "cases": {
  "SeriesSearch": {"keys": {"seriesId": "int"}, "required": ["seriesId"]},
  "CheckHealth": {},
  "ManualImport": {"keys": {
    "files": {"type": "list", "min": 1, "max": 200, "items": {"type": "object", "required": ["path", "seriesId"], "keys": {
      "path": {"type": "string", "max": 1024, "prefix": ["{import_paths}"]},
      "seriesId": {"type": "int", "min": 0},
      "quality": {"type": "object", "null": true, "keys": {"quality": {"type": "object", "keys": {"id": "int"}}}}}}},
    "importMode": {"type": "string", "enum": ["auto"]}}, "required": ["files"]}}}
```

| node key | |
|---|---|
| `type` | `string`, `int`, `number`, `bool`, `object`, `list` (a bare `"int"` is short for `{"type": "int"}`) |
| `null` | `true`: `null` is accepted too |
| `enum` | the allowed values |
| `min`, `max` | numbers: the range; strings and lists: the length (defaults: 4096 characters, 100 items; at most 1000 items) |
| `prefix` | strings: the value is a clean absolute path (no `..`, `.`, `//`, backslashes or control characters) inside one of these folders. `"{setting}"` = this installation's value(s) — a `list` setting gives several; unset = nothing matches |
| `keys`, `required` | objects: the only fields allowed, and the ones that must be there |
| `by`, `cases` | objects: the discriminator field (`name`) and, per value, `{keys, required}` on top of the common `keys`; any other value is refused |
| `items` | lists: what every item must be |

Everything else is refused: unknown fields at any level, other types (`true` is not `1`, `1.0` is not an int),
nesting deeper than described, duplicate or case-variant keys, `NaN`. A schema may be at most 8 levels deep, is for writes
only, and replaces `body_keys`/`body_allow`/`body_list`. The audit entry of a refused body names the field, never the value.

The gateway also refuses paths that no UI builds (dot segments, empty segments, encoded slashes or backslashes, control
characters). When a backend would read a path differently, for example `040` vs `40` or upper vs lower case, the
**stricter** matching route wins.

### Per-installation policy: `_protect`

Every module with a backend has the owner-only setting **owner-only paths**: entries that make existing routes
owner-only *in this installation* (admins get "ask owner", guests nothing). It never adds routes.

| entry | protects |
|---|---|
| `/nodes/*/lxc/112/**` | writes (POST/PUT/PATCH/DELETE) to that path, e.g. the container that holds your keys |
| `GET /api/machines/40/commands` | reading it too (admins may otherwise read every owner-only GET) |
| `POST,DELETE /x/**` | just those methods |
| `POST /interface/poe/power-cycle numbers=ether22` | only requests whose JSON body has that field value (or contains it in a list or comma list) — for APIs that name the target in the body |
| `/api/open/19/**` | (guacamole) the terminal of Guacamole connection 19: the owner only, admins never get a window ([modules/guacamole](../modules/guacamole/README.md)) |

### `settings`

Behaviour switches the owner can change in Settings (`bool`, `int`, `enum`, `text`, `list`). The UI reads them as
`ctx.settings.<key>`. Every module also gets the generic switches `_ticker`, `_overview`, `_alerts`, `_tiles` and
`_enabled`.

## Security model, in short

- The browser never talks to a backend; it calls `/api/m/<id>/<path>`, and the gateway checks the route, role, body and
  query, then forwards it with the module's credential or a signed `X-Lab-Auth`.
- Secrets live in the gateway's database, sealed with `/etc/lab/master.key` (`gateway/lab/secretbox.py`). Keep a copy
  of that key in your password manager; backups of the database are useless without it.
- Every write is audited with the user, the module, the path and the result.
