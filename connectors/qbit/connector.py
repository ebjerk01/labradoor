"""Labradoor connector `qbit`: the qBittorrent WebUI API (cookie login) for the module `qbit`.

Config (module config, from the gateway — connectors/README.md): url (the WebUI), username, password. qBittorrent has
ONE WebUI user (no API keys), so this is usually the same login the *arr apps use.

Routes (all need a valid X-Lab-Auth from the gateway; reads need admin, writes admin — the gateway checks the manifest too):
  GET  /api/overview                 transfer info + every torrent (compact; no trackers/peers: private tracker URLs carry passkeys)
  GET  /api/torrents/<hash>/files    file list of one torrent (spot .exe/.scr fakes)
  POST /api/torrents/stop|start|recheck|reannounce   {"hashes": [...]}
  POST /api/torrents/delete          {"hashes": [...]}   removes the torrent, KEEPS the data
  POST /api/torrents/delete-data     {"hashes": [...]}   removes the torrent AND its files
  POST /api/torrents/add             {"urls": "magnet:?... or http(s) URL, one per line", "category"?, "paused"?}
  GET  /api/categories               {"categories": [{"name", "save_path"}]}
  POST /api/categories               {"name", "save_path"?}   creates the category, or edits its save path when it exists
  POST /api/limits                   {"dl"?, "up"?}   global speed limits in bytes/s (0 = unlimited)
  POST /api/alt-speed                {"enabled": bool}   alternative speed limits on/off
The SID cookie never leaves this process."""
import http.client
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/opt/lab/sdk/python")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "sdk", "python"))
import labauth  # noqa: E402
import labconn  # noqa: E402

ID = os.environ.get("CONNECTOR_ID", "qbit")
PORT = int(os.environ.get("PORT", "8113"))
LAB_FROM = "127.0.0.1"
log = logging.getLogger(ID)

HASH_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")
MAX_HASHES = 300
MAX_URLS = 20
MAX_URL_LEN = 4096
MAGNET_RE = re.compile(r"^magnet:\?(?=[^\s]*xt=urn:(?:btih|btmh):)[^\s]+$", re.I)
HTTP_RE = re.compile(r"^https?://[^\s/@]+(?::\d+)?(?:/[^\s]*)?$", re.I)   # no user:pass@host
CATEGORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-]{0,63}(?:/[A-Za-z0-9][A-Za-z0-9 ._\-]{0,63}){0,3}$")
MAX_LIMIT = 10 * 1024 ** 3     # bytes/s; anything above is a typo
# compact torrent fields sent to the browser (no tracker, magnet_uri, comment, download_path: they can carry passkeys)
FIELDS = ("hash", "name", "category", "tags", "state", "progress", "dlspeed", "upspeed", "size", "total_size",
          "amount_left", "completed", "downloaded", "uploaded", "eta", "ratio", "added_on", "completion_on",
          "last_activity", "num_seeds", "num_leechs", "num_complete", "num_incomplete", "availability",
          "priority", "save_path", "force_start", "seq_dl", "time_active", "seeding_time", "content_path")
# qBittorrent 5 renamed pause/resume → stop/start; 4.x still answers the old names
VERBS = {"stop": ("stop", "pause"), "start": ("start", "resume"), "recheck": ("recheck",), "reannounce": ("reannounce",)}


def load_key():
    return labconn.load_key(ID)


class QbitError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


