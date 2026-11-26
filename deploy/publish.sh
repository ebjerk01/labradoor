#!/bin/bash
# Publish this repository to your own distribution point: the core as a signed release (the public build: modules of
# kind "private" left out) and your private modules as a signed module catalog. Optionally install it right away.
#
#   deploy/publish.sh core    [--version V] [--notes TEXT] [--install HOST]
#   deploy/publish.sh modules [ID …] [--all] [--install HOST]
#   deploy/publish.sh status
#
#   core       make-release.sh --exclude-private into DIST/core (index.json). Version: --version, else the VERSION file
#              plus a UTC timestamp when it is a pre-release (0.1.0-dev → 0.1.0-dev.20261115120000), so every build
#              from the repository is newer than the one before
#   modules    make-module.sh for each private module (default: every one whose files changed since its newest
#              published package; --all: every one, e.g. after the core moved to a new Svelte minor) into
#              DIST/modules (catalog.json). Version: the manifest's, or the newest published one's patch + 1 when the
#              manifest was not bumped
#   --install HOST   then install it there over ssh as root: `lab-admin update V --yes` (core) or
#                    `lab-admin package install|update ID V --yes` (modules)
#   status     what is published, and which private modules changed since
#
# Settings (environment, else ~/.config/labradoor/publish.env):
#   LAB_DIST_DIR        local copy of the distribution point [~/.local/share/labradoor-dist]
#   LAB_DIST_TARGET     rsync target that serves it, e.g. root@static-host:/var/www/labradoor-dist [none: local only]
#   LAB_DIST_URL        the HTTPS URL it is served at (shown, used for --install of a module not installed yet)
#   LAB_RELEASE_KEY / LAB_RELEASE_KEY_PASS_CMD, LAB_MODULE_KEY / LAB_MODULE_KEY_PASS_CMD   signing keys
#                       (make-release.sh, make-module.sh); the passphrase command runs once per publish
# The target is the truth: its files are fetched first, then the new ones added (nothing is deleted there).
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
if [ -f "$HOME/.config/labradoor/publish.env" ]; then   # the environment wins over the file
  _env="$(export -p | grep -E ' LAB_(DIST_|CATALOG_|RELEASE_KEY|MODULE_KEY)' || true)"
  . "$HOME/.config/labradoor/publish.env"; eval "$_env"
fi
DIST="${LAB_DIST_DIR:-$HOME/.local/share/labradoor-dist}" TARGET="${LAB_DIST_TARGET:-}" URL="${LAB_DIST_URL:-}"
WHAT="${1:-}"; [ $# -gt 0 ] && shift
VER="" NOTES="" HOST="" ALL=0 IDS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --version) VER="$2"; shift 2 ;;
    --notes) NOTES="$2"; shift 2 ;;
    --install) HOST="$2"; shift 2 ;;
    --all) ALL=1; shift ;;
    -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
    -*) echo "unknown option: $1 (see --help)"; exit 2 ;;
    *) IDS+=("$1"); shift ;;
  esac
done
case "$WHAT" in core|modules|status) ;; *) sed -n '2,27p' "$0"; exit 2 ;; esac
mkdir -p "$DIST/core" "$DIST/modules"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
pull() { [ -z "$TARGET" ] || rsync -a --exclude='*.part' "$TARGET/" "$DIST/"; }
push() {  # packages first, the signed index/catalog last: a client never sees an index naming files not there yet
  [ -z "$TARGET" ] && return 0
  rsync -a --exclude='index.json*' --exclude='catalog.json*' "$DIST/" "$TARGET/"
  rsync -a "$DIST/" "$TARGET/"
}
# ask for a passphrase once (the scripts sign several files): a 0600 file in our own temp dir, gone on exit
cache_pass() {  # VAR
  local v="$1"; [ -n "${!v:-}" ] || return 0
  (umask 077; sh -c "${!v}" > "$TMP/$v") || { echo "$v failed"; exit 1; }
  export "$v=cat '$TMP/$v'"
}
# id → "version commit" of its newest published package ("" when none)
published() {
  python3 -I - "$REPO/gateway" "$DIST/modules" "$1" <<'PY'
import json, os, sys, tarfile
sys.path.insert(0, sys.argv[1])
from lab import modpkg
d, mid = sys.argv[2:]
try:
    doc = json.load(open(os.path.join(d, "catalog.json")))
except OSError:
    sys.exit(0)
for e in doc.get("modules", []):
    if e["id"] != mid or not e.get("versions"):
        continue
    v = max((x["version"] for x in e["versions"]), key=__import__("functools").cmp_to_key(modpkg.compare))
    commit = ""
    try:
        with tarfile.open(os.path.join(d, f"{mid}-{v}.tar.gz")) as t:
            commit = json.load(t.extractfile(f"{mid}-{v}/package.json")).get("commit", "")
    except (OSError, KeyError, ValueError, tarfile.TarError):
        pass
    print(v, commit)
PY
}
changed_since() {  # ID COMMIT → 0 when its files changed (or the commit is unknown)
  [ -n "$2" ] && git cat-file -e "$2^{commit}" 2>/dev/null || return 0
  ! git diff --quiet "$2" HEAD -- "modules/$1" "connectors/$1"
}
next_version() {  # ID PUBLISHED → the manifest's version if newer, else PUBLISHED's patch + 1
  python3 -I - "$REPO/gateway" "modules/$1/manifest.json" "$2" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1])
