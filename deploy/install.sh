#!/bin/sh
# Run on the lab CT from the unpacked release (deploy/deploy.sh does this, under /run/lab-deploy.lock).
# Each deploy is a new release in /opt/lab-releases/<time>-<commit>; /opt/lab is a symlink switched atomically, the
# last 5 releases are kept, the databases are backed up first (/var/lib/lab-backups/<release>/, root 0700), and
# `lab-admin rollback [release] [--with-db]` goes back.
# Root never copies, chmods, chowns or deletes by name inside /var/lib/lab or /var/lib/lab-connectors/<id>: those
# belong to the gateway's / a connector's user, who could plant symlinks there (security review 2026-11-15, H2).
# deploy/lab-dbcopy does the database copies AS the owner; only root's own tree is touched as root.
set -eu
SRC="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$SRC/ui/dist/index.html" ] || { echo "ui/dist missing: build first (npm run build)"; exit 1; }
VER="$(cat "$SRC/VERSION" 2>/dev/null || echo unknown)"           # semver (the repo's VERSION file)
COMMIT="$(cat "$SRC/COMMIT" 2>/dev/null || echo "$VER")"           # git commit (before step 17 VERSION held it)
# never replace a live release with code that does not contain it (an older or diverged checkout)
LIVE="$(cat /opt/lab/COMMIT 2>/dev/null || cat /opt/lab/VERSION 2>/dev/null || true)"
if [ -n "$LIVE" ] && [ "$LIVE" != "$COMMIT" ] && [ "${LAB_DEPLOY_ANY:-}" != 1 ] && ! grep -qx "$LIVE" "$SRC/ANCESTRY" 2>/dev/null; then
  echo "REFUSED: live release $LIVE is not part of $COMMIT's history (someone deployed newer code?). Pull and retry."
  exit 1
