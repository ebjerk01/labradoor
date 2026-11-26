# Connectors

A connector is a small service on the Labradoor host for a third-party API that a manifest can't reach directly:
session/cookie logins (NPMplus, UniFi, qBittorrent, Guacamole), LDAP (Active Directory), several calls per answer, or
per-user rules on top of one admin key (Seerr). Labradoor runs, configures and isolates connectors itself — there are
no env files to write.

| | |
|---|---|
| code | `connectors/<id>/connector.py` (start from `_template/`), stdlib Python + `sdk/python` (`labauth`, `labconn`); a module installed from a catalog brings it in its package (`connector/`, [catalog.md](../docs/catalog.md)) and runs it from `/var/lib/lab-modules/<id>/<version>/connector` |
| module | `modules/<id>/manifest.json` with `"connector": {}` and `backend.url` = `http://127.0.0.1:<port>` |
| service | `lab-connector@<id>` (deploy/lab-connector@.service), user **`lab-c-<id>`** |
| key | `/etc/lab/keys/<id>.key`, handed to the service by systemd (`$CREDENTIALS_DIRECTORY/key`) |
| config | the module's `config` fields, from the gateway (`GET /api/connector/config`) |
| state | `/var/lib/lab-connectors/<id>` (systemd `StateDirectory`, 0700, its own user) |
| ephemeral files | `/run/lab-connectors/<id>` (tmpfs, removed when it stops) |

## How a connector gets its config

The owner fills in the module's connection in **Settings → module → connection** like for any other module: URL,
username, password or API key (stored **sealed** with the master key), TLS verification, a CA certificate, OUs …
whatever the manifest's `config.fields` ask for. Fields marked `"multiline": true` (a PEM, an ssh key) get a text box.

1. **Test.** The manifest's `config.validate` is `{"method": "POST", "path": "/api/_validate"}`. The gateway posts the
   values *as typed* (nothing saved yet) to the connector, signed as the owner. The connector tries its upstream login
   with exactly those values and answers `{"ok": true, "detail": "…"}` or `{"ok": false, "error": "…"}` — never a
   credential. If the connector isn't running yet (first setup), the gateway starts it for the test.
2. **Save.** The gateway seals the secrets into its database and asks the root helper to **restart** the connector.
3. **Start.** The connector reads its key from systemd and asks the gateway for its config:

   ```
   GET http://127.0.0.1:<gateway port>/api/connector/config
   X-Lab-Connector: <id>
   X-Lab-Auth: <labauth token signed with ITS key, claims {"u": "connector", "m": "_config.<id>"}>
   ```

   The gateway answers only on 127.0.0.1 (the socket address — a proxy header never counts), only for a module that
   declares `connector`, and only when the token verifies with **that module's** key in the `_config.<id>` scope (so a
   token the gateway sends *to* the connector for a user never passes as a config request, and vice versa):

   ```json
   {"id": "npm", "ready": true, "enabled": true, "missing": [],
    "values": {"url": "https://npm.lan:81", "username": "lab@example.com", "password": "…", "verify_tls": true},
    "uses": {}}
   ```

   `values` holds every config field, defaults filled in, secrets opened. `ready: false` (+ `missing`) means the module
   still needs setup: the connector answers 503 "needs setup" and the gateway doesn't route to it anyway.

The connector reads its config once; the gateway restarts it after every change. Until the gateway has answered (it
starts first, but may be restarting), the connector answers 503 and keeps retrying in the background.

### Credentials of other modules: `uses_credentials_of`

A connector that has to call **other** modules' backends the way the gateway does (the new-service wizard creates a
container through the Proxmox module, a reservation through UniFi …) lists them:

```json
"requires": [{"id": "proxmox", "optional": true}, {"id": "unifi", "optional": true}],
"connector": {"uses_credentials_of": ["proxmox", "unifi"]}
```

Each must also be in `requires`. Its config answer then carries, per listed module that is **on and set up**,
exactly what calling it needs and nothing more:

```json
"uses": {
  "proxmox": {"ready": true, "backend": {"url": "https://pve:8006/api2/json", "auth": {"type": "header", …}},
              "values": {"api_token": "…"}, "key": null},
  "unifi":   {"ready": true, "via": "gateway", "backend": {"timeout": 20}, "values": {}, "key": null},
  "cdn":     {"ready": false}
}
```

- **A third-party API** (`backend.auth` with a secret): its rendered backend plus the auth secret (and basic-auth
  username) only, not its other config. The connector calls it directly.
- **An own backend** (one that verifies `X-Lab-Auth`: npm, unifi, manage …): **no key, no URL** (`"via": "gateway"`).
  Its HMAC key would let the connector sign any user and any owner approval for that backend, and fetch that module's
  whole config if it is a connector too (security review 2026-11-15, L4). Instead the connector calls it **through the
  gateway**, as the person whose request started the work:

  ```python
  # in the request handler: the gateway sends an act token with every owner/admin request to a module that has
  # uses_credentials_of (X-Lab-Act, 2 h, bound to that person's session)
  act = self.headers.get(labconn.ACT_HEADER)
  code, headers, body = labconn.call(ID, KEY, act, "unifi", "POST", "/api/reservations",
                                     body=json.dumps({...}).encode(), headers={"Content-Type": "application/json"})
  ```

  `GET|POST|… /api/connector/call/<module>/<path>` on 127.0.0.1, signed with the connector's own key (scope
  `_call.<id>`). The gateway checks the token (minted for this connector, session still alive, the person re-read: a
  lower role counts), that the module is in `uses_credentials_of` and on, and then that person's own rules: the
  route, `owner_only`/`min`, `_protect` (body conditions too), the query and body allow-lists. An owner-only route
  for an admin is refused there (no approval is asked) — unless the owner approved the request that started the work:
  then the token carries that approval and the call passes with it. Writes are audited as `<label> via <connector>`.
  Keep the act token in memory only; it expires after 2 hours, or at logout.
