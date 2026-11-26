# Module catalogs

Labradoor ships with a set of **bundled** modules. More modules come from **catalogs**: signed lists of module
packages that the owner can install, update, roll back and remove in **Settings → `~/catalogs`**, each one on its own,
without a core update. This page covers:

- how the pieces fit together;
- the trust model (read this before you add a publisher);
- adding a publisher and a catalog;
- what the install dialog shows;
- updates, rollback and removal;
- private catalogs for your own modules;
- publishing modules (for module authors);
- the package format and the module ABI;
- the command line.

## How it fits together

| piece | what it is |
|---|---|
| **package** | one module version: `<id>-<version>.tar.gz` plus its signature `<id>-<version>.tar.gz.sig` |
| **catalog** | `catalog.json` plus `catalog.json.sig`: the modules a publisher offers, each with its versions, the sha256 of each package and a summary of what it asks for |
| **publisher** | whoever signs a catalog and its packages, identified by an OpenSSH public key |
| **trusted publishers** | the public keys in `/etc/lab/publishers.d/*.pub` inside the Labradoor container. Only root can add one |
| **module helper** | `lab-module-helper`, a small root service that checks, downloads, verifies and installs packages. The gateway asks it through a socket that only the gateway's group can use, and it accepts a fixed set of commands |
| **installed modules** | `/var/lib/lab-modules/<id>/<version>/`, owned by root and read-only for everyone else. Labradoor keeps the live version and the one before it |

The gateway itself runs as an unprivileged user and never writes module code. It stores the list of catalog URLs and
each module's settings, and it asks the helper for everything else.

## Trust model

**A module's screens run in your browser, with your rights.** A module's UI is JavaScript that the page loads into
the same origin as the rest of Labradoor. While you, the owner, look at one of its views, that code can do anything
you can do: read every module, change settings, approve requests, add users. The gateway checks every backend call
against the module's manifest, but it cannot tell your clicks apart from the module's code running in your tab.

So Labradoor installs **only signed modules from publishers that root on the host trusts**:

- A catalog and every package in it must be signed with a key in `/etc/lab/publishers.d/`. Anything else is refused,
  including a correctly signed catalog from an unknown key.
- Packages must be signed by the same publisher as the catalog that lists them. An update must come from the
  publisher of the installed version.
- Trusting a publisher is done **on the command line as root** (`lab-admin publisher add`), never from the web UI. A
  stolen owner session or a compromised gateway can't add a publisher.
- Nothing is trusted by default, not even the Labradoor project's own key: modules are a separate decision from
  core updates. The installer asks on a fresh install (`--trust-labradoor-modules`), or as root:
  `lab-admin publisher add /etc/lab/release.pub --name labradoor`.
- A package can never replace a bundled module unless it is newer **and** signed with the core's release key (which
  must also be a trusted publisher).
- **Privileged modules need a second yes from root.** A module whose manifest has `delegate: true` (its connector
  reads every module as the person using it, like the AI assistant) or `connector.uses_credentials_of` (its connector
  gets other modules' third-party API credentials and calls their own backends as the person using it, like the
  wizard) installs only when it is signed with the core's release key, or when root allowed that publisher for
  privileged modules: `lab-admin publisher add FILE.pub --name acme --allow-privileged`, or later
  `lab-admin publisher allow-privileged acme` (`revoke-privileged` takes it back). The decision is a root-owned file,
  `/etc/lab/publishers.d/<name>.privileged`, and the root helper checks it, never the gateway. Revoking it keeps
  installed modules but refuses their updates and rollbacks.

Treat adding a publisher like installing software from them on your server. Running module UIs in a sandboxed frame
on a separate origin, so that only the module's own routes are reachable, is **future work**. Until then, signatures
are the boundary.

What the checks do guarantee:

1. the catalog's signature (`ssh-keygen -Y verify`, namespace `labradoor-module`);
2. the package's sha256 matches the signed catalog;
3. the package's own signature, by the catalog's publisher;
4. the unpacked files: only plain files and directories inside `<id>-<version>/`, no links, no special files, no
   `..`, only the allowed layout, and every file listed in its `MANIFEST` with the right sha256, none missing and
   none extra;
5. `package.json` and `manifest.json` agree (id, version, kind, connector), and the manifest passes the same checks as
   a bundled module's (unknown keys are errors, every write route says who may call it);