fi
REL_ROOT=/opt/lab-releases
REL="$(date +%Y%m%d-%H%M%S)-$(echo "$COMMIT" | cut -c1-7)"
install -d -m 755 "$REL_ROOT"
id lab >/dev/null 2>&1 || useradd --system --home /var/lib/lab --shell /usr/sbin/nologin lab
install -d -o root -g lab -m 750 /etc/lab /etc/lab/keys
install -d -o lab -g lab -m 750 /var/lib/lab
# the database files stay private to the gateway: done AS lab (a planted link only reaches lab's own files)
runuser -u lab -- find -P /var/lib/lab -maxdepth 1 -name 'lab.sqlite3*' -type f -exec chmod 600 {} + 2>/dev/null || true
NEW="$REL_ROOT/$REL"
rm -rf "$NEW"; mkdir -p "$NEW/ui"
cp -r "$SRC/gateway" "$SRC/sdk" "$SRC/connectors" "$NEW/"
mkdir -p "$NEW/modules"
for m in "$SRC"/modules/*/; do n=$(basename "$m"); mkdir -p "$NEW/modules/$n"; cp -r "$m"* "$NEW/modules/$n/"; done
cp -r "$SRC/ui/dist" "$NEW/ui/dist"
echo "$VER" > "$NEW/VERSION"; echo "$COMMIT" > "$NEW/COMMIT"
install -m 755 "$SRC/deploy/lab-rollback" /usr/local/sbin/lab-rollback
install -m 755 "$SRC/deploy/lab-dbcopy" /usr/local/sbin/lab-dbcopy
find "$NEW" -name __pycache__ -prune -exec rm -rf {} +
chown -R root:root "$NEW"; chmod -R go-w "$NEW"
# the pre-release layout (a real /opt/lab directory + /opt/lab.old) becomes a release once
PREV="$(readlink -f /opt/lab 2>/dev/null || true)"; [ -e /opt/lab ] || PREV=""
# the oldest release; the name sorts first
if [ -d /opt/lab ] && [ ! -L /opt/lab ]; then PREV="$REL_ROOT/00000000-000000-legacy"; mv /opt/lab "$PREV"; fi
rm -rf /opt/lab.old
# databases first: a consistent copy of each (sqlite backup API, safe while the gateway runs), read AS its owner,
# into root's own tree. Backups made before 2026-11-15 (/var/lib/lab/backups, inside lab's directory) move there.
BK_ROOT=/var/lib/lab-backups
install -d -o root -g root -m 700 "$BK_ROOT"
python3 -I /usr/local/sbin/lab-dbcopy adopt /var/lib/lab/backups "$BK_ROOT" || echo "WARNING: old backups in /var/lib/lab/backups not adopted"
BK="$BK_ROOT/$REL"; [ ! -e "$BK" ] || rm -rf --one-file-system "$BK"; install -d -o root -g root -m 700 "$BK"
# owner:database:required — the legacy ai path (before step 15) only when the new one has none
for spec in lab:/var/lib/lab/lab.sqlite3:1 lab-c-ai:/var/lib/lab-connectors/ai/ai.sqlite3:1 lab:/var/lib/lab/ai/ai.sqlite3:0; do
  own="${spec%%:*}"; db="${spec#*:}"; need="${db##*:}"; db="${db%:*}"; dst="$BK/$(basename "$db")"
  id "$own" >/dev/null 2>&1 || continue
  [ ! -e "$dst" ] || continue
  rc=0; python3 -I /usr/local/sbin/lab-dbcopy backup --as "$own" "$db" "$dst" || rc=$?
  if [ "$rc" != 0 ] && [ "$rc" != 3 ]; then
    if [ "$need" = 1 ]; then echo "REFUSED: no backup of $db — nothing installed"; exit 1; fi
    echo "WARNING: no backup of $db"
  fi
done
python3 -I /usr/local/sbin/lab-dbcopy prune "$BK_ROOT"   # keep 10 (+ 5 rollback snapshots)
# switch atomically, then keep the 5 newest releases (and whatever is live)
ln -sfn "$NEW" /opt/lab.tmp && mv -Tf /opt/lab.tmp /opt/lab
for r in $(ls -1d "$REL_ROOT"/*/ | sed 's:/$::' | sort | head -n -5); do [ "$r" = "$NEW" ] || [ "$r" = "$PREV" ] || rm -rf "$r"; done
[ -f /etc/lab/lab.env ] || { install -o root -g lab -m 640 "$SRC/deploy/lab.env.example" /etc/lab/lab.env; echo "EDIT /etc/lab/lab.env"; }
[ -f /etc/lab/topology.json ] || { echo '{"zones": [], "nodes": [], "links": []}' > /etc/lab/topology.json; chown root:lab /etc/lab/topology.json; chmod 640 /etc/lab/topology.json; }
# the map's external part (deploy/topology.json) is per installation: only replaced when lab.env says so
[ -z "${LAB_TOPOLOGY_UPDATE:-}" ] && LAB_TOPOLOGY_UPDATE=$(sed -n 's/^LAB_TOPOLOGY_UPDATE=//p' /etc/lab/lab.env 2>/dev/null)
if [ "${LAB_TOPOLOGY_UPDATE:-0}" = 1 ]; then install -o root -g lab -m 640 "$SRC/deploy/topology.json" /etc/lab/topology.json; fi
cat > /usr/local/bin/lab-admin <<'W'
#!/bin/sh
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin   # pct exec from the Proxmox host has a short PATH
[ "${1:-}" = rollback ] && { shift; exec /usr/local/sbin/lab-rollback "$@"; }
set -a; . /etc/lab/lab.env; set +a
exec /usr/bin/python3 /opt/lab/gateway/lab_admin.py --modules /opt/lab/modules "$@"
W
chmod 755 /usr/local/bin/lab-admin
ln -sfn /usr/local/bin/lab-admin /usr/bin/lab-admin   # so `pct exec ID -- lab-admin …` works from the Proxmox host
install -m 644 "$SRC/deploy/lab.service" /etc/systemd/system/lab.service
install -m 644 "$SRC/deploy/lab-connector@.service" /etc/systemd/system/lab-connector@.service
# connectors: the root helper the gateway asks to create a connector's user + key and start/stop it (fixed commands)
install -m 755 "$SRC/deploy/lab-connector-helper" /usr/local/sbin/lab-connector-helper
install -m 644 "$SRC/deploy/lab-connector-helper.socket" /etc/systemd/system/lab-connector-helper.socket
install -m 644 "$SRC/deploy/lab-connector-helper@.service" /etc/systemd/system/lab-connector-helper@.service
# core updates from the UI / `lab-admin update`: the root helper that checks, downloads, verifies and installs signed
# releases (fixed commands, group lab only), its state dir, and the key releases must be signed with
install -m 755 "$SRC/deploy/lab-update-helper" /usr/local/sbin/lab-update-helper
install -m 644 "$SRC/deploy/lab-update-helper.socket" /etc/systemd/system/lab-update-helper.socket
install -m 644 "$SRC/deploy/lab-update-helper@.service" /etc/systemd/system/lab-update-helper@.service
install -d -o root -g root -m 700 /var/lib/lab-update
if [ -f "$SRC/deploy/release.pub" ]; then install -o root -g lab -m 644 "$SRC/deploy/release.pub" /etc/lab/release.pub; fi
# modules from catalogs (docs/catalog.md): the root helper that checks, downloads, verifies and installs signed module
# packages (fixed commands, group lab only), where installed modules live (root's, read-only for everyone else), its own
# state, and the trusted publisher keys (root only: lab-admin publisher add FILE). Nothing is trusted by default, not
# even the core's own release key: the owner opts in (installer --trust-labradoor-modules, or lab-admin publisher add).
install -m 755 "$SRC/deploy/lab-module-helper" /usr/local/sbin/lab-module-helper
install -m 644 "$SRC/deploy/lab-module-helper.socket" /etc/systemd/system/lab-module-helper.socket
install -m 644 "$SRC/deploy/lab-module-helper@.service" /etc/systemd/system/lab-module-helper@.service
install -d -o root -g root -m 755 /var/lib/lab-modules /etc/lab/publishers.d
install -d -o root -g root -m 700 /var/lib/lab-module-helper
# firewall: :8100 only from the reverse proxy + monitoring. The rule file is per installation (addresses): installed
# from the repo only when missing, then owned by the host. The unit loads it at boot, before the gateway.
[ -f /etc/nftables.d-lab.nft ] || install -m 644 "$SRC/deploy/lab-gateway.nft" /etc/nftables.d-lab.nft
install -m 644 "$SRC/deploy/lab-firewall.service" /etc/systemd/system/lab-firewall.service
# master key: seals module secrets in the database (gateway/lab/secretbox.py). Made once; keep a copy in the password
# manager — the off-site backup deliberately leaves it out, so a stolen backup can't open the secrets.
if [ ! -f /etc/lab/master.key ]; then
  python3 -c "import secrets; print(secrets.token_bytes(32).hex())" > /etc/lab/master.key.new
  chown root:lab /etc/lab/master.key.new; chmod 640 /etc/lab/master.key.new; mv /etc/lab/master.key.new /etc/lab/master.key
  echo "NEW /etc/lab/master.key — store a copy in the password manager"