- **A module that is off or not set up**: `{"ready": false}`, no credentials.

The owner sees `uses_credentials_of` (and `delegate`) under Settings → `~/modules` → the module, and confirms it when
turning the module on. In a catalog package these make it a **privileged module**: it installs only from the core's
release key or a publisher root allowed for that (`lab-admin publisher allow-privileged NAME`, docs/catalog.md).

A connector may also hold **its own**, narrower credentials for the same API in its own config (the wizard has a
Proxmox token that may only create containers in one pool). When a step names its own credential, that one is used,
never the module's.

## Users and isolation

| who | runs as | can read |
|---|---|---|
| gateway | `lab` (group `lab`) | `/etc/lab` (keys, `master.key` root:lab 0640), `/var/lib/lab` (its database) |
| connector `<id>` | `lab-c-<id>` (own group, **not** in `lab`) | its key copy from systemd, its own state + runtime dir, the code in `/opt/lab` |
| root helper | root, one process per request | — (creates users/keys, runs `systemctl` for one connector) |

The unit (deploy/lab-connector@.service) adds: `InaccessiblePaths=/etc/lab /var/lib/lab /run/lab-connector-helper.sock`,
`ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, `NoNewPrivileges`, `UMask=0077`. So a hole in one connector
exposes that connector's own upstream login and nothing else: not another connector's config or key, not the master
key, not the gateway's database.

Check it on the host:

```sh
sudo -u lab-c-npm cat /etc/lab/keys/npm.key          # Permission denied (even its own: it gets a copy via systemd)
sudo -u lab-c-npm cat /etc/lab/master.key            # Permission denied
sudo -u lab-c-npm ls /var/lib/lab-connectors/unifi   # Permission denied
id lab-c-npm                                         # no group lab
lab-admin keys                                       # inventory + isolation check, exit 1 if anything is off
```

### The root helper

The gateway never needs root. When the owner saves a connector module's config or switches the module on or off, the
gateway asks `lab-connector-helper` over `/run/lab-connector-helper.sock` (socket-activated, group `lab` only), one JSON
line each way. The command set is fixed:

| request | does |
|---|---|
| `{"op": "ensure", "id": ID}` | create user `lab-c-ID` + key if missing, enable, start if not running |
| `{"op": "restart", "id": ID}` | the same, then restart (new config) |
| `{"op": "stop", "id": ID}` | disable and stop (module switched off) |
| `{"op": "status"}` | state of every shipped connector |

`ID` must be a connector shipped with the release (`/opt/lab/connectors/ID/connector.py`) or the connector of a module
installed from a catalog (`/var/lib/lab-modules/ID/<version>/connector/connector.py`, root's; a unit drop-in points
`lab-connector@ID` there); anything else is refused.
The helper never sees a config value. At start the gateway starts every enabled, configured connector that isn't
running and stops the switched-off ones.

## Writing a connector

1. Copy `connectors/_template/` to `connectors/<id>/` and pick a free port (table below).
2. In `modules/<id>/manifest.json`: `"backend": {"url": "http://127.0.0.1:<port>", "health": "/healthz"}`,
   `"connector": {}`, the `config.fields` it needs (no defaults that belong to one installation: an empty required
   field means "needs setup"), `"validate": {"method": "POST", "path": "/api/_validate"}`, and the routes the UI may call.
3. In the connector:
   - `KEY = labconn.load_key(ID)`; verify every request with `labauth.verify(header, KEY, ID)`, only from 127.0.0.1.
   - `CONF = labconn.Config(ID, KEY, apply=configure)` and `CONF.start()` in `main`; `configure(values, conf)` sets up
     the upstream client. Answer 503 `CONF.why()` while `not CONF.ready`.
   - `POST /api/_validate`: `labconn.candidate(claims, body)` (owner only) → try the upstream login with those values.
   - State in `labconn.state_dir(ID)`, temporary secret files in `labconn.runtime_dir(ID)`.
   - Re-check owner-only operations yourself (defence in depth), and never return a credential, cookie or token.
4. Tests next to it (`test_*.py`, offline: fake the upstream, feed config with `CONF.set({...})`); the deploy runs them.

A connector that needs a third-party Python package gets its own venv outside `/opt/lab` from install.sh and a unit
drop-in (only `ai` today: `/opt/lab-venv-ai` with the pinned `anthropic` SDK); everything else stays stdlib.

Ports: 8110 npm · 8111 unifi · 8112 guacamole · 8113 qbit · 8114 seerr · 8115 ad · 8116 wizard · 8117 ai ·
8121 stalwart · 8118–8120 free (claim one here).
