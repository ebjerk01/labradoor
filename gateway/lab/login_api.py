"""Login routes of the gateway (mixed into server.Handler): first-run setup, local login with TOTP / recovery codes,
the user's own account (password, 2FA), local account management (People, owner) and the Login settings (owner).

  GET  /api/setup                      {needed, pending}: is there an owner yet? (no token needed to ask)
  POST /api/setup/check {token}        is this setup link still good?
  POST /api/setup {token, username, password, [name], [totp_secret, totp_code]}
                                       creates the first owner (once), logs them in; the setup route is gone after
  POST /auth/local {username, password, [code]}
                                       local login; code = a TOTP code or a recovery code when the account has 2FA
  GET  /api/account                    own login facts: local password, TOTP, recovery codes left, must enrol
  POST /api/account/password {current, password}
  POST /api/account/totp {secret, code, password}   turn TOTP on → recovery codes (shown once)
  POST /api/account/totp/off {password}
  POST /api/account/recovery {password}             new recovery codes (the old ones stop working)
  POST /api/users {username, password, role, groups, [name], [sso]}            owner: new local account
  POST /api/users/<name> {role, groups, name, disabled, sso, password, totp_reset}  owner: change an account
  POST /api/users/<name>/delete                                                owner
  GET  /api/login/settings             admin reads, owner edits: SSO config, role groups, 2FA policy, session lengths
  POST /api/login/settings {values}    owner
  POST /api/login/test {[issuer]}      owner: fetch the issuer's discovery document
"""
import logging
import re
import urllib.parse

from . import auth, config, login
from .errors import HTTPError
from .secretbox import SecretError

log = logging.getLogger("lab.login")
NOT_MINE = object()
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{1,63}$")
GROUP_RE = re.compile(r"^[\w .@-]{1,80}$")
USER_RE = re.compile(r"^/api/users/([^/]+)(/delete)?$")
TOTP_SCOPE = "_totp"  # secretbox context: (scope, username) — a sealed secret can't be moved to another account


