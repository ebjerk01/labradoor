"""Labradoor connector `guacamole`: Apache Guacamole → the console list for the machine objects.

Logs in to Guacamole's REST API as a read-only service user (READ on every connection, no system permissions) and lists
the connection tree. Guacamole hides connection parameters (host/IP) from non-admins, so each connection carries hints
parsed from its NAME ("web (CT 112)", "pve1 (Proxmox, 192.0.2.21)"): label, vmid, ip. The module matches those to
objects. The browser only ever gets names, ids and counts — never the service user's token or password.

Terminals / consoles (POST /api/open/<connection>/<object>): the gateway checks the route (owner; `_protect` makes a
machine owner-only) and audits it; the connector checks the caller once more (owner, or an admin holding a grant),
records who opened what, and answers the Guacamole client URL for exactly that connection. The browser opens it in
its own window, where Guacamole signs the viewer in with THEIR OWN account (SSO), so Guacamole's per-user
permissions still apply and its connection history names the real person. No token is minted: lab hands out nothing
that opens a console by itself.

Admins (only when the owner set admin_terminals): an admin asks the owner (approval) for POST /api/grant/<conn>/<obj>;
the approved run, signed with claim a=<owner>, stores a grant for that admin + connection for grant_minutes; within that
time the admin's own POST /api/open/... is let through. Grants live in memory (a restart drops them).

Config (module config, from the gateway — connectors/README.md):
  url              Guacamole base as the lab host reaches it (REST under /api)
  username         a service user with READ on the connections and no system permissions
  password
  public_url       where browsers open consoles (default: url)
  admin_terminals  admins may ask the owner for a time-limited terminal (default false: owner only)
  grant_minutes    how long such a grant lasts (default 30)
"""
import base64
import json
import logging
import os
import re
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

ID = os.environ.get("CONNECTOR_ID", "guacamole")
PORT = int(os.environ.get("PORT", "8112"))
KEY = labconn.load_key(ID)
PUBLIC = ""  # where browsers open consoles (config public_url, else url)
CACHE_S = int(os.environ.get("GUAC_CACHE_S", "20"))
POLICY = {"admins": False, "grant_minutes": 30}  # from config: admin_terminals, grant_minutes
TERMINAL_PROTOCOLS = ("ssh", "telnet")
log = logging.getLogger(ID)

VMID_RE = re.compile(r"\b(?:CT|VM)\s*(\d{2,6})\b")
IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


class GuacError(Exception):
    pass


def client_url(ident, source):
    """Guacamole's client identifier: base64("<id>\\0c\\0<dataSource>") (padding dropped, atob accepts it)."""
    raw = f"{ident}\0c\0{source}".encode()
    return f"{PUBLIC}/#/client/{base64.b64encode(raw).decode().rstrip('=')}"


def hints(name):
    """'workstation (CT 112)' → {'label': 'workstation', 'vmid': 112, 'ip': None}; 'web / example.com (CT 122)' → label 'web'."""
    label = re.split(r"\s+\(|\s+/\s+", name, maxsplit=1)[0].strip()
    m, ip = VMID_RE.search(name), IP_RE.search(name)
    return {"label": label, "vmid": int(m.group(1)) if m else None, "ip": ip.group(1) if ip else None}


def flatten(tree, source):
    """The connection tree → a flat list (group name kept), sorted by name."""
    out = []

    def walk(group, path):
        for c in group.get("childConnections") or []:
            out.append({"id": str(c.get("identifier")), "name": c.get("name", ""), "protocol": c.get("protocol", ""),
                        "group": path, "active": int(c.get("activeConnections") or 0),
                        "lastActive": (c.get("lastActive") or 0) // 1000 or None,
                        "terminal": c.get("protocol", "") in TERMINAL_PROTOCOLS, **hints(c.get("name", ""))})
        for g in group.get("childConnectionGroups") or []:
            walk(g, g.get("name", "") if path == "" else f"{path}/{g.get('name', '')}")

    walk(tree or {}, "")
    return sorted(out, key=lambda c: c["name"].lower())


