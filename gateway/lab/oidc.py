"""OpenID Connect login through Authentik: authorization code flow with PKCE (same design as the other apps).

The ID token is fetched by the server straight from the token endpoint over TLS, so its claims are trusted without a
signature check (OIDC Core 3.1.3.7); issuer, audience, expiry and nonce are still checked."""
import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

PENDING_SECONDS = 600
MAX_PENDING = 5000  # unauthenticated /auth/login calls each park a state here: bounded
# the only texts the login page may show (the callback's error_description is whatever an attacker put in a link)
CANCELLED = "login was cancelled or refused"
TIMED_OUT = "login timed out, try again"
INVALID = "invalid answer from the login service"
NO_USER = "the login service sent no username"
REFUSED = "the login service refused the code"
OTHER_BROWSER = "this login was not started in this browser: try again"
MESSAGES = {CANCELLED, TIMED_OUT, INVALID, NO_USER, REFUSED, OTHER_BROWSER}


class OIDCError(Exception):
    pass


class OIDC:
    def __init__(self, issuer, client_id, client_secret, redirect_uri):
        self.issuer = issuer.rstrip("/") + "/"
        self.client_id, self.client_secret, self.redirect_uri = client_id, client_secret, redirect_uri
        self._meta = None
        self._pending = {}
        self._lock = threading.Lock()

    def _discovery(self):
        if self._meta is None:
            with urllib.request.urlopen(self.issuer + ".well-known/openid-configuration", timeout=10) as r:
                self._meta = json.load(r)
        return self._meta

    def start(self, after="/"):
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        now = time.time()
        with self._lock:
            self._pending = {k: v for k, v in self._pending.items() if now - v[2] < PENDING_SECONDS}
            if len(self._pending) >= MAX_PENDING:  # drop the oldest
                for k in sorted(self._pending, key=lambda k: self._pending[k][2])[:MAX_PENDING // 10]:
                    del self._pending[k]
            self._pending[state] = (nonce, verifier, now, after)
        q = {"response_type": "code", "client_id": self.client_id, "redirect_uri": self.redirect_uri,
             "scope": "openid profile email", "state": state, "nonce": nonce,
             "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"}
        return self._discovery()["authorization_endpoint"] + "?" + urllib.parse.urlencode(q)

    def finish(self, query):
        """Returns (claims, after-login path)."""
        if query.get("error"):
            raise OIDCError(CANCELLED)
        with self._lock:
            pending = self._pending.pop(query.get("state") or "", None)
        if not pending or time.time() - pending[2] > PENDING_SECONDS:
            raise OIDCError(TIMED_OUT)
        nonce, verifier, _, after = pending
        claims = _claims(self._token(query.get("code") or "", verifier).get("id_token") or "")
        aud = claims.get("aud") if isinstance(claims.get("aud"), list) else [claims.get("aud")]
        if (claims.get("iss") != self._discovery()["issuer"] or self.client_id not in aud
                or (claims.get("exp") or 0) < time.time() or claims.get("nonce") != nonce):
            raise OIDCError(INVALID)
        if not claims.get("preferred_username"):
            raise OIDCError(NO_USER)
        return claims, after

    def _token(self, code, verifier):
        body = urllib.parse.urlencode({
            "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
            "client_id": self.client_id, "client_secret": self.client_secret, "code_verifier": verifier}).encode()
        req = urllib.request.Request(self._discovery()["token_endpoint"], body, {
            "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise OIDCError(REFUSED) from None


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _claims(jwt):
    try:
        part = jwt.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        raise OIDCError(INVALID) from None
