"""Manifest format v2 (`"manifest": 2`): strict, and free of anything specific to one installation.

The only manifest format (v1, the loose one, was removed on 2026-11-15; docs/modules.md is the full reference):
  * unknown keys are an error at every level (a typo such as "owner-only" must not silently grant access)
  * every write route says who may call it: `min` or `owner_only` (deny by default)
  * `version` (semver), `kind` (community | private), `category`, `requires`, `min_core`
  * `config`: the fields this module needs per installation (URL, API key, login …) plus a test call. The backend is a
    template filled from that config — no addresses or credentials in the manifest:
        "backend": {"url": "{url}/api", "tls_verify": "{verify_tls}",
                    "auth": {"type": "header", "name": "Authorization", "prefix": "Bearer ", "secret": "token"}}
    Secret fields (type "secret") are stored encrypted (secretbox.py) and never sent to the browser.
  * per-installation policy lives in settings, not in the manifest: `_protect` (owner-only path patterns for writes,
    e.g. the guests that hold your keys) replaces hardcoded IDs.
"""
import re

from . import bodyschema
from .registry import METHODS, ROLES, SETTING_TYPES, ID_RE, ManifestError, _compile

CATEGORIES = ("infrastructure", "network", "media", "identity", "monitoring", "apps", "tools")
KINDS = ("community", "private")
FIELD_TYPES = ("url", "text", "secret", "bool", "int", "enum", "list")
SEMVER = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}(?:-[0-9A-Za-z.-]{1,30})?$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]{0,40})\}")

TOP = {"manifest", "id", "name", "version", "kind", "category", "icon", "description", "min_core", "requires", "access",
       "backend", "config", "routes", "settings", "guest_safe", "delegate", "connector"}
ROUTE = {"method", "path", "label", "min", "owner_only", "secret", "audit", "body_allow", "body_keys", "body_list",
         "body_schema", "query_keys", "max_body", "cache", "timeout"}
BACKEND = {"url", "health", "timeout", "tls_verify", "decodes_slashes", "headers", "auth"}
AUTH = {"type", "secret", "name", "prefix", "username", "password"}
FIELD = {"key", "type", "label", "help", "required", "default", "options", "placeholder", "min", "max", "multiline"}
CONNECTOR = {"uses_credentials_of"}
CONNECTOR_URL = re.compile(r"^http://127\.0\.0\.1:(\d{2,5})/?$")
SETTING = {"key", "type", "label", "help", "default", "options", "min", "max"}
VALIDATE = {"method", "path", "expect", "json"}


def _strict(obj, allowed, where):
    if not isinstance(obj, dict):
        raise ManifestError(f"{where} must be an object")
    extra = set(obj) - allowed
    if extra:
        raise ManifestError(f"{where}: unknown key(s) {sorted(extra)} (allowed: {sorted(allowed)})")


def requires(m, mid):
    """`requires`: the other modules whose loaded data this module reads (ctx.peer) or acts through (ctx.via), as
    [{"id", "optional"}]. "*" (any module) is only for a delegating module (the AI assistant reads everything as the
    user). The browser enforces it (ui/src/lib/lab.svelte.js), the deploy gate checks
    the source (tests/isolation.mjs)."""
    raw = m.get("requires", [])
    if not isinstance(raw, list):
        raise ManifestError(f"{mid}: requires must be a list")
    req, seen = [], set()
    for r in raw:
        r = {"id": r} if isinstance(r, str) else r
        _strict(r, {"id", "optional"}, f"{mid}: requires entry")
        rid = r.get("id")
        if not (isinstance(rid, str) and (ID_RE.match(rid) or rid == "*")) or not isinstance(r.get("optional", False), bool):
            raise ManifestError(f"{mid}: requires entries are module ids or {{id, optional}}")
        if rid == "*" and m.get("delegate") is not True:
            raise ManifestError(f"{mid}: requires \"*\" is only for a delegating module (delegate: true)")
        if rid == mid or rid in seen:
            raise ManifestError(f"{mid}: requires lists {rid!r} twice or itself")
        seen.add(rid)
        req.append({"id": rid, "optional": r.get("optional", False)})
    return req