class LoginRoutes:
    # --- helpers ------------------------------------------------------------------------------------------------------
    def _must_enrol(self, u):
        """A local session of an owner/admin without TOTP while the owner requires 2FA: only enrolment is open."""
        return bool(u and u.get("via") == "local" and u.get("role") in ("owner", "admin") and not u.get("totp")
                    and self.app.login.get("require_2fa"))

    def _totp_secret(self, u):
        box = self.app.box
        if not box:
            raise HTTPError(503, "the gateway has no master key: two-factor accounts can't log in (see docs/login.md)")
        try:
            return box.open(TOTP_SCOPE, u["username"], u["totp"])
        except SecretError:
            raise HTTPError(503, "this account's 2FA secret can't be opened (master key changed?)") from None

    def _second_factor(self, u, code):
        """True when `code` is a fresh TOTP code or an unused recovery code of `u` (a recovery code is spent)."""
        st = self.app.store
        if auth.looks_like_recovery(code):
            ok = st.use_recovery(u["username"], auth.recovery_hash(code))
            if ok:
                st.audit(u, "recovery-code-used", target=u["username"])
            return ok
        step = auth.totp_verify(self._totp_secret(u), code, u.get("totp_step") or 0)
        return bool(step) and st.totp_used(u["username"], step)

    def _throttle(self):
        ip = self.client_ip()
        if self.app.store.login_failures(ip) >= config.LOGIN_ATTEMPTS:
            raise HTTPError(429, "too many attempts, wait 15 minutes")
        return ip

    def _check_own_password(self, u, password):
        st = self.app.store
        full = st.user(u["username"])
        if not (full and full.get("pw_hash")):
            raise HTTPError(400, "this account has no local password")
        ip = self._throttle()
        if not auth.check_password(str(password or ""), full["pw_hash"]):
            st.login_failed(ip)
            raise HTTPError(403, "wrong password")
        return full

    def _login_session(self, user, ip, detail):
        a = self.app
        days = a.login.get("local_session_days")
        token = a.store.new_session(user["username"], days, self.headers.get("User-Agent", ""), ip, "local")
        a.store.audit(user, "login", detail=detail)
        return token, days * 86400

    def _new_totp(self, username, secret, code):
        """Validates the enrolment code for `secret`; returns (sealed secret, step, recovery codes, their hashes)."""
        try:
            secret = auth.totp_clean_secret(secret)
        except ValueError as e:
            raise HTTPError(400, f"secret: {e}") from None
        step = auth.totp_verify(secret, code)
        if not step:
            raise HTTPError(400, "that code doesn't match: check the authenticator app's clock and try the next code")
        if not self.app.box:
            raise HTTPError(503, "the gateway has no master key: 2FA secrets can't be stored yet")
        codes, hashes = auth.recovery_new()
        return self.app.box.seal(TOTP_SCOPE, username, secret), step, codes, hashes

    def _owner_exists(self):
        """True when the first-run setup route is CLOSED: an active owner exists, or one existed and root has not made
        a recovery link (store.setup_open)."""
        return not self.app.store.setup_open()

    # --- dispatch -----------------------------------------------------------------------------------------------------
    def _login_get(self, path, q):
        a = self.app
        if path == "/api/setup":
            needed = not self._owner_exists()
            return self._json(200, {"needed": needed, "pending": needed and a.store.setup_token_pending()})
        if path == "/api/account":
            u = self._need(enrol_ok=True)
            full = a.store.user(u["username"]) or {}
            return self._json(200, {"username": u["username"], "local": bool(full.get("pw_hash")),
                                    "totp": bool(full.get("totp")), "recoveryLeft": len(_json_list(full.get("recovery"))),
                                    "sso": bool(full.get("sso")), "via": u.get("via", ""),
                                    "mustEnrol": self._must_enrol(u), "require2fa": bool(a.login.get("require_2fa"))})
        if path == "/api/login/settings":
            u = self._need("admin")
            from . import rolesync
            st = a.store
            privileged = [x for x in st.users() if x["role"] in ("owner", "admin") and not x["disabled"]]
            return self._json(200, {
                "fields": a.login.view(), "editable": u["role"] == "owner", "secretsReady": a.box is not None,
                "redirectUri": config.PUBLIC_URL + "/auth/callback", "ssoActive": a.oidc is not None,
                "rolesync": rolesync.mode(), "rolesyncSeconds": rolesync.INTERVAL,
                "without2fa": [x["username"] for x in privileged if x["local"] and not x["totp"]]})
        return NOT_MINE

    def _login_post(self, path):
        a = self.app
        if path == "/auth/local":
            return self._local_login()
        if path == "/api/setup/check":
            if self._owner_exists():
                raise HTTPError(404, "not found")
            self._throttle()
            ok = a.store.setup_token_valid(self._body().get("token"))
            if not ok:
                a.store.login_failed(self.client_ip())
            return self._json(200, {"ok": ok})
        if path == "/api/setup":
            return self._setup()
        if path.startswith("/api/account"):
            return self._account(path)
        if path == "/api/users":
            return self._user_create(self._need("owner"), self._body())
        m = USER_RE.match(path)
        if m and m.group(1) != "" and not path.endswith("/logout"):
            u = self._need("owner")
            name = urllib.parse.unquote(m.group(1))
            if m.group(2):
                return self._user_delete(u, name)
            return self._user_update(u, name, self._body())
        if path == "/api/login/settings":
            u = self._need("owner")
            return self._login_settings_save(u, self._body())
        if path == "/api/login/test":
            self._need("owner")
            issuer = self._body().get("issuer") or a.login.get("sso_issuer")
            if not issuer:
                raise HTTPError(400, "no issuer URL to test")
            try:
                issuer = login.check("sso_issuer", issuer)
            except ValueError as e:
                raise HTTPError(400, f"issuer: {e}") from None
            return self._json(200, login.discovery(issuer))
        return NOT_MINE

    # --- local login --------------------------------------------------------------------------------------------------
    def _local_login(self):
        a = self.app
        ip = self.client_ip()
        data = self._body()
        name = str(data.get("username") or "")[:100]
        user = a.store.user(name)
        password = str(data.get("password") or "")
        # counted BEFORE the (expensive) check and atomically, so parallel attempts can't all slip under the limit
        # (review M3); a successful login takes it back
        if not a.store.try_login_attempt(ip, config.LOGIN_ATTEMPTS):
            raise HTTPError(429, "too many attempts, wait 15 minutes")
        try:
            ok = auth.check_password(password, (user or {}).get("pw_hash") or auth.DUMMY_HASH)
        except auth.Busy:
            raise HTTPError(503, "busy, try again in a moment") from None
        if not (user and user.get("pw_hash") and ok and not user.get("disabled")):
            a.store.audit({"username": name[:60]}, "login-failed", detail=f"local from {ip}")
            raise HTTPError(401, "wrong username or password")
        a.store.login_attempt_ok(ip)
        if user.get("totp"):
            code = str(data.get("code") or "").strip()
            if not code:  # the password was right: ask for the second factor (not counted as a failure)
                raise HTTPError(401, "two-factor code needed", totp=True)
            if not self._second_factor(user, code):
                a.store.login_failed(ip)
                a.store.audit(user, "login-failed", detail=f"local from {ip}: wrong or reused 2FA code")
                raise HTTPError(401, "wrong or already used code", totp=True)
        if auth.needs_rehash(user["pw_hash"]):  # older/weaker hash: store a current scrypt one
            a.store.set_password_hash(user["username"], auth.hash_password(password))
        kind = "break-glass local" if a.oidc else "local"
        token, age = self._login_session(user, ip, f"{kind} from {ip}{' + 2FA' if user.get('totp') else ''}")
        user["via"] = "local"
        from .server import _public_user
        return self._json(200, {"user": _public_user(user), "mustEnrol": self._must_enrol(user)},
                          {"Set-Cookie": self._cookie(token, age)})

    # --- first run ----------------------------------------------------------------------------------------------------
    def _setup(self):
        a = self.app
        if self._owner_exists():
            raise HTTPError(404, "not found")  # the setup route is gone once an owner exists
        ip = self._throttle()
        data = self._body()
        token = data.get("token")
        if not a.store.setup_token_valid(token):
            a.store.login_failed(ip)
            raise HTTPError(403, "this setup link is invalid, used or expired: run `lab-admin setup-link` for a new one")
        username, password = str(data.get("username") or "").strip(), data.get("password")
        if not USERNAME_RE.match(username):
            raise HTTPError(400, "username: 2-64 letters, digits, . _ @ -")
        bad = auth.password_problem(password)
        if bad:
            raise HTTPError(400, f"password: {bad}")
        totp = None
        if data.get("totp_secret"):
            totp = self._new_totp(username, data.get("totp_secret"), data.get("totp_code"))
        if a.store.user(username) or a.store.user_casefold(username):
            raise HTTPError(409, "that username exists already")
        if not a.store.use_setup_token(token):  # spent atomically: a second request with the same token loses here
            raise HTTPError(403, "this setup link was just used")
        name = str(data.get("name") or "").strip()[:80] or username
        a.store.create_local_user(username, name, "owner", [], auth.hash_password(password))
        if totp:
            a.store.set_totp(username, totp[0], totp[1], totp[3])
        a.store.drop_setup_tokens()
        a.store.close_setup()
        user = a.store.user(username)
        a.store.audit(user, "setup-owner", target=username, detail=f"first-run setup from {ip}{' + 2FA' if totp else ''}")
        log.warning("first-run setup done: owner %s created from %s", username, ip)
        tok, age = self._login_session(user, ip, f"first-run setup from {ip}")
        user["via"] = "local"
        from .server import _public_user
        return self._json(200, {"user": _public_user(user), "recovery": totp[2] if totp else None},
                          {"Set-Cookie": self._cookie(tok, age)})

    # --- own account --------------------------------------------------------------------------------------------------
    def _account(self, path):
        a = self.app
        u = self._need(enrol_ok=True)
        data = self._body()
        st = a.store
        if path == "/api/account/password":
            self._check_own_password(u, data.get("current"))
            bad = auth.password_problem(data.get("password"))
            if bad:
                raise HTTPError(400, f"password: {bad}")
            st.set_password_hash(u["username"], auth.hash_password(data["password"]))
            # a stolen session must not outlive the password change: every other session ends
            ended = st.end_sessions_for(u["username"], keep=self._token())
            st.audit(u, "password-changed", target=u["username"], detail=f"{ended} other session(s) ended")
            return self._json(200, {"ok": True, "ended": ended})
        if path == "/api/account/totp":
            full = self._check_own_password(u, data.get("password"))
            if full.get("totp"):
                raise HTTPError(409, "2FA is on already: turn it off first to enrol a new device")
            sealed, step, codes, hashes = self._new_totp(u["username"], data.get("secret"), data.get("code"))
            st.set_totp(u["username"], sealed, step, hashes)
            ended = st.end_sessions_for(u["username"], keep=self._token())
            st.audit(u, "2fa-on", target=u["username"], detail=f"{ended} other session(s) ended")
            return self._json(200, {"ok": True, "recovery": codes})
        if path == "/api/account/totp/off":
            self._check_own_password(u, data.get("password"))
            if a.login.get("require_2fa") and u["role"] in ("owner", "admin"):
                raise HTTPError(403, "2FA is required for owners and admins on this installation")
            st.set_totp(u["username"], None)
            ended = st.end_sessions_for(u["username"], keep=self._token())
            st.audit(u, "2fa-off", target=u["username"], detail=f"{ended} other session(s) ended")
            return self._json(200, {"ok": True})
        if path == "/api/account/recovery":
            full = self._check_own_password(u, data.get("password"))
            if not full.get("totp"):
                raise HTTPError(400, "turn 2FA on first")
            codes, hashes = auth.recovery_new()
            st.set_recovery(u["username"], hashes)
            st.audit(u, "recovery-codes-new", target=u["username"])
            return self._json(200, {"ok": True, "recovery": codes})
        raise HTTPError(404, "not found")

    # --- People: local accounts (owner) --------------------------------------------------------------------------------
    @staticmethod
    def _clean_groups(g):
        if not (isinstance(g, list) and len(g) <= 30 and all(isinstance(x, str) and GROUP_RE.match(x) for x in g)):
            raise HTTPError(400, "groups must be a list of group names")
        return sorted(set(g))

    def _user_create(self, u, data):
        st = self.app.store
        name = str(data.get("username") or "").strip()
        if not USERNAME_RE.match(name):
            raise HTTPError(400, "username: 2-64 letters, digits, . _ @ -")
        role = data.get("role") or "guest"
        if role not in auth.ROLES:
            raise HTTPError(400, "role: owner, admin or guest")
        bad = auth.password_problem(data.get("password"))
        if bad:
            raise HTTPError(400, f"password: {bad}")
        groups = self._clean_groups(data.get("groups") or [])
        if st.user_casefold(name):  # "Admin" next to "admin" is the same person to most backends
            raise HTTPError(409, f"that username exists already (as {st.user_casefold(name)})")
        if not st.create_local_user(name, str(data.get("name") or "").strip()[:80] or name, role, groups,
                                    auth.hash_password(data["password"]), sso=bool(data.get("sso"))):
            raise HTTPError(409, "that username exists already")
        st.audit(u, "user-created", target=name, result=role, detail=f"groups {','.join(groups)}"[:400])
        return self._json(200, {"ok": True})

    def _guard_owner_change(self, actor, target, role=None, disabled=None, delete=False):
        if target["username"] == actor["username"] and (delete or disabled or (role and role != target["role"])):
            raise HTTPError(400, "you can't disable, delete or demote yourself")
        if target["role"] == "owner" and (delete or disabled or (role and role != "owner")):
            if [o for o in self.app.store.active_owners() if o != target["username"]] == []:
                raise HTTPError(400, "the last owner can't be removed")

    def _user_update(self, u, name, data):
        st = self.app.store
        cur = st.user(name)
        if not cur:
            raise HTTPError(404, "no such user")
        role, disabled = data.get("role"), data.get("disabled")
        if role is not None and role not in auth.ROLES:
            raise HTTPError(400, "role: owner, admin or guest")
        if disabled is not None and not isinstance(disabled, bool):
            raise HTTPError(400, "disabled must be true/false")
        if "sso" in data and not isinstance(data["sso"], bool):
            raise HTTPError(400, "sso must be true/false")
        self._guard_owner_change(u, cur, role=role, disabled=disabled)
        groups = self._clean_groups(data["groups"]) if "groups" in data else None
        nm = str(data["name"]).strip()[:80] if data.get("name") else None
        changed = []
        if "password" in data:
            bad = auth.password_problem(data.get("password"))
            if bad:
                raise HTTPError(400, f"password: {bad}")
            st.set_password_hash(name, auth.hash_password(data["password"]))
            changed.append("password")
        if data.get("totp_reset"):
            st.set_totp(name, None)
            changed.append("2fa-reset")
        st.update_user(name, name=nm, role=role, groups=groups, disabled=disabled, sso=data.get("sso"))
        changed += [k for k in ("name", "role", "groups", "disabled", "sso") if data.get(k) is not None and k in data]
        ended = 0
        if disabled or "password" in changed or "2fa-reset" in changed:
            # someone else's: all their sessions; the owner's own password: all but this one
            ended = st.end_sessions_for(name, keep=self._token() if name == u["username"] else None)
        st.audit(u, "user-changed", target=name, result=",".join(changed)[:40],
                 detail=f"role {role or cur['role']}; groups {','.join(groups if groups is not None else cur['groups'])}"[:400])
        return self._json(200, {"ok": True, "ended": ended})

    def _user_delete(self, u, name):
        st = self.app.store
        cur = st.user(name)
        if not cur:
            raise HTTPError(404, "no such user")
        self._guard_owner_change(u, cur, delete=True)
        st.delete_user(name)
        st.audit(u, "user-deleted", target=name, result=cur["role"])
        return self._json(200, {"ok": True})

    # --- Login settings (owner) ----------------------------------------------------------------------------------------
    def _login_settings_save(self, u, data):
        a = self.app
        values = data.get("values")
        if not isinstance(values, dict) or not values:
            raise HTTPError(400, "values must be a non-empty object")
        if values.get("require_2fa") is True:
            me = a.store.user(u["username"]) or {}
            if me.get("pw_hash") and not me.get("totp") and u.get("via") == "local":
                raise HTTPError(400, "turn on 2FA for your own account first (Settings → account)")
        try:
            changes = a.login.save(values)
        except ValueError as e:
            raise HTTPError(400, str(e)) from None
        except RuntimeError as e:
            raise HTTPError(503, str(e)) from None
        a.reload_login()
        shown = {k: ("<secret>" if login.FIELDS[k][0] == "secret" and v else v) for k, v in changes.items()}
        import json
        a.store.audit(u, "login-settings", target=",".join(changes)[:300], result="ok", detail=json.dumps(shown)[:900])
        return self._json(200, {"ok": True, "fields": a.login.view(), "ssoActive": a.oidc is not None})


def _json_list(raw):
    import json
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except ValueError:
        return []
