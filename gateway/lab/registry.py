"""Module registry: reads modules/<id>/manifest.json, decides who may use which module and which backend route.

A module never trusts the browser: the gateway checks every proxied request against the manifest's route list.

Roles (from Authentik groups, see auth.py):  owner > admin > guest.
  * access.roles   roles that may use the module at all (owner always may)
  * access.groups  Authentik groups that let a *guest* use it (e.g. "cdn-admins")
  * route.min      lowest role for that route (default "guest" = anyone with module access)
  * route.owner_only  owner may; admin may only through a one-time owner approval ("ask"); guest never.
                      Admins are GLOBAL READERS (user decision 2026-11-14): an owner_only GET is plain "yes" for an admin,
                      unless the route is also `secret: true` (it returns secret material) — then reading asks too.
"""
import json
import os
import re
import urllib.parse

ROLES = ("guest", "admin", "owner")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


class ManifestError(ValueError):
    pass


def rank(role):
    return ROLES.index(role) if role in ROLES else -1


def _compile(pattern):
    if not pattern.startswith("/"):
        raise ManifestError(f"route path must start with /: {pattern}")
    out, segs = [], pattern.strip("/").split("/") if pattern != "/" else []
    for i, s in enumerate(segs):
        if s == "**":
            if i != len(segs) - 1:
                raise ManifestError(f"** only allowed last: {pattern}")
            out.append("(?:/.*)?")
            break
        out.append("/" + ("[^/]+" if s == "*" else re.escape(s)))
    return re.compile("^" + ("".join(out) or "") + "/?$")


# --- path hygiene (security review 2026-11-14) ------------------------------------------------------------------------
# The browser's path is matched raw against the manifest, then sent to the backend as is. Backends decode, normalise and
# parse it in their own ways (Python int("040") == 40, .NET routes ignore case, Tomcat strips ";…", nginx resolves
# "%2e%2e"), so a path that LOOKS different from an owner-only route can still reach the same backend handler.
# 1. path_problem() refuses paths no UI builds: dot segments (also encoded / ";"-suffixed), empty segments, backslashes,
#    control characters, NULs.
# 2. find_route() also matches a canonical form (decoded, lower-case, numbers as int() reads them) and, when that hits a
#    stricter route than the raw match, uses the stricter one ("040" → workstation's owner-only "40").
_CTRL = re.compile(r"[\x00-\x20\x7f]")


def _decoded(path, rounds=3):
    for _ in range(rounds):
        nxt = urllib.parse.unquote(path, errors="replace")
        if nxt == path:
            break
        path = nxt
    return path


def path_problem(path, encoded_slash=True):
    """Why this backend path is refused, or None. `path` is the raw (still percent-encoded) path after /api/m/<id>.
    encoded_slash=False (manifest `backend.decodes_slashes: true`): the backend turns %2F into a path separator before
    routing (Proxmox does: /lxc/116%2Fsnapshot%2F/config reaches .../snapshot//config), so one `*` in a route could
    cover several backend segments: refuse it."""
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 2048:
        return "bad path"
    if "?" in path or "#" in path or _CTRL.search(path) or "\\" in path:
        return "bad characters in path"
    segs = path[1:].split("/")
    if any(s == "" for s in segs[:-1]):  # "//" (a trailing slash is fine)
        return "empty path segment"
    dec = _decoded(path)
    if _CTRL.search(dec.replace(" ", "")) or "\\" in dec or "\x00" in dec:
        return "bad encoded characters in path"
    if not encoded_slash and dec.count("/") != path.count("/"):
        return "encoded slash in path"
    for s in dec.split("/"):
        if s.split(";", 1)[0].strip() in (".", ".."):
            return "dot segment in path"
    return None


def _canon_seg(s):
    s = s.split(";", 1)[0]
    try:
        n = int(s)  # also "040", "+40", "4_0", " 40", Arabic-Indic digits …
    except ValueError:
        return s.lower()
    return str(n)


