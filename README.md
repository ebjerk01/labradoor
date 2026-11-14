# Labradoor

**One door to your whole homelab.**

Labradoor is a self-hosted control room for your homelab. You open one site and manage Proxmox, backups, DNS, the reverse proxy, the media stack, identity and more. Each service is a module, and every machine and service is one object with everything about it in one panel.

> **Status: pre-alpha, code not published yet.** Labradoor started as one person's homelab dashboard and runs there daily with ~40 modules. It is being turned into something anyone can install. This repository tracks that work in public: see the [roadmap](#roadmap) and the [issues](../../issues). The code lands here once it has been cleaned of everything specific to the original homelab.

## What it does

- **Object-based navigation.** A container, a host, a domain or a Jellyfin title is one object, whichever service reports it. Its panel shows status, metrics, backups, logs, alerts and the actions every module offers for it.
- **Overview, wall and map.** The overview is a dense status table. The wall is a grid of tiles. The map shows the topology from the internet edge down to every guest, laid out automatically with no crossing lines.
- **Modules for the services you already run:** Proxmox VE, Proxmox Backup Server, Nginx Proxy Manager, Cloudflare, UniFi, Technitium DNS, MikroTik, Guacamole, Graylog, Authentik, Active Directory, Jellyfin, Sonarr, Radarr, Prowlarr, Bazarr, qBittorrent and Seerr. More can be added.
- **Roles.** The owner can do everything. Admins can do everything except actions the owner marks "owner only"; for those they can ask the owner for a one-time approval. Guests see only the modules you give them.
- **Ctrl-K finds everything.** Search across modules and live lookups, and jump to any object or view.
- **Optional AI assistant** (bring your own Claude API key). It reads your lab *as you*, with your permissions, and investigates new alerts. It can only *propose* changes: nothing runs until you click.
- **Security first.** The gateway signs every request to a backend with HMAC, enforces each route's role rules, keeps an audit log, and holds third-party credentials server-side, never in the browser.
- **Light on resources.** The gateway is a dependency-free Python service and the UI is Svelte. It runs in a 512 MB container.

## Planned install

```sh
# on your Proxmox host (planned, not available yet)
bash -c "$(curl -fsSL https://raw.githubusercontent.com/ebjerk01/labradoor/main/install.sh)"
```

The installer will create a small Debian container, and a first-run page will let you create your owner account. After that you install modules from the catalog. Labradoor and each module update from the UI when a new release is published, with one-click rollback. Each module asks for a URL plus an API key or login, tests the connection, and starts working, much like integrations in Home Assistant. You can optionally sign in through your own OIDC provider (Authentik, Keycloak, …).

## Roadmap

Progress is tracked as [issues](../../issues), one per step, grouped into milestones. ✅ = done.

**Phase 1: safe ground**
- [x] 1. Safe deploys: release directories, atomic switch, rollback, database backups and migrations, lock against concurrent deploys
- [x] 2. Operating the gateway itself: self-monitoring alerts, firewall and unit files in the repo, key inventory, backups

**Phase 2: the new frame**
- [x] 3. Module format v2: strict manifest schema, categories, dependencies, config schema with connection test, encrypted secrets per installation
- [x] 4. Module SDK: shared helpers, tables and status handling; modules talk only through declared interfaces
- [x] 5. Speed: server-side polling shared by all users, pushed to the browser; modules loaded on demand
- [x] 6. Shell and navigation: menu grouped by category, one consistent design, task-aware Ctrl-K, compact mobile bar
- [x] 7. Pilot: two modules (one simple, one complex) on the v2 format before the rest follow

**Phase 3: every module moved once**
- [ ] 8. Infrastructure modules: PBS, NPM, Cloudflare, UniFi, Guacamole, Graylog, Authentik, AD, Domains
- [ ] 9. Media modules: Jellyfin, Sonarr, Radarr, Prowlarr, Bazarr, qBittorrent, Seerr
- [ ] 10. Private modules for the original homelab's own apps (not published)
- [ ] 11. MikroTik switch module: ports, PoE power-cycle, VLANs
- [ ] 12. Remove the v1 compatibility layer

**Phase 4: install and distribution**
- [ ] 13. Core with no homelab-specific defaults; sensible empty states
- [ ] 14. Login: first-run owner setup, local accounts, optional OIDC
- [ ] 15. Connectors (helper services) managed by Labradoor, each isolated with its own credentials
- [ ] 16. Signed module catalog: install, update and remove from the UI; every module versioned and updated on its own
- [ ] 17. Proxmox installer, releases, and one-click update (and rollback) from the UI when a new release is published
- [ ] 18. The original homelab moves to the public build
- [ ] 19. Security review of the module system
- [ ] 20. Clean-install test on a fresh Proxmox, following only the docs

**Phase 5: public release**
- [ ] 21. Code published here: scrubbed of personal data, secret scanning, fresh history
- [ ] 22. Documentation: install, module setup, writing modules, security model
- [ ] 23. CI, signed releases, contribution guide
- [ ] 24. Demo mode with sample data (optional)
- [ ] 25. v0.1.0

## Feedback

Ideas, questions and "please support X" are welcome as [issues](../../issues).

## License

[Apache License 2.0](LICENSE)
