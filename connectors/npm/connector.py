"""Labradoor connector `npm`: the NPMplus admin API behind the gateway.

NPMplus logs in with POST /tokens and keeps the session in a cookie, which a manifest can't do, so this connector holds
the login and translates. It never returns the NPM credentials, the session, certificate private keys or access-list
passwords. Owner-only operations (delete, advanced nginx config, auth gate) are also re-checked here (defence in depth).

Config (module config, from the gateway — connectors/README.md): url (the admin UI, e.g. https://npm:81; the API is
<url>/api), username, password (a dedicated non-admin NPM user), verify_tls.
"""
import calendar
import http.cookiejar
import json
import logging
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/opt/lab/sdk/python")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdk", "python"))
import labauth  # noqa: E402
import labconn  # noqa: E402

ID = os.environ.get("CONNECTOR_ID", "npm")
PORT = int(os.environ.get("PORT", "8110"))
KEY = labconn.load_key(ID)
CACHE_S = 10
PROBE_EVERY = 60
PROBE_TIMEOUT = 2.0
log = logging.getLogger(ID)

HOST_RE = re.compile(r"^(?=.{1,253}$)(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
TARGET_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
SECRET_LINE = re.compile(r"(password|passwd|secret|token|authorization|api[_-]?key|bearer|cookie)", re.I)
PROXY_PASS = re.compile(r"proxy_pass\s+(https?)://([A-Za-z0-9.-]+)(?::(\d+))?", re.I)


class NpmError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


# --- NPMplus session ---------------------------------------------------------------------------------------------
def api_url(url):
    url = (url or "").strip().rstrip("/")
    return url if not url or url.endswith("/api") else url + "/api"


class Npm:
    def __init__(self, url="", user="", password="", verify=True):
        self.url, self.user, self.password = api_url(url), user, password
        ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx),
                                              urllib.request.HTTPCookieProcessor(self.jar))
        self.lock = threading.Lock()
        self.logged = 0.0
        self.last_ok = 0.0
        self.last_error = ""

    def _raw(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        if not self.url:
            raise NpmError(503, "no NPMplus URL configured")
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "Accept": "application/json",
                                              "User-Agent": "lab-connector-npm/1"})
        try:
            with self.op.open(req, timeout=20) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read()[:2000]
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"error": {"message": raw.decode("utf-8", "replace")[:300]}}
        except (OSError, ValueError) as e:
            raise NpmError(502, f"npmplus unreachable: {e}") from None

    def login(self):
        if not (self.user and self.password):
            raise NpmError(503, "no NPMplus login configured")
        self.jar.clear()
        code, r = self._raw("POST", "/tokens", {"identity": self.user, "secret": self.password})
        if code != 200:
            self.last_error = f"login failed ({code})"
            raise NpmError(502, f"npmplus login failed ({code})")
        self.logged = time.time()

    def call(self, method, path, body=None):
        with self.lock:
            if not self.logged or time.time() - self.logged > 6 * 3600:
                self.login()
        code, r = self._raw(method, path, body)
        if code == 401:
            with self.lock:
                self.login()
            code, r = self._raw(method, path, body)
        if code >= 400:
            msg = (r.get("error") or {}).get("message") if isinstance(r, dict) else None
            self.last_error = f"{method} {path}: {code}"
            raise NpmError(code if code < 500 else 502, msg or f"npmplus {code}")
        self.last_ok = time.time()
        return r


NPM = Npm()


def configure(v, conf=None):
    """The module config (from the gateway) → the NPMplus session."""
    global NPM
    NPM = Npm(labconn.url(v, "url"), labconn.text(v, "username"), labconn.text(v, "password"), v.get("verify_tls") is not False)


CONF = labconn.Config(ID, KEY, apply=configure)


def validate(values):
    """Config test: log in with the CANDIDATE values."""
    n = Npm(labconn.url(values, "url"), labconn.text(values, "username"), labconn.text(values, "password"),
            values.get("verify_tls") is not False)
    try:
        n.login()
        n.call("GET", "/users/me")
    except NpmError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "detail": "logged in to NPMplus"}


