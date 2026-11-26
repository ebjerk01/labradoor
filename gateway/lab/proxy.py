"""Forwarding a checked request to a module backend, signed with that module's key (sdk/python/labauth.py)."""
import base64
import http.client
import os
import ssl
import sys
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdk", "python"))
import labauth  # noqa: E402

MAX_RESPONSE = 64 * 1024 * 1024
PASS_RESPONSE = ("content-type", "cache-control", "content-disposition", "etag", "last-modified", "content-range",
                 "accept-ranges", "retry-after")
PASS_REQUEST = ("content-type", "accept", "range", "if-none-match", "if-modified-since", "content-range", "x-file-name")


class BackendError(Exception):
    pass


class Keys:
    """Per-module HMAC keys from KEYS_DIR/<id>.key, cached until the file changes."""

    def __init__(self, keys_dir, lookup=None):
        self.dir, self._cache = keys_dir, {}
        self.lookup = lookup  # (module, field) -> config value or opened secret (v2 modules), set by the App

    def credentials(self, module):
        """(hmac key, extra headers) for a module. A backend.auth module (third-party API) gets its credential header
        from the keys dir instead of the signed X-Lab-Auth; the browser never sees it."""
        auth = (module.get("backend") or {}).get("auth")
        if not auth:
            return self.get(module["id"]), None
        if auth.get("secret"):  # v2: from the module's config, opened by the App (a connector: from its uses)
            lookup = self.lookup or (lambda _m, _k: None)
            secret = lookup(module["id"], auth["secret"])
            if secret and auth["type"] == "basic":
                if "password" in auth:  # the secret is the user, the password fixed text (Graylog access tokens)
                    secret = f"{secret}:{auth['password']}"
                else:
                    user = lookup(module["id"], auth.get("username") or "") or ""
                    secret = f"{user}:{secret}"
        else:
            secret = self.token(auth["file"])
        if not secret:
            return None, None
        kind = auth["type"]
        if kind == "bearer":
            return None, {"Authorization": f"Bearer {secret}"}
        if kind == "basic":
            return None, {"Authorization": "Basic " + base64.b64encode(secret.encode()).decode()}
        return None, {auth["name"]: f"{auth.get('prefix', '')}{secret}"}

    def token(self, name):
        try:
            with open(os.path.join(self.dir, name), encoding="utf-8") as f:
                return f.read().strip() or None
        except OSError:
            return None

    def get(self, mid):
        path = os.path.join(self.dir, f"{mid}.key")
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        hit = self._cache.get(mid)
        if hit and hit[0] == mtime:
            return hit[1]
        key = labauth.load_key(path)
        self._cache[mid] = (mtime, key)
        return key


def claims_for(user, module, approved_by=None):
    c = {"u": user["username"], "n": user.get("name") or user["username"], "r": user.get("role", "guest"),
         "g": list(user.get("groups") or [])[:40], "m": module}
    if approved_by:
        c["a"] = approved_by
    return c


_INSECURE = ssl._create_unverified_context()


def forward(module, key, user, method, path, query="", body=b"", headers=None, approved_by=None, client_ip="", bearer=None,
            extra=None, timeout=None):
    """timeout: the route's own (manifest route `timeout`, e.g. a slow interactive search), else the backend's (20 s)."""
    be = module["backend"]
    url = urllib.parse.urlsplit(be["url"])
    wait = timeout or be.get("timeout", 20)
    if url.scheme == "https":  # tls_verify: false for self-signed admin APIs on the LAN (Proxmox, PBS, UniFi)
        conn = http.client.HTTPSConnection(url.hostname, url.port, timeout=wait,
                                           context=_INSECURE if be.get("tls_verify") is False else None)
    else:
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=wait)
    target = (url.path.rstrip("/") + path) + (("?" + query) if query else "")
    out = {k: v for k, v in (headers or {}).items() if k.lower() in PASS_REQUEST}
    out.update(be.get("headers") or {})  # static per-backend headers, e.g. Graylog's X-Requested-By
    if key:
        out[labauth.HEADER] = labauth.sign(key, claims_for(user, module["id"], approved_by))
    if bearer:  # third-party API: the gateway's own credential headers (dict); lab's audit log names the user
        out.update(bearer)
    if extra:  # gateway-made headers (X-Lab-Delegation for a delegating module)
        out.update(extra)
    out["X-Forwarded-For"] = client_ip
    out["X-Forwarded-Proto"] = "https"
    out["User-Agent"] = "lab-gateway/1"
    try:
        conn.request(method, target, body=body or None, headers=out)
        r = conn.getresponse()
        data = r.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise BackendError("response too large")
        hdrs = {k: v for k, v in r.getheaders() if k.lower() in PASS_RESPONSE}
        return r.status, hdrs, data
    except TimeoutError:
        raise BackendError(f"{module['id']} did not answer within {wait:g} s") from None
    except (OSError, http.client.HTTPException) as e:
        raise BackendError(f"{module['id']} backend unreachable: {e}") from None
    finally:
        conn.close()
