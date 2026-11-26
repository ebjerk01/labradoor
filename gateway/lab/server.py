"""Labradoor gateway: login, roles, module registry, checked + signed proxy to module backends, owner approvals,
audit, prefs, and the built Svelte UI.  Stdlib only; PooledHTTPServer (bounded thread pool, see stdlib-app-pattern)."""
import hashlib
import hmac
import ipaddress
import json
import logging
import mimetypes
import os
import re
import socket
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import auth, config, notify, redact
from .delegate import ACT_HEADER, ACT_TTL, ACT_VERSION, HEADER as DELEGATION_HEADER, Delegation, lower_role, session_hash
from .health import Health, probe
from .events import Events
from .cache import ProxyCache, ttl_for
from .connectors import CALL_PREFIX as CONNECTOR_CALL_PREFIX, CONFIG_PATH as CONNECTOR_CONFIG_PATH, CONNECTOR_HEADER, \
    Connectors, call_scope
from . import oidc as oidc_mod
from .oidc import MESSAGES as OIDC_MESSAGES, OIDC, OIDCError
from .proxy import BackendError, Keys, forward
from .registry import Registry, check_value, protect_routes, ManifestError
from .secretbox import SecretBox
from . import manifest2
from .errors import HTTPError
from .login import LoginSettings
from .login_api import NOT_MINE, LoginRoutes
from .updates import UpdateRoutes, startup_audit
from .modstore import ModuleStoreRoutes
from .store import Store

log = logging.getLogger("lab")
COOKIE = "lab_session"
# the SSO login's state, bound to the browser that started it (review L1: no login CSRF / session swap): a hash of the
# state, only sent to the callback, for as long as the IdP round trip may take
STATE_COOKIE = "lab_oidc"
STATE_PATH = "/auth/callback"
MAX_BODY = 16 * 1024 * 1024      # hard ceiling (cdn upload chunks: route max_body)
ROUTE_BODY = 1024 * 1024         # default per proxied route (manifest `max_body` raises it)
SMALL_BODY = 64 * 1024           # the gateway's own endpoints (login, prefs, approvals, settings)
BIG_BODIES = threading.BoundedSemaphore(4)  # > ROUTE_BODY bodies held in memory at once (CT has 768 MB)
HEAD_SECONDS = 30                # whole request line + headers (slowloris); small bodies get the same again
MAX_PENDING_ASKS = 20            # open approval requests per admin
MAX_PREFS = 200                  # pref keys per user
PROXY_RE = re.compile(r"^/api/m/([a-z][a-z0-9-]{1,30})(/.*)?$")
APPROVAL_RE = re.compile(r"^/api/approvals/(\d+)/(approve|deny|cancel)$")
USER_LOGOUT_RE = re.compile(r"^/api/users/([^/]+)/logout$")
DELEGATE_RE = re.compile(r"^/api/delegate/m/([a-z][a-z0-9-]{1,30})(/.*)?$")
CONNECTOR_CALL_RE = re.compile(r"^/api/connector/call/([a-z][a-z0-9-]{1,30})(/.*)?$")
BUNDLE_RE = re.compile(r"^/modules/([a-z][a-z0-9-]{1,30})/([0-9A-Za-z.+-]{1,64})/ui\.js$")  # an installed module's UI
DELEGATE_ANSWER = 512 * 1024    # a delegated read larger than this is cut (the assistant truncates far below anyway)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
# Proxied backend answers are data (JSON, images, downloads), never a page of lab's origin: if one is opened directly and
# happens to be HTML/SVG (an uploaded file, an error page echoing the path), it runs sandboxed: no scripts, own origin.
PROXY_CSP = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; frame-ancestors 'none'"
NEXT_RE = re.compile(r"^/(?![/\\])[^\s\\]{0,500}$")  # same-site path after login: no //host, no /\host, no CR/LF
STARTED = time.time()
_UNSET = object()
PROXY_SECRET_HEADER = "X-Lab-Proxy-Secret"


def _loopback(addr):
    try:
        return ipaddress.ip_address(addr.split("%", 1)[0]).is_loopback or addr.startswith("::ffff:127.")
    except ValueError:
        return False


def _build(name, default):
    """/opt/lab/VERSION (semver) and /opt/lab/COMMIT (git commit), written by deploy/build-tree.sh. Releases before
    step 17 had only VERSION, holding the commit."""
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), name)) as f:
            return re.sub(r"[^0-9A-Za-z.+_-]", "", f.read().strip())[:64] or default
    except OSError:
        return default


BUILD = _build("VERSION", "dev")
BUILD_COMMIT = _build("COMMIT", "")
if not BUILD_COMMIT and re.fullmatch(r"[0-9a-f]{40}", BUILD):
    BUILD, BUILD_COMMIT = "dev", BUILD
SECRET_READ_AUDIT_SECONDS = 3600  # a secret GET is audited once per user + path per hour


class App:
    """Everything the handler needs; built once (tests build their own)."""

    def __init__(self):
        os.makedirs(os.path.dirname(config.DB) or ".", exist_ok=True)
        self.store = Store(config.DB)
        self.store.setup_closed()  # an installation from before the flag: an owner row now closes setup for good
        self.registry = Registry(config.MODULES_DIR, config.BACKENDS_FILE, installed_dir=config.INSTALLED_DIR,
                                 abi_file=os.path.join(config.STATIC_DIR, "abi.json"), release_pub=config.RELEASE_PUB)
        self.events = Events(session_alive=self.store.session_alive, user_lookup=self.store.user)
        self.cache = ProxyCache()
        self.box = SecretBox.from_file(config.MASTER_KEY)  # None until install.sh made /etc/lab/master.key
        self._cfg_lock = threading.Lock()
        self._cfg = {}
        self.keys = Keys(config.KEYS_DIR, lookup=self.config_value)
        self.connectors = Connectors(self)
        self.reload_config()
        _retire_published_view()
        self.delegation = Delegation(config.DELEGATION_KEY)
        # act tokens for connectors with uses_credentials_of (same secret, own version: never valid as the other kind)
        self.act = Delegation(config.DELEGATION_KEY, ttl=ACT_TTL, version=ACT_VERSION)
        self.health = Health(self.registry, config.HEALTH_INTERVAL, self.keys, on_change=self._health_changed)

        self.login = LoginSettings(self.store, self.box)  # Settings → Login (env LAB_OIDC_* etc. wins when set)
        self.oidc = None
        self.reload_login()
        self.counters = {"requests": 0, "proxied": 0, "proxy_errors": 0, "denied": 0}
        self._secret_reads = {}
        self._secret_lock = threading.Lock()
        for name, err in self.registry.errors.items():
            log.error("module %s not loaded: %s", name, err)

    # --- login (login.py / login_api.py) ------------------------------------------------------------------------------
    def reload_login(self):
        """(Re)build the SSO client from the Login settings; None = local accounts only."""
        lg = self.login
        lg.reload()
        if lg.sso_configured():
            self.oidc = OIDC(lg.get("sso_issuer"), lg.get("sso_client_id"), lg.get("sso_client_secret") or "",
                             config.PUBLIC_URL + "/auth/callback")
        else:
            self.oidc = None

    def first_run_notice(self, force=False, recover=False):
        """No owner yet: make a one-time setup link (valid 1 h) and return it. Returns None when an owner exists, when
        one existed before (setup_closed) unless recover, or when a link is still pending and force is False. Not called
        at startup any more: the link never goes to the journal — root makes it with `lab-admin
        setup-link` (install.sh does), into /etc/lab/setup-link."""
        if self.store.active_owners() or (self.store.setup_closed() and not recover):
            return None
        if self.store.setup_token_pending() and not force:
            return None
        return f"{config.PUBLIC_URL}/setup#{self.store.new_setup_token()}"

    def start_connectors(self):
        """Once, when the server starts (not in tests): connectors that should run, run; switched-off ones stop."""
        threading.Thread(target=self.connectors.reconcile, name="connectors", daemon=True).start()

    # --- push hints (events.py) ---------------------------------------------------------------------------------
    def module_changed(self, mod):
        """A write reached this module's backend: drop its cached reads, tell the tabs that may see it."""
        self.cache.invalidate(mod["id"])
        self.events.publish({"t": "invalidate", "m": mod["id"]}, may=lambda u: self.registry.can_use(mod, u))

    def approvals_changed(self):
        self.events.publish({"t": "approvals"}, may=lambda u: u.get("role") in ("owner", "admin"))

    def _health_changed(self, mid, up):
        mod = self.registry.get(mid)
        if mod:
            self.events.publish({"t": "health", "m": mid, "up": bool(up)}, may=lambda u: self.registry.can_use(mod, u))

    # --- per-installation module config (manifest v2) -------------------------------------------------------
    def reload_config(self):
        """Settings + config from the DB into the registry (v2 backends are rebuilt from it)."""
        with self._cfg_lock:
            self._cfg = self.store.module_config()
            view = {mid: {k: ("<set>" if sec else v) for k, (v, sec) in kv.items()} for mid, kv in self._cfg.items()}
            self.registry.apply(overrides=self.store.module_settings(), config=view)
        self.events.publish({"t": "registry"})

    def installed_check(self, every=10):
        """Pick up modules installed, updated or removed outside the UI (lab-admin package): at most every `every` s."""
        now = time.monotonic()
        if now - getattr(self, "_installed_checked", 0) < every:
            return
        self._installed_checked = now
        if self.registry.installed_changed():
            log.info("installed modules changed on disk: reloading the registry")
            self.registry.load()
            self.reload_config()

    def config_value(self, mid, key):
        """A config value, secrets opened (for the proxy and health checks; never sent to a browser)."""
        v, sec = self._cfg.get(mid, {}).get(key, (None, False))
        if not sec or v is None:
            return v
        if not self.box:
            return None
        try:
            return self.box.open(mid, key, v)
        except ValueError:
            log.error("config %s.%s: sealed value can't be opened (master key changed?)", mid, key)
            return None

    def first_secret_read(self, username, mid, path, window=SECRET_READ_AUDIT_SECONDS):
        """True when this user has not read this secret path in the last `window` seconds (then it is audited)."""
        now, k = time.time(), (username, mid, path)
        with self._secret_lock:
            if now - self._secret_reads.get(k, 0) < window:
                return False
            if len(self._secret_reads) > 5000:
                self._secret_reads = {x: t for x, t in self._secret_reads.items() if now - t < window}
            self._secret_reads[k] = now
            return True