# --- backend reachability (TCP connect from the lab CT) ------------------------------------------------------------
class Probes:
    """state per (host, port): up | refused | timeout | error, refreshed in the background at most once a minute."""

    def __init__(self):
        self.state, self.at, self.lock = {}, 0.0, threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=16)
        self.running = False

    @staticmethod
    def probe(host, port):
        t0 = time.monotonic()
        try:
            with socket.create_connection((host, int(port)), timeout=PROBE_TIMEOUT):
                return {"state": "up", "ms": round((time.monotonic() - t0) * 1000, 1), "at": time.time()}
        except ConnectionRefusedError:
            return {"state": "refused", "ms": None, "at": time.time()}
        except (socket.timeout, TimeoutError):
            return {"state": "timeout", "ms": None, "at": time.time()}
        except OSError as e:
            return {"state": "error", "ms": None, "at": time.time(), "error": str(e)[:80]}

    def refresh(self, targets):
        with self.lock:
            if self.running or time.time() - self.at < PROBE_EVERY:
                return
            self.running = True

        def run():
            try:
                futs = {t: self.pool.submit(self.probe, *t) for t in set(targets)}
                fresh = {f"{h}:{p}": f.result() for (h, p), f in futs.items()}
                with self.lock:
                    self.state, self.at = fresh, time.time()
            finally:
                self.running = False
        threading.Thread(target=run, daemon=True).start()

    def get(self, host, port):
        return self.state.get(f"{host}:{port}")


PROBES = Probes()


