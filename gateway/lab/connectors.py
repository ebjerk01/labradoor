"""Connectors managed by Labradoor: their config, their credentials of other modules, and their units.

A connector (connectors/<id>/connector.py; manifest `"connector": {...}`) is a small service on the lab host for an API
that a manifest can't reach directly. Labradoor runs it as `lab-connector@<id>`, as its OWN unix user `lab-c-<id>`:

  * its HMAC key reaches it through systemd (`LoadCredential=key:/etc/lab/keys/<id>.key`): root reads the file and
    hands the unit a private copy. The connector can't read /etc/lab or /var/lib/lab at all (InaccessiblePaths).
  * its config comes from HERE: GET /api/connector/config from 127.0.0.1, signed with its own key (claims
    m = "_config.<id>", so a token the gateway sends TO the connector never passes as a config request and vice versa).
    The answer holds its module config (secrets opened) and, for each module in `uses_credentials_of` that is on and
    set up, that module's rendered backend + only the credential it needs: the auth secret (+ username) of a
    third-party API. A module with an OWN backend (one that verifies X-Lab-Auth) is never reached with its HMAC key:
    that key would also sign any user and approval for it, and fetch that module's config if it is a connector
    (security review 2026-11-15, L4). The connector calls it THROUGH the gateway instead: /api/connector/call/<module>/…,
    signed with its own key (scope "_call.<id>") and carrying the X-Lab-Act token the gateway gave it with the user's
    request — the gateway then applies that user's own rules to the call, exactly as for the browser.
  * the gateway (user lab) never needs root: a socket-activated root helper (deploy/lab-connector-helper, socket
    /run/lab-connector-helper.sock, group lab only) creates the user and the key and starts/restarts/stops the unit.
    The gateway asks it when the owner saves a connector module's config or turns the module on/off, and once at start.
"""
import json
import logging
import os
import socket
import threading
import time

from .proxy import BackendError, forward

log = logging.getLogger("lab.connectors")
HELPER_SOCKET = os.environ.get("LAB_CONNECTOR_HELPER", "/run/lab-connector-helper.sock")
CONFIG_PATH = "/api/connector/config"
CALL_PREFIX = "/api/connector/call/"
CONNECTOR_HEADER = "X-Lab-Connector"


def config_scope(mid):
    """The `m` claim of a connector's own request for its config (domain separation from user tokens)."""
    return f"_config.{mid}"


def call_scope(mid):
    """The `m` claim of a connector's call through the gateway to a module in its uses_credentials_of."""
    return f"_call.{mid}"


class HelperError(Exception):
    pass