def validate_v2(m, folder_id=None):
    _strict(m, TOP, "manifest")
    mid = m.get("id")
    if not isinstance(mid, str) or not ID_RE.match(mid):
        raise ManifestError(f"bad id: {mid!r}")
    if folder_id and folder_id != mid:
        raise ManifestError(f"id {mid!r} does not match folder {folder_id!r}")
    for k in ("name", "version", "kind", "category"):
        if not isinstance(m.get(k), str) or not m[k]:
            raise ManifestError(f"{mid}: {k} missing")
    if not SEMVER.match(m["version"]):
        raise ManifestError(f"{mid}: version must be semver (1.2.3)")
    if m["kind"] not in KINDS:
        raise ManifestError(f"{mid}: kind must be one of {KINDS}")
    if m["category"] not in CATEGORIES:
        raise ManifestError(f"{mid}: category must be one of {CATEGORIES}")
    if "min_core" in m and not (isinstance(m["min_core"], str) and SEMVER.match(m["min_core"])):
        raise ManifestError(f"{mid}: min_core must be semver")
    for k in ("icon", "description"):
        if k in m and not isinstance(m[k], str):
            raise ManifestError(f"{mid}: {k} must be text")

    m["requires"] = requires(m, mid)

    acc = m.setdefault("access", {})
    _strict(acc, {"roles", "groups"}, f"{mid}: access")
    acc.setdefault("roles", ["owner", "admin"])
    acc.setdefault("groups", [])
    if not all(r in ROLES for r in acc["roles"]) or not all(isinstance(g, str) for g in acc["groups"]):
        raise ManifestError(f"{mid}: access.roles are {ROLES}, access.groups are group names")

    fields = _config(m, mid)
    be = m.get("backend")
    if be is not None:
        _backend(be, fields, mid)
    m["delegate"] = m.get("delegate", False)
    if m["delegate"] is not False and not (m["delegate"] is True and be and re.match(r"^http://127\.0\.0\.1:\d+/?$", be["url"])):
        raise ManifestError(f"{mid}: delegate: true is only for a connector on 127.0.0.1 (it acts as the user)")
    _connector(m, mid, be)
    if "guest_safe" in m and not isinstance(m["guest_safe"], bool):
        raise ManifestError(f"{mid}: guest_safe must be true/false")

    routes = m.setdefault("routes", [])
    if not isinstance(routes, list):
        raise ManifestError(f"{mid}: routes must be a list")
    for r in routes:
        _strict(r, ROUTE, f"{mid}: route {r.get('method')} {r.get('path')}")
        if r.get("method") not in METHODS:
            raise ManifestError(f"{mid}: bad method in {r}")
        if "min" in r and r["min"] not in ROLES:
            raise ManifestError(f"{mid}: bad min in {r}")
        for b in ("owner_only", "secret", "audit", "body_list"):
            if b in r and not isinstance(r[b], bool):
                raise ManifestError(f"{mid}: {b} must be true/false in {r['method']} {r['path']}")
        if r["method"] != "GET" and "min" not in r and not r.get("owner_only"):
            raise ManifestError(f"{mid}: write route {r['method']} {r['path']} must say who may call it (min or owner_only)")
        if r["method"] != "GET" and not r.get("label"):
            raise ManifestError(f"{mid}: write route {r['method']} {r['path']} needs a label (it is what the audit log shows)")
        if "cache" in r and not (r["method"] == "GET" and isinstance(r["cache"], int) and not isinstance(r["cache"], bool)
                                 and 0 <= r["cache"] <= 300):
            raise ManifestError(f"{mid}: cache is 0..300 seconds, on GET routes only ({r['path']})")
        if "timeout" in r and not (isinstance(r["timeout"], (int, float)) and not isinstance(r["timeout"], bool)
                                   and 1 <= r["timeout"] <= 300):
            raise ManifestError(f"{mid}: route timeout must be 1..300 s ({r['path']})")
        if r.get("secret") and not r.get("owner_only"):
            raise ManifestError(f"{mid}: secret: true only means something with owner_only: true ({r['path']})")
        setting_keys = {st.get("key") for st in m.get("settings") or [] if isinstance(st, dict)}
        for seg in str(r.get("path") or "").split("/"):  # "{key}" = a whole segment from this installation's value
            if "{" in seg or "}" in seg:
                if not PLACEHOLDER.fullmatch(seg) or (seg[1:-1] not in fields and seg[1:-1] not in setting_keys):
                    raise ManifestError(f"{mid}: path placeholder {seg} must be a whole segment naming a config field or setting")
        if "body_schema" in r:  # nested body rules (bodyschema.py); replaces the flat body_keys/body_allow/body_list
            if r["method"] == "GET" or any(k in r for k in ("body_keys", "body_allow", "body_list")):
                raise ManifestError(f"{mid}: body_schema is for writes and replaces body_keys/body_allow/body_list ({r['path']})")
            names = set()
            try:
                r["body_schema"] = bodyschema.compile_schema(r["body_schema"], f"{mid}: {r['method']} {r['path']} body_schema",
                                                             placeholders=names)
            except bodyschema.SchemaError as e:
                raise ManifestError(str(e)) from None
            bad = sorted(n for n in names if n not in fields and n not in setting_keys)
            if bad:
                raise ManifestError(f"{mid}: body_schema placeholder(s) {bad} are not config fields or settings")
        for vals in (r.get("body_allow") or {}).values():  # "{key}" = this installation's value (e.g. a storage name)
            for x in vals if isinstance(vals, list) else []:
                if isinstance(x, str) and PLACEHOLDER.fullmatch(x) and x[1:-1] not in fields and x[1:-1] not in setting_keys:
                    raise ManifestError(f"{mid}: body_allow placeholder {x} is not a config field or setting")
    if routes and be is None:
        raise ManifestError(f"{mid}: routes need a backend")

    seen = set()
    for st in m.setdefault("settings", []):
        _strict(st, SETTING, f"{mid}: setting")
        if not (KEY_RE.match(str(st.get("key") or "")) and st.get("type") in SETTING_TYPES and st["key"] not in seen):
            raise ManifestError(f"{mid}: bad setting {st!r}")
        seen.add(st["key"])
        if st["type"] == "enum" and not st.get("options"):
            raise ManifestError(f"{mid}: enum setting {st['key']} needs options")
    m["contributes"] = {}
    m["_v2"] = True
    return m


