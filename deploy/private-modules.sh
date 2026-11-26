#!/bin/sh
# The ids of the modules whose manifest says "kind": "private" (apps of your own), comma-separated: what the public
# build leaves out (make-release.sh --exclude-private) and what deploy/publish.sh puts in the private catalog.
cd "$(dirname "$0")/.." && python3 -I -c '
import glob, json, os
ids = []
for f in sorted(glob.glob("modules/*/manifest.json")):
    d = os.path.basename(os.path.dirname(f))
    if d.startswith(("_", ".")):
        continue
    if json.load(open(f, encoding="utf-8")).get("kind") == "private":
        ids.append(d)
print(",".join(ids))'