def canonical(path):
    """The form a lenient backend may see: decoded, lower-case, ;params dropped, numbers normalised."""
    return "/".join(_canon_seg(s) for s in _decoded(path).split("/"))


def strictness(route):
    if not route:
        return -1
    if route.get("min") == "owner":
        return 4
    if route.get("owner_only"):
        return 3 if route.get("secret") else 2
    return 1 if route.get("min") == "admin" else 0


def validate(m, folder_id=None):
    if not isinstance(m, dict):
        raise ManifestError("manifest must be an object")
    if m.get("manifest") == 2:  # the strict format (manifest2.py); its routes get the same checks below
        from .manifest2 import validate_v2
        validate_v2(m, folder_id)
        _check_routes(m, m["id"])
        from .manifest2 import render
        m["_backend_tpl"] = m.get("backend")
        # usable as is when nothing needs configuring (a connector's fixed URL); Registry.apply() redoes it per install
        m["backend"], m["_missing"] = render(m, {}) if m["_backend_tpl"] else (None, [])
        m["_routes_base"] = m["routes"]
        _check_settings(m, m["id"])
        return m
    raise ManifestError(f"{m.get('id')!r}: manifest format {m.get('manifest', 1)!r} is not supported — add "
                        '"manifest": 2 and see docs/modules.md (v1 was removed on 2026-11-15)')


def _check_routes(m, mid):
    for r in m["routes"]:
        if r.get("method") not in METHODS:
            raise ManifestError(f"{mid}: bad method in {r}")
        if r.get("min", "guest") not in ROLES:
            raise ManifestError(f"{mid}: bad min in {r}")
        r["_re"] = _compile(r.get("path") or "")
        r["_re_i"] = re.compile(r["_re"].pattern, re.IGNORECASE)
        ba = r.get("body_allow")
        if ba is not None and not (isinstance(ba, dict) and ba and all(isinstance(v, list) and v for v in ba.values())):
            raise ManifestError(f"{mid}: body_allow must map JSON fields to non-empty lists of allowed values")
        bk = r.get("body_keys")
        if bk is not None and not (isinstance(bk, list) and bk and all(isinstance(k, str) and k for k in bk)):
            raise ManifestError(f"{mid}: body_keys must be a non-empty list of JSON field names")
        qk = r.get("query_keys")
        if qk is not None and not (isinstance(qk, list) and all(isinstance(k, str) and k for k in qk)):
            raise ManifestError(f"{mid}: query_keys must be a list of query parameter names ([] = no query string)")
        if qk and r.get("body_schema") and {k.lower() for k in qk} & _schema_keys(r["body_schema"]):
            raise ManifestError(f"{mid}: a field may come from the query or the body, not both: {r.get('path')}")
        if qk and bk and {k.lower() for k in qk} & {k.lower() for k in bk}:
            raise ManifestError(f"{mid}: a field may come from the query or the body, not both: {r.get('path')}")
        bl = r.get("body_list")
        if bl is not None and not (bl is True and (ba or bk)):
            raise ManifestError(f"{mid}: body_list: true needs body_keys or body_allow (checked on every item)")
        mb = r.get("max_body")
        if mb is not None and not (isinstance(mb, int) and not isinstance(mb, bool) and 0 < mb <= 16 * 1024 * 1024):
            raise ManifestError(f"{mid}: max_body must be 1..16777216 bytes")


def _check_settings(m, mid):
    seen = set()
    for st in m.setdefault("settings", []):
        if not (isinstance(st, dict) and re.match(r"^[a-z][a-z0-9_]{0,40}$", str(st.get("key") or ""))
                and st.get("type") in SETTING_TYPES and st["key"] not in seen):
            raise ManifestError(f"{mid}: bad setting {st!r}")
        seen.add(st["key"])
        if st["type"] == "enum" and not st.get("options"):
            raise ManifestError(f"{mid}: enum setting {st['key']} needs options")