def _config(m, mid):
    cfg = m.get("config")
    if cfg is None:
        m["config"] = {"fields": [], "validate": None}
        return {}
    _strict(cfg, {"fields", "validate"}, f"{mid}: config")
    fields = {}
    for f in cfg.get("fields", []):
        _strict(f, FIELD, f"{mid}: config field")
        k = f.get("key")
        if not (isinstance(k, str) and KEY_RE.match(k)) or k in fields:
            raise ManifestError(f"{mid}: config field key {k!r} bad or repeated")
        if f.get("type") not in FIELD_TYPES:
            raise ManifestError(f"{mid}: config field {k}: type must be one of {FIELD_TYPES}")
        if f["type"] == "enum" and not (isinstance(f.get("options"), list) and f["options"]):
            raise ManifestError(f"{mid}: config field {k}: enum needs options")
        if f["type"] == "secret" and "default" in f:
            raise ManifestError(f"{mid}: config field {k}: a secret has no default")
        if not isinstance(f.get("label", ""), str) or not isinstance(f.get("required", False), bool):
            raise ManifestError(f"{mid}: config field {k}: label is text, required is true/false")
        if "multiline" in f and not (f["multiline"] is True and f["type"] in ("text", "secret")):
            raise ManifestError(f"{mid}: config field {k}: multiline: true is for text/secret fields (a PEM, an ssh key)")
        fields[k] = f
    v = cfg.get("validate")
    if v is not None:
        _strict(v, VALIDATE, f"{mid}: config.validate")
        if v.get("method", "GET") not in METHODS or not isinstance(v.get("path"), str) or not v["path"].startswith("/"):
            raise ManifestError(f"{mid}: config.validate = {{method, path, expect: [200]}}")
        if not all(isinstance(c, int) for c in v.get("expect", [200])):
            raise ManifestError(f"{mid}: config.validate.expect is a list of status codes")
        js = v.get("json")  # APIs that answer 200 even for a bad token (Technitium): {"status": "ok"} must be in the body
        if js is not None and not (isinstance(js, dict) and js and all(
                isinstance(k, str) and isinstance(x, (str, int, bool)) for k, x in js.items())):
            raise ManifestError(f"{mid}: config.validate.json maps top-level response fields to expected values")
    cfg.setdefault("fields", [])
    cfg.setdefault("validate", None)
    return fields