class Qbit:
    """Tiny qBittorrent WebUI client: one SID cookie, re-login on 403, thread-safe."""

    def __init__(self, url, user, password):
        u = urllib.parse.urlsplit(url or "http://unset.invalid")
        self.scheme, self.host, self.port = u.scheme, u.hostname, u.port or (443 if u.scheme == "https" else 80)
        self.base = u.path.rstrip("/")
        self.user, self.password = user, password
        self.cookie = None
        self.lock = threading.Lock()
        self.version = None

    def _conn(self):
        cls = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        return cls(self.host, self.port, timeout=20)

    def _raw(self, method, path, form=None, cookie=None):
        body = urllib.parse.urlencode(form, doseq=True).encode() if form is not None else None
        h = {"User-Agent": "lab-connector-qbit/1"}
        if body is not None:
            h["Content-Type"] = "application/x-www-form-urlencoded"
        if cookie:
            h["Cookie"] = cookie
        c = self._conn()
        try:
            c.request(method, self.base + path, body=body, headers=h)
            r = c.getresponse()
            return r.status, r.getheaders(), r.read(32 * 1024 * 1024)
        except (OSError, http.client.HTTPException) as e:
            raise QbitError(502, f"qBittorrent unreachable: {e}") from None
        finally:
            c.close()

    def login(self):
        status, headers, data = self._raw("POST", "/api/v2/auth/login", {"username": self.user, "password": self.password})
        # 4.x: 200 "Ok." / "Fails."; 5.x: 204 empty on success, 401 on failure
        text = data.decode("utf-8", "replace").strip()
        if status not in (200, 204) or text == "Fails.":
            raise QbitError(502, f"qBittorrent login failed ({status})")
        for k, v in headers:
            if k.lower() == "set-cookie":
                pair = v.split(";", 1)[0].strip()
                if "SID" in pair.split("=", 1)[0]:
                    self.cookie = pair
                    return
        raise QbitError(502, "qBittorrent login gave no session cookie")

    def call(self, method, path, form=None):
        for attempt in (0, 1):
            with self.lock:
                if not self.cookie:
                    self.login()
                cookie = self.cookie
            status, _, data = self._raw(method, path, form, cookie)
            if status == 403 and attempt == 0:
                with self.lock:
                    if self.cookie == cookie:
                        self.cookie = None
                continue
            if status >= 400:
                raise QbitError(status if status in (400, 404, 409) else 502, f"qBittorrent {path}: HTTP {status}")
            return data
        raise QbitError(502, "qBittorrent: session refused")

    def json(self, path):
        data = self.call("GET", path)
        return json.loads(data) if data else None

    def app_version(self):
        if not self.version:
            self.version = self.call("GET", "/api/v2/app/version").decode().strip()
        return self.version


QB = Qbit("", "", "")


def configure(v, conf=None):
    global QB
    QB = Qbit(labconn.url(v, "url"), labconn.text(v, "username"), labconn.text(v, "password"))


CONF = labconn.Config(ID, None, apply=configure)


def validate(values):
    """Config test: log in with the CANDIDATE values and read the version."""
    q = Qbit(labconn.url(values, "url"), labconn.text(values, "username"), labconn.text(values, "password"))
    if not labconn.url(values, "url"):
        return {"ok": False, "error": "no URL"}
    try:
        q.login()
        v = q.app_version()
    except QbitError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "detail": f"logged in, qBittorrent {v}"}


def compact(t):
    return {k: t.get(k) for k in FIELDS if k in t}


def overview():
    info = QB.json("/api/v2/transfer/info") or {}
    torrents = QB.json("/api/v2/torrents/info") or []
    cats = QB.json("/api/v2/torrents/categories") or {}
    try:
        prefs = QB.json("/api/v2/app/preferences") or {}
    except QbitError:
        prefs = {}
    out = [compact(t) for t in torrents]
    return {
        "alt_speed": {"enabled": bool(info.get("use_alt_speed_limits")), "dl": prefs.get("alt_dl_limit"), "up": prefs.get("alt_up_limit")},  # KiB/s
        "version": QB.app_version(),
        "transfer": {k: info.get(k) for k in ("dl_info_speed", "up_info_speed", "dl_info_data", "up_info_data",
                                                "dl_rate_limit", "up_rate_limit", "dht_nodes", "connection_status")},
        "categories": sorted(cats.keys()),
        "torrents": out,
        "at": int(time.time()),
    }


def hashes_of(body):
    hs = body.get("hashes") if isinstance(body, dict) else None
    if not isinstance(hs, list) or not hs or len(hs) > MAX_HASHES:
        return None
    hs = [str(h).lower() for h in hs]
    return hs if all(HASH_RE.match(h) for h in hs) else None


