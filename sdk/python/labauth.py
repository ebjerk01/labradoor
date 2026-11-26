"""Labradoor gateway identity — verifier for backends (copy this file into a backend; stdlib only).

The gateway signs every request it proxies to a module backend with a per-module HMAC key:

    X-Lab-Auth: v1.<base64url(JSON claims)>.<base64url(HMAC-SHA256(key, "v1." + payload))>

Claims: u (username), n (display name), r (role: owner|admin|guest), g (groups), m (module id),
t (issued, unix), x (expires, unix, ~60 s later), a (owner who approved this one request, optional).

A backend that receives the header must:
  1. accept it only from the gateway's address (LAB_FROM) — the key alone is enough, this is defence in depth;
  2. call verify(header, key, module) and treat the returned claims as the logged-in user.

    claims = labauth.verify(self.headers.get("X-Lab-Auth"), KEY, "drift")
    if claims: user = {"username": claims["u"], "role": claims["r"]}
"""
import base64
import hashlib
import hmac
import json
import time

HEADER = "X-Lab-Auth"
VERSION = "v1"
TTL = 60
ROLES = ("guest", "admin", "owner")


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def load_key(path):
    """Keys are stored as hex; returns bytes."""
    with open(path, encoding="ascii") as f:
        return bytes.fromhex(f.read().strip())


def sign(key, claims, now=None):
    now = int(now if now is not None else time.time())
    body = dict(claims, t=now, x=now + TTL)
    payload = _b64(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(key, f"{VERSION}.{payload}".encode(), hashlib.sha256).digest()
    return f"{VERSION}.{payload}.{_b64(mac)}"


def verify(header, key, module, now=None):
    """Returns the claims dict, or None when the header is missing, forged, expired or for another module."""
    if not header or not key:
        return None
    try:
        version, payload, mac = header.split(".")
        if version != VERSION:
            return None
        want = hmac.new(key, f"{version}.{payload}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(want, _unb64(mac)):
            return None
        claims = json.loads(_unb64(payload))
    except (ValueError, TypeError):
        return None
    now = time.time() if now is None else now
    if not isinstance(claims, dict) or claims.get("m") != module or claims.get("r") not in ROLES:
        return None
    if not (claims.get("t", 0) - 30 <= now <= claims.get("x", 0)):
        return None
    if not isinstance(claims.get("u"), str) or not claims["u"]:
        return None
    return claims


def at_least(claims, role):
    return ROLES.index(claims.get("r", "guest")) >= ROLES.index(role)