SETTING_TYPES = ("bool", "int", "enum", "text", "list")
# switches every module has, handled by the shell (stored with a leading underscore)
GENERIC = [{"key": "_ticker", "type": "bool", "default": True, "label": "show in the ticker"},
           {"key": "_overview", "type": "bool", "default": True, "label": "section on the overview"},
           {"key": "_alerts", "type": "bool", "default": True, "label": "alerts"},
           {"key": "_tiles", "type": "bool", "default": True, "label": "tiles on the wall"}]
# per-installation policy for modules with a backend: path patterns whose writes are owner-only here (e.g. the guest that
# holds your keys) — instead of IDs hardcoded in a manifest
PROTECT = {"key": "_protect", "type": "list", "default": [], "label": "owner-only paths (writes)",
           "help": "Owner-only here. '/path/**' = its writes; 'GET /path' = reading it too; 'POST /path field=value' = only "
                   "requests whose JSON body has that value. * = one segment, ** = the rest."}
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


_BODY_EQ = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]{0,60})=(.{1,200})$")


def parse_protect(entry):
    """One _protect entry → (methods, path, {body field: value}).
         "/nodes/*/lxc/112/**"                              writes to that path (POST/PUT/PATCH/DELETE)
         "GET /api/machines/40/commands"                    reading it too (owner-only + secret: admins ask)
         "POST,DELETE /x/**"                                just those methods
         "POST /poe/power-cycle numbers=ether22"            only when the JSON body's field has that value
    Raises ManifestError for anything else."""
    parts = str(entry).split()
    if not parts:
        raise ManifestError("empty entry")
    methods = WRITE_METHODS
    if not parts[0].startswith("/"):
        methods = tuple(x.strip().upper() for x in parts.pop(0).split(",") if x.strip())
        if not methods or any(x not in METHODS for x in methods):
            raise ManifestError(f"bad methods in {entry!r} (GET, POST, PUT, PATCH, DELETE)")
    if not parts:
        raise ManifestError(f"no path in {entry!r}")
    path = parts.pop(0)
    _compile(path)
    cond = {}
    for c in parts:
        m = _BODY_EQ.match(c)
        if not m:
            raise ManifestError(f"body condition must be field=value: {c!r}")
        cond[m.group(1).lower()] = m.group(2)
    return methods, path, cond


def protect_routes(patterns):
    """Synthetic owner-only routes for the _protect setting (they win over looser routes, see find_route; the ones with
    a body condition are checked separately, once the body is read: Registry.body_protected)."""
    out = []
    for p in patterns or []:
        methods, path, cond = parse_protect(p)
        rx = _compile(path)
        for meth in methods:
            r = {"method": meth, "path": path, "owner_only": True, "label": f"protected: {p} (owner only)",
                 "_re": rx, "_re_i": re.compile(rx.pattern, re.IGNORECASE), "_protect": True}
            if meth == "GET":
                r["secret"] = True  # an admin may read every other owner_only GET; a protected one asks
            if cond:
                r["_body_eq"] = cond
            out.append(r)
    return out


def check_value(st, v):
    """Validates one setting value against its schema; returns the clean value or raises ValueError."""
    t = st["type"]
    if t == "bool":
        if not isinstance(v, bool):
            raise ValueError("expected true/false")
        return v
    if t == "int":
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("expected a whole number")
        if ("min" in st and v < st["min"]) or ("max" in st and v > st["max"]):
            raise ValueError(f"out of range {st.get('min')}..{st.get('max')}")
        return v
    if t == "enum":
        if v not in st["options"]:
            raise ValueError(f"one of {st['options']}")
        return v
    if t == "text":
        if not isinstance(v, str) or len(v) > st.get("max", 500):
            raise ValueError("text too long")
        return v
    if not (isinstance(v, list) and len(v) <= 100 and all(isinstance(x, str) and len(x) <= 100 for x in v)):
        raise ValueError("expected a short list of strings")
    return v


