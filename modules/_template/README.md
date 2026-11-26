# __NAME__ (lab module `__ID__`)

- `manifest.json` — server side: backend URL, who may use the module (`access`), and EVERY backend route the UI may call,
  each with `min` role (`guest`/`admin`) or `owner_only` (admins then get "ask owner" for a one-time approval).
- `ui/index.js` — UI side: `load`, `objects`, facets, tiles, views … Use `ctx` and `$lab/sdk.js` only (docs/sdk.md):
  no `$lab/lab.svelte.js`, no imports from other modules; list modules you read via `ctx.peer` in the manifest's `requires`.
- Backend: copy `sdk/python/labauth.py`, accept `X-Lab-Auth` only from the gateway address, `labauth.verify(header, key, "__ID__")`.
- Key: on the gateway `lab-admin keygen __ID__`, put the printed key on the backend.