def helper(req, timeout=60, path=None):
    """One request to the root helper: one JSON line in, one JSON line out ({"ok": bool, ...})."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path or HELPER_SOCKET)
            s.sendall(json.dumps(req).encode() + b"\n")
            s.shutdown(socket.SHUT_WR)
            buf = b""
            while len(buf) < 65536:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
    except OSError as e:
        raise HelperError(f"connector helper unavailable ({e.__class__.__name__}): is lab-connector-helper.socket running?") from None
    try:
        out = json.loads(buf.decode() or "{}")
    except ValueError:
        raise HelperError("connector helper gave no answer") from None
    if not out.get("ok"):
        raise HelperError(str(out.get("error") or "connector helper refused"))
    return out


class Connectors:
    def __init__(self, app, call=helper):
        self.app, self.call = app, call
        self._lock = threading.Lock()

    # --- which modules are connectors, and should each run? ------------------------------------------------------
    def modules(self):
        return [m for m in self.app.registry.modules.values() if m.get("connector")]

    def is_connector(self, m):
        return bool(m and m.get("connector"))

    def wanted(self, m):
        reg = self.app.registry
        return reg.enabled(m) and not reg.needs_setup(m)

    def apply(self, mid, restart=True):
        """Bring connector `mid` to its wanted state after the owner changed its config or switched it on/off: running
        with the new config (restart) or stopped. Never raises; returns the helper's answer or {"error": …}."""
        m = self.app.registry.get(mid)
        if not self.is_connector(m):
            return None
        op = ("restart" if restart else "ensure") if self.wanted(m) else "stop"
        try:
            with self._lock:
                out = self.call({"op": op, "id": mid})
            log.info("connector %s: %s → %s", mid, op, out.get("state"))
            return out
        except HelperError as e:
            log.warning("connector %s: %s failed: %s", mid, op, e)
            return {"error": str(e)}

    def reconcile(self):
        """At gateway start: start wanted connectors that aren't running (no restart), stop the ones switched off.
        A connector that merely needs setup is left alone (it answers 503 itself, and the gateway doesn't route to it)."""
        for m in self.modules():
            reg = self.app.registry
            if self.wanted(m):
                op = "ensure"
            elif not reg.enabled(m):
                op = "stop"
            else:
                continue
            try:
                with self._lock:
                    self.call({"op": op, "id": m["id"]})
            except HelperError as e:
                log.warning("connector %s: %s at start failed: %s", m["id"], op, e)
                return  # no helper on this host (development): don't try the rest

    def ensure_running(self, mid, wait=8.0):
        """For a config test of a connector that isn't running yet (first setup): start it and wait for /healthz."""
        m = self.app.registry.get(mid)
        try:
            with self._lock:
                self.call({"op": "ensure", "id": mid})
        except HelperError as e:
            return str(e)
        port = (m.get("connector") or {}).get("port")
        until = time.monotonic() + wait
        while time.monotonic() < until:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return None
            except OSError:
                time.sleep(0.3)
        return f"connector {mid} did not start (journalctl -u lab-connector@{mid})"

    # --- what a connector may learn --------------------------------------------------------------------------------
    def verify(self, mid, header, client_ip, scope=None):
        """The claims of a connector's own request (its config; with scope=call_scope(mid) a call through the gateway),
        or None (wrong key/scope/address/expired)."""
        import labauth  # sdk/python, on the path via .proxy
        m = self.app.registry.get(mid)
        if client_ip != "127.0.0.1" or not self.is_connector(m):
            return None
        claims = labauth.verify(header, self.app.keys.get(mid), scope or config_scope(mid))
        return claims if claims and claims.get("u") == "connector" else None

    def uses(self, m):
        return list(((m or {}).get("connector") or {}).get("uses_credentials_of") or [])

    def values(self, m):
        """The module's config: every field (defaults for unset ones), secrets opened."""
        out = {}
        for f in m["config"]["fields"]:
            v = self.app.config_value(m["id"], f["key"])
            out[f["key"]] = v if v is not None else f.get("default")
        return out

    def credential_of(self, mid):
        """What a connector needs to call module `mid`'s backend exactly as the gateway would — and nothing more.
          * a third-party API (backend.auth with a config secret): the rendered backend (URL, TLS, auth scheme) and the
            auth secret (+ basic-auth username) — nothing else of that module's config;
          * an own backend (verifies X-Lab-Auth): NO key. {"via": "gateway"}: call it through /api/connector/call/<mid>/…
            (the gateway signs as the user the connector acts for, with that user's rules). The backend URL is left
            out too: nothing to call it with directly.
        A module that is off or not set up gives {"ready": False}: its credentials are not handed out."""
        reg = self.app.registry
        m = reg.get(mid)
        if not m or not m.get("backend") or not reg.enabled(m) or reg.needs_setup(m):
            return {"ready": False}
        be = json.loads(json.dumps(m["backend"]))
        auth = be.get("auth")
        if not auth:
            return {"ready": True, "via": "gateway", "values": {}, "key": None,
                    "backend": {k: be[k] for k in ("timeout",) if k in be}}
        out = {"ready": True, "backend": be, "values": {}, "key": None}
        if auth.get("secret"):
            for k in (auth["secret"], auth.get("username")):
                if k:
                    out["values"][k] = self.app.config_value(mid, k)
        return out

    def payload(self, mid):
        m = self.app.registry.get(mid)
        return {"id": mid, "ready": not self.app.registry.needs_setup(m), "enabled": self.app.registry.enabled(m),
                "missing": m.get("_missing") or [], "values": self.values(m),
                "uses": {u: self.credential_of(u) for u in self.uses(m)}}

    # --- the config test: the CONNECTOR checks the candidate values against its upstream ----------------------------
    def validate(self, mod, plain, user):
        v = mod["config"]["validate"]
        key = self.app.keys.get(mod["id"])
        started = None
        if not key:  # first setup: the helper makes the user + key and starts it
            started = self.ensure_running(mod["id"])
            key = self.app.keys.get(mod["id"])
            if not key:
                return {"ok": False, "status": None, "error": started or f"no key for {mod['id']} (connector helper?)"}
        body = json.dumps({"values": plain}).encode()
        t0 = time.monotonic()
        for attempt in (1, 2):
            try:
                code, _, data = forward({"id": mod["id"], "backend": {"url": f"http://127.0.0.1:{mod['connector']['port']}",
                                                                      "timeout": 25}},
                                        key, user, v.get("method", "POST"), v["path"], "", body,
                                        {"Content-Type": "application/json", "Accept": "application/json"})
                break
            except BackendError:
                if attempt == 2:
                    return {"ok": False, "status": None, "error": started or f"connector {mod['id']} is not running"}
                started = self.ensure_running(mod["id"])
                if started:
                    return {"ok": False, "status": None, "error": started}
        try:
            ans = json.loads(data or b"{}")
        except ValueError:
            ans = {}
        ok = code in tuple(v.get("expect") or [200]) and ans.get("ok") is True
        err = "" if ok else str(ans.get("error") or ans.get("detail") or f"HTTP {code}")[:300]
        return {"ok": ok, "status": code, "ms": round((time.monotonic() - t0) * 1000, 1), "error": err,
                "detail": str(ans.get("detail") or "")[:300]}