class Registry:
    def __init__(self, modules_dir, backends_file=None, installed_dir=None, abi_file=None, release_pub=None):
        self.modules_dir, self.backends_file = modules_dir, backends_file
        # modules installed from catalogs (docs/catalog.md, gateway/lab/modpkg.py): root's tree, read-only here
        self.installed_dir, self.abi_file, self.release_pub = installed_dir, abi_file, release_pub
        self.modules, self.errors = {}, {}
        self.shadowed = {}   # id -> why an installed package of that id is not the one in use
        self.overrides = {}  # module -> {"_enabled": bool, "_groups": [...], other settings...} (owner, from the DB)
        self.config = {}     # module -> {field: value} per installation (v2 config; secrets only as "set" markers)
        self.load()

    def load(self):
        mods, errs = {}, {}
        overrides = {}
        if self.backends_file and os.path.exists(self.backends_file):
            with open(self.backends_file, encoding="utf-8") as f:
                overrides = json.load(f)
        if os.path.isdir(self.modules_dir):
            for name in sorted(os.listdir(self.modules_dir)):
                path = os.path.join(self.modules_dir, name, "manifest.json")
                if name.startswith(("_", ".")) or not os.path.isfile(path):
                    continue
                try:
                    with open(path, encoding="utf-8") as f:
                        m = validate(json.load(f), name)
                    if m["id"] in overrides and m.get("backend"):
                        m["backend"]["url"] = overrides[m["id"]]
                    m["_source"] = "bundled"
                    mods[m["id"]] = m
                except (OSError, ValueError) as e:
                    errs[name] = str(e)
        self._seen = self.installed_signature()
        shadowed = self._load_installed(mods, errs)
        self.modules, self.errors, self.shadowed = mods, errs, shadowed
        self.apply()

    def installed_signature(self):
        """What the installed tree looks like (ids + their state.json's mtime): changes when the helper installs, updates,
        rolls back or removes a module — also from `lab-admin package`, which the gateway does not hear about."""
        from . import modpkg
        if not self.installed_dir:
            return ()
        out = []
        for mid in modpkg.installed_ids(self.installed_dir):
            try:
                out.append((mid, os.stat(os.path.join(self.installed_dir, mid, "state.json")).st_mtime_ns))
            except OSError:
                pass
        return tuple(out)

    def installed_changed(self):
        return self.installed_signature() != getattr(self, "_seen", ())

    def _load_installed(self, mods, errs):
        """Merge the modules installed from catalogs into `mods`. An installed package of a bundled id is used only when
        it is newer AND signed with the core's release key (the helper refuses anything else, this is the reader's
        side of the same rule); a package whose UI this shell can't run (svelte ABI, after a core update) is left out
        and the bundled one, if any, stays. → {id: why the installed one is not used}."""
        from . import modpkg
        if not self.installed_dir:
            return {}
        shadowed = {}
        abi = modpkg.load_abi(self.abi_file) if self.abi_file else None
        core = set(modpkg.file_fingerprints(self.release_pub)) if self.release_pub else set()
        for mid in modpkg.installed_ids(self.installed_dir):
            st = modpkg.installed_state(mid, self.installed_dir)
            ver = st["version"]
            d = os.path.join(self.installed_dir, mid, ver)
            try:
                with open(os.path.join(d, "manifest.json"), encoding="utf-8") as f:
                    m = validate(json.load(f), mid)
                with open(os.path.join(d, "package.json"), encoding="utf-8") as f:
                    pkg = modpkg.check_package_json(json.load(f), mid, ver)
                if m["version"] != ver:
                    raise ManifestError(f"{mid}: the installed manifest says {m['version']}, not {ver}")
            except (OSError, ValueError) as e:
                errs[f"{mid}@{ver}"] = f"installed {mid} {ver}: {e}"
                continue
            pub = st.get("publisher") or {}
            why = modpkg.abi_problem(pkg["abi"], abi)
            b = mods.get(mid)
            if not why and b:
                if not (pub.get("fingerprint") in core and modpkg.is_version(b.get("version"))
                        and modpkg.compare(ver, b["version"]) > 0):
                    why = (f"the bundled {b.get('version')} is used: an installed package replaces it only when newer and "
                           "signed with the core's release key")
            if why:
                shadowed[mid] = why
                if not b:
                    errs[f"{mid}@{ver}"] = f"installed {mid} {ver} not loaded: {why}"
                continue
            m["_source"] = "installed"
            m["_installed"] = {"version": ver, "previous": st.get("previous"), "publisher": pub,
                               "dir": d, "bundle": f"/modules/{mid}/{ver}/ui.js", "replaces": b.get("version") if b else None}
            mods[mid] = m
        return shadowed

    def bundle_file(self, mid, version):
        """The installed UI bundle of `mid` at `version` when that is the live one, else None."""
        m = self.modules.get(mid)
        inst = (m or {}).get("_installed")
        if not inst or inst["version"] != version:
            return None
        root = os.path.realpath(self.installed_dir)
        path = os.path.realpath(os.path.join(inst["dir"], "ui", "ui.js"))
        return path if path.startswith(root + os.sep) and os.path.isfile(path) else None

    def apply(self, overrides=None, config=None):
        """Re-derive what depends on this installation: v2 backends from config, _protect routes from settings."""
        from .manifest2 import render, render_routes
        if overrides is not None:
            self.overrides = overrides
        if config is not None:
            self.config = config
        for m in self.modules.values():
            if m.get("_v2"):
                m["backend"], m["_missing"] = render(m, self.config.get(m["id"], {}))
            base = render_routes(m, {**self.values(m), **self.config.get(m["id"], {})}) if m.get("_v2") else m["_routes_base"]
            pats = self.overrides.get(m["id"], {}).get("_protect") if m.get("backend") or m.get("_backend_tpl") else None
            try:
                m["routes"] = protect_routes(pats) + base
            except ManifestError as e:  # a bad pattern stored earlier: keep the module, without that policy
                self.errors[m["id"] + ":_protect"] = str(e)
                m["routes"] = base

    def needs_setup(self, m):
        return bool(m.get("_v2") and m.get("_backend_tpl") and m.get("backend") is None)

    def get(self, mid):
        return self.modules.get(mid)

    def enabled(self, m):
        return self.overrides.get(m["id"], {}).get("_enabled", True) is not False

    def can_use(self, m, user):
        if not user or not self.enabled(m) or self.needs_setup(m):  # not configured yet: only Settings shows it
            return False
        role = user.get("role", "guest")
        if role in ("owner", "admin") or role in m["access"]["roles"]:  # admin = global reader: every module
            return True
        extra = self.overrides.get(m["id"], {}).get("_groups") or []
        if not self.guest_safe(m):
            extra = []  # shared-token module: owner-added guest groups would read everything with that token
        return bool(set(user.get("groups") or []) & (set(m["access"]["groups"]) | set(extra)))

    @staticmethod
    def guest_safe(m):
        """Modules that reach a third-party API with the gateway's own shared credential (backend.auth) answer every
        caller the same way: unless the manifest says `guest_safe: true`, guests must not be added to them."""
        return not (m.get("backend") or {}).get("auth") or m.get("guest_safe") is True

    def schema(self, m):
        return GENERIC + ([PROTECT] if m.get("backend") or m.get("_backend_tpl") else []) + m.get("settings", [])

    def values(self, m):
        ov = self.overrides.get(m["id"], {})
        return {st["key"]: ov.get(st["key"], st.get("default")) for st in self.schema(m)}

    @staticmethod
    def path_problem(m, path):
        """path_problem() with this module's backend quirks (decodes_slashes)."""
        return path_problem(path, encoded_slash=not (m.get("backend") or {}).get("decodes_slashes"))

    @staticmethod
    def find_route(m, method, path):
        """The manifest route for this request: the first raw match — unless the path's canonical form (see canonical())
        also matches a STRICTER route, which then wins. Callers must refuse path_problem() paths first."""
        routes = [r for r in m.get("routes", []) if r["method"] == method and not r.get("_body_eq")]
        first = next((r for r in routes if not r.get("_protect") and r["_re"].match(path)), None)
        if not first:
            return None
        canon = canonical(path)
        best = first
        for r in routes:
            if strictness(r) > strictness(best) and (r["_re"].match(path) or r["_re_i"].match(canon)):
                best = r
        return best

    @staticmethod
    def body_protected(m, method, path, body, query="", content_type="application/json"):
        """The _protect route with a body condition this request meets, or None. Called once the body is read; the verdict
        then is that route's. Security review 2026-11-15 (M1): the condition is checked in the JSON body AND the query
        string, values are compared canonically (true/True/"true", 112/"0112"/112.0, case-insensitive text, also inside
        lists and comma lists), and anything the gateway can't read the way the backend will (not JSON, duplicate or
        case-variant keys, unparsable) counts as matching: the owner decides."""
        cands = [r for r in m.get("routes", []) if r.get("_body_eq") and r["method"] == method
                 and (r["_re"].match(path) or r["_re_i"].match(canonical(path)))]
        if not cands:
            return None
        ctype = (content_type or "").split(";")[0].strip().lower()
        if body and ctype and ctype != "application/json":
            return cands[0]

        def pairs(items):
            seen = set()
            for k, _ in items:
                if str(k).lower() in seen:
                    raise ValueError("duplicate key")
                seen.add(str(k).lower())
            return dict(items)
        try:
            raw = (body or b"{}").decode("utf-8") if isinstance(body, (bytes, bytearray)) else (body or "{}")
            data = json.loads(raw or "{}", object_pairs_hook=pairs)
            qs = urllib.parse.parse_qsl(query or "", keep_blank_values=True, strict_parsing=bool(query))
        except (ValueError, UnicodeDecodeError, RecursionError):
            return cands[0]
        qlow = {}
        for k, v in qs:
            if k.lower() in qlow:
                return cands[0]
            qlow[k.lower()] = v
        items = [x for x in (data if isinstance(data, list) else [data]) if isinstance(x, dict)] or [{}]
        for r in cands:
            for it in items:
                low = {str(k).lower(): v for k, v in it.items()}
                if all(_cond_hit(low.get(k), v) or _cond_hit(qlow.get(k), v) for k, v in r["_body_eq"].items()):
                    return r
        return None

    @staticmethod
    def body_restricted(route):
        return bool(route and (route.get("body_allow") or route.get("body_keys") or route.get("body_schema")))

    @staticmethod
    def body_problem(route, body):
        """Why the body breaks the route's body_schema (field names only), or None. bodyschema.py."""
        from . import bodyschema
        try:
            data = bodyschema.parse(body or b"{}")
        except (ValueError, UnicodeDecodeError, RecursionError):
            return "body: not one JSON value (UTF-8, no duplicate keys)"
        return bodyschema.check(route["body_schema"], data)

    @staticmethod
    def body_ok(route, body):
        """route.body_allow = {"name": ["A", "B"]}: the JSON body must be an object whose listed fields hold allowed values
        (stops e.g. 'POST /api/v3/command' from running any command the *arr API knows).
        route.body_keys = ["cores", …]: the JSON body may only carry these top-level fields.
        route.body_list = true: the body is a JSON array (≤ 100 items) of such objects (Jellyfin task triggers).
        Strict on both: UTF-8 JSON object, no duplicate keys (also not differing only in case — .NET binds
        case-insensitively and the last one wins), field names compared case-insensitively."""
        if route.get("body_schema"):  # nested rules (bodyschema.py) instead of the flat ones below
            return Registry.body_problem(route, body) is None
        allow, keys, many = route.get("body_allow"), route.get("body_keys"), route.get("body_list") is True
        if not allow and not keys:
            return True

        def pairs(items):
            seen = set()
            for k, _ in items:
                if k.lower() in seen:
                    raise ValueError("duplicate key")
                seen.add(k.lower())
            return dict(items)
        try:
            data = json.loads((body or (b"[]" if many else b"{}")).decode("utf-8"), object_pairs_hook=pairs)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return False
        if many and not (isinstance(data, list) and len(data) <= 100):
            return False
        for item in (data if many else [data]):
            if not isinstance(item, dict):
                return False
            low = {k.lower(): v for k, v in item.items()}
            if keys and not set(low) <= {k.lower() for k in keys}:
                return False
            for k, v in (allow or {}).items():
                got = low.get(k.lower())
                if not any(type(got) is type(x) and got == x for x in v):  # True != 1 here
                    return False
        return True

    @staticmethod
    def query_ok(route, query):
        """route.query_keys = ["name", …]: the query string may only carry these parameters (names compared
        case-insensitively, as .NET binds them; [] = no query string at all). Without query_keys: a body-restricted
        route takes no query string (Proxmox merges query parameters into the body's); other routes pass it on."""
        keys = (route or {}).get("query_keys")
        if keys is None:
            return not (query and Registry.body_restricted(route))
        if not query:
            return True
        try:
            got = urllib.parse.parse_qsl(query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            return False
        allowed = {k.lower() for k in keys}
        return all(k.lower() in allowed for k, _ in got)

    @staticmethod
    def permission(route, user):
        """'yes' | 'ask' (admin, owner-only route: needs a one-time owner approval) | 'no'."""
        if not route or not user:
            return "no"
        role = user.get("role", "guest")
        if route.get("owner_only"):
            if role == "owner":
                return "yes"
            if role == "admin":
                return "yes" if route["method"] == "GET" and not route.get("secret") else "ask"
            return "no"
        return "yes" if rank(role) >= rank(route.get("min", "guest")) else "no"

    def visible(self, user):
        """The manifests this user may use, as sent to the browser (no backend URLs, routes with this user's verdict)."""
        out = []
        for m in self.modules.values():
            if not self.can_use(m, user):
                continue
            out.append({
                "id": m["id"], "name": m["name"], "icon": m.get("icon", ""), "description": m.get("description", ""),
                "version": m.get("version", 1), "contributes": m["contributes"], "settings": self.values(m),
                "category": m.get("category") or "", "kind": m.get("kind") or "",
                "manifest": 2 if m.get("_v2") else 1, "requires": m.get("requires", []),
                "source": m.get("_source", "bundled"), "bundle": (m.get("_installed") or {}).get("bundle") or "",
                "routes": [{"method": r["method"], "path": r["path"], "label": r.get("label", ""),
                            "allow": self.permission(r, user)} for r in m.get("routes", [])],
            })
        return out


def _schema_keys(schema):
    from .bodyschema import top_keys
    return top_keys(schema)


def _canon_val(x):
    """A value as the condition compares it: booleans as true/false, numbers without leading zeros or .0, text casefolded."""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, (int, float)):
        return str(int(x)) if float(x).is_integer() else str(x)
    t = str(x).strip()
    if re.fullmatch(r"[+-]?\d+(?:\.0*)?", t):
        return str(int(float(t)))
    return t.casefold()


def _cond_hit(got, want):
    """Does the request's value `got` contain the protected value `want` (also in a list or a comma list)?"""
    if got is None:
        return False
    w = _canon_val(want)
    vals = got if isinstance(got, list) else ([got] if not isinstance(got, str) else got.split(","))
    return any(_canon_val(v) == w for v in vals if not isinstance(v, (dict, list)))
