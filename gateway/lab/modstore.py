"""Modules from catalogs (mixed into server.Handler; owner only). Settings → Modules. docs/catalog.md.

The gateway runs as the unprivileged user lab and never writes module code: it asks the root helper
deploy/lab-module-helper (socket /run/lab-module-helper.sock, group lab only), which verifies every catalog and package
against the trusted publisher keys (/etc/lab/publishers.d, root-only: `lab-admin publisher add FILE`) and installs into
/var/lib/lab-modules (root's, read-only here). Module UI code runs in the page with the viewer's rights, so only signed
packages from publishers the host's root trusts can be installed.

  GET  /api/modules/store                    catalogs (URLs saved here), the helper's status (installed modules,
                                             publishers, checked catalogs), bundled modules, this core's svelte ABI
  POST /api/modules/catalogs {url, remove?}  add / remove a catalog URL (adding checks it: it must be signed by a
                                             trusted publisher)
  POST /api/modules/check {url?}             fetch + verify one or every catalog → modules, versions, what's installable
  POST /api/modules/stage {id, version, catalog?}   download + verify → what the module asks for (the install dialog)
  POST /api/modules/install {id, version}    install the staged version
  POST /api/modules/update {id, version}     update an installed module to the staged version (same publisher)
  POST /api/modules/rollback {id}            back to the version before
  POST /api/modules/remove {id, keep_config} remove it; keep_config false also drops its config + settings here

Every step is audited (module-catalog-add/-remove, module-check, module-stage, module-install, module-update,
module-rollback, module-remove)."""
import json
import socket
import time
import urllib.parse

from . import config
from .errors import HTTPError
from .login_api import NOT_MINE
from .modpkg import ID_RE, is_version

CATALOGS_KEY = "module_catalogs"   # gateway_config: [{"url", "added", "by"}]
MAX_CATALOGS = 20


class ModuleHelperError(Exception):
    def __init__(self, msg, extra=None):
        super().__init__(msg)
        self.extra = extra or {}