class Guac:
    """One logged-in session, re-used; re-login once on 401/403 (Guacamole tokens die after ~60 min idle)."""

    def __init__(self, url="", user="", password=""):
        self.url, self.user, self.password = (url or "").rstrip("/"), user, password
        self.lock = threading.Lock()
        self.token, self.source = None, "mysql"
        self.cache = (0.0, None)
        self.last_error = ""

    def _req(self, method, path, data=None, token=True):
        headers = {"Accept": "application/json", "User-Agent": "lab-connector-guacamole/1"}
        if token and self.token:
            headers["Guacamole-Token"] = self.token
        body = None
        if data is not None:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if not self.url:
            raise GuacError("no Guacamole URL configured")
        req = urllib.request.Request(self.url + "/api" + path, data=body, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
        return json.loads(raw) if raw else None

    def _login(self):
        if not (self.user and self.password):
            raise GuacError("no Guacamole login configured")
        try:
            r = self._req("POST", "/tokens", {"username": self.user, "password": self.password}, token=False)
        except urllib.error.HTTPError as e:
            raise GuacError(f"login refused ({e.code})") from None
        except (OSError, ValueError) as e:
            raise GuacError(f"guacamole unreachable: {str(e)[:150]}") from None
        self.token = r["authToken"]
        self.source = r.get("dataSource") or "mysql"
        if "mysql" in (r.get("availableDataSources") or []):
            self.source = "mysql"

    def _get(self, path):
        for attempt in (0, 1):
            if not self.token:
                self._login()
            try:
                return self._req("GET", path.replace("{ds}", urllib.parse.quote(self.source)))
            except urllib.error.HTTPError as e:
                if e.code in (401, 403) and attempt == 0:
                    self.token = None
                    continue
                raise GuacError(f"guacamole {path.split('/')[-1]}: HTTP {e.code}") from None
        raise GuacError("unreachable")

    def connections(self, fresh=False):
        with self.lock:
            at, data = self.cache
            if data is not None and not fresh and time.time() - at < CACHE_S:
                return data
            try:
                tree = self._get("/session/data/{ds}/connectionGroups/ROOT/tree")
            except (OSError, ValueError, KeyError) as e:
                self.last_error = str(e)[:200]
                raise GuacError(f"guacamole unreachable: {self.last_error}") from None
            except GuacError as e:
                self.last_error = str(e)
                raise
            data = {"connections": flatten(tree, self.source), "public": PUBLIC, "source": self.source,
                    "fetched": int(time.time())}  # no client URLs here: those come only from POST /api/open (audited)
            self.last_error = ""
            self.cache = (time.time(), data)
            return data


    def logout(self):
        if self.token:
            try:
                self._req("DELETE", f"/tokens/{urllib.parse.quote(self.token, safe='')}")
            except (OSError, ValueError):
                pass
            self.token = None


GUAC = Guac()


def configure(v, conf=None):
    global GUAC, PUBLIC
    GUAC = Guac(labconn.url(v, "url"), labconn.text(v, "username"), labconn.text(v, "password"))
    PUBLIC = labconn.url(v, "public_url") or labconn.url(v, "url")
    POLICY["admins"] = v.get("admin_terminals") is True or labconn.text(v, "admin_terminals").lower() == "true"
    try:
        POLICY["grant_minutes"] = max(5, min(240, int(v.get("grant_minutes") or 30)))
    except (TypeError, ValueError):
        POLICY["grant_minutes"] = 30


CONF = labconn.Config(ID, KEY, apply=configure)


def validate(values):
    """Config test: log in with the CANDIDATE values and read the connection tree (then log out again)."""
    g = Guac(labconn.url(values, "url"), labconn.text(values, "username"), labconn.text(values, "password"))
    try:
        tree = g._get("/session/data/{ds}/connectionGroups/ROOT/tree")
        n = len(flatten(tree, g.source))
    except GuacError as e:
        return {"ok": False, "error": str(e)}
    except (OSError, ValueError, KeyError) as e:
        return {"ok": False, "error": f"guacamole unreachable: {str(e)[:150]}"}
    finally:
        g.logout()
    return {"ok": True, "detail": f"logged in, {n} connection(s) visible"}


SAFE_OBJ = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
SAFE_CONN = re.compile(r"^[0-9]{1,9}$")


class Sessions:
    """Grants (admin + connection → until) in memory, and the log of opened consoles (memory + a JSONL file in the
    connector's state directory, so the machine panel can show who opened what after a restart). The gateway's audit
    log is the authoritative record; this one adds the connection's name."""

    KEEP = 500

    def __init__(self, path=None):
        self.lock = threading.Lock()
        self.grants = {}  # (user, conn) → {"until", "by", "object", "name"}
        self.path = path
        self.opened = []
        if path:
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        try:
                            self.opened.append(json.loads(line))
                        except ValueError:
                            continue
                self.opened = self.opened[-self.KEEP:]
            except OSError:
                pass

    def grant(self, user, conn, by, obj, name, minutes, now=None):
        now = now or time.time()
        with self.lock:
            g = {"user": user, "id": conn, "object": obj, "name": name, "by": by, "at": int(now),
                 "until": int(now + minutes * 60)}
            self.grants[(user, conn)] = g
            return dict(g)

    def granted(self, user, conn, now=None):
        now = now or time.time()
        with self.lock:
            g = self.grants.get((user, conn))
            if g and g["until"] > now:
                return dict(g)
            self.grants.pop((user, conn), None)
            return None

    def list_grants(self, user=None, now=None):
        now = now or time.time()
        with self.lock:
            for k in [k for k, g in self.grants.items() if g["until"] <= now]:
                del self.grants[k]
            return [dict(g) for g in self.grants.values() if user is None or g["user"] == user]

    def revoke(self, user=None, conn=None):
        with self.lock:
            gone = [k for k in self.grants if (user is None or k[0] == user) and (conn is None or k[1] == conn)]
            for k in gone:
                del self.grants[k]
            return len(gone)

    def record(self, entry):
        with self.lock:
            self.opened.append(entry)
            trim = len(self.opened) > 2 * self.KEEP
            if trim:
                self.opened = self.opened[-self.KEEP:]
            if self.path:
                try:
                    if trim:
                        tmp = self.path + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as f:
                            f.writelines(json.dumps(e) + "\n" for e in self.opened)
                        os.replace(tmp, self.path)
                    else:
                        with open(self.path, "a", encoding="utf-8") as f:
                            f.write(json.dumps(entry) + "\n")
                except OSError as e:
                    log.warning("could not write %s: %s", self.path, e)

    def recent(self, user=None, conn=None, limit=50):
        with self.lock:
            out = [e for e in reversed(self.opened) if (user is None or e["user"] == user) and (conn is None or e["id"] == conn)]
        return out[:limit]


def _sessions_path():
    d = labconn.state_dir(ID, "GUAC_STATE_DIR")
    return os.path.join(d, "opened.jsonl") if os.path.isdir(d) and os.access(d, os.W_OK) else None


SESSIONS = Sessions(_sessions_path())


def find_conn(conn, fresh=False):
    """The connection with this id as the service user sees it, or None."""
    return next((c for c in GUAC.connections(fresh=fresh)["connections"] if c["id"] == conn), None)


def open_console(claims, conn, obj, now=None):
    """→ (code, answer). Owner: yes. Admin: only with a live grant (and the owner's admin_terminals). Guest: never.
    An approved run of /api/open itself is refused: its answer never reaches the admin, a grant is the way."""
    role, user = claims.get("r"), claims.get("u")
    if role not in ("owner", "admin"):
        return 403, {"error": "consoles are for the owner (and admins the owner allows)"}
    if not (SAFE_CONN.match(conn or "") and SAFE_OBJ.match(obj or "")):
        return 400, {"error": "bad connection or object id"}
    via = "owner"
    if role == "admin":
        if claims.get("a"):
            return 409, {"error": "an approved open cannot hand you the window; ask the owner for a terminal grant instead"}
        if not POLICY["admins"]:
            return 403, {"error": "terminals are owner-only in this installation"}
        g = SESSIONS.granted(user, conn, now)
        if not g:
            return 403, {"error": "no terminal grant for this machine: ask the owner"}
        via = f"grant by {g['by']}"
    c = find_conn(conn) or find_conn(conn, fresh=True)
    if not c:
        return 404, {"error": "no such console (or the service user cannot see it)"}
    entry = {"ts": int(now or time.time()), "user": user, "role": role, "id": conn, "object": obj, "name": c["name"],
             "protocol": c["protocol"], "via": via}
    SESSIONS.record(entry)
    log.info("console opened: user=%s role=%s connection=%s (%s, %s) object=%s via=%s",
             user, role, conn, c["name"], c["protocol"], obj, via)
    return 200, {"url": client_url(conn, GUAC.source), "window": f"lab-console-{conn}", "id": conn, "name": c["name"],
                 "protocol": c["protocol"], "terminal": c["terminal"], "object": obj}


def grant_console(claims, conn, obj, now=None):
    """The approved run of an admin's request: claims r=admin, a=<owner who approved>. Anything else is refused."""
    if not (SAFE_CONN.match(conn or "") and SAFE_OBJ.match(obj or "")):
        return 400, {"error": "bad connection or object id"}
    if claims.get("r") == "owner":
        return 400, {"error": "the owner needs no grant"}
    if claims.get("r") != "admin" or not claims.get("a"):
        return 403, {"error": "a terminal grant needs the owner's approval"}
    if not POLICY["admins"]:
        return 403, {"error": "terminals are owner-only in this installation (setting: admins may ask for terminals)"}
    c = find_conn(conn) or find_conn(conn, fresh=True)
    if not c:
        return 404, {"error": "no such console"}
    g = SESSIONS.grant(claims["u"], conn, claims["a"], obj, c["name"], POLICY["grant_minutes"], now)
    log.info("terminal grant: user=%s connection=%s (%s) object=%s approved_by=%s for %d min",
             claims["u"], conn, c["name"], obj, claims["a"], POLICY["grant_minutes"])
    return 200, {"grant": g}


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

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        path, q = url.path.rstrip("/") or "/", urllib.parse.parse_qs(url.query)
        if path == "/healthz":
            if not CONF.ready:
                return self._json(503, {"ok": False, "config": False, "error": CONF.why()})
            try:
                n = len(GUAC.connections()["connections"])
                return self._json(200, {"ok": True, "connections": n})
            except GuacError as e:
                return self._json(502, {"ok": False, "error": str(e)})
        claims = self._claims()
        if not claims:
            return self._json(401, {"error": "lab signature required"})
        if not CONF.ready:
            return self._json(503, {"error": CONF.why()})
        try:
            if path == "/api/connections":
                d = dict(GUAC.connections(fresh=q.get("fresh") == ["1"]))
                d["admins"] = POLICY["admins"]
                return self._json(200, d)
            if path == "/api/status":
                d = GUAC.connections()
                return self._json(200, {"connector": ID, "you": claims["u"], "role": claims["r"], "guacamole": GUAC.url,
                                        "connections": len(d["connections"]),
                                        "active": sum(c["active"] for c in d["connections"])})
            if path == "/api/sessions":
                # owner: everyone's; admin: their own grants + opens; ?id=<connection> narrows the log
                mine = None if claims["r"] == "owner" else claims["u"]
                conn = (q.get("id") or [None])[0]
                return self._json(200, {"admins": POLICY["admins"], "grant_minutes": POLICY["grant_minutes"],
                                        "grants": SESSIONS.list_grants(mine),
                                        "opened": SESSIONS.recent(mine, conn if conn and SAFE_CONN.match(conn) else None)})
        except GuacError as e:
            return self._json(502, {"error": str(e)})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        claims = self._claims()
        if not claims:
            return self._json(401, {"error": "lab signature required"})
        m = re.fullmatch(r"/api/(open|grant)/([^/]+)/([^/]+)", url.path)
        if m:
            self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 4096))
            conn, obj = urllib.parse.unquote(m.group(2)), urllib.parse.unquote(m.group(3))
            try:
                code, ans = (open_console if m.group(1) == "open" else grant_console)(claims, conn, obj)
            except GuacError as e:
                code, ans = 502, {"error": str(e)}
            return self._json(code, ans)
        if url.path == "/api/sessions/revoke":
            if claims.get("r") != "owner":
                return self._json(403, {"error": "owner only"})
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) if 0 < n <= 4096 else b"{}") or {}
            except ValueError:
                return self._json(400, {"error": "bad JSON"})
            user, conn = body.get("user"), body.get("id")
            n = SESSIONS.revoke(str(user) if user else None, str(conn) if conn else None)
            log.info("terminal grants revoked by %s: %d (user=%s connection=%s)", claims["u"], n, user, conn)
            return self._json(200, {"revoked": n})
        if url.path != "/api/_validate":
            return self._json(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) if 0 < n <= 65536 else b"{}")
            return self._json(200, validate(labconn.candidate(claims, body)))
        except PermissionError as e:
            return self._json(403, {"error": str(e)})
        except ValueError as e:
            return self._json(400, {"error": str(e)})


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