# --- translation -------------------------------------------------------------------------------------------------
def ts(s):
    """NPM dates ('2026-11-19 05:47:04' UTC or ISO) → unix seconds."""
    if not s:
        return None
    try:
        return calendar.timegm(time.strptime(str(s)[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None


def redact(text):
    return "\n".join("# [redacted by lab: may hold a credential]" if SECRET_LINE.search(line) else line
                     for line in (text or "").splitlines())


def extra_targets(adv):
    out = []
    for scheme, host, port in PROXY_PASS.findall(adv or ""):
        out.append({"scheme": scheme.lower(), "host": host, "port": int(port or (443 if scheme.lower() == "https" else 80))})
    return out


def host_out(h):
    adv = h.get("advanced_config") or ""
    extra = extra_targets(adv)
    meta = h.get("meta") or {}
    return {
        "id": h["id"], "domains": h.get("domain_names") or [], "scheme": h.get("forward_scheme"),
        "host": h.get("forward_host"), "port": h.get("forward_port"), "enabled": bool(h.get("enabled")),
        "online": meta.get("nginx_online"), "err": meta.get("nginx_err"), "certId": h.get("certificate_id") or 0,
        "sslForced": bool(h.get("ssl_forced")), "http2": bool(h.get("http2_support")), "hsts": bool(h.get("hsts_enabled")),
        "hstsSub": bool(h.get("hsts_subdomains")), "websockets": bool(h.get("allow_websocket_upgrade")),
        "blockExploits": bool(h.get("block_exploits")), "caching": bool(h.get("caching_enabled")),
        "accessLists": h.get("npmplus_access_list_ids") or ([h["access_list_id"]] if h.get("access_list_id") else []),
        "accessType": h.get("npmplus_access_list_type") or ("custom" if h.get("access_list_id") else "public"),
        "authRequest": h.get("npmplus_auth_request") or "none",
        "originLock": bool(re.search(r"^\s*ssl_verify_client\s+on", adv, re.M)),
        "advanced": redact(adv), "extra": extra, "locations": len(h.get("locations") or []),
        "created": ts(h.get("created_on")), "modified": ts(h.get("modified_on")),
        "backend": PROBES.get(h.get("forward_host"), h.get("forward_port")),
        "extraBackend": [PROBES.get(x["host"], x["port"]) for x in extra],
    }


def cert_out(c):
    return {"id": c["id"], "name": c.get("nice_name") or ", ".join(c.get("domain_names") or []),
            "domains": c.get("domain_names") or [], "provider": c.get("provider"), "expires": ts(c.get("expires_on")),
            "created": ts(c.get("created_on")), "modified": ts(c.get("modified_on")),
            "dnsChallenge": bool((c.get("meta") or {}).get("dns_challenge"))}


def acl_out(a):
    return {"id": a["id"], "name": a.get("name"), "satisfyAny": bool(a.get("satisfy_any")),
            "passAuth": bool(a.get("pass_auth")), "hosts": a.get("proxy_host_count"),
            "clients": [{"address": c.get("address"), "directive": c.get("directive")} for c in a.get("clients") or []],
            "authUsers": len(a.get("items") or [])}  # basic-auth users: count only, never names/passwords


def simple_out(h, kind):
    meta = h.get("meta") or {}
    out = {"id": h["id"], "kind": kind, "domains": h.get("domain_names") or [], "enabled": bool(h.get("enabled")),
           "online": meta.get("nginx_online"), "err": meta.get("nginx_err"), "certId": h.get("certificate_id") or 0}
    if kind == "redirection":
        out.update({"target": h.get("forward_domain_name"), "scheme": h.get("forward_scheme"),
                    "code": h.get("forward_http_code"), "keepPath": bool(h.get("preserve_path"))})
    return out


_cache = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()


def overview(force=False):
    with _cache_lock:
        if not force and _cache["data"] and time.time() - _cache["at"] < CACHE_S:
            return _cache["data"]
    hosts = NPM.call("GET", "/nginx/proxy-hosts")
    certs = NPM.call("GET", "/nginx/certificates")
    acls = NPM.call("GET", "/nginx/access-lists?expand=items,clients")
    redirs = NPM.call("GET", "/nginx/redirection-hosts")
    dead = NPM.call("GET", "/nginx/dead-hosts")
    streams = NPM.call("GET", "/nginx/streams")
    targets = []
    for h in hosts:
        if h.get("forward_host") and h.get("forward_port"):
            targets.append((h["forward_host"], h["forward_port"]))
        targets += [(x["host"], x["port"]) for x in extra_targets(h.get("advanced_config"))]
    PROBES.refresh(targets)
    data = {
        "at": int(time.time()), "probedAt": int(PROBES.at) or None,
        "hosts": sorted((host_out(h) for h in hosts), key=lambda x: x["id"]),
        "certs": [cert_out(c) for c in certs],
        "accessLists": [acl_out(a) for a in acls],
        "redirections": [simple_out(h, "redirection") for h in redirs],
        "deadHosts": [simple_out(h, "404") for h in dead],
        "streams": [{"id": s["id"], "port": s.get("incoming_port"), "host": s.get("forwarding_host"),
                     "fport": s.get("forwarding_port"), "enabled": bool(s.get("enabled"))} for s in streams],
    }
    with _cache_lock:
        _cache.update(at=time.time(), data=data)
    return data


def invalidate():
    with _cache_lock:
        _cache["at"] = 0.0
    PROBES.at = 0.0


# --- writes ------------------------------------------------------------------------------------------------------
BOOLS = {"sslForced": "ssl_forced", "http2": "http2_support", "hsts": "hsts_enabled", "hstsSub": "hsts_subdomains",
         "websockets": "allow_websocket_upgrade", "blockExploits": "block_exploits", "caching": "caching_enabled"}


def safe_fields(b, creating=False):
    """lab field names → NPM fields, validated. Anything not listed here is refused, not passed through."""
    out = {}
    if "domains" in b or creating:
        ds = b.get("domains")
        if not isinstance(ds, list) or not ds or len(ds) > 20:
            raise NpmError(400, "domains: 1–20 names")
        ds = [str(d).strip().lower() for d in ds]
        bad = [d for d in ds if not HOST_RE.match(d)]
        if bad:
            raise NpmError(400, f"not a hostname: {', '.join(bad)}")
        out["domain_names"] = ds
    if "scheme" in b or creating:
        if b.get("scheme") not in ("http", "https"):
            raise NpmError(400, "scheme: http or https")
        out["forward_scheme"] = b["scheme"]
    if "host" in b or creating:
        h = str(b.get("host") or "").strip()
        if not TARGET_RE.match(h):
            raise NpmError(400, "host: an IP address or hostname")
        out["forward_host"] = h
    if "port" in b or creating:
        try:
            p = int(b.get("port"))
        except (TypeError, ValueError):
            p = 0
        if not 1 <= p <= 65535:
            raise NpmError(400, "port: 1–65535")
        out["forward_port"] = p
    if "certId" in b:
        try:
            out["certificate_id"] = max(0, int(b["certId"]))
        except (TypeError, ValueError):
            raise NpmError(400, "certId: a number") from None
    for k, f in BOOLS.items():
        if k in b:
            out[f] = bool(b[k])
    return out


def acl_fields(b):
    if "accessLists" not in b:
        return {}
    ids = b["accessLists"]
    if not isinstance(ids, list) or not all(isinstance(i, int) and i > 0 for i in ids):
        raise NpmError(400, "accessLists: list of access list ids")
    return {"npmplus_access_list_ids": ids, "npmplus_access_list_type": "custom" if ids else "public"}


def create_host(b):
    base = safe_fields(b, creating=True)
    base.setdefault("certificate_id", 0)
    for f in BOOLS.values():
        base.setdefault(f, False)
    # NPMplus rejects unknown fields on create; locations must be [] (null breaks the auth upstream template)
    created = NPM.call("POST", "/nginx/proxy-hosts", {**base, "meta": {}, "advanced_config": "", "locations": []})
    extra = acl_fields(b)
    if extra:
        NPM.call("PUT", f"/nginx/proxy-hosts/{created['id']}", extra)
    return created["id"]


def owner_ok(claims):
    return claims.get("r") == "owner" or bool(claims.get("a"))


# --- HTTP --------------------------------------------------------------------------------------------------------
ROUTES = []


def route(method, pattern, min_role="guest", owner=False):
    rx = re.compile("^" + pattern + "/?$")

    def deco(fn):
        ROUTES.append((method, rx, min_role, owner, fn))
        return fn
    return deco


@route("GET", "/api/overview")
def r_overview(c, m, b, q):
    return 200, overview(force=q.get("fresh") == ["1"])


@route("POST", "/api/hosts", "admin")
def r_create(c, m, b, q):
    hid = create_host(b)
    log.info("%s created proxy host %s %s", c["u"], hid, b.get("domains"))
    invalidate()
    return 200, {"ok": True, "id": hid}


@route("PUT", r"/api/hosts/(\d+)", "admin")
def r_edit(c, m, b, q):
    fields = {**safe_fields(b), **acl_fields(b)}
    if not fields:
        raise NpmError(400, "nothing to change")
    NPM.call("PUT", f"/nginx/proxy-hosts/{m[0]}", fields)
    log.info("%s edited proxy host %s: %s", c["u"], m[0], sorted(fields))
    invalidate()
    return 200, {"ok": True}


@route("GET", r"/api/hosts/(\d+)/advanced", owner=True)
def r_adv_get(c, m, b, q):
    h = NPM.call("GET", f"/nginx/proxy-hosts/{m[0]}")
    return 200, {"id": h["id"], "advanced": h.get("advanced_config") or "", "authRequest": h.get("npmplus_auth_request")}


@route("PUT", r"/api/hosts/(\d+)/advanced", owner=True)
def r_adv_put(c, m, b, q):
    fields = {}
    if "advanced" in b:
        if not isinstance(b["advanced"], str) or len(b["advanced"]) > 16000:
            raise NpmError(400, "advanced: text up to 16k")
        fields["advanced_config"] = b["advanced"]
    if "authRequest" in b:
        if b["authRequest"] not in ("none", "authentik", "tinyauth"):
            raise NpmError(400, "authRequest: none | authentik | tinyauth")
        fields["npmplus_auth_request"] = b["authRequest"]
    if not fields:
        raise NpmError(400, "nothing to change")
    NPM.call("PUT", f"/nginx/proxy-hosts/{m[0]}", fields)
    log.info("%s changed advanced config of proxy host %s (approved by %s)", c["u"], m[0], c.get("a") or "-")
    invalidate()
    return 200, {"ok": True}


KINDS = {"hosts": "proxy-hosts", "redirections": "redirection-hosts", "dead-hosts": "dead-hosts"}


@route("POST", r"/api/(hosts|redirections|dead-hosts)/(\d+)/(enable|disable)", "admin")
def r_toggle(c, m, b, q):
    NPM.call("POST", f"/nginx/{KINDS[m[0]]}/{m[1]}/{m[2]}")
    log.info("%s %sd %s %s", c["u"], m[2], m[0], m[1])
    invalidate()
    return 200, {"ok": True}


@route("DELETE", r"/api/(hosts|redirections|dead-hosts)/(\d+)", owner=True)
def r_delete(c, m, b, q):
    NPM.call("DELETE", f"/nginx/{KINDS[m[0]]}/{m[1]}")
    log.info("%s DELETED %s %s (approved by %s)", c["u"], m[0], m[1], c.get("a") or "-")
    invalidate()
    return 200, {"ok": True}


@route("POST", r"/api/certificates/(\d+)/renew", "admin")
def r_renew(c, m, b, q):
    NPM.call("POST", f"/nginx/certificates/{m[0]}/renew")
    log.info("%s renewed certificate %s", c["u"], m[0])
    invalidate()
    return 200, {"ok": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _claims(self):
        # per request, never cached on the handler (keep-alive connections carry many users)
        if self.client_address[0] != "127.0.0.1":
            return None
        return labauth.verify(self.headers.get(labauth.HEADER), KEY, ID)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 64 * 1024:
            raise NpmError(413, "body too large")
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            b = json.loads(raw)
        except ValueError:
            raise NpmError(400, "body must be JSON") from None
        if not isinstance(b, dict):
            raise NpmError(400, "body must be a JSON object")
        return b

    def _handle(self, method):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/healthz":
            return self._json(200, {"ok": True, "config": CONF.ready, "npm": bool(NPM.last_ok), "lastOk": int(NPM.last_ok) or None})
        claims = self._claims()
        if not claims:
            return self._json(401, {"error": "lab signature required"})
        try:
            body = self._body() if method in ("POST", "PUT", "PATCH") else {}
            if method == "POST" and url.path == "/api/_validate":
                try:
                    return self._json(200, validate(labconn.candidate(claims, body)))
                except PermissionError as e:
                    return self._json(403, {"error": str(e)})
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
            if not CONF.ready:
                return self._json(503, {"error": CONF.why()})
            for meth, rx, min_role, owner, fn in ROUTES:
                mm = rx.match(url.path)
                if meth != method or not mm:
                    continue
                if owner and not owner_ok(claims):
                    return self._json(403, {"error": "owner only"})
                if not labauth.at_least(claims, min_role):
                    return self._json(403, {"error": "not allowed"})
                code, obj = fn(claims, mm.groups(), body, urllib.parse.parse_qs(url.query))
                return self._json(code, obj)
            return self._json(404, {"error": "not found"})
        except NpmError as e:
            return self._json(e.code, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            log.exception("request failed")
            return self._json(500, {"error": f"connector error: {type(e).__name__}"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


class PooledHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    pool = ThreadPoolExecutor(max_workers=8)

    def process_request(self, request, client_address):
        self.pool.submit(self.process_request_thread, request, client_address)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    log.info("connector %s on 127.0.0.1:%s (key %s)", ID, PORT, "ok" if KEY else "MISSING")
    CONF.start()
    PooledHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
