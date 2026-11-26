#!/bin/bash
# Build ONE installable module package and add it to a module catalog (docs/catalog.md):
#   <id>-<version>.tar.gz (+ .sig) and its entry in DIR/catalog.json (+ .sig)
#
#   deploy/make-module.sh ID [--out DIR] [--version V] [--key FILE] [--src DIR] [--connector DIR] [--notes TEXT]
#                            [--catalog-name NAME] [--base-url URL] [--no-index] [--allow-dirty]
#
#   ID                    modules/ID (its manifest, its ui/) and, when the manifest has `connector`, connectors/ID
#   --out DIR             where the files go (default: module-out/); DIR/catalog.json is created or updated
#   --version V           stamp this version into the package's manifest (default: the manifest's own `version`)
#   --key FILE            the publisher's OpenSSH private key (default: $LAB_MODULE_KEY or
#                         ~/.config/labradoor/module-signing-key). Its public key is what installations trust
#                         (`lab-admin publisher add FILE.pub` as root on each of them)
#   --src DIR             build from DIR (manifest.json + ui/) instead of modules/ID (a module kept in another repository)
#   --connector DIR       its connector from DIR instead of connectors/ID
#   --notes TEXT          release notes shown in Settings → Modules
#   --catalog-name NAME   the catalog's name, shown with its publisher (kept once set)
#   --base-url URL        absolute URL of DIR as served (default: relative URLs, resolved against the catalog URL)
#   --no-index            only the package and its signature; leave catalog.json alone
#   --allow-dirty         build from uncommitted files (testing; a published package should match git)
#
# The UI is built on its own (vite.module.config.js): ONE ES module, `svelte` and `$lab/…` left as imports that each
# installation's import map resolves to its own shell — so a package records the svelte version it was compiled with
# (the ABI) and every name it imports, and installations refuse a package their shell can't run.
# Signatures are OpenSSH signatures under the namespace labradoor-module (ssh-keygen -Y sign -n labradoor-module).
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
ID="${1:-}"; [ $# -gt 0 ] && shift
OUT=module-out VER="" KEY="${LAB_MODULE_KEY:-$HOME/.config/labradoor/module-signing-key}" SRC="" CONN="" NOTES=""
CNAME="" BASE="" INDEX=1 DIRTY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --version) VER="$2"; shift 2 ;;
    --key) KEY="$2"; shift 2 ;;
    --src) SRC="$2"; shift 2 ;;
    --connector) CONN="$2"; shift 2 ;;
    --notes) NOTES="$2"; shift 2 ;;
    --catalog-name) CNAME="$2"; shift 2 ;;
    --base-url) BASE="${2%/}/"; shift 2 ;;
    --no-index) INDEX=0; shift ;;
    --allow-dirty) DIRTY=1; shift ;;
    -h|--help) sed -n '2,29p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)"; exit 2 ;;
  esac
done
[[ "$ID" =~ ^[a-z][a-z0-9-]{1,30}$ ]] || { echo "usage: deploy/make-module.sh ID [options] (see --help)"; exit 2; }
SRC="${SRC:-modules/$ID}"; CONN="${CONN:-connectors/$ID}"
[ -f "$SRC/manifest.json" ] && [ -f "$SRC/ui/index.js" ] || { echo "no module at $SRC (manifest.json + ui/index.js)"; exit 1; }
[ -f "$KEY" ] || { echo "no signing key at $KEY (--key FILE or LAB_MODULE_KEY)"; exit 1; }
command -v ssh-keygen >/dev/null || { echo "ssh-keygen missing"; exit 1; }
[ -d node_modules ] || npm ci --no-audit --no-fund >/dev/null
if [ "$DIRTY" != 1 ] && [ -n "$(git status --porcelain -- "$SRC" "$CONN" 2>/dev/null)" ]; then
  echo "$SRC or $CONN has uncommitted changes: commit first (a package should match git), or --allow-dirty"; exit 1
fi

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
# an encrypted signing key (recommended): ssh-keygen asks on the terminal, or LAB_MODULE_KEY_PASS_CMD names a command that prints
# the passphrase (e.g. from your password manager); it reaches ssh-keygen through SSH_ASKPASS, never on a command line
if [ -n "${LAB_MODULE_KEY_PASS_CMD:-}" ]; then
  printf '#!/bin/sh\nexec sh -c "$LAB_MODULE_KEY_PASS_CMD"\n' > "$TMP/askpass"; chmod 700 "$TMP/askpass"
  export SSH_ASKPASS="$TMP/askpass" SSH_ASKPASS_REQUIRE=force LAB_MODULE_KEY_PASS_CMD
fi
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
# the manifest (validated exactly as installations validate it) → its version, whether it has a connector
read -r VER HASCONN < <(python3 -I - "$REPO/gateway" "$SRC/manifest.json" "$ID" "$VER" "$TMP/manifest.json" <<'PY'
import copy, json, sys
sys.path.insert(0, sys.argv[1])
from lab.registry import validate
src, mid, ver, out = sys.argv[2:]
raw = json.load(open(src))
if ver:
    raw["version"] = ver
validate(copy.deepcopy(raw), mid)          # the same checks as every installation (raises on anything wrong)
json.dump(raw, open(out, "w"), indent=2)
print(raw["version"], 1 if raw.get("connector") is not None else 0)
PY
)
NAME="$ID-$VER"
PKG="$TMP/$NAME"; mkdir -p "$PKG/ui"
cp "$TMP/manifest.json" "$PKG/manifest.json"
echo "building $NAME (UI → one ES module) …"
LAB_MODULE_ID="$ID" LAB_MODULE_SRC="$SRC" LAB_MODULE_OUT="$TMP/ui" npx vite build -c vite.module.config.js >"$TMP/vite.log" 2>&1 || {
  tail -n 30 "$TMP/vite.log"; echo "UI build failed"; exit 1; }