def _retire_published_view():
    """Until step 15 the gateway published every v2 backend + SEALED secrets for connectors to open with the master key
    (group-readable then). Connectors now get only their own config from /api/connector/config: remove the old file."""
    path = os.path.join(os.path.dirname(config.DB) or ".", "backends.v2.json")
    try:
        os.unlink(path)
        log.info("removed the old published backend view %s", path)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("can't remove %s: %s", path, e)


APP = None
CONFIG_RE = re.compile(r"^/api/config/([a-z][a-z0-9-]{1,30})(/test)?$")


def _config_check(f, v):
    """One config value against its field (manifest2.FIELD_TYPES) → the clean value, or ValueError."""
    t = f["type"]
    if t in ("text", "secret", "url"):
        if not isinstance(v, str) or len(v) > (f.get("max") or (8192 if t == "secret" else 2000)):
            raise ValueError("expected text (not too long)")
        v = v.strip()
        if t == "url" and v:
            u = urllib.parse.urlsplit(v)
            if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError("expected http(s)://host[:port][/path] (no credentials or query in the URL)")
            v = v.rstrip("/")
        if f.get("multiline"):
            v = v.replace("\r\n", "\n")
            if "\r" in v or "\0" in v:
                raise ValueError("no carriage returns or NUL")
        elif "\n" in v or "\r" in v:
            raise ValueError("no line breaks")
        return v
    if t == "bool":
        if not isinstance(v, bool):
            raise ValueError("expected true/false")
        return v
    if t == "int":
        if isinstance(v, bool) or not isinstance(v, int) or ("min" in f and v < f["min"]) or ("max" in f and v > f["max"]):
            raise ValueError(f"expected a whole number {f.get('min', '')}..{f.get('max', '')}")
        return v
    if t == "enum":
        if v not in f["options"]:
            raise ValueError(f"one of {f['options']}")
        return v
    if not (isinstance(v, list) and len(v) <= 200 and all(isinstance(x, str) and len(x) <= 200 for x in v)):
        raise ValueError("expected a list of short texts")
    return v


def sso_name_problem(store, name):
    """Why an SSO login name can't be used here, or None (review 2026-11-15, L7). The IdP's preferred_username must be a
    plain lab username (login_api.USERNAME_RE: ASCII letters, digits, . _ @ -, no spaces, no look-alikes), and a NEW
    one may not differ from an existing account only by case: backends (and people) treat those as the same person."""
    from .login_api import USERNAME_RE
    if not (isinstance(name, str) and USERNAME_RE.fullmatch(name)):
        return "this account's username can't be used here (letters, digits, . _ @ - only, 2-64 characters)"
    if store.user(name):
        return None
    other = store.user_casefold(name)
    if other:
        return "an account whose name differs only in upper/lower case exists already (ask the owner)"
    return None