fi
# connectors with a dependency (today only ai: the Claude SDK) get a venv — but NOT here: no network pip at install
# (review 2026-11-15, L9). Their unit drop-in makes the root helper build it right before the connector starts, as an
# unprivileged user, from the hash-locked connectors/<id>/requirements.txt of this signed release (wheels only), and
# only when that file changed. A connector that is never turned on never gets a venv.
for req in "$NEW"/connectors/*/requirements.txt; do
  [ -f "$req" ] || continue
  id=$(basename "$(dirname "$req")")
  install -d -m 755 "/etc/systemd/system/lab-connector@$id.service.d"
  printf '%s\n' "# install.sh: a connector with a requirements.txt runs from its own venv, (re)built before each start if needed" \
    '[Service]' "ExecStartPre=+/usr/local/sbin/lab-connector-helper venv $id" 'TimeoutStartSec=900' \
    'ExecStart=' "ExecStart=/var/lib/lab-venvs/$id/bin/python connector.py" \
    > "/etc/systemd/system/lab-connector@$id.service.d/venv.conf"
done
install -d -o root -g root -m 755 /var/lib/lab-venvs
systemctl daemon-reload
systemctl enable lab-connector-helper.socket >/dev/null 2>&1; systemctl restart lab-connector-helper.socket
# not restarted: an update job may be the one running this script (it runs as its own unit, but leave it be)
systemctl enable lab-update-helper.socket >/dev/null 2>&1; systemctl is-active -q lab-update-helper.socket || systemctl start lab-update-helper.socket
systemctl enable lab-module-helper.socket >/dev/null 2>&1; systemctl is-active -q lab-module-helper.socket || systemctl start lab-module-helper.socket

# --- connectors run as their own users (step 15) ---------------------------------------------------------------------
# Which connectors run is the gateway's decision (module on + configured → it asks the helper). Here: the ones that
# are enabled get their user, their state moves out of /var/lib/lab (connectors can't see that directory any more),
# the old shared user lab-conn leaves group lab, and the old published view of sealed secrets goes away.
CONNECTORS=""
for c in /opt/lab/connectors/*/; do
  id=$(basename "$c"); case "$id" in _*) continue;; esac
  if systemctl is-enabled -q "lab-connector@$id" 2>/dev/null || [ -f "/etc/lab/connectors/$id.env" ]; then CONNECTORS="$CONNECTORS $id"; fi
