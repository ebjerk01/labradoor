#!/bin/bash
# Build a signed Labradoor release from HEAD: labradoor-<version>.tar.gz (+ .sig) and its entry in the release index.
#
#   deploy/make-release.sh [--out DIR] [--version V] [--min-upgrade-from V] [--notes TEXT | --notes-file FILE]
#                          [--base-url URL] [--key FILE] [--pub FILE] [--exclude-modules ID,ID] [--no-index]
#
#   --out DIR             where the files go (default: release-out/); DIR/index.json is created or updated
#   --version V           the version to stamp (default: the repo's VERSION file); semver
#   --min-upgrade-from V  installs older than V must update to an intermediate release first (default: none)
#   --notes / --notes-file  release notes shown in Settings → Updates (plain text)
#   --base-url URL        absolute URL of DIR as it will be served (default: entries use relative URLs, resolved
#                         against the index URL — serve the files next to index.json)
#   --key FILE            OpenSSH private key to sign with (default: $LAB_RELEASE_KEY or ~/.config/labradoor/release-signing-key)
#   --pub FILE            the public key the signature must verify with (default: deploy/release.pub; another one only
#                         for a fork or a test key)
#   --exclude-modules L   leave these modules out of the release (they come from a module catalog: docs/catalog.md)
#   --exclude-private     leave out every module whose manifest says "kind": "private" (the public build: those come
#                         from the owner's own private catalog, deploy/publish.sh)
#   --no-index            only the tarball, its signature and DIR/labradoor-<v>.json; leave index.json alone
#
# The tarball holds exactly the tree deploy.sh ships (deploy/build-tree.sh: all test suites gate it): the git tree of
# HEAD, ui/dist, VERSION, COMMIT, ANCESTRY and a MANIFEST with the sha256 of every file. Signatures are OpenSSH
# signatures (ssh-keygen -Y sign -n labradoor-release); installs verify them with /etc/lab/release.pub (deploy/release.pub).
# Only a clean tree is released.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=release-out VER="" MIN="" NOTES="" BASE="" KEY="${LAB_RELEASE_KEY:-$HOME/.config/labradoor/release-signing-key}" INDEX=1 PUB=deploy/release.pub
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --version) VER="$2"; shift 2 ;;
    --min-upgrade-from) MIN="$2"; shift 2 ;;
    --notes) NOTES="$2"; shift 2 ;;
    --notes-file) NOTES="$(cat "$2")"; shift 2 ;;
    --base-url) BASE="${2%/}/"; shift 2 ;;
    --key) KEY="$2"; shift 2 ;;
    --pub) PUB="$2"; shift 2 ;;
    --exclude-modules) export LAB_EXCLUDE_MODULES="${LAB_EXCLUDE_MODULES:+$LAB_EXCLUDE_MODULES,}$2"; shift 2 ;;
    --exclude-private) P="$(deploy/private-modules.sh)"; [ -z "$P" ] || export LAB_EXCLUDE_MODULES="${LAB_EXCLUDE_MODULES:+$LAB_EXCLUDE_MODULES,}$P"; shift ;;
    --no-index) INDEX=0; shift ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)"; exit 2 ;;
  esac
done
[ -n "$VER" ] || VER="$(tr -d '[:space:]' < VERSION)"
semver() { python3 -I -c 'import re,sys; sys.exit(0 if re.match(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$", sys.argv[1]) else 1)' "$1"; }
semver "$VER" || { echo "not a release version (semver, no +build): $VER"; exit 1; }
[ -z "$MIN" ] || semver "$MIN" || { echo "--min-upgrade-from: not a version: $MIN"; exit 1; }
[ -f "$KEY" ] || { echo "no signing key at $KEY (--key FILE or LAB_RELEASE_KEY)"; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "working tree not clean: commit first (a release must match git)"; exit 1; }
command -v ssh-keygen >/dev/null || { echo "ssh-keygen missing"; exit 1; }

NAME="labradoor-$VER"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
# an encrypted signing key (recommended): ssh-keygen asks on the terminal, or LAB_RELEASE_KEY_PASS_CMD names a command that prints
# the passphrase (e.g. from your password manager); it reaches ssh-keygen through SSH_ASKPASS, never on a command line
if [ -n "${LAB_RELEASE_KEY_PASS_CMD:-}" ]; then
  printf '#!/bin/sh\nexec sh -c "$LAB_RELEASE_KEY_PASS_CMD"\n' > "$TMP/askpass"; chmod 700 "$TMP/askpass"
  export SSH_ASKPASS="$TMP/askpass" SSH_ASKPASS_REQUIRE=force LAB_RELEASE_KEY_PASS_CMD
fi
mkdir "$TMP/$NAME"
echo "building $NAME from $(git rev-parse --short HEAD) (tests gate the build) …"
deploy/build-tree.sh "$TMP/$NAME" "$VER"
python3 -I deploy/lab-update-helper verify-tree "$TMP/$NAME" "$VER" >/dev/null   # the MANIFEST we just wrote checks out

# reproducible tarball: sorted names, root-owned, timestamps of the commit
TS="$(git log -1 --format=%ct HEAD)"
tar -C "$TMP" --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$TS" --mode='go-w' -cf - "$NAME" | gzip -n -9 > "$OUT/$NAME.tar.gz"
rm -f "$OUT/$NAME.tar.gz.sig"
ssh-keygen -q -Y sign -f "$KEY" -n labradoor-release "$OUT/$NAME.tar.gz"
SHA="$(sha256sum "$OUT/$NAME.tar.gz" | cut -d' ' -f1)"

# check the signature with the public key the release ships (catches signing with the wrong key)
python3 -I deploy/lab-update-helper verify-sig "$OUT/$NAME.tar.gz" "$OUT/$NAME.tar.gz.sig" "$PUB" >/dev/null || {
  echo "the signature does not verify with $PUB: wrong key?"; exit 1; }

python3 -I - "$OUT" "$NAME" "$VER" "$SHA" "$MIN" "$NOTES" "$BASE" "$INDEX" "$(git rev-parse HEAD)" <<'PY'
import json, os, sys, time
out, name, ver, sha, low, notes, base, index, commit = sys.argv[1:]
entry = {"version": ver, "date": time.strftime("%Y-%m-%d", time.gmtime()), "sha256": sha,
         "url": f"{base}{name}.tar.gz", "sig": f"{base}{name}.tar.gz.sig", "min_upgrade_from": low or None,
         "notes": notes, "commit": commit}
with open(os.path.join(out, f"{name}.json"), "w") as f:
    json.dump(entry, f, indent=2)
if index == "1":
    path = os.path.join(out, "index.json")
    doc = {"format": 1, "product": "labradoor", "releases": []}
    if os.path.exists(path):
        with open(path) as f:
            doc = json.load(f)
    doc["releases"] = [e for e in doc.get("releases", []) if e.get("version") != ver] + [entry]
    doc["generated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(path + ".new", "w") as f:
        json.dump(doc, f, indent=2)
    os.replace(path + ".new", path)
print(json.dumps(entry, indent=2))
PY
if [ "$INDEX" = 1 ]; then
  rm -f "$OUT/index.json.sig"
  ssh-keygen -q -Y sign -f "$KEY" -n labradoor-release "$OUT/index.json"
fi
echo "release: $OUT/$NAME.tar.gz ($(du -h "$OUT/$NAME.tar.gz" | cut -f1), sha256 $SHA)"
[ "$INDEX" = 1 ] && echo "index:   $OUT/index.json (+ .sig) — serve $OUT as-is and point LAB_RELEASE_INDEX at index.json"
exit 0