def _connector(m, mid, be):
    """`connector`: this module's backend is a connector that Labradoor runs and configures itself (connectors/<id>/,
    unit lab-connector@<id> as its own unix user). It gets ITS config — and, for `uses_credentials_of`, the rendered
    backend + credential of those modules (each must be in `requires`) — from the gateway (gateway/lab/connectors.py)."""
    c = m.get("connector")
    if c is None:
        m["connector"] = None
        return
    _strict(c, CONNECTOR, f"{mid}: connector")
    if not (be and CONNECTOR_URL.match(be["url"])):
        raise ManifestError(f"{mid}: a connector's backend.url is http://127.0.0.1:<port> (it runs on the lab host)")
    if be.get("auth"):
        raise ManifestError(f"{mid}: a connector verifies X-Lab-Auth itself; backend.auth is for third-party APIs")
    uses = c.setdefault("uses_credentials_of", [])
    req = {r["id"] for r in m["requires"]}
    if not (isinstance(uses, list) and len(uses) <= 30 and all(isinstance(u, str) and ID_RE.match(u) for u in uses)):
        raise ManifestError(f"{mid}: connector.uses_credentials_of is a list of module ids")
    for u in uses:
        if u == mid or u not in req:
            raise ManifestError(f"{mid}: connector.uses_credentials_of {u!r} must be another module listed in requires")
    c["uses_credentials_of"] = sorted(set(uses))
    c["port"] = int(CONNECTOR_URL.match(be["url"]).group(1))


def _backend(be, fields, mid):
    _strict(be, BACKEND, f"{mid}: backend")
    if not isinstance(be.get("url"), str) or not be["url"]:
        raise ManifestError(f"{mid}: backend.url missing")
    for name in PLACEHOLDER.findall(be["url"]):
        f = fields.get(name)
        if not f or f["type"] not in ("url", "text", "int", "enum"):
            raise ManifestError(f"{mid}: backend.url placeholder {{{name}}} must be a url/text/int/enum config field")
    tv = be.get("tls_verify")
    if tv is not None and not (isinstance(tv, bool) or (isinstance(tv, str) and PLACEHOLDER.fullmatch(tv)
                                                        and (fields.get(tv[1:-1]) or {}).get("type") == "bool")):
        raise ManifestError(f"{mid}: backend.tls_verify is true/false or a bool config field like \"{{verify_tls}}\"")
    if "decodes_slashes" in be and not isinstance(be["decodes_slashes"], bool):
        raise ManifestError(f"{mid}: backend.decodes_slashes must be true/false")
    if "timeout" in be and not (isinstance(be["timeout"], (int, float)) and 1 <= be["timeout"] <= 300):
        raise ManifestError(f"{mid}: backend.timeout must be 1..300 s")
    if "health" in be and not (isinstance(be["health"], str) and be["health"].startswith("/")):
        raise ManifestError(f"{mid}: backend.health is a path")
    hdrs = be.get("headers")
    if hdrs is not None and not (isinstance(hdrs, dict) and len(hdrs) <= 8 and all(
            isinstance(k, str) and re.match(r"^[A-Za-z][A-Za-z0-9-]{1,40}$", k) and isinstance(v, str) and len(v) < 200
            and k.lower() not in ("authorization", "cookie", "host", "x-lab-auth", "x-forwarded-for") for k, v in hdrs.items())):
        raise ManifestError(f"{mid}: backend.headers must be a few static, non-credential headers")
    auth = be.get("auth")
    if auth is not None:
        _strict(auth, AUTH, f"{mid}: backend.auth")
        if auth.get("type") not in ("bearer", "header", "basic"):
            raise ManifestError(f"{mid}: backend.auth.type is bearer | header | basic")
        sf = fields.get(str(auth.get("secret") or ""))
        if not sf or sf["type"] != "secret":
            raise ManifestError(f"{mid}: backend.auth.secret must name a config field of type secret")
        if auth["type"] == "header" and not (re.match(r"^[A-Za-z][A-Za-z0-9-]{1,40}$", str(auth.get("name") or ""))
                                             and auth["name"].lower() not in ("cookie", "host", "x-lab-auth", "x-forwarded-for")):
            raise ManifestError(f"{mid}: backend.auth.name must be a header name")
        if auth["type"] == "basic":
            # user + secret password ({username: <text field>, secret}), or the secret as the user with a fixed password
            # ({secret, password: "token"} — Graylog's access tokens log in as "<token>:token")
            if "password" in auth:
                if not (isinstance(auth["password"], str) and 0 < len(auth["password"]) <= 100) or "username" in auth:
                    raise ManifestError(f"{mid}: basic auth: password is fixed text, used with the secret as the user")
            else:
                uf = fields.get(str(auth.get("username") or ""))
                if not uf or uf["type"] != "text":
                    raise ManifestError(f"{mid}: basic auth needs username: <a text config field> (or a fixed password)")
        elif "password" in auth or "username" in auth:
            raise ManifestError(f"{mid}: username/password belong to basic auth")