done
install -d -m 755 /var/lib/lab-connectors
for id in $CONNECTORS; do
  id "lab-c-$id" >/dev/null 2>&1 || useradd --system --user-group --no-create-home --home-dir /nonexistent \
    --shell /usr/sbin/nologin --comment "Labradoor connector $id" "lab-c-$id"
  D="/var/lib/lab-connectors/$id"
  if [ -d "/var/lib/lab/$id" ] && [ ! -L "/var/lib/lab/$id" ] && [ ! -e "$D" ] && [ ! -L "$D" ]; then
    systemctl stop "lab-connector@$id" 2>/dev/null || true
    mv -T "/var/lib/lab/$id" "$D"   # a rename: whatever is there now comes along as it is, never followed
    if [ -L "$D" ] || [ ! -d "$D" ]; then
      rm -f "$D"; echo "connector $id: /var/lib/lab/$id was not a directory — dropped"
    else
      # first out of everyone's reach, then the contents (no links followed, no hard-linked files), then the owner
      chown root:root "$D"; chmod 700 "$D"
      find -P "$D" -xdev -mindepth 1 \( -type d -o \( -type f -links 1 \) \) -exec chown -h "lab-c-$id:lab-c-$id" {} +
      echo "connector $id: state moved to $D"
    fi
  fi
  # only the directory itself (in root's /var/lib/lab-connectors, so nobody can swap it): never chown -R a tree its
  # user controls
  if [ -d "$D" ] && [ ! -L "$D" ]; then chown "lab-c-$id:lab-c-$id" "$D"; chmod 700 "$D"; fi
done
if id lab-conn >/dev/null 2>&1 && id -nG lab-conn | grep -qw lab; then gpasswd -d lab-conn lab >/dev/null; fi
rm -f /var/lib/lab/backends.v2.json
chown root:lab /etc/lab/master.key; chmod 640 /etc/lab/master.key
systemctl enable lab-firewall >/dev/null 2>&1; systemctl is-active -q lab-firewall || systemctl start lab-firewall
systemctl enable lab >/dev/null 2>&1
systemctl restart lab
for _ in 1 2 3 4 5 6 7 8 9 10; do curl -fsS http://127.0.0.1:8100/healthz >/dev/null 2>&1 && break; sleep 1; done
systemctl is-active lab && curl -fsS http://127.0.0.1:8100/healthz && echo
# connectors after the gateway (they fetch their config from it); restart only those whose code (or the shared sdk)
# changed, or that aren't running
for id in $CONNECTORS; do
  systemctl is-enabled -q "lab-connector@$id" 2>/dev/null || systemctl enable "lab-connector@$id" >/dev/null 2>&1
  if [ -n "$PREV" ] && [ -d "$PREV/connectors/$id" ] && diff -rq "$PREV/connectors/$id" "$NEW/connectors/$id" >/dev/null 2>&1 \
     && diff -rq "$PREV/sdk" "$NEW/sdk" >/dev/null 2>&1 && systemctl is-active -q "lab-connector@$id"; then
    echo "connector $id: unchanged"
  else
    # one connector that fails to start (a venv build without network …) must not stop the rest of the install
    systemctl restart "lab-connector@$id" || echo "connector $id: did not start (journalctl -u lab-connector@$id)"
    echo "connector $id: $(systemctl is-active lab-connector@$id)"
  fi
done
# the venv the installer used to build (before the hash-locked one in /var/lib/lab-venvs): gone once nothing runs it
if [ -d /opt/lab-venv-ai ] && ! pgrep -f '^/opt/lab-venv-ai/bin/python' >/dev/null 2>&1; then rm -rf --one-file-system /opt/lab-venv-ai; echo "removed /opt/lab-venv-ai"; fi
# the old shared connector user: gone once no connector runs as it
if id lab-conn >/dev/null 2>&1 && ! pgrep -u lab-conn >/dev/null 2>&1; then userdel lab-conn 2>/dev/null && echo "removed user lab-conn"; fi
/usr/local/bin/lab-admin modules || true
# first run (no owner yet): a fresh one-time link to create the owner account (docs/login.md). The link itself goes to a
# root-only file, not into this output (an update job's log is shown in the UI; journals get shipped to log servers).
# The Proxmox installer (repo-root install.sh) sets LAB_SKIP_SETUP_LINK=1: it sets the public address afterwards and mints
# the one link itself (one link, one audit entry).
if [ "${LAB_SKIP_SETUP_LINK:-0}" != 1 ] && /usr/local/bin/lab-admin setup-link >/dev/null 2>&1; then
  echo; echo "FIRST RUN — no owner yet: the one-time link (1 h) is in /etc/lab/setup-link (root only; a fresh one: lab-admin setup-link)"
fi
echo "release $REL ($VER) live (previous: $(basename "${PREV:-none}"))"