cp "$TMP/ui/ui.js" "$PKG/ui/ui.js"
if [ "$HASCONN" = 1 ]; then
  [ -f "$CONN/connector.py" ] || { echo "the manifest has a connector but $CONN/connector.py is missing"; exit 1; }
  mkdir -p "$PKG/connector"
  ( cd "$CONN" && find . -type f ! -name 'test_*' ! -name '*.pyc' ! -path '*/__pycache__/*' -print0 ) |
    while IFS= read -r -d '' f; do mkdir -p "$PKG/connector/$(dirname "$f")"; cp "$CONN/$f" "$PKG/connector/$f"; done
fi
for f in README.md LICENSE; do [ -f "$SRC/$f" ] && cp "$SRC/$f" "$PKG/$f"; done
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo '')"
python3 -I - "$PKG" "$TMP/ui/imports.json" "$REPO/node_modules/svelte/package.json" "$COMMIT" <<'PY'
import json, sys, time
pkg, imports, svelte, commit = sys.argv[1:]
m = json.load(open(f"{pkg}/manifest.json"))
doc = {"format": 1, "id": m["id"], "name": m["name"], "version": m["version"], "kind": m["kind"],
       "min_core": m.get("min_core"), "connector": m.get("connector") is not None,
       "abi": {"svelte": json.load(open(svelte))["version"], "imports": json.load(open(imports))},
       "built": time.strftime("%Y-%m-%d", time.gmtime()), "commit": commit}
if doc["min_core"] is None:
    del doc["min_core"]
json.dump(doc, open(f"{pkg}/package.json", "w"), indent=1)
PY
find "$PKG" -name __pycache__ -prune -exec rm -rf {} +
python3 -I deploy/lab-update-helper write-manifest "$PKG" >/dev/null

TS="$(git log -1 --format=%ct HEAD 2>/dev/null || echo 0)"
tar -C "$TMP" --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$TS" --mode='go-w' -cf - "$NAME" | gzip -n -9 > "$OUT/$NAME.tar.gz"
rm -f "$OUT/$NAME.tar.gz.sig"
ssh-keygen -q -Y sign -f "$KEY" -n labradoor-module "$OUT/$NAME.tar.gz"
ssh-keygen -y -f "$KEY" > "$TMP/publisher.pub"
# check it the way an installation will (signature, layout, MANIFEST, package.json, manifest)
LAB_GATEWAY_CODE="$REPO/gateway" python3 -I deploy/lab-module-helper verify-package "$OUT/$NAME.tar.gz" "$TMP/publisher.pub" >/dev/null || {
  rm -f "$OUT/$NAME.tar.gz" "$OUT/$NAME.tar.gz.sig"; echo "the package does not verify"; exit 1; }
SHA="$(sha256sum "$OUT/$NAME.tar.gz" | cut -d' ' -f1)"

if [ "$INDEX" = 1 ]; then
  python3 -I - "$REPO/gateway" "$OUT" "$PKG" "$SHA" "$NOTES" "$CNAME" "$BASE" <<'PY'
import copy, json, os, sys, time
sys.path.insert(0, sys.argv[1])
from lab import modpkg
from lab.registry import validate
out, pkg, sha, notes, cname, base = sys.argv[2:]
m = json.load(open(f"{pkg}/manifest.json"))
p = json.load(open(f"{pkg}/package.json"))
perms = modpkg.permissions(validate(copy.deepcopy(m), m["id"]))
path = os.path.join(out, "catalog.json")
doc = json.load(open(path)) if os.path.exists(path) else {"format": 1, "product": "labradoor-modules", "name": "", "modules": []}
if cname:
    doc["name"] = cname
name = f"{m['id']}-{m['version']}.tar.gz"
entry = {"version": m["version"], "date": time.strftime("%Y-%m-%d", time.gmtime()), "sha256": sha,
         "url": base + name, "sig": base + name + ".sig", "min_core": m.get("min_core"), "svelte": p["abi"]["svelte"],
         "notes": notes, "permissions": perms}
mods = {e["id"]: e for e in doc.get("modules", [])}
e = mods.setdefault(m["id"], {"id": m["id"], "versions": []})
e.update({k: m.get(k, "") for k in ("name", "kind", "category", "description", "icon")})
e["versions"] = [v for v in e["versions"] if v["version"] != m["version"]] + [entry]
doc["modules"] = [mods[k] for k in sorted(mods)]
doc["generated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
with open(path + ".new", "w") as f:
    json.dump(doc, f, indent=1)
os.replace(path + ".new", path)
PY
  rm -f "$OUT/catalog.json.sig"
  ssh-keygen -q -Y sign -f "$KEY" -n labradoor-module "$OUT/catalog.json"
fi
echo "package: $OUT/$NAME.tar.gz ($(du -h "$OUT/$NAME.tar.gz" | cut -f1), sha256 $SHA)"
echo "publisher key: $(ssh-keygen -l -f "$TMP/publisher.pub")"
[ "$INDEX" = 1 ] && echo "catalog: $OUT/catalog.json (+ .sig) — serve $OUT as-is; installations add the catalog URL in Settings → Modules"
exit 0