def valid_urls(value):
    """`urls` as one string (newline separated) or a list → clean list of magnets / http(s) URLs, or None."""
    if isinstance(value, str):
        value = value.splitlines()
    if not isinstance(value, list) or not value or len(value) > MAX_URLS:
        return None
    out = []
    for u in value:
        if not isinstance(u, str):
            return None
        u = u.strip()
        if not u:
            continue
        if len(u) > MAX_URL_LEN or not (MAGNET_RE.match(u) or HTTP_RE.match(u)):
            return None
        out.append(u)
    return out or None


def categories():
    cats = QB.json("/api/v2/torrents/categories") or {}
    return {k: (v or {}).get("savePath", "") for k, v in cats.items()}


def valid_path(p):
    return isinstance(p, str) and len(p) <= 512 and p.startswith("/") and ".." not in p.split("/") and "\0" not in p and "\n" not in p


def add_torrents(body):
    """→ (status, answer). Category must already exist (create it with /api/categories first)."""
    urls = valid_urls(body.get("urls")) if isinstance(body, dict) else None
    if not urls:
        return 400, {"error": f"urls: 1..{MAX_URLS} magnet links or http(s) URLs"}
    form = {"urls": "\n".join(urls)}
    cat = body.get("category")
    if cat not in (None, ""):
        if not isinstance(cat, str) or cat not in categories():
            return 400, {"error": "category: must be one of qBittorrent's categories"}
        form["category"] = cat
    paused = body.get("paused", False)
    if not isinstance(paused, bool):
        return 400, {"error": "paused: true or false"}
    if paused:
        form["paused"] = "true"      # 4.x name
        form["stopped"] = "true"     # 5.x name
    QB.call("POST", "/api/v2/torrents/add", form)
    return 200, {"ok": True, "count": len(urls)}


def set_category(body):
    name = body.get("name") if isinstance(body, dict) else None
    if not isinstance(name, str) or not CATEGORY_RE.match(name) or ".." in name:
        return 400, {"error": "name: letters, digits, space . _ - (and / for sub-categories), at most 64 per part"}
    path = body.get("save_path", "")
    if path not in ("", None) and not valid_path(path):
        return 400, {"error": "save_path: an absolute path without .."}
    existing = categories()
    verb = "editCategory" if name in existing else "createCategory"
    if verb == "editCategory" and path in ("", None):
        return 200, {"ok": True, "verb": "unchanged"}
    QB.call("POST", f"/api/v2/torrents/{verb}", {"category": name, "savePath": path or ""})
    return 200, {"ok": True, "verb": "edited" if verb == "editCategory" else "created"}


def set_limits(body):
    if not isinstance(body, dict) or not set(body) & {"dl", "up"} or set(body) - {"dl", "up"}:
        return 400, {"error": "limits: dl and/or up, bytes per second (0 = unlimited)"}
    vals = {}
    for k in ("dl", "up"):
        if k in body:
            v = body[k]
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= MAX_LIMIT:
                return 400, {"error": f"{k}: whole bytes per second, 0..{MAX_LIMIT}"}
            vals[k] = v
    if "dl" in vals:
        QB.call("POST", "/api/v2/transfer/setDownloadLimit", {"limit": vals["dl"]})
    if "up" in vals:
        QB.call("POST", "/api/v2/transfer/setUploadLimit", {"limit": vals["up"]})
    return 200, {"ok": True, **vals}


def set_alt_speed(body):
    en = body.get("enabled") if isinstance(body, dict) else None
    if not isinstance(en, bool):
        return 400, {"error": "enabled: true or false"}
    now = QB.call("GET", "/api/v2/transfer/speedLimitsMode").decode().strip() == "1"
    if now != en:
        QB.call("POST", "/api/v2/transfer/toggleSpeedLimitsMode", {})
    return 200, {"ok": True, "enabled": en}


