# Contributing to Labradoor

Thanks for your interest. Labradoor is a self-hosted homelab control room: a role-gated Python gateway and a Svelte UI, with each integration shipped as a signed module. The server uses only the Python standard library.

## Development setup

Requirements: Node 20+ and Python 3.11+.

```sh
npm ci && npm run build          # build the UI into ui/dist
python3 -m unittest discover -s tests
# run the gateway (from gateway/), serving the built UI:
LAB_DB=/tmp/lab.db LAB_STATIC=ui/dist LAB_MODULES=modules LAB_KEYS=/tmp/keys LAB_COOKIE_SECURE=0 \
  python3 -m lab   # from gateway/;  `npm run dev` proxies /api and /auth to it
```

## Before you open a pull request

Run the same gates CI runs (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)):

```sh
npm run build
python3 -W ignore -m unittest discover -s tests
for t in connectors/*/test_*.py; do python3 -W ignore -m unittest discover -s "$(dirname "$t")" -p 'test_*.py'; done
find modules ui/src tests -name '*.test.mjs' | sort | while read -r t; do node "$t"; done
```

Keep every suite green, including `tests/module_isolation.test.mjs` (modules talk only through declared interfaces).

## Writing a module

Start from `modules/_template` and `connectors/_template`, and read:

- `docs/modules.md` — the manifest (config, backend, routes, settings) and the security model
- `docs/sdk.md` — the browser-side SDK (`ctx`, hooks, components)
- `docs/design.md` — the UI rules (shared components, no bespoke button styles)

Rules that keep the project portable and safe:

- **Nothing installation-specific in a manifest or UI** — no URLs, IPs, hostnames, tokens, IDs, or user/group names. Connection details are `config` fields (with a `validate` test); values the UI needs are `settings` (config never reaches the browser).
- Declare every interface a module uses; no cross-module imports.
- Dangerous actions are `owner_only`, each with a clear `label`.
- No new server dependencies: the gateway is standard-library Python.

## Style

- Python: standard library, small and readable; match the surrounding code.
- Svelte 5 + the SDK; follow `docs/design.md`.
- Keep commits focused and describe the behaviour change.

## Reporting security issues

See [SECURITY.md](SECURITY.md) — please don't open a public issue for a vulnerability.

## License

By contributing you agree that your contributions are licensed under the [Apache License 2.0](LICENSE).