def render_routes(m, values):
    """Routes with this installation's values in body_allow placeholders ("{backup_storage}" → "pbs") and body_schema
    prefixes ("{import_paths}" → the folders of a list setting). values = settings
    (with defaults) overlaid by config. A placeholder with no value matches nothing (refuses every body until set).
    Use a SETTING when the UI must know the value too (config never reaches the browser)."""
    fields = {f["key"]: f for f in m["config"]["fields"]}
    fields.update({st["key"]: st for st in m.get("settings") or []})
    out = []
    for r in m["_routes_base"]:
        if "{" in r["path"]:  # a path placeholder: this installation's value, one safe segment, or the route matches nothing
            r = _render_path(r, values, fields)
        if r.get("body_schema") and bodyschema.has_placeholders(r["body_schema"]):  # "{import_paths}" → the folders
            r = {**r, "body_schema": bodyschema.render(
                r["body_schema"], lambda k: values.get(k, fields.get(k, {}).get("default")))}
        ba = r.get("body_allow")
        if not ba or not any(isinstance(x, str) and PLACEHOLDER.fullmatch(x) for v in ba.values() for x in v):
            out.append(r)
            continue
        new = {}
        for k, vals in ba.items():
            res = []
            for x in vals:
                if isinstance(x, str) and PLACEHOLDER.fullmatch(x):
                    v = values.get(x[1:-1], fields.get(x[1:-1], {}).get("default"))
                    if v not in (None, ""):
                        res.append(v)
                else:
                    res.append(x)
            new[k] = res or ["\0no value configured\0"]
        out.append({**r, "body_allow": new})
    return out


_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]{1,100}$")


def _render_path(r, values, fields):
    import re as _re
    from .registry import _compile

    def seg(x):
        if not PLACEHOLDER.fullmatch(x):
            return x
        v = values.get(x[1:-1], fields.get(x[1:-1], {}).get("default"))
        return str(v) if v not in (None, "") and _SEGMENT.match(str(v)) else "\0unset\0"
    path = "/".join(seg(x) for x in r["path"].split("/"))
    if "\0" in path:  # unset/unsafe value: a route that can never match
        rx = _re.compile(r"(?!)")
    else:
        rx = _compile(path)
    return {**r, "path": path, "_re": rx, "_re_i": _re.compile(rx.pattern, _re.IGNORECASE)}


def render(m, values):
    """The concrete backend for this installation, or (None, [missing required fields]).
    values: {field: value} incl. secrets (only their presence matters here; the proxy reads them itself)."""
    fields = {f["key"]: f for f in m["config"]["fields"]}
    missing = [k for k, f in fields.items() if f.get("required") and values.get(k) in (None, "")]
    tpl = m.get("_backend_tpl") or m.get("backend")
    if tpl is None:
        return None, missing
    if missing:
        return None, missing

    def val(k):
        v = values.get(k, fields.get(k, {}).get("default"))
        return v

    url = PLACEHOLDER.sub(lambda x: str(val(x.group(1)) or "").rstrip("/"), tpl["url"])
    be = {k: v for k, v in tpl.items() if k != "url"}
    be["url"] = url
    tv = tpl.get("tls_verify")
    if isinstance(tv, str):
        be["tls_verify"] = bool(val(tv[1:-1]) if val(tv[1:-1]) is not None else True)
    return be, []