class Handler(LoginRoutes, UpdateRoutes, ModuleStoreRoutes, BaseHTTPRequestHandler):
    server_version = "lab"
    sys_version = ""
    # HTTP/1.0 = one request per connection. With 1.1 keep-alive every idle upstream connection from the proxy held a
    # pool thread for its whole life and 16 modules loading at once starved the pool (17 s healthz). Costs ~nothing on LAN.
    protocol_version = "HTTP/1.0"
    timeout = 30  # a client that stalls mid-request gives its thread back

    # --- plumbing --------------------------------------------------------------------------------------------
    @property
    def app(self):
        return self.server.app

    def log_request(self, code="-", size="-"):
        # Successful reads are ~all traffic (every open tab polls ~40 modules every 15 s) and would flood Graylog:
        # log them at DEBUG; writes, errors and denials at INFO (writes are also in the audit table).
        ok = str(code).startswith(("2", "3"))
        # reads at DEBUG — incl. read-only POSTs (graylog searches: routes with audit:false), which were ~1000/day at INFO
        read = self.command in ("GET", "HEAD") or getattr(self, "_read_post", False)
        level = logging.DEBUG if ok and read else logging.INFO
        log.log(level, '%s "%s" %s', self.client_ip(), self.requestline, code)

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _from_trusted_proxy(self):
        """Does this request come from the reverse proxy (so its X-Real-IP / X-Forwarded-* count)? Only a peer in
        LAB_TRUSTED_PROXIES; with LAB_PROXY_SECRET set, only with that secret too; and a loopback peer only with the
        secret — local connectors share 127.0.0.1 and must not pick client IPs (review 2026-11-15, L6)."""
        peer = self.client_address[0]
        if not (config.TRUST_PROXY and peer in config.TRUSTED_PROXIES):
            return False
        if config.PROXY_SECRET:
            return hmac.compare_digest((self.headers.get(PROXY_SECRET_HEADER) or "").encode(), config.PROXY_SECRET.encode())
        return not _loopback(peer)

    def client_ip(self):
        # X-Real-IP / X-Forwarded-For only from the reverse proxy itself: anyone else on the LAN could pick an address
        # per request (break-glass throttling, audit IPs). LAB_TRUSTED_PROXIES (+ LAB_PROXY_SECRET): _from_trusted_proxy.
        if self._from_trusted_proxy():
            real = self.headers.get("X-Real-IP")
            if real:
                return real.strip()
            fwd = self.headers.get("X-Forwarded-For")
            if fwd:
                return fwd.split(",")[0].strip()
        return self.client_address[0]

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", headers=None, csp=CSP):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (headers or {}).items():
            for one in (v if isinstance(v, list) else [v]):   # a list: the header several times (Set-Cookie)
                self.send_header(k, one)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj, headers=None):
        h = {"Cache-Control": "no-store"}
        h.update(headers or {})
        self._send(code, json.dumps(obj, separators=(",", ":")).encode(), headers=h)

    def _redirect(self, where, headers=None):
        h = {"Location": where, "Cache-Control": "no-store"}
        h.update(headers or {})
        self._send(302, b"", "text/plain", h)

    def _token(self):
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return c[COOKIE].value if COOKIE in c else None

    def _cookie(self, value, max_age):
        parts = [f"{COOKIE}={value}", "Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={max_age}"]
        if config.COOKIE_SECURE:
            parts.append("Secure")
        return "; ".join(parts)

    def _state_cookie(self, state, max_age):
        value = hashlib.sha256(state.encode()).hexdigest() if state else ""
        path = urllib.parse.urlsplit(config.PUBLIC_URL).path.rstrip("/") + STATE_PATH   # where the IdP sends it back
        parts = [f"{STATE_COOKIE}={value}", f"Path={path}", "HttpOnly", "SameSite=Lax", f"Max-Age={max_age}"]
        if config.COOKIE_SECURE:
            parts.append("Secure")
        return "; ".join(parts)

    def _state_matches(self, state):
        c = SimpleCookie(self.headers.get("Cookie", ""))
        have = c[STATE_COOKIE].value if STATE_COOKIE in c else ""
        return bool(state and have) and hmac.compare_digest(have, hashlib.sha256(state.encode()).hexdigest())

    def _user(self):
        # Cached per REQUEST only: with keep-alive one handler serves many requests (from different users via the proxy).
        if self._u is _UNSET:
            self._u = self.app.store.session_user(self._token())
        return self._u

    def _need(self, role="guest", enrol_ok=False):
        u = self._user()
        if not u:
            raise HTTPError(401, "not logged in")
        if not enrol_ok and self._must_enrol(u):  # owner requires 2FA and this owner/admin has none yet: enrol first
            raise HTTPError(403, "set up two-factor login first", enrol=True)
        if ("guest", "admin", "owner").index(u["role"]) < ("guest", "admin", "owner").index(role):
            raise HTTPError(403, "not allowed")
        return u

    def _length(self):
        raw = (self.headers.get("Content-Length") or "0").strip()
        if not (raw.isascii() and raw.isdigit()):  # "-1" would make rfile.read() read until the client hangs up
            raise HTTPError(400, "bad Content-Length")
        if self.headers.get("Transfer-Encoding"):
            raise HTTPError(411, "send a Content-Length")
        return int(raw)

    def _raw_body(self, limit=SMALL_BODY):
        n = self._length()
        if n > min(limit, MAX_BODY):
            raise HTTPError(413, "request too large")
        if not n:
            return b""
        if n <= SMALL_BODY:  # small bodies (also before any login): the same deadline as the headers
            REAPER.watch(self.connection, HEAD_SECONDS)
            try:
                return self.rfile.read(n)
            finally:
                REAPER.done(self.connection)
        return self.rfile.read(n)

    def _body(self):
        try:
            data = json.loads(self._raw_body() or b"{}")
        except (ValueError, RecursionError):
            raise HTTPError(400, "invalid JSON") from None
        if not isinstance(data, dict):
            raise HTTPError(400, "expected a JSON object")
        return data

    def _same_origin(self):
        """CSRF guard for state-changing requests: the browser's Origin (when sent) must be this site, and so must
        Sec-Fetch-Site (when sent: every current browser). A sibling page on another subdomain is same-SITE, not same-origin."""
        site = self.headers.get("Sec-Fetch-Site")
        if site and site not in ("same-origin", "none"):
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("X-Forwarded-Host") if self._from_trusted_proxy() else None
        allowed = {urllib.parse.urlsplit(config.PUBLIC_URL).netloc, host or self.headers.get("Host")} - {None, ""}
        return urllib.parse.urlsplit(origin).netloc in allowed

    # --- dispatch --------------------------------------------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def setup(self):
        super().setup()
        REAPER.watch(self.connection, HEAD_SECONDS)  # request line + headers must arrive within HEAD_SECONDS

    def finish(self):
        REAPER.done(self.connection)
        super().finish()

    def _dispatch(self, method):
        REAPER.done(self.connection)
        self._u = _UNSET
        self._read_post = False
        self.app.counters["requests"] += 1
        url = urllib.parse.urlsplit(self.path)
        path, query = url.path, url.query
        try:
            if path.startswith("/api/delegate/"):  # a local connector acting as a user (no cookie, no browser)
                return self._delegate(method, path, query)
            if path == CONNECTOR_CONFIG_PATH:  # a local connector fetching its own config (signed with its own key)
                return self._connector_config(method)
            if path.startswith(CONNECTOR_CALL_PREFIX):  # a local connector calling a module it uses, AS a user
                return self._connector_call(method if method != "HEAD" else "GET", path, query)
            if method not in ("GET", "HEAD") and not self._same_origin():
                raise HTTPError(403, "cross-site request refused")
            m = PROXY_RE.match(path)
            if m:
                return self._proxy(method if method != "HEAD" else "GET", m.group(1), m.group(2) or "/", query)
            if method in ("GET", "HEAD"):
                return self._get(path, urllib.parse.parse_qs(query))
            if method == "POST":
                return self._post(path)
            raise HTTPError(405, "method not allowed")
        except HTTPError as e:
            if e.code in (401, 403):
                self.app.counters["denied"] += 1
            self._json(e.code, {"error": e.msg, **e.extra})
        except BackendError as e:
            self.app.counters["proxy_errors"] += 1
            self._json(502, {"error": str(e)})
        except auth.Busy:  # too many password checks at once (auth.SCRYPT_SLOTS)
            self._json(503, {"error": "busy, try again in a moment"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:  # noqa: BLE001
            log.exception("unhandled error on %s %s", method, path)
            self._json(500, {"error": "internal error"})

    # --- GET -------------------------------------------------------------------------------------------------
    def _get(self, path, q):
        a = self.app
        arg = lambda k, d="": (q.get(k) or [d])[0]  # noqa: E731
        if path == "/healthz":
            return self._json(200, {"ok": True})
        if path == "/metrics":
            if self.client_address[0] not in config.METRICS_ALLOW:
                raise HTTPError(403, "not allowed")
            return self._send(200, self._metrics().encode(), "text/plain; version=0.0.4")
        if path == "/auth/login":
            if not a.oidc:
                return self._redirect("/?login=local")
            nxt = arg("next", "/")
            nxt = nxt if NEXT_RE.match(nxt) else "/"
            try:
                where = a.oidc.start(nxt)
                state = urllib.parse.parse_qs(urllib.parse.urlsplit(where).query).get("state", [""])[0]
                return self._redirect(where, {"Set-Cookie": self._state_cookie(state, oidc_mod.PENDING_SECONDS)})
            except (OSError, ValueError) as e:
                log.warning("SSO unavailable: %s", e)
                return self._redirect("/?login=local&sso_error=" + urllib.parse.quote("login service unavailable"))
        if path == "/auth/callback":
            return self._oidc_callback(q)
        if path == "/api/me":
            u = self._user()
            me = {"user": _public_user(u, self._must_enrol(u)) if u else None, "sso": bool(a.oidc),
                  "ssoName": a.login.sso_name() if a.oidc else "", "brand": config.BRAND,
                  "roleGroups": dict(auth.GROUPS) if u and a.oidc else None}
            if not u and a.store.setup_open():
                me["setup"] = True  # first run (or root's recovery link): the login page points at the setup link
            return self._json(200, me)
        if path == "/api/events":
            u = self._need()
            if not a.events.subscribe(self.connection, u, session_hash(self._token())):
                raise HTTPError(429, "too many open event streams")
            self.server.detach(self.connection)  # the broadcaster owns the socket now; this pool thread is free
            self.close_connection = True
            return None
        m = BUNDLE_RE.match(path)
        if m:
            return self._module_bundle(m.group(1), m.group(2))
        if not path.startswith("/api/"):
            return self._static(path)
        r = self._login_get(path, q)
        if r is not NOT_MINE:
            return r
        r = self._update_get(path)
        if r is not NOT_MINE:
            return r
        r = self._modstore_get(path)
        if r is not NOT_MINE:
            return r

        u = self._need()
        if path == "/api/registry":
            a.installed_check()
            pending = len(a.store.approvals("pending")) if u["role"] == "owner" else \
                len(a.store.approvals("pending", requester=u["username"]))
            return self._json(200, {"user": _public_user(u), "modules": a.registry.visible(u),
                                    "health": {k: v for k, v in a.health.state.items()
                                               if a.registry.get(k) and a.registry.can_use(a.registry.get(k), u)},
                                    "approvalsPending": pending, "errors": a.registry.errors if u["role"] != "guest" else {},
                                    "serverTime": time.time()})
        if path == "/api/health":
            return self._json(200, {"modules": {k: v for k, v in a.health.state.items()
                                                if a.registry.get(k) and a.registry.can_use(a.registry.get(k), u)}})
        if path == "/api/topology":
            self._need("admin")
            try:
                with open(config.TOPOLOGY_FILE, encoding="utf-8") as f:
                    return self._json(200, json.load(f))
            except FileNotFoundError:
                return self._json(200, {"zones": [], "nodes": [], "links": []})
        if path == "/api/audit":
            self._need("admin")
            try:
                before = int(arg("before", "0") or 0) or None
                limit = max(1, min(int(arg("limit", "200")), 1000))
            except ValueError:
                raise HTTPError(400, "before/limit must be numbers") from None
            return self._json(200, {"audit": a.store.audit_list(limit, before)})
        if path == "/api/approvals":
            if u["role"] == "owner":
                return self._json(200, {"approvals": a.store.approvals(arg("status") or None)})
            # admins are global readers: they see every request, never the results (those can hold secrets)
            rows = a.store.approvals(arg("status") or None, requester=None if u["role"] == "admin" else u["username"])
            for r in rows:  # the answer to an owner-only request can be a secret (keys, pairing codes): owner sees it only
                r["result_body"] = None
                if r["requester"] != u["username"]:  # someone else's body can carry what they typed (a password)
                    r["body"] = None
            return self._json(200, {"approvals": rows})
        if path == "/api/prefs":
            return self._json(200, {"prefs": a.store.prefs(u["username"])})
        if path == "/api/settings":
            self._need("admin")
            reg = a.registry
            mods = [{"id": m["id"], "name": m["name"], "icon": m.get("icon", ""), "description": m.get("description", ""),
                     "enabled": reg.enabled(m), "roles": m["access"]["roles"], "groups": m["access"]["groups"],
                     "extraGroups": reg.overrides.get(m["id"], {}).get("_groups") or [],
                     "schema": reg.schema(m), "values": reg.values(m),
                     "category": m.get("category") or "", "kind": m.get("kind") or "", "version": m.get("version", 1),
                     "configurable": bool(m.get("_v2") and m["config"]["fields"]), "needsSetup": reg.needs_setup(m),
                     "missing": m.get("_missing") or [], "source": m.get("_source", "bundled"),
                     "delegate": bool(m.get("delegate")), "usesCredentialsOf": a.connectors.uses(m),
                     "installed": {k: v for k, v in (m.get("_installed") or {}).items() if k != "dir"} or None,
                     "health": a.health.state.get(m["id"])} for m in sorted(reg.modules.values(), key=lambda x: x["id"])]
            return self._json(200, {"modules": mods, "editable": u["role"] == "owner"})
        m = CONFIG_RE.match(path)
        if m and not m.group(2):
            self._need("owner")
            return self._json(200, self._config_view(self._config_module(m.group(1))))
        if path == "/api/users":
            self._need("admin")
            return self._json(200, {"users": a.store.users(), "sessions": a.store.sessions()})
        raise HTTPError(404, "not found")

    def _oidc_callback(self, q):
        a = self.app
        if not a.oidc:
            raise HTTPError(404, "not found")
        clear = self._state_cookie("", 0)
        try:
            query = {k: v[0] for k, v in q.items()}
            if not query.get("error") and not self._state_matches(query.get("state") or ""):
                # a callback link from someone else's login (or another browser): never logs this browser in
                raise OIDCError(oidc_mod.OTHER_BROWSER)
            claims, after = a.oidc.finish(query)
        except (OIDCError, OSError, ValueError) as e:
            log.warning("SSO login failed: %s", e)
            # only our own wording reaches the login page (error_description in the callback URL is attacker text)
            msg = str(e) if isinstance(e, OIDCError) and e.args and e.args[0] in OIDC_MESSAGES else "login failed, try again"
            return self._redirect("/?sso_error=" + urllib.parse.quote(msg), {"Set-Cookie": clear})
        groups = [g for g in (claims.get("groups") or []) if isinstance(g, str)]
        name = claims["preferred_username"]
        why = sso_name_problem(a.store, name)
        if why:  # review 2026-11-15 L7: backends key users by name (some case-insensitively)
            shown = name[:60] if isinstance(name, str) else repr(name)[:60]
            a.store.audit({"username": shown}, "login-failed", detail=f"sso from {self.client_ip()}: {why}")
            log.warning("SSO login refused for %r: %s", shown, why)
            return self._redirect("/?sso_error=" + urllib.parse.quote(why), {"Set-Cookie": clear})
        have = a.store.user(name)
        if have and (have.get("disabled") or not have.get("sso")):
            # a disabled account stays out; a local-only account with the same name is somebody else's until the
            # owner links it (People → sso), so an SSO user can't take over (or demote) a local owner by name
            why = "this account is disabled" if have.get("disabled") else \
                "a local account with this name exists and is not linked to SSO (the owner can link it in People)"
            a.store.audit({"username": name[:60]}, "login-failed", detail=f"sso from {self.client_ip()}: {why}")
            return self._redirect("/?sso_error=" + urllib.parse.quote(why))
        user = a.store.upsert_user(name, claims.get("name") or "", claims.get("email") or "", groups, auth.role_for(groups))
        if not have:
            a.store.update_user(name, sso=True)
        from . import rolesync
        seconds = a.login.get("session_days") * 86400
        if rolesync.mode() == "none":  # nothing refreshes roles: a removed SSO user must not keep access for days
            seconds = min(seconds, a.login.get("sso_max_age_hours") * 3600)
        token = a.store.new_session(user["username"], 0, self.headers.get("User-Agent", ""), self.client_ip(), "oidc",
                                    seconds=seconds)
        a.store.audit(user, "login", detail=f"sso from {self.client_ip()}")
        return self._redirect(after or "/", {"Set-Cookie": [self._cookie(token, seconds), clear]})

    # --- POST ------------------------------------------------------------------------------------------------
    def _post(self, path):
        a = self.app
        r = self._login_post(path)
        if r is not NOT_MINE:
            return r
        if path == "/auth/logout":
            u = self._user()
            a.store.end_session(self._token())
            if u:
                a.store.audit(u, "logout")
            return self._json(200, {"ok": True}, {"Set-Cookie": self._cookie("", 0)})
        r = self._update_post(path)
        if r is not NOT_MINE:
            return r
        r = self._modstore_post(path)
        if r is not NOT_MINE:
            return r
        u = self._need()
        if path == "/api/prefs":
            data = self._body()
            key = data.get("key")
            if not isinstance(key, str) or not re.match(r"^[a-z0-9._-]{1,64}$", key):
                raise HTTPError(400, "bad key")
            if len(json.dumps(data.get("value"))) > 64 * 1024:
                raise HTTPError(413, "value too large")
            have = a.store.prefs(u["username"])
            if key not in have and len(have) >= MAX_PREFS:
                raise HTTPError(413, "too many prefs")
            a.store.set_pref(u["username"], key, data.get("value"))
            return self._json(200, {"ok": True})
        if path == "/api/approvals":
            return self._ask_owner(u, self._body())
        if path == "/api/settings/module":
            return self._module_settings(u, self._body())
        m = CONFIG_RE.match(path)
        if m:
            self._need("owner")
            return self._config_save(u, self._config_module(m.group(1)), self._body(), test_only=bool(m.group(2)))
        m = APPROVAL_RE.match(path)
        if m:
            return self._decide(u, int(m.group(1)), m.group(2), self._body())
        m = USER_LOGOUT_RE.match(path)
        if m:
            self._need("owner")
            n = a.store.end_sessions_for(m.group(1))
            a.store.audit(u, "revoke-sessions", target=m.group(1), result=n)
            return self._json(200, {"ended": n})
        raise HTTPError(404, "not found")

    # --- module settings (owner only: turning modules on/off and widening access is identity) ---------------
    def _module_settings(self, u, data):
        a = self.app
        self._need("owner")
        mod = a.registry.get(str(data.get("module") or ""))
        if not mod:
            raise HTTPError(404, "no such module")
        changes = {}
        if "enabled" in data:
            if not isinstance(data["enabled"], bool):
                raise HTTPError(400, "enabled must be true/false")
            changes["_enabled"] = data["enabled"]
        if "extraGroups" in data:
            g = data["extraGroups"]
            if not (isinstance(g, list) and len(g) <= 30 and all(isinstance(x, str) and re.match(r"^[\w .-]{1,80}$", x) for x in g)):
                raise HTTPError(400, "extraGroups must be a list of group names")
            if g and not a.registry.guest_safe(mod):
                raise HTTPError(400, f"{mod['id']} uses a shared admin credential for its backend: guest groups would see "
                                     "everything through it (mark the manifest guest_safe only if the backend filters per user)")
            changes["_groups"] = sorted(set(g))
        schema = {st["key"]: st for st in a.registry.schema(mod)}
        vals = data.get("values") or {}
        if not isinstance(vals, dict):
            raise HTTPError(400, "values must be an object")
        for k, v in vals.items():
            if k not in schema:
                raise HTTPError(400, f"unknown setting {k}")
            try:
                changes[k] = None if v is None else check_value(schema[k], v)
                if k == "_protect" and v:
                    protect_routes(v)  # each must be a valid route pattern
            except (ValueError, ManifestError) as e:
                raise HTTPError(400, f"{k}: {e}") from None
        for k, v in changes.items():
            a.store.set_module_setting(mod["id"], k, v)
        a.reload_config()
        if "_enabled" in changes:  # a connector module switched on/off: start or stop its service
            a.connectors.apply(mod["id"], restart=False)
        a.store.audit(u, "module-settings", mod["id"], ",".join(changes), "ok", json.dumps(changes)[:900])
        return self._json(200, {"ok": True, "values": a.registry.values(mod), "enabled": a.registry.enabled(mod)})

    # --- module config (manifest v2): owner only, secrets never leave the gateway -------------------------------
    def _config_module(self, mid):
        mod = self.app.registry.get(mid)
        if not mod or not mod.get("_v2"):
            raise HTTPError(404, "no such module, or it has no per-installation config (manifest v1)")
        return mod

    def _connector_config(self, method):
        """GET /api/connector/config from a connector on this host: its own module config (secrets opened) + what it
        may use of other modules (gateway/lab/connectors.py). Authenticated with the connector's OWN key, scope
        "_config.<id>"; only from 127.0.0.1 (the socket address — a proxy header never counts)."""
        a = self.app
        mid = str(self.headers.get(CONNECTOR_HEADER) or "")
        if method != "GET" or not a.connectors.verify(mid, self.headers.get("X-Lab-Auth"), self.client_address[0]):
            log.warning("connector config refused: id=%r from %s", mid[:40], self.client_address[0])
            raise HTTPError(403, "not a connector of this gateway")
        body = a.connectors.payload(mid)
        log.info("connector %s fetched its config (ready=%s, uses=%s)", mid, body["ready"], ",".join(body["uses"]) or "-")
        return self._json(200, body, {"Cache-Control": "no-store"})

    def _connector_call(self, method, path, query):
        """/api/connector/call/<module>/<path> from a connector on this host (security review 2026-11-15, L4): a
        connector with `uses_credentials_of` reaches a module with an OWN backend only through here, never with that
        module's HMAC key. Needed, all of them:
          * the raw socket is 127.0.0.1, and X-Lab-Auth is signed with the connector's OWN key, scope "_call.<id>";
          * X-Lab-Act: the act token the gateway gave the connector with a user's request (delegate.py, version a1),
            minted for THIS connector, its session still alive; the user is re-read (disabled = out, a lower role counts);
          * the module is in the connector's uses_credentials_of, both modules are on and usable by that user;
          * then the user's own rules, as in _proxy: route, owner_only/min, _protect (body conditions too), query and
            body allow-lists. "Ask" is refused unless the token carries an owner's approval (the owner approved the
            request that started this work) and that owner is still an active owner.
        No cache, no approvals made from here; writes are audited as "<label> via <connector>"."""
        a = self.app
        caller = str(self.headers.get(CONNECTOR_HEADER) or "")
        cm = a.registry.get(caller) if re.fullmatch(r"[a-z][a-z0-9-]{1,30}", caller) else None
        if not cm or not a.connectors.verify(caller, self.headers.get("X-Lab-Auth"), self.client_address[0],
                                             call_scope(caller)):
            log.warning("connector call refused: id=%r from %s", caller[:40], self.client_address[0])
            raise HTTPError(403, "not a connector of this gateway")
        claims = a.act.verify(self.headers.get(ACT_HEADER))
        if not claims or claims["v"] != caller:
            raise HTTPError(401, "missing, forged or expired act token (it comes with a user's request to the connector)")
        if not a.store.session_alive(claims["s"]):
            raise HTTPError(401, "the session behind this act token has ended")
        user = a.store.user(claims["u"])
        if not user or user.get("disabled") or user["role"] not in ("owner", "admin"):
            raise HTTPError(403, "this user may not act through a connector")
        u = {**user, "role": lower_role(claims["r"], user["role"])}
        m = CONNECTOR_CALL_RE.match(path)
        if not m:
            raise HTTPError(404, "not found")
        mid, sub = m.group(1), m.group(2) or "/"
        if not (a.registry.enabled(cm) and a.registry.can_use(cm, u)):
            raise HTTPError(403, f"module {caller} is off or not for this user")
        if mid not in a.connectors.uses(cm):
            a.store.audit(u, f"denied via {caller}", mid, f"{method} {sub}"[:300], "not in uses_credentials_of")
            raise HTTPError(403, f"{mid} is not in {caller}'s connector.uses_credentials_of")
        mod = a.registry.get(mid)
        if not mod or not a.registry.enabled(mod) or not a.registry.can_use(mod, u):
            raise HTTPError(404, "no such module")
        bad = a.registry.path_problem(mod, sub)
        if bad:
            raise HTTPError(400, bad)
        approver = claims.get("a")
        approver_ok = bool(approver) and approver in a.store.active_owners()

        def allowed(route_or_prot):
            v = a.registry.permission(route_or_prot, u)
            return v == "yes" or (v == "ask" and approver_ok)

        def refuse(why):
            a.store.audit(u, f"denied via {caller}", mid, f"{method} {sub}"[:300], "403", why)
            raise HTTPError(403, f"not allowed for {u['username']} through {caller}: {why}")

        route = a.registry.find_route(mod, method, sub)
        if not route:
            refuse("no such route")
        if not allowed(route):
            refuse("owner approval needed" if a.registry.permission(route, u) == "ask" else "not allowed")
        body = self._raw_body(route.get("max_body") or ROUTE_BODY) if method != "GET" else b""
        ctype = self.headers.get("Content-Type") or "application/json"
        if method != "GET":
            prot = a.registry.body_protected(mod, method, sub, body, query, ctype)
            if prot and not allowed(prot):
                refuse("owner approval needed (protected)")
        if not a.registry.query_ok(route, query):
            refuse("query string not in the route's allow-list")
        hdrs = {"Accept": self.headers.get("Accept") or "application/json"}
        if body:
            hdrs["Content-Type"] = ctype
        if a.registry.body_restricted(route):
            if not a.registry.body_ok(route, body):
                refuse("body not in the route's allow-list")
            hdrs["Content-Type"] = "application/json"
        key, bearer = a.keys.credentials(mod)
        if not (key or bearer):
            raise HTTPError(503, f"module {mid} has no key on this gateway")
        a.counters["proxied"] += 1
        code, rh, data = forward(mod, key, u, method, sub, query, body, hdrs,
                                 approved_by=approver if approver_ok else None, client_ip="127.0.0.1", bearer=bearer,
                                 timeout=route.get("timeout"))
        if method != "GET" and code < 400:
            a.module_changed(mod)
        if method != "GET" and route.get("audit", True):
            a.store.audit(u, f"{route.get('label') or 'action'} via {caller}", mid, f"{method} {sub}"[:300], code,
                          f"approved by {approver}" if approver_ok and approver else "")
        ctype_out = rh.pop("Content-Type", None) or rh.pop("content-type", None) or "application/octet-stream"
        rh["Cache-Control"] = "no-store"
        return self._send(code, data, ctype_out, rh, csp=PROXY_CSP)

    def _config_view(self, mod):
        stored = self.app.store.module_config(mod["id"])
        fields = []
        for f in mod["config"]["fields"]:
            v, sec = stored.get(f["key"], (None, f["type"] == "secret"))
            pub = {k: f[k] for k in ("key", "type", "label", "help", "required", "options", "placeholder", "min", "max",
                                     "multiline") if k in f}
            if f["type"] == "secret":
                pub["set"] = v is not None  # the value itself never leaves the gateway
            else:
                pub["value"] = v if v is not None else f.get("default")
            fields.append(pub)
        return {"module": mod["id"], "fields": fields, "needsSetup": self.app.registry.needs_setup(mod),
                "missing": mod.get("_missing") or [], "testable": bool(mod["config"].get("validate")),
                "secretsReady": self.app.box is not None}

    def _config_candidate(self, mod, values):
        """Merge the posted values over what is stored → ({field: plain value}, {field: sealed-or-None changes})."""
        if not isinstance(values, dict):
            raise HTTPError(400, "values must be an object")
        fields = {f["key"]: f for f in mod["config"]["fields"]}
        unknown = set(values) - set(fields)
        if unknown:
            raise HTTPError(400, f"unknown config field(s): {sorted(unknown)}")
        a = self.app
        plain = {k: a.config_value(mod["id"], k) for k in fields}
        changes = {}
        for k, v in values.items():
            f = fields[k]
            if v is None:  # null = clear the field
                plain[k] = None
                changes[k] = None
                continue
            try:
                plain[k] = _config_check(f, v)
            except ValueError as e:
                raise HTTPError(400, f"{k}: {e}") from None
            changes[k] = plain[k]
        missing = [k for k, f in fields.items() if f.get("required") and plain.get(k) in (None, "")]
        # security review 2026-11-15 (M4): a stored secret never follows a changed address — whoever points the module
        # somewhere else must type the secret again (else a test call would hand it to the new host)
        stored = a.store.module_config(mod["id"])
        moved = [k for k, f in fields.items() if f["type"] == "url" and k in changes
                 and (stored.get(k, (None, False))[0] or f.get("default")) not in (None, "")
                 and changes[k] != (stored.get(k, (None, False))[0] or f.get("default"))]
        kept = [k for k, f in fields.items() if f["type"] == "secret" and k not in changes and stored.get(k, (None, False))[0]]
        if moved and kept:
            raise HTTPError(400, f"the address changed ({', '.join(moved)}): enter {', '.join(kept)} again")
        return plain, changes, missing

    def _config_save(self, u, mod, data, test_only=False):
        a = self.app
        plain, changes, missing = self._config_candidate(mod, data.get("values") or {})
        if any(f["type"] == "secret" and changes.get(f["key"]) for f in mod["config"]["fields"]) and not a.box:
            raise HTTPError(503, "no master key (/etc/lab/master.key): secrets can't be stored yet")
        result = None
        if not missing and mod["config"].get("validate") and (test_only or data.get("test", True)):
            result = self._config_test(mod, plain, u)
        if test_only:
            return self._json(200, {"ok": bool(result and result["ok"]), "missing": missing, "test": result})
        if result and not result["ok"] and not data.get("force"):
            return self._json(422, {"error": "connection test failed (save with force to keep it anyway)",
                                    "test": result, "missing": missing})
        for k, v in changes.items():
            f = next(x for x in mod["config"]["fields"] if x["key"] == k)
            if f["type"] == "secret" and v is not None:
                a.store.set_module_config(mod["id"], k, a.box.seal(mod["id"], k, v), secret=True)
            else:
                a.store.set_module_config(mod["id"], k, v)
        a.reload_config()
        shown = {k: ("<secret>" if any(f["key"] == k and f["type"] == "secret" for f in mod["config"]["fields"]) and v
                     else v) for k, v in changes.items()}
        a.store.audit(u, "module-config", mod["id"], ",".join(changes), "ok" if not missing else "incomplete",
                      json.dumps(shown)[:900])
        unit = a.connectors.apply(mod["id"]) if changes else None  # a connector restarts with its new config
        return self._json(200, {"ok": True, "test": result, **self._config_view(mod),
                                **({"connector": unit} if unit is not None else {})})

    def _config_test(self, mod, plain, u):
        """One call to the module's config.validate route with the CANDIDATE config (nothing saved yet). A connector
        answers it itself: the gateway posts the candidate values to it and it tries its upstream login with them."""
        if mod.get("connector"):
            return self.app.connectors.validate(mod, plain, u)
        be, _ = manifest2.render(mod, plain)
        v = mod["config"]["validate"]
        hdrs = dict(be.get("headers") or {})
        auth = be.get("auth")
        if auth:
            secret = plain.get(auth["secret"]) or ""
            if auth["type"] == "bearer":
                hdrs["Authorization"] = f"Bearer {secret}"
            elif auth["type"] == "basic":
                import base64
                pair = f"{secret}:{auth['password']}" if "password" in auth else f"{plain.get(auth.get('username')) or ''}:{secret}"
                hdrs["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
            else:
                hdrs[auth["name"]] = f"{auth.get('prefix', '')}{secret}"
        return probe(be, v.get("method", "GET"), v["path"], hdrs, expect=v.get("expect") or [200], want_json=v.get("json"))

    # --- approvals -------------------------------------------------------------------------------------------
    def _ask_owner(self, u, data):
        a = self.app
        if u["role"] != "admin":
            raise HTTPError(403, "only admins ask for approvals")
        mod = a.registry.get(str(data.get("module") or ""))
        method, path = str(data.get("method") or "").upper(), str(data.get("path") or "")
        query = str(data.get("query") or "")
        if not mod or not a.registry.can_use(mod, u):
            raise HTTPError(404, "no such module")
        # what is stored is exactly what will run: a clean path and a plain query (both shown to the owner as they are)
        if a.registry.path_problem(mod, path) or len(query) > 2000 or re.search(r"[\x00-\x20\x7f#]", query):
            raise HTTPError(400, "bad path or query")
        route = a.registry.find_route(mod, method, path)
        body = data.get("body")
        body = json.dumps(body) if body is not None and not isinstance(body, str) else (body or "")
        verdict = a.registry.permission(route, u)
        if verdict == "yes" and route:
            prot = a.registry.body_protected(mod, method, path, body, query)
            verdict = a.registry.permission(prot, u) if prot else verdict
        if verdict != "ask":
            raise HTTPError(400, "this action does not need (or cannot get) an approval")
        if len(body) > SMALL_BODY:
            raise HTTPError(413, "request body too large for an approval")
        if not a.registry.body_ok(route, body.encode()) or not a.registry.query_ok(route, query):
            raise HTTPError(403, "this request body or query is not allowed for that route")
        if len(a.store.approvals("pending", requester=u["username"])) >= MAX_PENDING_ASKS:
            raise HTTPError(429, "too many open requests: wait for the owner or cancel some")
        label = str(data.get("label") or route.get("label") or f"{method} {path}")
        ap = a.store.add_approval(u["username"], mod["id"], method, path, query, body, label,
                                  str(data.get("reason") or ""), config.APPROVAL_HOURS)
        a.store.audit(u, "approval-asked", mod["id"], f"{method} {path}", ap["id"], ap["label"])
        a.approvals_changed()
        notify.send(f"[lab] {u['username']} asks: {ap['label']}",
                    f"{u.get('name') or u['username']} asks for a one-time approval on {config.BRAND} ({config.PUBLIC_URL}):\n\n"
                    f"  {ap['label']}\n  route: {route.get('label') or '-'}\n"
                    f"  module {mod['id']}: {method} {path}{'?' + query if query else ''}\n"
                    f"  body: {body[:1500] or '-'}\n\nReason: {ap['reason'] or '-'}\n\n"
                    f"Approve or deny: {config.PUBLIC_URL}/?approvals=1\n(expires in {config.APPROVAL_HOURS} h)")
        return self._json(200, {"approval": ap})

    def _decide(self, u, aid, verb, data):
        a = self.app
        ap = a.store.approval(aid)
        if not ap:
            raise HTTPError(404, "no such approval")
        if verb == "cancel":
            if u["role"] != "owner":
                ap = {**ap, "result_body": None}
            if ap["requester"] != u["username"]:
                raise HTTPError(403, "not yours")
            if not a.store.decide_approval(aid, "cancelled", u["username"]):
                raise HTTPError(409, "already decided or expired")
            a.store.audit(u, "approval-cancelled", ap["module"], ap["path"], aid)
            a.approvals_changed()
            return self._json(200, {"approval": {**a.store.approval(aid), "result_body": None}})
        self._need("owner")
        if verb == "deny":
            if not a.store.decide_approval(aid, "denied", u["username"]):
                raise HTTPError(409, "already decided or expired")
            a.store.audit(u, "approval-denied", ap["module"], ap["path"], aid, data.get("note") or "")
            a.approvals_changed()
            return self._json(200, {"approval": a.store.approval(aid)})
        # approve: re-check the route against the current manifest, then run the request once, as the requester
        mod = a.registry.get(ap["module"])
        requester = a.store.user(ap["requester"])
        route = a.registry.find_route(mod, ap["method"], ap["path"]) if mod and not a.registry.path_problem(mod, ap["path"]) else None
        verdict = a.registry.permission(route, requester) if route else "no"
        if verdict == "yes" and route:  # a body-protected request ("… field=value" in _protect) still needs this approval
            prot = a.registry.body_protected(mod, ap["method"], ap["path"], ap["body"], ap["query"])
            verdict = a.registry.permission(prot, requester) if prot else verdict
        if not (mod and requester and route and a.registry.can_use(mod, requester)
                and verdict == "ask" and a.registry.body_ok(route, ap["body"].encode())
                and a.registry.query_ok(route, ap["query"])):
            a.store.decide_approval(aid, "invalid", u["username"])
            a.store.audit(u, "approval-invalid", ap["module"], f"{ap['method']} {ap['path']}", aid)
            raise HTTPError(409, "the action is no longer valid")
        if not a.store.decide_approval(aid, "running", u["username"]):
            raise HTTPError(409, "already decided or expired")
        key, bearer = a.keys.credentials(mod)
        if not (key or bearer):
            a.store.set_approval_result(aid, "failed", 503, "module key missing")
            raise HTTPError(503, "module key missing")
        extra = None
        if a.connectors.uses(mod) and requester["role"] in ("owner", "admin"):
            # the approved work may call the modules its connector uses as the requester, with this approval
            extra = {ACT_HEADER: a.act.mint(requester, mod["id"], session_hash(self._token()), approved_by=u["username"])}
        try:
            code, _, body = forward(mod, key, requester, ap["method"], ap["path"], ap["query"],
                                    ap["body"].encode(), {"Content-Type": "application/json"}, u["username"],
                                    self.client_ip(), bearer, extra, timeout=route.get("timeout"))
        except BackendError as e:
            a.store.set_approval_result(aid, "failed", 502, str(e))
            raise
        status = "done" if code < 400 else "failed"
        a.store.set_approval_result(aid, status, code, body.decode("utf-8", "replace"))
        if code < 400 and ap["method"] != "GET":
            a.module_changed(mod)
        a.approvals_changed()
        # (the requester sees status + code only; GET /api/approvals strips result_body for non-owners)
        a.store.audit(u, "approval-approved", mod["id"], f"{ap['method']} {ap['path']}", code,
                      f"#{aid} for {ap['requester']}")
        return self._json(200, {"approval": a.store.approval(aid)})

    # --- proxy -----------------------------------------------------------------------------------------------
    def _proxy(self, method, mid, path, query):
        a = self.app
        u = self._need()
        mod = a.registry.get(mid)
        if not mod or not a.registry.can_use(mod, u):
            raise HTTPError(404, "no such module")
        bad = a.registry.path_problem(mod, path)
        if bad:
            a.store.audit(u, "denied", mid, f"{method} {path}", "path", bad)
            raise HTTPError(400, bad)
        route = a.registry.find_route(mod, method, path)
        verdict = a.registry.permission(route, u)
        if verdict == "ask":
            raise HTTPError(403, "owner approval needed", approval=True, label=route.get("label", ""))
        if verdict != "yes":
            a.store.audit(u, "denied", mid, f"{method} {path}") if method != "GET" else None
            raise HTTPError(403, "not allowed")
        key, bearer = a.keys.credentials(mod)
        if not (key or bearer):
            raise HTTPError(503, f"module {mid} has no key on this gateway")
        body = b""
        if method != "GET":
            big = self._length() > ROUTE_BODY
            if big and not BIG_BODIES.acquire(timeout=30):
                raise HTTPError(503, "busy with other uploads, try again")
            try:
                body = self._raw_body(route.get("max_body") or ROUTE_BODY)
            finally:
                if big:
                    BIG_BODIES.release()
            prot = a.registry.body_protected(mod, method, path, body, query,  # _protect "… field=value" (this install)
                                             self.headers.get("Content-Type") or "application/json")
            if prot:
                pv = a.registry.permission(prot, u)
                if pv == "ask":
                    raise HTTPError(403, "owner approval needed", approval=True, label=prot.get("label", ""))
                if pv != "yes":
                    a.store.audit(u, "denied", mid, f"{method} {path}", "protected body")
                    raise HTTPError(403, "not allowed")
        hdrs = {k: v for k, v in self.headers.items()}
        if not a.registry.query_ok(route, query):
            # query_keys: only the listed parameters; body-restricted routes without it: no query string at all, so it
            # cannot carry the same fields (Proxmox merges query parameters into the body's)
            a.store.audit(u, "denied", mid, f"{method} {path}", "query", "query not in route's allow-list")
            raise HTTPError(403, "this query string is not allowed for that route")
        if a.registry.body_restricted(route):
            # what was checked is what the backend parses: JSON only
            if not a.registry.body_ok(route, body):
                why = a.registry.body_problem(route, body) if route.get("body_schema") else None
                a.store.audit(u, "denied", mid, f"{method} {path}", "body", why or "body not in route's allow-list")
                raise HTTPError(403, "this request body is not allowed for that route")
            hdrs = {k: v for k, v in hdrs.items() if k.lower() != "content-type"}
            hdrs["Content-Type"] = "application/json"
        a.counters["proxied"] += 1
        extra = None
        if mod.get("delegate") is True and u["role"] in ("owner", "admin"):
            # the module may read other modules AS this user through /api/delegate (see delegate.py)
            extra = {DELEGATION_HEADER: a.delegation.mint(u, mid, session_hash(self._token()))}
        if a.connectors.uses(mod) and u["role"] in ("owner", "admin"):
            # its connector may call the modules it uses AS this user, through /api/connector/call (connectors.py)
            extra = {**(extra or {}), ACT_HEADER: a.act.mint(u, mid, session_hash(self._token()))}
        ttl = ttl_for(mod, route) if method == "GET" and not extra else 0
        cache_state = None
        if ttl:  # many tabs/users polling the same thing: one backend call per ttl (cache.py)
            ckey = a.cache.key(mod, route, u, path, query)
            (code, rh, data), hit = a.cache.get(ckey, ttl, lambda: forward(
                mod, key, u, method, path, query, body, hdrs, client_ip=self.client_ip(), bearer=bearer, extra=extra,
                timeout=route.get("timeout")))
            rh, cache_state = dict(rh), "hit" if hit else "miss"
        else:
            code, rh, data = forward(mod, key, u, method, path, query, body, hdrs, client_ip=self.client_ip(),
                                     bearer=bearer, extra=extra, timeout=route.get("timeout"))
        if cache_state:
            rh["X-Lab-Cache"] = cache_state
        self._read_post = method != "GET" and route.get("audit", True) is False
        if method != "GET" and not self._read_post and code < 400:
            a.module_changed(mod)
        if method != "GET" and route.get("audit", True):
            a.store.audit(u, route.get("label") or "action", mid, f"{method} {path}", code)
        elif route.get("secret") and a.first_secret_read(u["username"], mid, path):
            # reading a secret is audited too, but once per user + path per hour: a page that loads it on every
            # refresh (prowlarr's indexer list) buried every real action in the log
            a.store.audit(u, route.get("label") or "action", mid, f"{method} {path}", code)
        ctype = rh.pop("Content-Type", None) or rh.pop("content-type", None) or "application/octet-stream"
        rh.setdefault("Cache-Control", "no-store")
        return self._send(code, data, ctype, rh, csp=PROXY_CSP)

    # --- delegation (delegate.py): a local connector reads AS the user, with the user's rules + a few more -------
    def _delegate(self, method, path, query):
        a = self.app
        if self.client_address[0] != "127.0.0.1":  # the raw socket: connectors run on the lab CT itself
            raise HTTPError(403, "delegation only from the lab CT")
        if method not in ("GET", "HEAD"):
            raise HTTPError(405, "delegated calls are read-only: writes run from the user's browser")
        claims = a.delegation.verify(self.headers.get(DELEGATION_HEADER))
        if not claims:
            raise HTTPError(401, "missing, forged or expired delegation")
        if not a.store.session_alive(claims["s"]):
            raise HTTPError(401, "the session behind this delegation has ended")
        user = a.store.user(claims["u"])
        if not user or user["role"] not in ("owner", "admin"):
            raise HTTPError(403, "this user may not delegate")
        u = {**user, "role": lower_role(claims["r"], user["role"]), "via": claims["v"]}
        via = a.registry.get(claims["v"])
        if not (via and via.get("delegate") is True and a.registry.can_use(via, u)):
            raise HTTPError(403, f"module {claims['v']} is off or not delegating")
        if path == "/api/delegate/whoami":
            return self._json(200, {"user": _public_user(u), "settings": a.registry.values(via),
                                    "modules": self._catalog(u), "expires": claims["x"]})
        m = DELEGATE_RE.match(path)
        if not m:
            raise HTTPError(404, "not found")
        mid, sub = m.group(1), m.group(2) or "/"
        mod = a.registry.get(mid)
        if not mod or not a.registry.can_use(mod, u):
            raise HTTPError(404, "no such module")
        if mod.get("delegate"):
            raise HTTPError(403, "a delegating module cannot be read through a delegation")
        bad = a.registry.path_problem(mod, sub)
        if bad:
            raise HTTPError(400, bad)
        route = a.registry.find_route(mod, "GET", sub)
        if not route or route.get("secret") or a.registry.permission(route, u) != "yes":
            a.store.audit(u, f"denied via {claims['v']}", mid, f"GET {sub}"[:300], "403")
            raise HTTPError(403, "not allowed for this user through the assistant (secret routes never are)")
        if not a.registry.query_ok(route, query):
            raise HTTPError(403, "this query string is not allowed for that route")
        key, bearer = a.keys.credentials(mod)
        if not (key or bearer):
            raise HTTPError(503, f"module {mid} has no key on this gateway")
        a.counters["proxied"] += 1
        code, rh, data = forward(mod, key, u, "GET", sub, query, b"", {"Accept": "application/json"},
                                 client_ip="127.0.0.1", bearer=bearer)
        a.store.audit(u, f"read via {claims['v']}", mid, f"GET {sub}" + (f"?{query}" if query else ""), code,
                      f"{u['username']} via {claims['v']}")
        ctype = (rh.get("Content-Type") or rh.get("content-type") or "").lower()
        raw = data[:DELEGATE_ANSWER]
        if "json" in ctype or raw[:1] in (b"{", b"["):
            try:
                out = redact.data(json.loads(raw.decode("utf-8", "replace")))
            except ValueError:
                out = {"text": redact.text(raw.decode("utf-8", "replace"))}
        elif ctype.startswith("text/") or not ctype:
            out = {"text": redact.text(raw.decode("utf-8", "replace"))}
        else:
            out = {"error": f"binary answer ({ctype}) is not passed to the assistant"}
        return self._json(200, {"status": code, "truncated": len(data) > DELEGATE_ANSWER, "body": out})

    def _catalog(self, u):
        """The modules + routes this user may use, as the assistant may see them: no secret routes, no delegating
        modules, no backend URLs; each route with this user's verdict (yes/ask) and its body/query allow-lists."""
        out = []
        for m in sorted(self.app.registry.modules.values(), key=lambda x: x["id"]):
            if m.get("delegate") or not self.app.registry.can_use(m, u):
                continue
            routes = []
            for r in m.get("routes", []):
                verdict = self.app.registry.permission(r, u)
                if r.get("secret") or verdict == "no":
                    continue
                x = {"method": r["method"], "path": r["path"], "allow": verdict}
                for k in ("label", "body_keys", "query_keys", "body_allow", "body_list", "body_schema"):
                    if r.get(k) not in (None, "", []) or (k == "query_keys" and r.get(k) == []):
                        x[k] = r[k]
                routes.append(x)
            out.append({"id": m["id"], "name": m["name"], "description": (m.get("description") or "")[:300],
                        "routes": routes})
        return out

    # --- installed modules' UI (docs/catalog.md) ------------------------------------------------------------
    def _module_bundle(self, mid, version):
        """/modules/<id>/<version>/ui.js: the UI bundle of a module installed from a catalog, for users who may use it
        (code is not secret, but a guest has no business with modules they can't open). Revalidated with an ETag: the
        version is in the path, but a removed and reinstalled module could come back with other bytes."""
        u = self._need()
        a = self.app
        mod = a.registry.get(mid)
        path = a.registry.bundle_file(mid, version)
        if not path or not a.registry.can_use(mod, u):
            raise HTTPError(404, "not found")
        with open(path, "rb") as f:
            data = f.read()
        etag = '"' + hashlib.sha256(data).hexdigest()[:32] + '"'
        if self.headers.get("If-None-Match") == etag:
            return self._send(304, b"", "text/javascript; charset=utf-8", {"ETag": etag, "Cache-Control": "private, no-cache"})
        return self._send(200, data, "text/javascript; charset=utf-8",
                          {"ETag": etag, "Cache-Control": "private, no-cache"})

    # --- static UI -------------------------------------------------------------------------------------------
    def _static(self, path):
        root = os.path.realpath(config.STATIC_DIR)
        rel = path.lstrip("/") or "index.html"
        full = os.path.realpath(os.path.join(root, rel))
        if not full.startswith(root + os.sep) or not os.path.isfile(full):
            if "." in os.path.basename(path):
                raise HTTPError(404, "not found")
            full = os.path.join(root, "index.html")  # client-side route
            if not os.path.isfile(full):
                return self._send(503, b"UI not built", "text/plain")
        with open(full, "rb") as f:
            data = f.read()
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        cache = "public, max-age=31536000, immutable" if "/assets/" in full else "no-cache"
        # the page's inline import map (the module ABI, ui/vite-abi.js) is a script: CSP allows exactly that one by hash
        csp = _csp_for_page(data) if ctype.startswith("text/html") else CSP
        return self._send(200, data, ctype, {"Cache-Control": cache}, csp=csp)

    # --- metrics ---------------------------------------------------------------------------------------------
    def _metrics(self):
        a = self.app
        lines = ["# TYPE lab_up gauge", "lab_up 1", f'lab_build_info{{version="{BUILD}",commit="{BUILD_COMMIT[:12]}"}} 1',
                 f"lab_uptime_seconds {time.time() - STARTED:.0f}",
                 f"lab_modules {len(a.registry.modules)}", f"lab_module_errors {len(a.registry.errors)}",
                 f"lab_sessions {len(a.store.sessions())}",
                 f"lab_approvals_pending {len(a.store.approvals('pending'))}"]
        for k, v in a.counters.items():
            lines.append(f"lab_{k}_total {v}")
        lines += [f"lab_event_streams {a.events.count()}", f"lab_events_sent_total {a.events.sent}",
                  f"lab_proxy_cache_hits_total {a.cache.hits}", f"lab_proxy_cache_misses_total {a.cache.misses}"]
        for mid, s in a.health.state.items():
            lines.append(f'lab_backend_up{{module="{mid}"}} {1 if s["up"] else 0}')
            lines.append(f'lab_backend_ms{{module="{mid}"}} {s["ms"]}')
        return "\n".join(lines) + "\n"


_IMPORTMAP = re.compile(rb'<script type="importmap">(.*?)</script>', re.S)
_csp_cache = {}


def _csp_for_page(html):
    """CSP for a page of the UI: script-src also allows its inline import map, by sha256 (and nothing else inline)."""
    m = _IMPORTMAP.search(html)
    if not m:
        return CSP
    body = m.group(1)
    h = _csp_cache.get(body)
    if not h:
        import base64
        h = _csp_cache[body] = base64.b64encode(hashlib.sha256(body).digest()).decode()
        if len(_csp_cache) > 8:
            _csp_cache.clear()
    return CSP.replace("script-src 'self'", f"script-src 'self' 'sha256-{h}'", 1)


def _public_user(u, must_enrol=False):
    out = {"username": u["username"], "name": u.get("name") or u["username"], "role": u["role"],
           "groups": u.get("groups") or [], "via": u.get("via", ""), "totp": bool(u.get("totp")),
           "local": bool(u.get("pw_hash"))}
    if must_enrol:
        out["mustEnrol"] = True
    return out


class Reaper:
    """Closes connections that miss their deadline (slowloris: a client sending one header byte every 29 s would hold a
    pool thread for ever; the socket timeout only bounds each single recv). One thread for all connections."""

    def __init__(self):
        self.lock, self.due = threading.Lock(), {}
        threading.Thread(target=self._loop, name="reaper", daemon=True).start()

    def watch(self, sock, seconds):
        with self.lock:
            self.due[sock] = time.monotonic() + seconds

    def done(self, sock):
        with self.lock:
            self.due.pop(sock, None)

    def _loop(self):
        while True:
            time.sleep(1)
            now = time.monotonic()
            with self.lock:
                late = [s for s, t in self.due.items() if t < now]
                for s in late:
                    self.due.pop(s, None)
            for s in late:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


REAPER = Reaper()


class PooledHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, handler, app, workers=64):
        super().__init__(addr, handler)
        self.app = app
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="req")

    def process_request(self, request, client_address):
        self._pool.submit(self.process_request_thread, request, client_address)

    # /api/events hands its socket to the event broadcaster: the server must not shut it down after the handler returns
    _detached = set()

    def detach(self, request):
        self._detached.add(request)

    def shutdown_request(self, request):
        if request in self._detached:
            self._detached.discard(request)
            return
        super().shutdown_request(request)


def serve():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    app = App()
    app.health.start()

    def prune_loop():
        while True:
            try:
                app.store.prune()
            except Exception:  # noqa: BLE001
                log.exception("prune failed")
            time.sleep(3600)
    import threading
    from . import rolesync
    threading.Thread(target=prune_loop, daemon=True).start()
    rolesync.CONFIG = app.config_value  # authentik URL + token from its (v2, encrypted) module config
    rolesync.SETTINGS = app.login       # neutral mode: the SSO session cap
    loop = sorted(p for p in config.TRUSTED_PROXIES if _loopback(p))
    if loop and not config.PROXY_SECRET:
        log.warning("LAB_TRUSTED_PROXIES has %s: ignored without LAB_PROXY_SECRET (local connectors share loopback "
                    "and could forge client IPs)", ",".join(loop))
    if not app.store.active_owners():   # the link itself never goes to the journal (shipped to log servers)
        if app.store.setup_closed():
            log.warning("NO ACTIVE OWNER (one existed before): setup stays closed. Root: lab-admin user NAME --enable, "
                        "lab-admin passwd NAME --role owner, or lab-admin setup-link --recover")
        else:
            log.warning("FIRST RUN: no owner yet. The one-time link to create the owner account is in %s (root only); "
                        "a fresh one: lab-admin setup-link", config.SETUP_LINK_FILE)
    threading.Thread(target=rolesync.loop, args=(app.store,), name="rolesync", daemon=True).start()
    srv = PooledHTTPServer((config.HOST, config.PORT), Handler, app)
    log.info("lab gateway on %s:%s, %d module(s): %s", config.HOST, config.PORT, len(app.registry.modules),
             ", ".join(app.registry.modules) or "-")
    app.start_connectors()  # after the socket is bound: a starting connector fetches its config from us
    threading.Thread(target=startup_audit, args=(app,), name="update-audit", daemon=True).start()
    srv.serve_forever()