from lab import modpkg
m, pub = json.load(open(sys.argv[2]))["version"], sys.argv[3]
if not pub or modpkg.compare(m, pub) > 0:
    print(m)
else:
    a, b, c = modpkg.parse_version(pub)[:3]
    print(f"{a}.{b}.{c + 1}")
PY
}
PRIVATE="$(deploy/private-modules.sh | tr ',' ' ')"

if [ "$WHAT" = status ]; then
  pull
  echo "distribution point: ${URL:-$DIST}${TARGET:+  (served from $TARGET)}"
  python3 -I -c 'import json,sys
try: d=json.load(open(sys.argv[1]))
except OSError: print("core: nothing published"); sys.exit()
print("core:", ", ".join(r["version"] for r in d.get("releases", [])[-5:]))' "$DIST/core/index.json"
  for id in $PRIVATE; do
    read -r v c < <(published "$id"; echo) || true
    if [ -z "${v:-}" ]; then echo "  $id: not published"
    elif changed_since "$id" "${c:-}"; then echo "  $id: $v — CHANGED since (publish.sh modules $id)"
    else echo "  $id: $v"; fi
  done
  exit 0
fi

[ -z "$(git status --porcelain)" ] || { echo "working tree not clean: commit first (what is published must match git)"; exit 1; }
pull

if [ "$WHAT" = core ]; then
  if [ -z "$VER" ]; then
    base="$(tr -d '[:space:]' < VERSION)"
    case "$base" in *-*) VER="$base.$(date -u +%Y%m%d%H%M%S)" ;; *) VER="$base" ;; esac
  fi
  cache_pass LAB_RELEASE_KEY_PASS_CMD
  deploy/make-release.sh --out "$DIST/core" --version "$VER" --exclude-private ${NOTES:+--notes "$NOTES"} > "$TMP/release.log" 2>&1 || {
    tail -n 60 "$TMP/release.log"; echo "make-release.sh failed"; exit 1; }
  grep -E "^(release|index):" "$TMP/release.log" || true
  push
  echo "published core $VER${URL:+ → $URL/core/index.json}"
  if [ -n "$HOST" ]; then
    ssh "$HOST" "lab-admin update --check >/dev/null && lab-admin update '$VER' --yes"
  fi
  exit 0
fi

# modules
if [ ${#IDS[@]} -eq 0 ]; then IDS=($PRIVATE); else
  for id in "${IDS[@]}"; do case " $PRIVATE " in *" $id "*) ;; *) echo "$id is not a private module (kind \"private\")"; exit 1 ;; esac; done
fi
cache_pass LAB_MODULE_KEY_PASS_CMD
DONE=()
for id in "${IDS[@]}"; do
  read -r pv pc < <(published "$id"; echo) || true
  if [ -n "${pv:-}" ] && [ "$ALL" != 1 ] && ! changed_since "$id" "${pc:-}"; then
    echo "$id $pv: unchanged since it was published"; continue
  fi
  v="$(next_version "$id" "${pv:-}")"
  deploy/make-module.sh "$id" --out "$DIST/modules" --version "$v" --catalog-name "${LAB_CATALOG_NAME:-Private modules}" > "$TMP/$id.log" 2>&1 || {
    tail -n 40 "$TMP/$id.log"; echo "make-module.sh $id failed"; exit 1; }
  grep -E "^package:" "$TMP/$id.log" || true
  DONE+=("$id:$v")
done
[ ${#DONE[@]} -gt 0 ] || { echo "nothing to publish"; exit 0; }
push
echo "published: ${DONE[*]}${URL:+ → $URL/modules/catalog.json}"
if [ -n "$HOST" ]; then
  [ -n "$URL" ] || { echo "--install needs LAB_DIST_URL (the catalog's URL as the host fetches it)"; exit 1; }
  ssh "$HOST" "lab-admin package check '$URL/modules/catalog.json' >/dev/null"   # the helper installs from checked catalogs
  for iv in "${DONE[@]}"; do
    id="${iv%%:*}" v="${iv#*:}"
    # update when the host has it from a catalog, install otherwise
    ssh "$HOST" "if lab-admin package status | grep -q '^installed $id '; then lab-admin package update '$id' '$v' --yes;
                 else lab-admin package install '$id' '$v' --catalog '$URL/modules/catalog.json' --yes; fi"
  done
fi
