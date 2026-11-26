"""Login settings (Settings → Login, owner only): SSO (OpenID Connect) config, role group names, 2FA policy and
session lengths.

Every field has three sources, in this order: the environment (LAB_* in /etc/lab/lab.env — an installation configured
that way keeps working unchanged and the UI shows the field as locked), the database (gateway_config; the client secret
is sealed with the master key, like module secrets), then the default. A missing environment variable or an empty one
means "not set by the environment"."""
import json
import os
import urllib.parse
import urllib.request

from . import auth, config
from .secretbox import SecretError

SECRET_SCOPE = "_login"  # secretbox context for sealed login secrets (module ids can't start with "_")

# key: (type, env var, label, extra)
FIELDS = {
    "sso_issuer": ("url", "LAB_OIDC_ISSUER", "issuer URL", {}),
    "sso_client_id": ("text", "LAB_OIDC_CLIENT_ID", "client id", {}),
    "sso_client_secret": ("secret", "LAB_OIDC_CLIENT_SECRET", "client secret", {}),
    "sso_name": ("text", "LAB_OIDC_NAME", "button name", {}),
    "owner_group": ("text", "LAB_OWNER_GROUP", "owner group", {}),
    "admin_group": ("text", "LAB_ADMIN_GROUP", "admin group", {}),
    "require_2fa": ("bool", "LAB_REQUIRE_2FA", "require 2FA for owners/admins", {}),
    "session_days": ("int", "LAB_SESSION_DAYS", "SSO session (days)", {"min": 1, "max": 90}),
    "local_session_days": ("int", "LAB_LOCAL_SESSION_DAYS", "local session (days)", {"min": 1, "max": 90}),
    "sso_max_age_hours": ("int", "LAB_SSO_MAX_AGE_HOURS", "SSO session cap without role refresh (hours)",
                          {"min": 1, "max": 2160}),
}
DEFAULTS = {"owner_group": "lab-owners", "admin_group": "lab-admins", "require_2fa": False, "session_days": 14,
            "sso_max_age_hours": 24, "sso_name": "", "sso_issuer": "", "sso_client_id": ""}


def _env(var):
    v = os.environ.get(var)
    return v if v not in (None, "") else None


def _cast(t, v):
    if t == "bool":
        return v.strip().lower() in ("1", "true", "yes", "on") if isinstance(v, str) else bool(v)
    if t == "int":
        return int(v)
    return v


def check(key, v):
    """A posted value for `key` → the clean value; ValueError when it doesn't fit."""
    t, _, _, extra = FIELDS[key]
    if t == "bool":
        if not isinstance(v, bool):
            raise ValueError("expected true/false")
        return v
    if t == "int":
        if isinstance(v, bool) or not isinstance(v, int) or not extra["min"] <= v <= extra["max"]:
            raise ValueError(f"expected a whole number {extra['min']}..{extra['max']}")
        return v
    if not isinstance(v, str) or len(v) > (4096 if t == "secret" else 500) or "\n" in v or "\r" in v:
        raise ValueError("expected one line of text")
    v = v.strip()
    if t == "url" and v:
        u = urllib.parse.urlsplit(v)
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError("expected http(s)://host[/path] (no credentials or query)")
    if key in ("owner_group", "admin_group") and not v:
        raise ValueError("a group name is needed")
    return v


class LoginSettings:
    def __init__(self, store, box):
        self.store, self.box = store, box
        self._db = {}
        self.reload()

    def reload(self):
        self._db = self.store.gateway_config()
        auth.GROUPS.update(owner=self.get("owner_group"), admin=self.get("admin_group"))

    def source(self, key):
        if _env(FIELDS[key][1]) is not None:
            return "env"
        return "db" if key in self._db else "default"

    def get(self, key):
        t, var, _, _ = FIELDS[key]
        env = _env(var)
        if env is not None:
            try:
                return _cast(t, env)
            except ValueError:
                pass
        if key in self._db:
            v, sec = self._db[key]
            if not sec:
                return v
            if not self.box:
                return None
            try:
                return self.box.open(SECRET_SCOPE, key, v)
            except SecretError:
                return None
        if key == "local_session_days":  # break-glass next to SSO: short; the normal login of a local-only install: long
            return 1 if self.sso_configured() else self.get("session_days")
        return DEFAULTS.get(key)

    def sso_configured(self):
        return bool(self.get("sso_issuer") and self.get("sso_client_id"))

    def sso_name(self):
        if not self.sso_configured():
            return ""
        return self.get("sso_name") or urllib.parse.urlsplit(self.get("sso_issuer")).hostname or "SSO"

    def save(self, values):
        """values {key: value|None}; None clears the stored value. Env-set fields can't be changed here."""
        changes = {}
        for k, v in values.items():
            if k not in FIELDS:
                raise ValueError(f"unknown setting {k}")
            if self.source(k) == "env":
                raise ValueError(f"{k} is set in the environment ({FIELDS[k][1]}): change it there")
            changes[k] = None if v is None else check(k, v)
        for k, v in changes.items():
            if FIELDS[k][0] == "secret" and v:
                if not self.box:
                    raise RuntimeError("no master key: the client secret can't be stored yet")
                self.store.set_gateway_config(k, self.box.seal(SECRET_SCOPE, k, v), secret=True)
            else:
                self.store.set_gateway_config(k, None if v in (None, "") and FIELDS[k][0] != "bool" else v)
        self.reload()
        return changes

    def view(self):
        out = []
        for k, (t, var, label, extra) in FIELDS.items():
            f = {"key": k, "type": t, "label": label, "source": self.source(k), "env": var, **extra}
            if t == "secret":
                f["set"] = bool(self.get(k))
            else:
                f["value"] = self.get(k)
            out.append(f)
        return out


def discovery(issuer, timeout=10):
    """The issuer's OpenID configuration (the Settings "test" button): {ok, issuer, endpoints…} or {ok: false, error}."""
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            meta = json.loads(r.read(256 * 1024))
    except Exception as e:  # noqa: BLE001 — whatever went wrong is the answer
        return {"ok": False, "error": f"{url}: {e}"[:300]}
    if not isinstance(meta, dict):
        return {"ok": False, "error": "the discovery document is not a JSON object"}
    missing = [k for k in ("issuer", "authorization_endpoint", "token_endpoint") if not meta.get(k)]
    if missing:
        return {"ok": False, "error": f"discovery document lacks {', '.join(missing)}"}
    same = meta["issuer"].rstrip("/") == issuer.rstrip("/")
    return {"ok": same, "issuer": meta["issuer"], "authorization_endpoint": meta["authorization_endpoint"],
            "token_endpoint": meta["token_endpoint"], "scopes": (meta.get("scopes_supported") or [])[:20],
            "pkce": "S256" in (meta.get("code_challenge_methods_supported") or []),
            **({} if same else {"error": f"the document says issuer {meta['issuer']}: use exactly that"})}
