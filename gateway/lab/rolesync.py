"""Keep SSO roles fresh between logins (security review: a removed admin kept admin rights until the session ended).

Two modes (mode()), chosen by what the installation has:

  "authentik" — the authentik module is configured (its URL + API token in the module config): every few minutes, for
     each user with a live SSO session, ask Authentik for their current groups and active flag:
       * groups changed  → store the new groups + role (takes effect on the user's next request);
       * user inactive or gone → end their sessions.
     Fails open on errors (the login service down must not log everyone out).

  "none" — any other OpenID Connect provider (Keycloak, …): there is no provider-neutral way to ask for a user's groups
     without their browser, so nothing is refreshed. Instead SSO sessions are capped: new ones last at most the Login
     setting "SSO session cap" (sso_max_age_hours, default 24 h) and this loop ends older ones, so a user removed from
     the login service (or from a group) loses access within that time; at their next login the groups are read again.

Local sessions are left alone (break-glass for when the login service is down, and local accounts have no SSO groups).
What it changed is logged in the audit table."""
import json
import logging
import os
import time
import urllib.parse
import urllib.request

from . import auth, config

log = logging.getLogger("lab.rolesync")
INTERVAL = int(os.environ.get("LAB_ROLESYNC_SECONDS", "300"))
AK_API = os.environ.get("LAB_ROLESYNC_AUTHENTIK", "")  # fallback only: normally the authentik module's config
TOKEN_FILE = os.path.join(config.KEYS_DIR, "authentik.token")


# Since the authentik module moved to manifest v2 (2026-11-15) its URL and token live in the module config; the gateway
# passes App.config_value as `config`. The old file + env URL stay as a fallback for installations without it.
CONFIG = None  # (module, key) -> value; set by server.serve()
SETTINGS = None  # login.LoginSettings (sso_max_age_hours); set by server.serve()
DEFAULT_MAX_AGE_HOURS = 24


def mode():
    """"authentik" when the authentik module (or the legacy token file + env URL) can answer, else "none"."""
    return "authentik" if _token() and _api() else "none"


def max_age_hours():
    try:
        return int(SETTINGS.get("sso_max_age_hours")) if SETTINGS else DEFAULT_MAX_AGE_HOURS
    except (TypeError, ValueError):
        return DEFAULT_MAX_AGE_HOURS


def cap_sessions(store):
    """Neutral mode: end SSO sessions older than the cap."""
    ended = store.end_sessions_older("oidc", max_age_hours() * 3600)
    for name in ended:
        store.audit({"username": "rolesync"}, "sessions-ended", target=name, result="max-age",
                    detail=f"SSO session older than {max_age_hours()} h (no role refresh configured)")
    return {"mode": "none", "changed": [], "ended": ended}


def _token():
    if CONFIG:
        t = CONFIG("authentik", "token")
        if t:
            return t
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _api():
    url = CONFIG("authentik", "url") if CONFIG else None
    return f"{str(url).rstrip('/')}/api/v3" if url else AK_API or None


def _lookup(username, token):
    """Authentik's view of one user: {"active": bool, "groups": [...]} or None if no such user."""
    q = urllib.parse.urlencode({"username": username, "page_size": 2})
    req = urllib.request.Request(f"{_api()}/core/users/?{q}", headers={"Authorization": f"Bearer {token}",
                                                                      "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        rows = [u for u in json.load(r).get("results", []) if u.get("username") == username]
    if not rows:
        return None
    u = rows[0]
    return {"active": bool(u.get("is_active")), "groups": sorted(g.get("name") for g in u.get("groups_obj") or [])}


def sync_once(store, lookup=_lookup, token=None):
    token = token or _token()
    if not token or (lookup is _lookup and not _api()):
        return cap_sessions(store)
    changed, ended = [], []
    users = {s["username"] for s in store.sessions() if s.get("via") == "oidc"}
    for name in sorted(users):
        try:
            ak = lookup(name, token)
        except Exception as e:  # noqa: BLE001 — Authentik unreachable: keep everything as it is
            log.warning("role sync: authentik lookup failed for %s: %s", name, e)
            return {"error": str(e)}
        cur = store.user(name)
        if not cur:
            continue
        if ak is None or not ak["active"]:
            n = store.end_sessions_for(name)
            store.audit({"username": "rolesync"}, "sessions-ended", target=name, result=n,
                        detail="user missing or deactivated in Authentik")
            ended.append(name)
            continue
        role = auth.role_for(ak["groups"])
        if role != cur["role"] or ak["groups"] != sorted(cur.get("groups") or []):
            store.upsert_user(name, cur.get("name") or name, cur.get("email") or "", ak["groups"], role)
            store.audit({"username": "rolesync"}, "role-refreshed", target=name, result=role,
                        detail=f"{cur['role']} → {role}; groups now {','.join(ak['groups'])[:400]}")
            changed.append(name)
    return {"changed": changed, "ended": ended}


def loop(store):
    while True:
        time.sleep(INTERVAL)
        try:
            r = sync_once(store)
            if r.get("changed") or r.get("ended"):
                log.info("role sync: %s", r)
        except Exception:  # noqa: BLE001
            log.exception("role sync failed")