def call_module_helper(req, timeout=120, path=None):
    """One request to the module helper: one JSON line in, one JSON line out ({"ok": bool, ...})."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path or config.MODULE_HELPER)
            s.sendall(json.dumps(req).encode() + b"\n")
            s.shutdown(socket.SHUT_WR)
            buf = b""
            while len(buf) < 4 << 20:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
    except OSError as e:
        raise ModuleHelperError(f"module helper unavailable ({e.__class__.__name__}): is lab-module-helper.socket "
                                "running?") from None
    try:
        out = json.loads(buf.decode() or "{}")
    except ValueError:
        raise ModuleHelperError("module helper gave no answer") from None
    if not out.get("ok"):
        raise ModuleHelperError(str(out.get("error") or "module helper refused"),
                                {k: v for k, v in out.items() if k in ("signer",)})
    out.pop("ok", None)
    return out


def check_catalog_url(v):
    if not isinstance(v, str) or not v or len(v) > 2048 or any(c in v for c in "\r\n\t "):
        raise HTTPError(400, "url: one catalog URL")
    p = urllib.parse.urlsplit(v)
    if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password or p.fragment:
        raise HTTPError(400, "url: an https:// URL of a catalog.json (http:// only for a LAN test server, if the host "
                             "allows it)")
    return v


def catalogs(store):
    v = store.gateway_config().get(CATALOGS_KEY, (None, False))[0]
    return [c for c in v if isinstance(c, dict) and isinstance(c.get("url"), str)] if isinstance(v, list) else []


class ModuleStoreRoutes:
    _MODULE_TIMEOUTS = {"catalog-check": 120, "stage": 600, "install": 180, "update": 180, "rollback": 120,
                        "remove": 120, "status": 60}

    def _module_call(self, req):
        call = getattr(self.app, "module_helper", None) or call_module_helper
        try:
            return call(req, timeout=self._MODULE_TIMEOUTS.get(req.get("op"), 120))
        except ModuleHelperError as e:
            code = 502 if "unavailable" in str(e) or "no answer" in str(e) else 409
            raise HTTPError(code, str(e), **e.extra) from None

    def _modstore_get(self, path):
        if path != "/api/modules/store":
            return NOT_MINE
        u = self._need("owner")
        a = self.app
        try:
            status, helper_error = self._module_call({"op": "status", "by": u["username"]}), ""
        except HTTPError as e:
            status, helper_error = None, e.msg
        reg = a.registry
        bundled = sorted(({"id": m["id"], "version": m.get("version"), "source": m.get("_source", "bundled"),
                           "installed": (m.get("_installed") or {}).get("version")} for m in reg.modules.values()),
                         key=lambda x: x["id"])
        return self._json(200, {"catalogs": catalogs(a.store), "helper": status, "helperError": helper_error,
                                "modules": bundled, "shadowed": reg.shadowed})

    def _modstore_post(self, path):
        if not path.startswith("/api/modules/"):
            return NOT_MINE
        u = self._need("owner")
        a = self.app
        verb = path[len("/api/modules/"):]
        data = self._body()
        if verb == "catalogs":
            url = check_catalog_url(data.get("url"))
            have = catalogs(a.store)
            if data.get("remove"):
                left = [c for c in have if c["url"] != url]
                a.store.set_gateway_config(CATALOGS_KEY, left)
                a.store.audit(u, "module-catalog-remove", "_modules", url[:200], "ok" if len(left) < len(have) else "absent")
                return self._json(200, {"catalogs": left})
            if any(c["url"] == url for c in have):
                raise HTTPError(409, "that catalog is in the list already")
            if len(have) >= MAX_CATALOGS:
                raise HTTPError(409, f"at most {MAX_CATALOGS} catalogs")
            out = self._module_step(u, "catalog-check", {"index": url}, url, audit_as="module-catalog-add")
            have.append({"url": url, "added": round(time.time()), "by": u["username"],
                         "name": out["catalog"].get("name") or "", "publisher": out["catalog"].get("publisher")})
            a.store.set_gateway_config(CATALOGS_KEY, have)
            return self._json(200, {"catalogs": have, "check": out})
        if verb == "check":
            urls = [check_catalog_url(data["url"])] if data.get("url") else [c["url"] for c in catalogs(a.store)]
            results = []
            for url in urls:
                try:
                    results.append({"url": url, "ok": True, **self._module_step(u, "catalog-check", {"index": url}, url,
                                                                                 audit_as="module-check")})
                except HTTPError as e:
                    results.append({"url": url, "ok": False, "error": e.msg, **e.extra})
            return self._json(200, {"results": results})
        mid, ver = data.get("id"), data.get("version")
        if not (isinstance(mid, str) and ID_RE.match(mid)):
            raise HTTPError(400, "id: a module id")
        if verb in ("stage", "install", "update") and not is_version(ver):
            raise HTTPError(400, "version: a module version")
        if verb == "stage":
            req = {"id": mid, "version": ver}
            if data.get("catalog"):
                req["catalog"] = check_catalog_url(data["catalog"])
            return self._json(200, self._module_step(u, "stage", req, f"{mid} {ver}"))
        if verb in ("install", "update"):
            out = self._module_step(u, verb, {"id": mid, "version": ver}, f"{mid} {ver}")
            self._modules_changed(mid)
            return self._json(200, out)
        if verb == "rollback":
            out = self._module_step(u, "rollback", {"id": mid}, mid)
            self._modules_changed(mid)
            return self._json(200, out)
        if verb == "remove":
            keep = data.get("keep_config", True)
            if not isinstance(keep, bool):
                raise HTTPError(400, "keep_config: true or false")
            out = self._module_step(u, "remove", {"id": mid, "keep_config": keep},
                                    f"{mid}{'' if keep else ' + config'}")
            if not keep and not out.get("bundled_remains"):
                dropped = a.store.drop_module(mid)
                out["config_dropped"] = dropped
            self._modules_changed(mid)
            return self._json(200, out)
        raise HTTPError(404, "not found")

    def _module_step(self, u, op, req, target, audit_as=None):
        action = audit_as or f"module-{op}"
        try:
            out = self._module_call({"op": op, **req, "by": u["username"]})
        except HTTPError as e:
            self.app.store.audit(u, action, req.get("id") or "_modules", target[:200], "refused", e.msg)
            raise
        detail = {
            "catalog-check": lambda: f"{out['catalog'].get('name') or '?'} · publisher {out['catalog']['publisher']['name']} "
                                     f"{out['catalog']['publisher']['fingerprint']} · {len(out.get('modules') or [])} modules",
            "stage": lambda: f"sha256 {out['staged']['sha256'][:16]} · publisher {out['staged']['publisher']['name']} · "
                             f"{out['staged']['permissions']['writes']} write routes, "
                             f"{out['staged']['permissions']['owner_only']} owner-only"
                             f"{', connector' if out['staged']['permissions']['connector'] else ''}",
            "install": lambda: f"{out.get('version')} from {out.get('publisher', {}).get('name')}",
            "update": lambda: f"{out.get('previous')} → {out.get('version')}",
            "rollback": lambda: f"{out.get('from')} → {out.get('version')}",
            "remove": lambda: f"{out.get('version')} removed{'' if out.get('kept_config') else ', config dropped'}"
                              f"{'; bundled ' + out['bundled_remains'] + ' remains' if out.get('bundled_remains') else ''}",
        }.get(op, lambda: "")()
        self.app.store.audit(u, action, req.get("id") or "_modules", target[:200], "ok", detail)
        return out

    def _modules_changed(self, mid):
        """The set of installed modules changed: reload the registry (installed + bundled), the config view, tell every
        tab (they reload /api/registry and import the new UI), and bring a connector to its wanted state."""
        a = self.app
        a.registry.load()
        a.reload_config()
        a._installed_checked = 0
        m = a.registry.get(mid)
        if m and m.get("connector"):
            a.connectors.apply(mid, restart=False)
