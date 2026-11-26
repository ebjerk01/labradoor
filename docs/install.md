# Installing Labradoor

Labradoor runs in its own small container on a Proxmox VE host. One script creates the container, installs the newest
signed release in it, and prints a one-time link that creates your owner account. This page covers:

- requirements;
- the one-line install and its options;
- the first run;
- updates and rollback;
- modules from catalogs;
- uninstalling;
- how releases are signed and checked;
- running behind a reverse proxy.

## Requirements

- **Proxmox VE 8 or 9.** Run the installer as `root` on the Proxmox host (the node's shell in the web UI works).
- **Resources.** The container gets 1 core, 512 MB of RAM and a 4 GB disk by default. That is enough for the gateway
  and a handful of modules. Add more if you enable many connectors.
- **Network.** The container needs an address (DHCP by default) and internet access while installing, to fetch the
  Debian template, a few packages and the release.
- **Storage.** A storage that can hold containers (for example `local-lvm` or `local-zfs`), and one that holds
  templates (`local` by default).

What the installer creates:

- an **unprivileged** Debian 13 container (no nesting, starts at boot, tagged `labradoor`);
- inside it: `python3`, `ca-certificates`, `nftables`, `curl` and `openssh-client` from Debian, and Labradoor itself.

Labradoor has no other dependencies. The optional AI connector builds its own Python environment the first time
Labradoor is installed (it needs internet access for that; without it, only that connector is unavailable).

The installer changes nothing outside the new container: no DNS records, no DHCP reservations, no firewall rules on
the host.

## Install

> **Before 0.1.0 there is no public release server.** The commands below use `https://RELEASE-SERVER/` for the
> address of a release server: until the first release ships, that is one you run yourself (the files
> `deploy/make-release.sh` writes, served over HTTPS), or skip the server and give the installer a tarball with
> `--release-file`. The installer has no built-in index yet, so pass `--index URL`, `--release-url URL` or
> `--release-file PATH`.

On the Proxmox host, as root:

```
bash -c "$(curl -fsSL https://RELEASE-SERVER/install.sh)" _ --index https://RELEASE-SERVER/index.json
```

Everything after the `_` goes to the installer as options (the `_` only fills a slot `bash -c` needs). The script asks
a few questions. Press Enter to keep a default. It then shows a summary and asks before it creates anything.

If you'd rather read the script first, download it and run it from disk; the options are the same:

```
curl -fsSLO https://RELEASE-SERVER/install.sh
bash install.sh --index https://RELEASE-SERVER/index.json
```

For an unattended install, pipe it to `bash` and pass `--yes` with the options you need:

```
curl -fsSL https://RELEASE-SERVER/install.sh | bash -s -- --yes --index https://RELEASE-SERVER/index.json \
  --ctid 210 --storage local-zfs --ip dhcp
```

Proxmox prints a warning while the container is created (`Systemd 257 detected. You may need to enable nesting.`,
then `Task finished with 1 warning(s)!`). That is expected and harmless: Labradoor runs without nesting on purpose.

### Options

| option | default | |
|---|---|---|
| `--ctid ID` | the next free id | container id |
| `--hostname NAME` | `labradoor` | |
| `--storage STORAGE` | `local-lvm`, `local-zfs`, or the first storage that holds containers | root disk |
| `--disk GB` | `4` | root disk size |
| `--bridge BRIDGE` | `vmbr0` | |
| `--vlan TAG` | none | VLAN tag on the bridge |
| `--ip dhcp\|CIDR` | `dhcp` | for example `192.168.1.50/24`; a static address also needs `--gateway` |
| `--gateway IP` | | |
| `--cores N` | `1` | |
| `--memory MB` | `512` | |
| `--pool POOL` | none | Proxmox resource pool |
| `--template-storage S` | `local` | where the Debian 13 template is kept (downloaded once with `pveam` if missing) |
| `--ssh-key FILE` | none | public keys for `root` in the container; without it, use `pct enter ID` |
| `--index URL` | `$LAB_RELEASE_INDEX` (no built-in default before 0.1.0) | the signed release index |
| `--version V` | the newest | install this version from the index |
| `--release-url URL` | | install this tarball (`URL.sig` must be next to it) instead of using an index |
| `--release-file PATH` | | install a local tarball (`PATH.sig` next to it), for offline installs |
| `--release-pub FILE` | the key built into the script | check signatures with another public key (for forks) |
| `--public-url URL` | `http://<container ip>:8100` | the address people open (see [reverse proxy](#behind-a-reverse-proxy)) |
| `--allow-http` | off | allow plain `http://` to a LAN address. **For testing a local release server only.** The installed copy may then also update from such a server. |
| `--trust-labradoor-modules` | asked on a fresh install; no with `--yes` | trust modules published by the Labradoor project (the key that signs its releases), see [modules from catalogs](#modules-from-catalogs) |
| `--reinstall` | | install the release again into an existing Labradoor container |
| `--uninstall` | | with `--ctid ID`: stop and destroy a container this installer created (see [uninstall](#uninstall)) |
| `--yes`, `-y` | | no questions; defaults and options only |
| `--help` | | the options, as the script knows them |

Running the script again is safe. Without `--ctid`, it looks for a container with the `labradoor` tag on this node:

- **one** found: it uses that container (pressing Enter at "container id" keeps it), leaves the installation alone and
  applies only what you pass: `--public-url`, `--index` or `--allow-http`, saying what it set;
- **several** found: it lists them and asks which one (with `--yes` it stops and asks for `--ctid`);
- **none**: a new container.

A second installation on the same node needs an explicit new `--ctid`. The script never touches a container that it
did not create.

If something fails after the container was created, the script leaves the container in place so you can look inside
(`pct enter ID`, then `journalctl -u lab`). Run the script again to continue, or remove the container with
`--uninstall`.

## First run

When the install finishes, the script prints the address and a **one-time setup link**:

```
==> Labradoor 0.1.0 is running in container 210
  open:          http://192.168.1.50:8100
  FIRST RUN — open this link within 1 hour to create the owner account (it works once):

    http://192.168.1.50:8100/setup#4mYk…
```

Open the link and create the owner account (a password of at least 12 characters, and two-factor login, which is on by
default). The token is the part after `#`: the page takes it out of the address bar, and reloading the same tab keeps
it, but a copy of the address without it won't work. Only the newest link works, once, for an hour. For a new one,
on the Proxmox host:

```
pct exec 210 -- lab-admin setup-link
```

The link is also kept in `/etc/lab/setup-link` (root only) inside the container; it is useless once the owner exists,
and the next update or `lab-admin setup-link` removes it.

[Login](login.md) explains accounts, two-factor login and single sign-on.

After the first login the **Overview** is empty ("no machines yet"): that is expected until a module is set up. Every
bundled module starts switched on but **needs setup**. Open **Settings → `~/modules`**, expand a module and fill in its
**connection** (URL, API key, and so on; the form tests it before saving), or switch it off if you don't use that
service.

With DHCP (the default), the address the installer printed can change. Reserve it in your router, or install with a
static `--ip`. If it does change, run the installer again with `--public-url http://NEW-ADDRESS:8100`.

**Commands inside the container.** `lab-admin` runs as root in the container. From the Proxmox host, either open a
shell in it (`pct enter 210`) or run one command: `pct exec 210 -- lab-admin …`.

## Updates

Updates are off until a release index is set. The installer writes the index it installed from to `/etc/lab/lab.env`
(`LAB_RELEASE_INDEX`): that is the default. An owner can point the installation at another index in
**Settings → `~/updates`**. Clearing the field there goes back to the default. Whatever index you use, its releases must be
signed with the key in `/etc/lab/release.pub`.

In **Settings → `~/updates`**:

1. **check for updates** fetches the index, checks its signature, and lists newer releases with their notes.
2. **update to X** downloads the release, checks it, and installs it. The page follows the progress and reloads when
   the new version is live. The gateway restarts during the update, so the page is unavailable for a few seconds.

From the command line in the container (as root; `pct enter ID`, or `pct exec ID -- lab-admin …` from the host):

```
lab-admin update --check     # what is available
lab-admin update             # install the newest allowed release (asks first; --yes to skip)
lab-admin update 0.2.0       # install that version
lab-admin update --status    # installed version, releases on disk, the last update job
```

Every install works the same way, whether it comes from the UI, `lab-admin` or a new install:

- the databases are backed up first (`/var/lib/lab-backups/<release>/`, root only; the last 10 are kept);
- database migrations run when the new version starts;
- the new release goes to `/opt/lab-releases/<time>-<commit>`, and `/opt/lab` switches to it in one step (the last 5
  releases are kept);
- if the install fails before the switch, nothing changes;
- if the new version does not come up, Labradoor goes back to the previous release and restores the database backup
  automatically.

Some updates are refused:

- a release that is **not newer** than the installed one (to go back, use rollback);
- a release whose `min_upgrade_from` is newer than the installed version. Install the release the index names first.

Every step is written to the audit log (**Log**, or `lab-admin audit`): `update-check`, `update-stage`,
`update-apply`, `update-rollback`, and the result.

## Rollback

**Settings → `~/updates` → roll back** switches back to an earlier release that is still on disk (by default, the one
before the live release). It switches the code only. Restoring the database as well needs root in the container: the
gateway can't ask for it, so a compromised gateway can't make root put files back. From the command line:

```
lab-admin rollback --list             # releases on disk (* = live)
lab-admin rollback                    # the previous release
lab-admin rollback RELEASE --with-db  # and restore the database from before the live release was installed
```

When a release changed the database schema, an older release can't open the newer database. Roll back **with the
database** in that case. This brings back the database as it was just before the live release was installed, so
changes made since then are lost. The databases as they were just before the rollback are kept in
`/var/lib/lab-backups/rollback-<time>-from-<release>/`. If you roll back without the database and the older release
does not start, Labradoor switches forward again by itself and tells you why.

## Modules from catalogs

Modules that do not ship with the core come from signed catalogs: **Settings → `~/catalogs`** lists catalogs, installs,
updates, rolls back and removes modules, each on its own. Only catalogs and packages signed by a publisher that root
trusts inside the Labradoor container can be installed (`lab-admin publisher add FILE.pub`), because a module's
screens run in your browser with your rights. There is no public Labradoor module catalog yet; until there is,
trusting the Labradoor publisher changes nothing you can see. [catalog.md](catalog.md) explains the trust model, the install dialog and publishing.

The installer sets up the root helper for this (`lab-module-helper`, a socket only the gateway's group can use),
`/var/lib/lab-modules` for installed modules (root's, read-only for the gateway), and an empty `/etc/lab/publishers.d`.
No publisher is trusted by default, not even the Labradoor project's own key. The installer asks on a fresh install
(`--trust-labradoor-modules` answers yes); later, as root in the container:
`lab-admin publisher add /etc/lab/release.pub --name labradoor`.

## Uninstall

On the Proxmox host, with the same installer (from the release server, or the copy you downloaded):

```
bash -c "$(curl -fsSL https://RELEASE-SERVER/install.sh)" _ --uninstall --ctid 210
bash install.sh --uninstall --ctid 210        # a downloaded copy
```

The script refuses containers that it did not create. It asks you to type the container id (`--yes` skips that),
then stops the container and destroys it together with its disks (`pct destroy --purge`). The Debian template it
downloaded stays in the template storage for a later install (remove it under the storage's CT Templates if you like). Everything Labradoor stored is in the container, so this
removes it all: accounts, settings and module secrets. If you want a copy, back up the container with Proxmox first.

## How releases are signed and checked

A release is one tarball, `labradoor-<version>.tar.gz`. It holds the gateway, the SDK, connectors, modules, the built
UI and the deploy scripts. It also holds `VERSION`, `COMMIT`, and a `MANIFEST` that lists the SHA-256 of every file.
Releases are signed with **OpenSSH signatures**. These need no extra software on Debian or Proxmox:

```
ssh-keygen -Y sign   -f release-key -n labradoor-release labradoor-0.1.0.tar.gz           # the maintainer
ssh-keygen -Y verify -f allowed_signers -I labradoor-release -n labradoor-release \
           -s labradoor-0.1.0.tar.gz.sig < labradoor-0.1.0.tar.gz                         # every install
```

The release index (`index.json`) is signed the same way (`index.json.sig`). Each entry lists the version, date,
SHA-256, tarball URL, signature URL, `min_upgrade_from` and notes.

The public key is pinned in three places: in `install.sh`, in each release (`deploy/release.pub`), and on each
installation (`/etc/lab/release.pub`). Before anything runs, Labradoor checks:

1. the index signature;
2. that the tarball's SHA-256 matches the signed index;
3. the tarball's own signature;
4. the unpacked files: each one must be in the `MANIFEST` with the right SHA-256, with none missing and none extra.
   The tarball may hold no links and no paths outside its own directory, and `VERSION` must name the expected release.

The installer checks all of this again in the container before it installs anything, and the update helper checks the
staged copy once more right before installing it.

Only `https://` URLs are accepted, including redirects. The one exception is testing: plain `http://` to a LAN address
works only when the container has `LAB_UPDATE_ALLOW_HTTP=1` in `/etc/lab/update.env` (the installer's
`--allow-http` writes it).

The gateway itself runs as an unprivileged user and cannot install anything. It asks a small root helper
(`lab-update-helper`, a socket that only the gateway's group can use). The helper accepts only fixed commands: check,
stage, apply, rollback and status. An install runs as its own systemd unit (`lab-update-job`), so it keeps going while
the gateway restarts. Its log is in `/var/lib/lab-update/logs/`.

### Building releases (maintainers)

```
deploy/make-release.sh --out release-out --notes "what changed" [--min-upgrade-from 0.1.0]
```

This runs every test suite, builds the UI, writes the tree and its `MANIFEST`, packs a reproducible tarball, signs it,
and adds the entry to `release-out/index.json`, which it signs again. Upload the contents of `release-out/` (and
`install.sh`) to the release server. `--exclude-modules a,b` leaves modules out of the release (they then come from a
module catalog), `--exclude-private` every module of kind `private` (your own apps: publish those as a private catalog,
[catalog.md](catalog.md#publishing-from-a-repository-deploypublishsh)), and `--pub FILE` checks the signature against another public key (a fork, a test key). Entries use URLs relative to the index, so the files only need to sit next to
each other. The signing key is read from `~/.config/labradoor/release-signing-key` (or `--key`, or
`LAB_RELEASE_KEY`). Give it a passphrase (`ssh-keygen -p -f KEY`), keep a copy in a password manager, and never put
it in the repository. `ssh-keygen` asks for the passphrase on the terminal; for scripted releases set
`LAB_RELEASE_KEY_PASS_CMD` to a command that prints it (for example a password-manager CLI), which reaches `ssh-keygen`
through `SSH_ASKPASS` rather than a command line.

## Behind a reverse proxy

Labradoor listens on port 8100 over plain HTTP. For anything beyond a quick test, put a reverse proxy with HTTPS in
front of it (Nginx Proxy Manager, Caddy, Traefik, nginx, and so on):

1. Point the proxy at `http://<container ip>:8100`. WebSockets aren't needed. Do turn off response buffering for
   `/api/events`, which is a server-sent event stream (most proxies handle this by default).
2. Tell Labradoor its public address and which proxy it may trust. Re-run the installer with
   `--public-url https://labradoor.example.com`, or edit `/etc/lab/lab.env` in the container:

   ```
   LAB_PUBLIC_URL=https://labradoor.example.com
   LAB_COOKIE_SECURE=1
   LAB_TRUST_PROXY=1
   LAB_TRUSTED_PROXIES=192.168.1.10
   ```

   Put your proxy's address in `LAB_TRUSTED_PROXIES`. Keep comments on lines of their own: systemd reads this file
   too, and it does not strip a comment at the end of a line.

   A proxy **in the same container** (Caddy or nginx on `127.0.0.1`) also needs a shared secret: connectors run there
   too and reach port 8100 from loopback, so loopback alone proves nothing. Set `LAB_PROXY_SECRET=<a long random
   string>` and have the proxy send it as the header `X-Lab-Proxy-Secret`. With a secret set, every trusted proxy
   must send it.

   Then run `systemctl restart lab`. Only the addresses in `LAB_TRUSTED_PROXIES` may set `X-Forwarded-For` or
   `X-Real-IP`. Logins and the audit log use the real client address only when it comes from a trusted proxy.
3. Narrow the container's firewall to the proxy. By default `/etc/nftables.d-lab.nft` allows port 8100 from private
   networks only. Edit it to allow just the proxy (and your monitoring server), then run
   `systemctl restart lab-firewall`.
4. If you use single sign-on, the redirect URI to register with your identity provider is
   `https://labradoor.example.com/auth/callback`. Settings → `~/login` shows it.
