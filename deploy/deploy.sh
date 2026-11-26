#!/bin/bash
# From workstation: test + build HEAD, ship it to the lab CT, install it as a new release. Usage: deploy/deploy.sh [ssh-host]
#
# Rules (several agents deploy; on 2026-11-14 they overwrote each other's work):
#   * only a clean tree whose HEAD is origin/main is deployed (push first) — LAB_DEPLOY_ANY=1 overrides in an emergency
#   * the install on the CT runs under a lock and refuses a release that does not contain the live one (an older or
#     diverged HEAD would silently drop someone else's deployed commits) — same override
#   * every test suite gates the deploy and its output is shown when it fails
set -euo pipefail
HOST="${1:-lab}"
cd "$(dirname "$0")/.."
[ -z "$(git status --porcelain)" ] || { echo "working tree not clean: commit first (deploys must match git)"; exit 1; }
git fetch -q origin
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ] && [ "${LAB_DEPLOY_ANY:-}" != 1 ]; then
  echo "HEAD $(git rev-parse --short HEAD) is not origin/main $(git rev-parse --short origin/main): pull/push first"
  echo "(LAB_DEPLOY_ANY=1 deploys anyway — emergencies only)"; exit 1
fi

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
# modules the host has installed from a catalog (Settings → Modules: e.g. your private modules, deploy/publish.sh) are
# left out: a bundled copy would take their place. Those are published + installed with deploy/publish.sh modules.
ssh "$HOST" 'if [ -x /usr/local/sbin/lab-module-helper ]; then lab-admin package status; fi' > "$TMP.pkgs"
FROMCAT="$(awk '$1=="installed"{print $2}' "$TMP.pkgs" | while read -r m; do [ ! -d "modules/$m" ] || echo "$m"; done | paste -sd, -)"
rm -f "$TMP.pkgs"
if [ -n "$FROMCAT" ]; then
  echo "left out, $HOST has them from a catalog: $FROMCAT (deploy/publish.sh modules --install $HOST)"
  export LAB_EXCLUDE_MODULES="${LAB_EXCLUDE_MODULES:+$LAB_EXCLUDE_MODULES,}$FROMCAT"
fi
# a build from the repository is a pre-release stamped with the time: always newer than the one before (Settings →
# Updates compares versions), never newer than the release it leads up to
BASE="$(tr -d '[:space:]' < VERSION)"; case "$BASE" in *-*) DV="$BASE.$(date -u +%Y%m%d%H%M%S)" ;; *) DV="$BASE" ;; esac
deploy/build-tree.sh "$TMP" "$DV"   # tests + UI build + the release tree (VERSION, COMMIT, ANCESTRY, MANIFEST)
tar -C "$TMP" -czf - . | ssh "$HOST" "LAB_DEPLOY_ANY='${LAB_DEPLOY_ANY:-}' flock -w 900 /run/lab-deploy.lock sh -c '
  rm -rf /root/lab-release && mkdir /root/lab-release && tar -xzf - -C /root/lab-release &&
  LAB_DEPLOY_ANY=\"\$LAB_DEPLOY_ANY\" sh /root/lab-release/deploy/install.sh'"
echo "deployed $(git rev-parse --short HEAD) to $HOST"