6. `min_core` is met, and the UI was built for this core's Svelte version and imports only what this core exports
   (see [the module ABI](#the-module-abi));
7. a connector port that no other module uses;
8. a privileged module (`delegate`, `uses_credentials_of`) comes from the core's release key or a publisher root
   allowed for privileged modules.

The helper checks all of this again just before it installs a staged package, and again before a rollback.

Plain `http://` catalog and package URLs are refused. The one exception is testing: plain `http://` to a LAN address
works when `/etc/lab/update.env` has `LAB_UPDATE_ALLOW_HTTP=1` (the same switch as for core updates; the installer's
`--allow-http` sets it).

## Adding a publisher and a catalog

1. Get the publisher's public key (`publisher.pub`) **and its fingerprint from a second channel**, for example their
   website and their repository's README. The fingerprint looks like `SHA256:8G+HAKv…`.
2. Inside the Labradoor container, as root (`pct enter ID` on the Proxmox host, or prefix each command with
   `pct exec ID --`):

   ```
   lab-admin publisher add publisher.pub --name acme
   ```

   It prints the fingerprint and asks before it trusts the key. `lab-admin publisher list` shows every trusted key, and
   `lab-admin publisher remove acme` removes one. Installed modules stay after you remove a publisher, but they can't
   be updated from that publisher any more.
3. In **Settings → `~/catalogs`**, add the catalog URL (`https://…/catalog.json`). Labradoor checks its
   signature right away. If the publisher is not trusted yet, the error shows the fingerprint that signed it, so you
   can compare it before you add the key.

## The install dialog

**check catalogs** fetches every catalog and lists its modules with their category, description and newest version.
It also says why a version can't be installed here (the core is too old, it was built for another Svelte, the core
ships that module already, it is privileged and root has not allowed its publisher for that).

**install** downloads and verifies the package first, then shows what the module asks for **before** anything is
installed:

| | |
|---|---|
| publisher | name and key fingerprint |
| kind | `community` or `private`, the category, the minimum core version, and whether it replaces a bundled module |
| who may use it | the roles in its manifest, and the guest groups |
| talks to | a connector on this host (port, running as its own unix user), your own backend (signed per user), or a third-party API with one shared credential; plus each address you will be asked for (the URL fields of its connection) |
| secrets it stores | the secret fields of its connection (stored encrypted, never sent to a browser) |
| reads other modules | its `requires` (optional ones are marked) |
| uses credentials of | the modules its connector uses (`uses_credentials_of`): it receives their third-party API credentials, and calls their own backends through the gateway as the person using it (never with their keys) |
| delegate | a connector that may read every module as the person using it (an assistant) |
| PRIVILEGED | shown in a box when either of the two above applies, with why it is allowed here (the core's release key, or root allowed the publisher) |
| routes | every backend route its UI may call, who may call it, which are owner-only, which return secrets |

A freshly installed module is **not set up** until you fill in its connection under Settings → `~/modules` → (expand the module) → connection.
Until then nobody can use it.

## Updates, rollback, removal

- **Updates.** When a checked catalog has a newer version of an installed module, the module's row shows
  **update to X**. The same dialog appears (what the new version asks for). The previous version stays on disk.
- **Rollback.** **roll back to X** switches back to the version before. Its files are verified against their
  `MANIFEST` again first.
- **Remove.** By default a module's connection and settings are kept, so a reinstall picks them up again. Untick
  *keep its connection and settings* to remove those too. That also removes its connector's key, state and unix user,
  unless a bundled module with the same id still uses them.
- A module's connector, if it has one, restarts on the new code after an update or rollback.

Each step is written to the audit log (**Log**, or `lab-admin audit`): `module-catalog-add`, `module-check`,
`module-stage`, `module-install`, `module-update`, `module-rollback` and `module-remove`, each with its result.

After a **core** update, an installed module whose UI was built for another Svelte version is not loaded (Settings
shows why) until its publisher ships a rebuilt package. If a bundled module with the same id exists, that one is used
in the meantime.

## Private catalogs

Modules for your own applications (`"kind": "private"`) can come from a catalog of your own, signed with your own key,
next to the public catalogs:

1. Make a signing key for your modules on the machine where you build them. Give it a passphrase or keep it on a
   hardware key, and don't put it on the Labradoor container:

   ```
   ssh-keygen -t ed25519 -C my-modules -f ~/.config/labradoor/module-signing-key
   ```

2. Build each module into one output folder (see [Publishing modules](#publishing-modules)) and serve that folder
   over HTTPS where your Labradoor host can reach it: a static site on your LAN, an object store, or a private
   repository's release assets.
3. Inside the Labradoor container, as root: `lab-admin publisher add module-signing-key.pub --name mine`.
4. In Settings → `~/catalogs`, add `https://…/catalog.json`.

Each catalog is checked against its own publisher. Your private modules can only be updated by your key, and a public
publisher can never ship an update for them.

### Publishing from a repository: `deploy/publish.sh`

When your private modules live in a Labradoor checkout next to the core (`modules/<id>` with `"kind": "private"`, and
`connectors/<id>`), `deploy/publish.sh` does the whole round trip:

```
deploy/publish.sh core    [--install HOST]   # the core WITHOUT the private modules → DIST/core/index.json
deploy/publish.sh modules [ID …] [--install HOST]   # changed private modules → DIST/modules/catalog.json
deploy/publish.sh status                      # what is published, which modules changed since
```

- `core` is `make-release.sh --exclude-private`: the same build anyone else gets, so your installation runs the public
  core plus your catalog. A build of a pre-release `VERSION` (`0.1.0-dev`) is stamped with the time
  (`0.1.0-dev.20261115120000`), so each one is newer than the last.
- `modules` builds every private module whose files changed since its newest published package (`--all`: every one,
  e.g. after the core moved to a new Svelte minor). The version is the manifest's, or the last published one's patch
  plus one when the manifest was not raised.
- `--install HOST` then installs it over ssh as root (`lab-admin update V`, `lab-admin package check` + `install` or
  `update`).
- Settings live in `~/.config/labradoor/publish.env` (or the environment): `LAB_DIST_DIR` (a local copy),
  `LAB_DIST_TARGET` (an rsync target that serves it), `LAB_DIST_URL` (its HTTPS URL), `LAB_CATALOG_NAME`, and the
  key settings `LAB_RELEASE_KEY_PASS_CMD` / `LAB_MODULE_KEY_PASS_CMD`. The target is fetched first and nothing is
  deleted there; packages go up before the signed index that names them.

`deploy/deploy.sh` (a development deploy straight from the repository) leaves out every module the host has installed
from a catalog, so a bundled copy never takes the place of your package.

## Publishing modules

A module is a folder with `manifest.json` and `ui/` ([modules.md](modules.md), [sdk.md](sdk.md)), and optionally a
connector ([connectors/README.md](../connectors/README.md)). From a Labradoor checkout:

```
deploy/make-module.sh ID [--out DIR] [--version V] [--key FILE] [--src DIR] [--connector DIR]
                         [--notes TEXT] [--catalog-name NAME] [--base-url URL]
```

It validates the manifest exactly as installations do, builds the UI as **one** ES module, packs the package
reproducibly, signs it (`ssh-keygen -Y sign -n labradoor-module`), verifies the result the way an installation will,
and adds the version to `DIR/catalog.json`, which it signs again. Upload the contents of `DIR` as they are. Entries use
URLs relative to the catalog unless you pass `--base-url`.

- `--src DIR` builds a module kept outside the Labradoor repository (a folder with `manifest.json` and `ui/`), and
  `--connector DIR` takes its connector from elsewhere.
- The key comes from `--key`, `$LAB_MODULE_KEY` or `~/.config/labradoor/module-signing-key`. It never goes into a
  repository. With a passphrase, `ssh-keygen` asks on the terminal, or `LAB_MODULE_KEY_PASS_CMD` names a command that
  prints it (handed over through `SSH_ASKPASS`).
- Packages should match a commit. The script refuses uncommitted module files unless you pass `--allow-dirty` (for
  tests).
- Rebuild your packages when the core moves to a new Svelte minor version (see below), and raise `min_core` when your
  module needs something new from the SDK.

## The package format

```
<id>-<version>/
  package.json    {"format": 1, "id", "name", "version", "kind", "min_core", "connector": true|false,
                   "abi": {"svelte": "5.57.3", "imports": {"svelte/internal/client": [...], "$lab/sdk.js": [...]}},
                   "built", "commit"}
  manifest.json   the module's manifest (same id and version)
  ui/ui.js        the UI: one ES module
  connector/      optional: its connector (stdlib Python, connector.py)
  README.md       optional
  LICENSE         optional
  MANIFEST        sha256 of every other file
```

The catalog:

```json
{"format": 1, "product": "labradoor-modules", "name": "Acme modules", "generated": "…",
 "modules": [{"id": "acme-dns", "name": "…", "kind": "community", "category": "network", "description": "…",
              "icon": "globe",
              "versions": [{"version": "1.2.0", "date": "…", "sha256": "…", "url": "acme-dns-1.2.0.tar.gz",
                            "sig": "acme-dns-1.2.0.tar.gz.sig", "min_core": "0.2.0", "svelte": "5.57.3",
                            "notes": "…", "permissions": {…}}]}]}
```

`permissions` is the same summary the install dialog shows. The dialog itself is built from the downloaded package,
not from the catalog.

### Connectors in packages

A package's connector runs exactly like a bundled one: as its own unix user `lab-c-<id>`, configured by the gateway,
started once the module is set up. The helper points the connector's service at the installed package with a systemd
drop-in. Connectors in packages may use the Python standard library and the Labradoor SDK only (no extra
dependencies), and their port must be free.

## The module ABI

A module's UI imports `svelte` and the shared Labradoor parts (`$lab/sdk.js`, `$lab/Table.svelte` …). In a package,
these stay imports. The page resolves them through an **import map** to the shell's own copies, so every module shares
one Svelte runtime and one SDK.

- The shell's build writes `ui/dist/abi.json`: the Svelte version and every name each specifier exports. Each
  package records the Svelte version it was compiled with, and every name it imports.
- A package is installable when it was built with the **same Svelte major.minor** as the shell, and the shell exports
  every name it imports. The page's Content-Security-Policy allows exactly this one inline import map, by hash.
- `$lab/lab.svelte.js`, the shell's own state, is not part of the ABI. Modules reach the shell through `ctx` only.

### The svelte rule

**A module package runs only on a core whose Svelte has the same major.minor as the Svelte it was compiled with**
(5.57.x with 5.57.x; not 5.56 on 5.57, not 5.58 on 5.57). Patch versions don't matter. Svelte's compiled output
calls internal runtime functions whose names and signatures can change between minor versions, so a looser rule
would let a package load and then fail in the browser. The catalog listing, the install dialog and the helper all
refuse a mismatch with the same message: `built for svelte X, this core runs svelte Y: a module needs the same
major.minor`.

For a **publisher**, a core release that moves Svelte to a new minor means rebuilding:

1. check out the Labradoor core version your users run (its `package.json` pins `svelte`), `npm ci`;
2. `deploy/make-module.sh ID --version <next patch>` for each module (this repository: `deploy/publish.sh modules
   --all`), which compiles the UI against that Svelte and records it in the package's `abi`;
3. publish the new catalog. Keep the older package versions listed: installations still on the older core keep
   installing those.

For an **owner**: after a core update with a Svelte minor bump, installed packages built for the old minor stop
loading (Settings shows why) until their publisher ships rebuilt versions; `lab-admin rollback` brings the old core
back meanwhile.

## Command line

Inside the Labradoor container, as root (`pct enter ID`, or `pct exec ID -- lab-admin …` from the Proxmox host):

```
lab-admin publisher list | add FILE.pub [--name N] [--allow-privileged] | remove N
lab-admin publisher allow-privileged N | revoke-privileged N   # modules with delegate / uses_credentials_of
lab-admin package                                   # installed modules, publishers, checked catalogs
lab-admin package check URL                         # verify a catalog and list what it offers
lab-admin package install ID VERSION [--catalog URL] [--yes]
lab-admin package update ID VERSION [--yes]
lab-admin package rollback ID
lab-admin package remove ID [--drop-config]
lab-admin package catalog-add URL                   # add to the list Settings → `~/catalogs` checks (verified first)
lab-admin package catalog-remove URL
```

`lab-admin package install` shows the same summary as the install dialog before it asks. The gateway notices a change
made from the command line on the next registry load (open pages reload it every minute). Changes made in Settings
take effect at once.

### Building a slim core

`deploy/make-release.sh --exclude-modules a,b` leaves those modules out of a release, both their files and their UI,
for a core whose other modules come from a catalog. `--exclude-private` leaves out every module of kind `private`
(`deploy/private-modules.sh` lists them).
