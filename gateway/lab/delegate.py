"""Delegation: a module's connector acting AS the calling user, through the gateway (today only `ai`).

A module whose manifest says `"delegate": true` gets, on every request an owner/admin makes to it, a short-lived
token in X-Lab-Delegation. With it the connector may call GET /api/delegate/… on the gateway (from 127.0.0.1 only):
the gateway checks the token, re-reads the user (a role that dropped since counts), and then applies the user's own
manifest rules to the read — so the connector never gets more than the user has. Rules on top of the user's:
  * reads only (GET) — writes are never delegated: they run from the user's browser, on a click;
  * no `secret` routes, no delegating module (the assistant cannot call itself or another delegator);
  * answers are redacted (redact.py) before the connector sees them; every read is audited "<user> via <module>".

Token:  d1.<base64url(JSON claims)>.<base64url(HMAC-SHA256(secret, "d1." + payload))>
Claims: u user, r role at mint, v delegating module, s hash of the session it came from (logout ends it),
        t issued, x expires (TTL), j nonce.
The secret is the gateway's own (LAB_DELEGATION_KEY, default next to the DB, mode 600, user lab): each connector runs as
its own user lab-c-<id> with /var/lib/lab out of reach — so a connector cannot mint a delegation itself.

The same class, with version "a1" (so a token of one kind never passes as the other), makes the ACT token
(X-Lab-Act) a connector with `connector.uses_credentials_of` gets: proof of who it acts for when it calls a module with an
own backend through the gateway (POST/GET /api/connector/call/<module>/…, security review 2026-11-15 L4), instead of
holding that module's HMAC key. Extra claim: a = the owner who approved the request that started the work (if any)."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

VERSION = "d1"
TTL = 900  # background work (triage, the morning summary) may finish a few minutes after the request that started it
HEADER = "X-Lab-Delegation"
ACT_VERSION = "a1"
ACT_TTL = 7200  # a wizard run (create a CT, wait for DHCP, install, …) continues long after the click that started it
ACT_HEADER = "X-Lab-Act"
ROLES = ("guest", "admin", "owner")


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def load_secret(path):
    """The gateway's delegation secret; created (0600) on first use."""
    try:
        with open(path, encoding="ascii") as f:
            return bytes.fromhex(f.read().strip())
    except FileNotFoundError:
        pass
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    raw = secrets.token_bytes(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # another process won the race
        return load_secret(path)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(raw.hex())
    return raw


class Delegation:
    def __init__(self, path, ttl=TTL, version=VERSION):
        self.path, self.ttl, self.version = path, ttl, version
        self._secret = None

    @property
    def secret(self):
        if self._secret is None:
            self._secret = load_secret(self.path)
        return self._secret

    def mint(self, user, via, session_hash, now=None, approved_by=None):
        now = int(time.time() if now is None else now)
        claims = {"u": user["username"], "r": user.get("role", "guest"), "v": via, "s": session_hash or "",
                  "t": now, "x": now + self.ttl, "j": secrets.token_hex(6)}
        if approved_by:
            claims["a"] = approved_by
        payload = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
        mac = hmac.new(self.secret, f"{self.version}.{payload}".encode(), hashlib.sha256).digest()
        return f"{self.version}.{payload}.{_b64(mac)}"

    def verify(self, token, now=None):
        """Claims, or None when missing, forged, expired, malformed or not an owner/admin token."""
        if not token or not isinstance(token, str) or len(token) > 2048:
            return None
        try:
            version, payload, mac = token.split(".")
            if version != self.version:
                return None
            want = hmac.new(self.secret, f"{version}.{payload}".encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(want, _unb64(mac)):
                return None
            c = json.loads(_unb64(payload))
        except (ValueError, TypeError):
            return None
        now = time.time() if now is None else now
        if not isinstance(c, dict) or c.get("r") not in ("owner", "admin"):
            return None
        if not (isinstance(c.get("u"), str) and c["u"] and isinstance(c.get("v"), str) and isinstance(c.get("s"), str)):
            return None
        if not (isinstance(c.get("t"), int) and isinstance(c.get("x"), int) and c["t"] - 30 <= now <= c["x"]):
            return None
        if "a" in c and not (isinstance(c["a"], str) and c["a"]):
            return None
        return c


def lower_role(a, b):
    """The weaker of two roles (a token minted as owner for someone who is admin now acts as admin)."""
    ra = ROLES.index(a) if a in ROLES else 0
    rb = ROLES.index(b) if b in ROLES else 0
    return ROLES[min(ra, rb)]


def session_hash(token):
    return hashlib.sha256(token.encode()).hexdigest() if token else ""
