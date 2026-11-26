"""Labradoor connector runtime: the key and the config of a connector (stdlib only; import as `labconn`).

A connector runs as its own unix user and can't read /etc/lab. It gets:
  * its HMAC key from systemd: `LoadCredential=key:/etc/lab/keys/<id>.key` puts a private copy in
    $CREDENTIALS_DIRECTORY/key (LAB_KEY_FILE overrides it for development);
  * its config from the gateway: GET /api/connector/config on 127.0.0.1, signed with that key (scope "_config.<id>").
    The answer: {"id", "ready", "enabled", "missing", "values": {field: value, secrets opened},
                 "uses": {module: {"ready", "backend", "values", "key", "via"}}} (uses = manifest connector.uses_credentials_of)
    A module with an own backend comes as {"ready": true, "via": "gateway"} and NO key: call it with `call()` below,
    as the user whose request carried the X-Lab-Act token (the gateway applies that user's rules).

    KEY = labconn.load_key(ID)
    CONF = labconn.Config(ID, KEY, apply=configure)   # configure(values, conf) sets the connector's globals
    CONF.start()                                      # background: fetch (retrying until the gateway answers)
    ...
    if not CONF.ready: answer 503 CONF.why()           # in request handling, before using the config

The gateway restarts a connector after its config changed, so a connector reads its config once.
"""
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import labauth

GATEWAY = os.environ.get("LAB_GATEWAY", "http://127.0.0.1:8100").rstrip("/")
PATH = "/api/connector/config"
CALL_PATH = "/api/connector/call/"
ACT_HEADER = "X-Lab-Act"   # the gateway hands it to a connector with uses_credentials_of, with each owner/admin request
log = logging.getLogger("labconn")


def load_key(cid):
    """The connector's HMAC key (bytes) or None."""
    path = os.environ.get("LAB_KEY_FILE")
    if not path and os.environ.get("CREDENTIALS_DIRECTORY"):
        path = os.path.join(os.environ["CREDENTIALS_DIRECTORY"], "key")
    if not path or not os.path.exists(path):
        log.warning("connector %s: no key (systemd LoadCredential=key:… or LAB_KEY_FILE)", cid)
        return None
    return labauth.load_key(path)


def state_dir(cid, env=None):
    """Where the connector keeps state: an explicit env override, else systemd's StateDirectory."""
    return (env and os.environ.get(env)) or os.environ.get("STATE_DIRECTORY") or f"/var/lib/lab-connectors/{cid}"


def runtime_dir(cid):
    """Ephemeral files (tmpfs, removed when it stops): systemd's RuntimeDirectory."""
    return os.environ.get("RUNTIME_DIRECTORY") or f"/run/lab-connectors/{cid}"


def fetch(cid, key, gateway=None, timeout=10):
    """One config request → the answer dict. Raises OSError/ValueError when the gateway can't be asked."""
    if not key:
        raise ValueError("no key")
    req = urllib.request.Request((gateway or GATEWAY) + PATH, headers={
        "X-Lab-Connector": cid, labauth.HEADER: labauth.sign(key, {"u": "connector", "r": "guest", "m": f"_config.{cid}"}),
        "Accept": "application/json", "User-Agent": f"lab-connector/{cid}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read(4 * 1024 * 1024))
    if not isinstance(data, dict) or data.get("id") != cid or not isinstance(data.get("values"), dict):
        raise ValueError("unexpected config answer")
    return data


def call(cid, key, act, module, method, path, query="", body=b"", headers=None, gateway=None, timeout=60):
    """Call module `module` (in this connector's uses_credentials_of, with an own backend) THROUGH the gateway, as the
    user whose request gave us `act` (the X-Lab-Act header). → (status, headers, body bytes). The gateway checks
    this connector's key (scope "_call.<id>"), the act token, and that user's own rules for the route; answers
    401/403 otherwise. Raises OSError when the gateway can't be reached."""
    import http.client
    if not key or not act:
        raise ValueError("no key or no act token (the request that started this work brought none)")
    u = urllib.parse.urlsplit(gateway or GATEWAY)
    target = CALL_PATH + module + (path if path.startswith("/") else "/" + path) + (("?" + query) if query else "")
    h = {k: v for k, v in (headers or {}).items() if k.lower() in ("content-type", "accept")}
    h.update({"X-Lab-Connector": cid, ACT_HEADER: act, "User-Agent": f"lab-connector/{cid}",
              labauth.HEADER: labauth.sign(key, {"u": "connector", "r": "guest", "m": f"_call.{cid}"})})
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    try:
        conn.request(method, target, body=body or None, headers=h)
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read(64 * 1024 * 1024)
    except http.client.HTTPException as e:
        raise OSError(f"gateway: {e}") from None
    finally:
        conn.close()


class Config:
    """The connector's config, fetched once in the background. `values`/`uses` are empty until `loaded`."""

    def __init__(self, cid, key, apply=None, gateway=None):
        self.cid, self.key, self.apply, self.gateway = cid, key, apply, gateway
        self.values, self.uses, self.raw = {}, {}, {}
        self.loaded = threading.Event()
        self.error = "waiting for the gateway"

    @property
    def ready(self):
        """Loaded AND the module is set up (every required field filled in)."""
        return self.loaded.is_set() and bool(self.raw.get("ready"))

    def why(self):
        if not self.loaded.is_set():
            return f"connector {self.cid} is starting ({self.error})"
        missing = ", ".join(self.raw.get("missing") or [])
        return f"connector {self.cid} needs setup (Settings → {self.cid} → connection{': ' + missing if missing else ''})"

    def set(self, data):
        """Use this config (tests call it directly)."""
        self.raw = data
        self.values = dict(data.get("values") or {})
        self.uses = dict(data.get("uses") or {})
        if self.apply:
            self.apply(self.values, self)
        self.loaded.set()

    def load_once(self):
        self.set(fetch(self.cid, self.key, self.gateway))

    def start(self, retry=2.0, max_retry=30.0):
        def run():
            delay = retry
            while not self.loaded.is_set():
                try:
                    self.load_once()
                    log.info("connector %s: config loaded (%s)", self.cid, "ready" if self.ready else "needs setup")
                    return
                except urllib.error.HTTPError as e:
                    self.error = f"gateway said {e.code}"
                    if e.code == 403:  # key mismatch: retrying won't help soon, but the key may be re-made
                        log.error("connector %s: the gateway refused its key (403)", self.cid)
                except (OSError, ValueError) as e:
                    self.error = f"gateway unreachable: {e.__class__.__name__}"
                except Exception as e:  # noqa: BLE001  (a bug in apply(): keep the service up, say so)
                    self.error = f"config could not be applied: {e.__class__.__name__}"
                    log.exception("connector %s: applying the config failed", self.cid)
                time.sleep(delay)
                delay = min(max_retry, delay * 1.5)
        t = threading.Thread(target=run, name="config", daemon=True)
        t.start()
        return t


def text(values, key, default=""):
    v = values.get(key)
    return default if v is None else str(v).strip()


def url(values, key):
    return text(values, key).rstrip("/")


def candidate(claims, body):
    """The values of a config test (POST /api/_validate from the gateway, owner only) → dict, or raises ValueError.
    A connector tries its upstream login with THESE values (not its current config) and answers
    {"ok": true, "detail": "..."} or {"ok": false, "error": "..."} — never a credential."""
    if not claims or claims.get("r") != "owner":
        raise PermissionError("owner only")
    vals = (body or {}).get("values")
    if not isinstance(vals, dict):
        raise ValueError("values must be an object")
    return vals