def act(verb, hashes):
    """verb in VERBS or delete/delete-data; tries qBittorrent 5 names first, falls back to 4.x on 404."""
    joined = "|".join(hashes)
    if verb in ("delete", "delete-data"):
        QB.call("POST", "/api/v2/torrents/delete",
                {"hashes": joined, "deleteFiles": "true" if verb == "delete-data" else "false"})
        return
    last = None
    for name in VERBS[verb]:
        try:
            QB.call("POST", f"/api/v2/torrents/{name}", {"hashes": joined})
            return
        except QbitError as e:
            if e.status != 404:
                raise
            last = e
    raise last


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    key = None

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _json(self, code, obj):
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _claims(self):
        # per request, never cached on the handler (keep-alive connections carry many users)
        if self.client_address[0] != LAB_FROM:
            return None
        return labauth.verify(self.headers.get(labauth.HEADER), Handler.key, ID)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 256 * 1024:
            return None
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return None

    def _guard(self):
        claims = self._claims()
        if not claims:
            self._json(401, {"error": "lab signature required"})
            return None
        if not labauth.at_least(claims, "admin"):
            self._json(403, {"error": "admin only"})
            return None
        return claims

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path.rstrip("/")
        if path == "/healthz":
            return self._json(200, {"ok": True, "key": bool(Handler.key), "config": CONF.ready})
        if not self._guard():
            return
        if not CONF.ready:
            return self._json(503, {"error": CONF.why()})
        try:
            if path == "/api/overview":
                return self._json(200, overview())
            if path == "/api/categories":
                return self._json(200, {"categories": [{"name": k, "save_path": v} for k, v in sorted(categories().items())]})
            m = re.match(r"^/api/torrents/([0-9a-f]{40}|[0-9a-f]{64})/files$", path)
            if m:
                files = QB.json(f"/api/v2/torrents/files?hash={m.group(1)}") or []
                return self._json(200, {"files": [{k: f.get(k) for k in ("name", "size", "progress", "priority")} for f in files]})
        except QbitError as e:
            return self._json(e.status, {"error": str(e)})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path.rstrip("/")
        if path == "/api/_validate":
            try:
                return self._json(200, validate(labconn.candidate(self._claims(), self._body())))
            except PermissionError as e:
                return self._json(403, {"error": str(e)})
            except ValueError as e:
                return self._json(400, {"error": str(e)})
        claims = self._guard()
        if not claims:
            return
        if not CONF.ready:
            return self._json(503, {"error": CONF.why()})
        simple = {"/api/torrents/add": ("add", add_torrents), "/api/categories": ("category", set_category),
                  "/api/limits": ("limits", set_limits), "/api/alt-speed": ("alt-speed", set_alt_speed)}
        if path in simple:
            name, fn = simple[path]
            body = self._body()
            if not isinstance(body, dict):
                return self._json(400, {"error": "JSON object body required"})
            try:
                code, out = fn(body)
            except QbitError as e:
                return self._json(e.status, {"error": str(e)})
            if code == 200:
                log.info("%s %s%s", claims["u"], name, f" (approved by {claims['a']})" if claims.get("a") else "")
            return self._json(code, out)
        m = re.match(r"^/api/torrents/(stop|start|recheck|reannounce|delete|delete-data)$", path)
        if not m:
            return self._json(404, {"error": "not found"})
        body = self._body()
        hashes = hashes_of(body)
        if not hashes:
            return self._json(400, {"error": f"hashes: 1..{MAX_HASHES} torrent hashes"})
        try:
            act(m.group(1), hashes)
        except QbitError as e:
            return self._json(e.status, {"error": str(e)})
        log.info("%s %s %d torrent(s)%s", claims["u"], m.group(1), len(hashes),
                 f" (approved by {claims['a']})" if claims.get("a") else "")
        return self._json(200, {"ok": True, "verb": m.group(1), "count": len(hashes)})


class PooledHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    pool = ThreadPoolExecutor(max_workers=8)

    def process_request(self, request, client_address):
        self.pool.submit(self.process_request_thread, request, client_address)


def serve(host="127.0.0.1", port=PORT):
    Handler.key = CONF.key = load_key()
    return PooledHTTPServer((host, port), Handler)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    srv = serve()
    log.info("connector %s on 127.0.0.1:%s (key %s)", ID, PORT, "ok" if Handler.key else "MISSING")
    CONF.start()
    srv.serve_forever()
