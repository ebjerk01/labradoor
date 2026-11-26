#!/bin/bash
# Test + build HEAD and write the release tree into DEST — the one tree that deploy.sh ships and make-release.sh packs:
# the git tree of HEAD + the built UI (ui/dist) + VERSION (semver, from the repo's VERSION file unless given) + COMMIT +
# ANCESTRY (install.sh: the live release must be in here) + MANIFEST (sha256 of every file; checked before an update).
# Every test suite gates it; the output of a failing one is shown.  Usage: deploy/build-tree.sh DEST [VERSION]
# LAB_EXCLUDE_MODULES=id,id leaves those modules (and their connectors) out of the tree AND the UI build: a slim core
# whose other modules come from a catalog (docs/catalog.md). Default: every module ships.
set -euo pipefail
DEST="$1"; VER="${2:-}"
cd "$(dirname "$0")/.."
[ -d "$DEST" ] || { echo "build-tree: $DEST is not a directory"; exit 1; }
LOG=$(mktemp); trap 'rm -f "$LOG"' EXIT
step() { local what="$1"; shift; if ! "$@" >>"$LOG" 2>&1; then echo "FAILED: $what"; tail -n 60 "$LOG"; exit 1; fi; }
step "npm ci" npm ci --no-audit --no-fund
step "ui build" npm run build
step "gateway tests" python3 -W ignore -m unittest discover -s tests
for t in connectors/*/test_*.py; do
  [ -f "$t" ] || continue
  step "connector tests $(dirname "$t")" python3 -W ignore -m unittest discover -s "$(dirname "$t")" -p 'test_*.py'
done
while IFS= read -r t; do step "node test $t" node "$t"; done < <(find modules ui/src tests -name '*.test.mjs' -not -path '*/node_modules/*' | sort)

git archive HEAD | tar -x -C "$DEST"
for m in $(echo "${LAB_EXCLUDE_MODULES:-}" | tr ',' ' '); do
  case "$m" in ''|_*|*/*|*.*) echo "build-tree: bad module id in LAB_EXCLUDE_MODULES: $m"; exit 1 ;; esac
  [ -d "$DEST/modules/$m" ] || { echo "build-tree: no module $m to exclude"; exit 1; }
  rm -rf "$DEST/modules/$m" "$DEST/connectors/$m"
done
cp -r ui/dist "$DEST/ui/dist"
[ -n "$VER" ] || VER="$(tr -d '[:space:]' < VERSION)"
echo "$VER" > "$DEST/VERSION"
git rev-parse HEAD > "$DEST/COMMIT"
git rev-list --max-count=2000 HEAD > "$DEST/ANCESTRY"
python3 deploy/lab-update-helper write-manifest "$DEST" >/dev/null
