"""Login tests (step 14): first-run setup token, local accounts (scrypt, hash upgrade, create/disable/role/delete),
TOTP (window, replay), recovery codes, the 2FA policy, Login settings (sealed client secret, env precedence, discovery
test), SSO account linking and rolesync's neutral mode.

Imports the gateway lazily and patches lab.config in setUpModule (and restores it), like test_gateway_delegation.py:
test_gateway.py configures lab.config through the environment at import time and all suites share one process.
The gateway here has NO modules and NO owner: a fresh installation."""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gateway"))

TMP = None
ISSUER = None


class Discovery(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path != "/app/.well-known/openid-configuration":
            self.send_response(404)
            self.end_headers()
            return
        out = json.dumps({"issuer": ISSUER, "authorization_endpoint": ISSUER + "/authorize",
                          "token_endpoint": ISSUER + "/token", "code_challenge_methods_supported": ["S256"]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def setUpModule():
    global TMP, GW, PORT, SAVED, SAVED_GROUPS, server, config, auth, rolesync, DISC, ISSUER
    from lab import auth, config, rolesync, server  # noqa: F811 (lazy: see the module docstring)
    TMP = tempfile.mkdtemp(prefix="lablogin-")
    for d in ("modules", "keys", "dist"):
        os.makedirs(os.path.join(TMP, d))
    with open(os.path.join(TMP, "dist", "index.html"), "w") as f:
        f.write("<!doctype html><title>lab</title>")
    with open(os.path.join(TMP, "master.key"), "w") as f:
        f.write("cd" * 32)
    SAVED = {k: getattr(config, k) for k in ("DB", "MODULES_DIR", "KEYS_DIR", "STATIC_DIR", "BACKENDS_FILE", "MASTER_KEY",
                                             "DELEGATION_KEY", "COOKIE_SECURE", "TRUST_PROXY", "HEALTH_INTERVAL",
                                             "LOGIN_ATTEMPTS", "PUBLIC_URL")}
    SAVED_GROUPS = dict(auth.GROUPS)
    config.DB = os.path.join(TMP, "lab.sqlite3")
    config.MODULES_DIR = os.path.join(TMP, "modules")
    config.KEYS_DIR = os.path.join(TMP, "keys")
    config.STATIC_DIR = os.path.join(TMP, "dist")
    config.BACKENDS_FILE = os.path.join(TMP, "backends.json")
    config.MASTER_KEY = os.path.join(TMP, "master.key")
    config.DELEGATION_KEY = os.path.join(TMP, "delegation.key")
    config.PUBLIC_URL = "https://door.example"
    config.COOKIE_SECURE, config.TRUST_PROXY, config.HEALTH_INTERVAL, config.LOGIN_ATTEMPTS = False, False, 3600, 5
    for k in [k for k in os.environ if k.startswith(("LAB_OIDC_", "LAB_OWNER_GROUP", "LAB_ADMIN_GROUP", "LAB_REQUIRE_2FA",
                                                       "LAB_SESSION_DAYS", "LAB_LOCAL_SESSION_DAYS", "LAB_SSO_MAX_AGE"))]:
        os.environ.pop(k)
    DISC = HTTPServer(("127.0.0.1", 0), Discovery)
    ISSUER = f"http://127.0.0.1:{DISC.server_address[1]}/app"
    threading.Thread(target=DISC.serve_forever, daemon=True).start()
    app = server.App()
    GW = server.PooledHTTPServer(("127.0.0.1", 0), server.Handler, app, workers=4)
    PORT = GW.server_address[1]
    threading.Thread(target=GW.serve_forever, daemon=True).start()


def tearDownModule():
    GW.shutdown()
    DISC.shutdown()
    for k, v in SAVED.items():
        setattr(config, k, v)
    auth.GROUPS.clear()
    auth.GROUPS.update(SAVED_GROUPS)
    shutil.rmtree(TMP, ignore_errors=True)


def call(method, path, body=None, token=None, cookies=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    h = {}
    jar = dict(cookies or {})
    if token:
        jar["lab_session"] = token
    if jar:
        h["Cookie"] = "; ".join(f"{k}={v}" for k, v in jar.items())
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    c.request(method, path, data, h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = raw.decode()
    hd = dict(r.getheaders())
    hd["_set_cookies"] = [v for k, v in r.getheaders() if k.lower() == "set-cookie"]
    return r.status, payload, hd


def cookie(h):
    return h["Set-Cookie"].split(";")[0].split("=", 1)[1]


def st():
    return GW.app.store


def unthrottle():
    st().x("DELETE FROM login_failures")


SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
STATE_Y = {"lab_oidc": __import__("hashlib").sha256(b"y").hexdigest()}   # the browser that started login with state y
OWNER_PW = "owner password 1234"


class A_FirstRun(unittest.TestCase):
    """Runs first (class names sort): the installation has no owner."""

    def setUp(self):
        unthrottle()

    def test_setup_flow(self):
        app = GW.app
        self.assertTrue(call("GET", "/api/me")[1].get("setup"))
        self.assertEqual(call("GET", "/api/setup")[1], {"needed": True, "pending": False})
        link = app.first_run_notice()
        self.assertTrue(link.startswith("https://door.example/setup#"))
        self.assertIsNone(app.first_run_notice())  # pending: the installer's link stays valid
        tok = link.split("#", 1)[1]
        self.assertTrue(call("GET", "/api/setup")[1]["pending"])
        self.assertEqual(st().q("SELECT COUNT(*) AS n FROM setup_tokens WHERE token_hash=?", (tok,))[0]["n"], 0)  # hashed
        # nothing creates the owner without the token
        good = {"username": "boss", "password": OWNER_PW, "name": "The Boss"}
        self.assertEqual(call("POST", "/api/setup", {**good, "token": "nope"})[0], 403)
        self.assertEqual(call("POST", "/api/setup", good)[0], 403)
        self.assertEqual(call("POST", "/api/users", {"username": "x", "password": OWNER_PW, "role": "owner"})[0], 401)
        unthrottle()
        self.assertEqual(call("POST", "/api/setup/check", {"token": tok})[1], {"ok": True})
        # bad input does not spend the token
        self.assertEqual(call("POST", "/api/setup", {**good, "token": tok, "password": "short"})[0], 400)
        self.assertEqual(call("POST", "/api/setup", {**good, "token": tok, "totp_secret": SECRET, "totp_code": "000000"})[0], 400)
        # a fresh link (lab-admin setup-link) replaces the old one
        tok2 = app.first_run_notice(force=True).split("#", 1)[1]
        self.assertEqual(call("POST", "/api/setup/check", {"token": tok})[1], {"ok": False})
        # expiry: one hour
        st().x("UPDATE setup_tokens SET expires=?", (time.time() - 1,))
        self.assertEqual(call("POST", "/api/setup", {**good, "token": tok2})[0], 403)
        unthrottle()
        tok3 = app.first_run_notice(force=True).split("#", 1)[1]
        s, r, h = call("POST", "/api/setup", {**good, "token": tok3, "totp_secret": SECRET,
                                              "totp_code": auth.totp_code(SECRET)})
        self.assertEqual(s, 200, r)
        self.assertEqual((r["user"]["role"], r["user"]["totp"], len(r["recovery"])), ("owner", True, 10))
        tok_owner = cookie(h)
        self.assertEqual(call("GET", "/api/me", token=tok_owner)[1]["user"]["username"], "boss")
        # single use, and the setup route is gone once an owner exists
        self.assertEqual(call("POST", "/api/setup", {**good, "token": tok3, "username": "boss2"})[0], 404)
        self.assertEqual(call("POST", "/api/setup/check", {"token": tok3})[0], 404)
        self.assertEqual(call("GET", "/api/setup")[1], {"needed": False, "pending": False})
        self.assertIsNone(app.first_run_notice(force=True))
        self.assertNotIn("setup", call("GET", "/api/me")[1])
        self.assertEqual(st().q("SELECT COUNT(*) AS n FROM setup_tokens")[0]["n"], 0)
        u = st().user("boss")
        self.assertTrue(u["pw_hash"].startswith("scrypt$32768$8$1$"))
        self.assertTrue(u["totp"].startswith("v1:"))  # sealed with the master key
        self.assertNotIn(SECRET, json.dumps(u))
        self.assertFalse(u["sso"])

    def test_setup_never_reopens_by_itself(self):
        """Review L2: once an owner has existed, losing the last active owner (demoted by rolesync, disabled) does not
        reopen setup; only root's `lab-admin setup-link --recover` does, for one link."""
        app = GW.app
        self.assertTrue(st().setup_closed())   # test_setup_flow made the owner (classes and tests sort by name)
        st().set_role("boss", "admin")
        try:
            self.assertEqual(st().active_owners(), [])
            self.assertEqual(call("GET", "/api/setup")[1], {"needed": False, "pending": False})
            self.assertNotIn("setup", call("GET", "/api/me")[1])
            self.assertIsNone(app.first_run_notice(force=True))          # what install.sh's setup-link would do
            unthrottle()
            self.assertEqual(call("POST", "/api/setup/check", {"token": "x"})[0], 404)
            self.assertEqual(call("POST", "/api/setup", {"username": "evil", "password": OWNER_PW, "token": "x"})[0], 404)
            # root's recovery link opens it, once
            tok = app.first_run_notice(force=True, recover=True).split("#", 1)[1]
            self.assertEqual(call("GET", "/api/setup")[1], {"needed": True, "pending": True})
            unthrottle()
            s, r, _ = call("POST", "/api/setup", {"username": "boss3", "password": OWNER_PW, "token": tok})
            self.assertEqual(s, 200, r)
            self.assertEqual(call("GET", "/api/setup")[1], {"needed": False, "pending": False})
        finally:
            st().set_role("boss", "owner")
            st().delete_user("boss3")
        self.assertEqual(call("GET", "/api/setup")[1], {"needed": False, "pending": False})

    def test_token_single_use_race(self):
        tok = st().new_setup_token()
        self.assertTrue(st().use_setup_token(tok))
        self.assertFalse(st().use_setup_token(tok))


def owner_login():
    """A fresh owner session (test shortcut: forget the last used step, since a code can't be used twice)."""
    unthrottle()
    st().x("UPDATE users SET totp_step=0 WHERE username='boss'")
    s, r, h = call("POST", "/auth/local", {"username": "boss", "password": OWNER_PW, "code": auth.totp_code(SECRET)})
    assert s == 200, r
    return cookie(h)


class B_Passwords(unittest.TestCase):
    def test_scrypt_and_upgrade(self):
        h = auth.hash_password("correct horse battery")
        self.assertTrue(auth.check_password("correct horse battery", h))
        self.assertFalse(auth.check_password("wrong horse battery", h))
        self.assertFalse(auth.needs_rehash(h))
        weak = auth.hash_password("x" * 12, n=2 ** 10)
        self.assertTrue(auth.check_password("x" * 12, weak) and auth.needs_rehash(weak))
        self.assertFalse(auth.check_password("x", "scrypt$1048577$8$1$AAAA$AAAA"))  # absurd parameters refused
        self.assertEqual(auth.password_problem("short"), "at least 12 characters")
        self.assertEqual(auth.password_problem("aaaaaaaaaaaaaaaa"), "too repetitive")
        self.assertIsNone(auth.password_problem("a fine long passphrase"))

    def test_legacy_pbkdf2_upgraded_on_login(self):
        import base64
        import hashlib
        salt = b"0123456789abcdef"
        dk = hashlib.pbkdf2_hmac("sha256", b"old break glass pw", salt, 1000)
        legacy = f"pbkdf2_sha256$1000${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"
        st().create_local_user("oldbg", "Old", "admin", [], legacy)
        unthrottle()
        s, r, _ = call("POST", "/auth/local", {"username": "oldbg", "password": "old break glass pw"})
        self.assertEqual((s, r["user"]["role"]), (200, "admin"))
        self.assertTrue(st().user("oldbg")["pw_hash"].startswith("scrypt$"))
        self.assertEqual(call("POST", "/auth/local", {"username": "oldbg", "password": "old break glass pw"})[0], 200)
        st().delete_user("oldbg")


class C_Totp(unittest.TestCase):
    def test_rfc6238_vectors_window_replay(self):
        rfc = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # "12345678901234567890"
        self.assertEqual(auth.totp_code(rfc, 59), "287082")
        self.assertEqual(auth.totp_code(rfc, 1111111109), "081804")
        now = 1_700_000_000
        code = auth.totp_code(SECRET, now)
        step = auth.totp_verify(SECRET, code, 0, at=now)
        self.assertEqual(step, now // 30)
        self.assertEqual(auth.totp_verify(SECRET, auth.totp_code(SECRET, now - 30), 0, at=now), now // 30 - 1)  # drift ok
        self.assertIsNone(auth.totp_verify(SECRET, auth.totp_code(SECRET, now - 90), 0, at=now))  # too old
        self.assertIsNone(auth.totp_verify(SECRET, code, step, at=now))  # the same code twice: refused
        self.assertIsNone(auth.totp_verify(SECRET, "12345", 0, at=now))
        with self.assertRaises(ValueError):
            auth.totp_clean_secret("not base32!!!!!!!!")

    def test_login_with_totp_and_replay(self):
        unthrottle()
        s, r, _ = call("POST", "/auth/local", {"username": "boss", "password": OWNER_PW})
        self.assertEqual((s, r.get("totp")), (401, True))  # password right → asks for the code
        st().x("UPDATE users SET totp_step=0 WHERE username='boss'")
        code = auth.totp_code(SECRET)
        self.assertEqual(call("POST", "/auth/local", {"username": "boss", "password": OWNER_PW, "code": code})[0], 200)
        s, r, _ = call("POST", "/auth/local", {"username": "boss", "password": OWNER_PW, "code": code})
        self.assertEqual((s, r["error"]), (401, "wrong or already used code"))  # replay
        self.assertEqual(call("POST", "/auth/local", {"username": "boss", "password": "wrong password!!", "code": code})[1].get("totp"), None)

    def test_recovery_codes(self):
        tok = owner_login()
        s, r, _ = call("POST", "/api/account/recovery", {"password": OWNER_PW}, token=tok)
        self.assertEqual((s, len(r["recovery"])), (200, 10))
        code = r["recovery"][0]
        self.assertNotIn(code, json.dumps(st().user("boss")))  # stored hashed
        unthrottle()
        self.assertEqual(call("POST", "/auth/local", {"username": "boss", "password": OWNER_PW, "code": code.upper()})[0], 200)
        self.assertEqual(call("POST", "/auth/local", {"username": "boss", "password": OWNER_PW, "code": code})[0], 401)  # once
        self.assertEqual(call("GET", "/api/account", token=tok)[1]["recoveryLeft"], 9)
        self.assertEqual(call("POST", "/api/account/recovery", {"password": "wrong password!!"}, token=tok)[0], 403)


class D_Accounts(unittest.TestCase):
    def setUp(self):
        unthrottle()

    def test_create_login_disable_role_delete(self):
        own = owner_login()
        new = {"username": "guesty", "password": "guest password 99", "role": "guest", "groups": ["media", "media"]}
        self.assertEqual(call("POST", "/api/users", {**new, "password": "short"}, token=own)[0], 400)
        self.assertEqual(call("POST", "/api/users", {**new, "role": "god"}, token=own)[0], 400)
        self.assertEqual(call("POST", "/api/users", {**new, "username": "../x"}, token=own)[0], 400)
        self.assertEqual(call("POST", "/api/users", new, token=own)[0], 200)
        self.assertEqual(call("POST", "/api/users", new, token=own)[0], 409)
        s, r, h = call("POST", "/auth/local", {"username": "guesty", "password": "guest password 99"})
        self.assertEqual((s, r["user"]["role"], r["user"]["groups"]), (200, "guest", ["media"]))
        g = cookie(h)
        self.assertEqual(call("GET", "/api/registry", token=g)[0], 200)
        self.assertEqual(call("POST", "/api/users", {**new, "username": "x2"}, token=g)[0], 403)  # owner only
        self.assertEqual(call("GET", "/api/users", token=g)[0], 403)
        # role + groups
        self.assertEqual(call("POST", "/api/users/guesty", {"role": "admin", "groups": ["a"]}, token=own)[0], 200)
        self.assertEqual(call("GET", "/api/me", token=g)[1]["user"]["role"], "admin")
        users = {u["username"]: u for u in call("GET", "/api/users", token=own)[1]["users"]}
        self.assertEqual((users["guesty"]["local"], users["guesty"]["totp"], users["boss"]["totp"]), (True, False, True))
        self.assertNotIn("pw_hash", users["guesty"])
        # disable: sessions end, login refused
        s, r, _ = call("POST", "/api/users/guesty", {"disabled": True}, token=own)
        self.assertEqual((s, r["ended"]), (200, 1))
        self.assertEqual(call("GET", "/api/me", token=g)[1]["user"], None)
        self.assertEqual(call("POST", "/auth/local", {"username": "guesty", "password": "guest password 99"})[0], 401)
        call("POST", "/api/users/guesty", {"disabled": False}, token=own)
        self.assertEqual(call("POST", "/auth/local", {"username": "guesty", "password": "guest password 99"})[0], 200)
        # owner password reset for someone else ends their sessions
        call("POST", "/api/users/guesty", {"password": "another guest pw 1"}, token=own)
        self.assertEqual(call("POST", "/auth/local", {"username": "guesty", "password": "another guest pw 1"})[0], 200)
        # guards: not yourself, not the last owner
        self.assertEqual(call("POST", "/api/users/boss", {"role": "admin"}, token=own)[0], 400)
        self.assertEqual(call("POST", "/api/users/boss", {"disabled": True}, token=own)[0], 400)
        self.assertEqual(call("POST", "/api/users/boss/delete", {}, token=own)[0], 400)
        self.assertEqual(call("POST", "/api/users/nobody", {"role": "admin"}, token=own)[0], 404)
        self.assertEqual(call("POST", "/api/users/guesty/delete", {}, token=own)[0], 200)
        self.assertIsNone(st().user("guesty"))
        acts = [a["action"] for a in st().audit_list(50)]
        for want in ("user-created", "user-changed", "user-deleted"):
            self.assertIn(want, acts)

    def test_own_password_and_totp(self):
        own = owner_login()
        call("POST", "/api/users", {"username": "selfie", "password": "selfie password 1", "role": "guest"}, token=own)
        _, _, h = call("POST", "/auth/local", {"username": "selfie", "password": "selfie password 1"})
        me = cookie(h)
        self.assertEqual(call("POST", "/api/account/password", {"current": "nope nope nope", "password": "selfie password 2"}, token=me)[0], 403)
        _, _, h2 = call("POST", "/auth/local", {"username": "selfie", "password": "selfie password 1"})
        other = cookie(h2)   # e.g. a stolen session
        s, r, _ = call("POST", "/api/account/password", {"current": "selfie password 1", "password": "selfie password 2"}, token=me)
        self.assertEqual((s, r["ended"]), (200, 1))   # review L5: the other session ends, this one stays
        self.assertIsNone(call("GET", "/api/me", token=other)[1]["user"])
        self.assertEqual(call("GET", "/api/me", token=me)[1]["user"]["username"], "selfie")
        _, _, h2 = call("POST", "/auth/local", {"username": "selfie", "password": "selfie password 2"})
        other = cookie(h2)
        sec = auth.totp_new_secret()
        self.assertEqual(call("POST", "/api/account/totp", {"password": "selfie password 2", "secret": sec, "code": "123456"}, token=me)[0], 400)
        s, r, _ = call("POST", "/api/account/totp", {"password": "selfie password 2", "secret": sec, "code": auth.totp_code(sec)}, token=me)
        self.assertEqual((s, len(r["recovery"])), (200, 10))
        self.assertTrue(call("GET", "/api/account", token=me)[1]["totp"])
        self.assertIsNone(call("GET", "/api/me", token=other)[1]["user"])   # 2FA on: other sessions end too
        unthrottle()
        self.assertEqual(call("POST", "/auth/local", {"username": "selfie", "password": "selfie password 2"})[1].get("totp"), True)
        # owner resets a lost phone
        call("POST", "/api/users/selfie", {"totp_reset": True}, token=own)
        self.assertEqual(call("POST", "/auth/local", {"username": "selfie", "password": "selfie password 2"})[0], 200)
        st().delete_user("selfie")


class E_Policy(unittest.TestCase):
    def setUp(self):
        unthrottle()

    def tearDown(self):
        GW.app.login.save({"require_2fa": None})
        GW.app.reload_login()

    def test_require_2fa_enrol(self):
        own = owner_login()
        call("POST", "/api/users", {"username": "adm", "password": "admin password 77", "role": "admin"}, token=own)
        self.assertEqual(call("POST", "/api/login/settings", {"values": {"require_2fa": True}}, token=own)[0], 200)
        s, r, h = call("POST", "/auth/local", {"username": "adm", "password": "admin password 77"})
        self.assertEqual((s, r["mustEnrol"]), (200, True))
        adm = cookie(h)
        self.assertTrue(call("GET", "/api/me", token=adm)[1]["user"]["mustEnrol"])
        s, r, _ = call("GET", "/api/registry", token=adm)
        self.assertEqual((s, r.get("enrol")), (403, True))  # nothing but enrolment until 2FA is on
        self.assertEqual(call("GET", "/api/account", token=adm)[1]["mustEnrol"], True)
        sec = auth.totp_new_secret()
        self.assertEqual(call("POST", "/api/account/totp", {"password": "admin password 77", "secret": sec,
                                                            "code": auth.totp_code(sec)}, token=adm)[0], 200)
        self.assertEqual(call("GET", "/api/registry", token=adm)[0], 200)
        self.assertEqual(call("POST", "/api/account/totp/off", {"password": "admin password 77"}, token=adm)[0], 403)
        # guests are not affected
        call("POST", "/api/users", {"username": "gg", "password": "guest password 77", "role": "guest"}, token=own)
        s, r, _ = call("POST", "/auth/local", {"username": "gg", "password": "guest password 77"})
        self.assertFalse(r["mustEnrol"])
        # an owner without 2FA can't switch the policy on (would lock themselves into enrolment)
        call("POST", "/api/users", {"username": "own2", "password": "owner2 password 7", "role": "owner"}, token=own)
        GW.app.login.save({"require_2fa": None})
        _, _, h = call("POST", "/auth/local", {"username": "own2", "password": "owner2 password 7"})
        self.assertEqual(call("POST", "/api/login/settings", {"values": {"require_2fa": True}}, token=cookie(h))[0], 400)
        for n in ("adm", "gg", "own2"):
            st().delete_user(n)


class F_SsoSettings(unittest.TestCase):
    def setUp(self):
        unthrottle()

    def test_sso_config_storage_env_and_test(self):
        own = owner_login()
        self.assertFalse(call("GET", "/api/me")[1]["sso"])
        s, r, _ = call("POST", "/api/login/settings", {"values": {"sso_issuer": "ftp://x"}}, token=own)
        self.assertEqual(s, 400)
        s, r, _ = call("POST", "/api/login/settings", {"values": {
            "sso_issuer": ISSUER, "sso_client_id": "door", "sso_client_secret": "very-secret-value", "sso_name": "Key Door",
            "owner_group": "door-owners"}}, token=own)
        self.assertEqual((s, r["ssoActive"]), (200, True))
        me = call("GET", "/api/me")[1]
        self.assertEqual((me["sso"], me["ssoName"]), (True, "Key Door"))
        raw = dict(st().gateway_config())
        self.assertTrue(raw["sso_client_secret"][0].startswith("v1:") and raw["sso_client_secret"][1])
        self.assertNotIn("very-secret-value", json.dumps(st().q("SELECT * FROM gateway_config")))
        _, view, _ = call("GET", "/api/login/settings", token=own)
        f = {x["key"]: x for x in view["fields"]}
        self.assertEqual((f["sso_client_secret"]["set"], "value" in f["sso_client_secret"]), (True, False))
        self.assertEqual((f["sso_issuer"]["source"], view["redirectUri"], view["rolesync"]), ("db", "https://door.example/auth/callback", "none"))
        self.assertEqual(GW.app.oidc.client_secret, "very-secret-value")
        self.assertEqual(auth.role_for(["door-owners"]), "owner")
        # the discovery test
        s, r, _ = call("POST", "/api/login/test", {}, token=own)
        self.assertEqual((s, r["ok"], r["pkce"]), (200, True, True))
        self.assertFalse(call("POST", "/api/login/test", {"issuer": ISSUER + "/nope"}, token=own)[1]["ok"])
        # env wins: the field is locked and its value is the env one
        os.environ["LAB_OIDC_ISSUER"] = "https://env.example/app"
        os.environ["LAB_OWNER_GROUP"] = "env-owners"
        try:
            GW.app.reload_login()
            self.assertEqual(GW.app.login.get("sso_issuer"), "https://env.example/app")
            self.assertEqual(auth.role_for(["env-owners"]), "owner")
            self.assertEqual(auth.role_for(["door-owners"]), "guest")
            s, r, _ = call("POST", "/api/login/settings", {"values": {"sso_issuer": ISSUER}}, token=own)
            self.assertEqual(s, 400)
            self.assertIn("LAB_OIDC_ISSUER", r["error"])
            f = {x["key"]: x for x in call("GET", "/api/login/settings", token=own)[1]["fields"]}
            self.assertEqual(f["sso_issuer"]["source"], "env")
            self.assertEqual(f["sso_client_id"]["source"], "db")
        finally:
            os.environ.pop("LAB_OIDC_ISSUER")
            os.environ.pop("LAB_OWNER_GROUP")
            GW.app.reload_login()
        # admins read, only the owner writes
        call("POST", "/api/users", {"username": "rdr", "password": "reader password 1", "role": "admin"}, token=own)
        _, _, h = call("POST", "/auth/local", {"username": "rdr", "password": "reader password 1"})
        s, r, _ = call("GET", "/api/login/settings", token=cookie(h))
        self.assertEqual((s, r["editable"]), (200, False))
        self.assertEqual(call("POST", "/api/login/settings", {"values": {"sso_name": "x"}}, token=cookie(h))[0], 403)
        st().delete_user("rdr")
        # clearing the issuer turns SSO off
        call("POST", "/api/login/settings", {"values": {"sso_issuer": None, "owner_group": None}}, token=own)
        self.assertIsNone(GW.app.oidc)
        self.assertEqual(auth.role_for(["lab-owners"]), "owner")

    def test_sso_linking_and_neutral_cap(self):
        own = owner_login()
        call("POST", "/api/login/settings", {"values": {"sso_issuer": ISSUER, "sso_client_id": "door"}}, token=own)
        try:
            app = GW.app
            claims = {"preferred_username": "boss", "groups": ["lab-admins"], "name": "Impostor"}
            app.oidc.finish = lambda q: (dict(claims), "/")
            s, _, h = call("GET", "/auth/callback?code=x&state=y", cookies=STATE_Y)
            self.assertEqual(s, 302)
            self.assertIn("sso_error=", h["Location"])  # a local-only owner is not taken over (or demoted) by name
            self.assertEqual(st().user("boss")["role"], "owner")
            # a new SSO user: created, linked, session capped (no role refresh configured)
            claims.update(preferred_username="ssouser", name="SSO User")
            s, _, h = call("GET", "/auth/callback?code=x&state=y", cookies=STATE_Y)
            self.assertEqual((s, h["Location"]), (302, "/"))
            sess = [c for c in h["_set_cookies"] if c.startswith("lab_session=")]
            self.assertIn("Max-Age=86400", sess[0])  # 24 h cap, not 14 days
            u = st().user("ssouser")
            self.assertEqual((u["role"], u["sso"]), ("admin", 1))
            # disabled: no SSO login either
            st().update_user("ssouser", disabled=True)
            s, _, h = call("GET", "/auth/callback?code=x&state=y", cookies=STATE_Y)
            self.assertIn("disabled", h["Location"])
            # the owner links a local account to SSO → the same person can use both
            call("POST", "/api/users/boss", {"sso": True}, token=own)
            claims.update(preferred_username="boss", groups=["lab-owners"])
            s, _, h = call("GET", "/auth/callback?code=x&state=y", cookies=STATE_Y)
            self.assertEqual(h["Location"], "/")
            st().delete_user("ssouser")
            call("POST", "/api/users/boss", {"sso": False}, token=own)
        finally:
            call("POST", "/api/login/settings", {"values": {"sso_issuer": None, "sso_client_id": None}}, token=own)

    def test_sso_usernames_are_validated(self):
        """Review L7: preferred_username must be a plain lab username, and a new one may not be a case variant."""
        own = owner_login()
        call("POST", "/api/login/settings", {"values": {"sso_issuer": ISSUER, "sso_client_id": "door"}}, token=own)
        try:
            app = GW.app
            claims = {"preferred_username": "x", "groups": ["lab-admins"]}
            app.oidc.finish = lambda q: (dict(claims), "/")
            for bad in ("admin ", " admin", "admin\n", "wiktоr", "admin\u200b", "a", "", None, 42, "a/b", "x" * 65):
                claims["preferred_username"] = bad
                s, _, h = call("GET", "/auth/callback?code=x&state=y", cookies=STATE_Y)
                self.assertEqual(s, 302, bad)
                self.assertIn("sso_error=", h["Location"], bad)
                self.assertFalse([c for c in h["_set_cookies"] if c.startswith("lab_session=") and "Max-Age=0" not in c])
            claims["preferred_username"] = "Ssocase"
            s, _, h = call("GET", "/auth/callback?code=x&state=y", cookies=STATE_Y)
            self.assertEqual(h["Location"], "/")
            for variant in ("ssocase", "SSOCASE"):  # same person to most backends: refused, never a second account
                claims["preferred_username"] = variant
                s, _, h = call("GET", "/auth/callback?code=x&state=y", cookies=STATE_Y)
                self.assertIn("sso_error=", h["Location"])
                self.assertIsNone(st().user(variant))
            claims["preferred_username"] = "Ssocase"  # the exact name keeps working
            s, _, h = call("GET", "/auth/callback?code=x&state=y", cookies=STATE_Y)
            self.assertEqual(h["Location"], "/")
            # local accounts: the same rule (People → add)
            code, d = call("POST", "/api/users", {"username": "SSOCASE", "password": "a-long-enough-pw-9", "role": "guest"},
                           token=own)[:2]
            self.assertEqual(code, 409, d)
            st().delete_user("Ssocase")
        finally:
            call("POST", "/api/login/settings", {"values": {"sso_issuer": None, "sso_client_id": None}}, token=own)

    def test_sso_state_bound_to_browser(self):
        """Review L1: a callback link made from someone else's login must not log this browser in."""
        import hashlib
        import urllib.parse as up
        own = owner_login()
        call("POST", "/api/login/settings", {"values": {"sso_issuer": ISSUER, "sso_client_id": "door"}}, token=own)
        try:
            app = GW.app
            s, _, h = call("GET", "/auth/login?next=/x")
            self.assertEqual(s, 302)
            state = up.parse_qs(up.urlsplit(h["Location"]).query)["state"][0]
            sc = [c for c in h["_set_cookies"] if c.startswith("lab_oidc=")]
            self.assertEqual(len(sc), 1)
            self.assertIn(f"lab_oidc={hashlib.sha256(state.encode()).hexdigest()};", sc[0])
            for want in ("Path=/auth/callback", "HttpOnly", "SameSite=Lax", "Max-Age=600"):
                self.assertIn(want, sc[0])
            self.assertNotIn(state, sc[0])   # only its hash
            seen = []
            app.oidc.finish = lambda q: seen.append(q) or ({"preferred_username": "victimswap", "groups": []}, "/")
            # the attacker's own callback link, opened in the victim's browser (no cookie, or the cookie of another login)
            for jar in (None, {"lab_oidc": hashlib.sha256(b"another state").hexdigest()}, {"lab_oidc": state}):
                s, _, h = call("GET", f"/auth/callback?code=c&state={state}", cookies=jar)
                self.assertEqual(s, 302)
                self.assertIn("sso_error=", h["Location"])
                self.assertIn(up.quote("not started in this browser"), h["Location"])
                self.assertFalse([c for c in h["_set_cookies"] if c.startswith("lab_session=") and "Max-Age=0" not in c])
            self.assertEqual(seen, [])                       # the code was never even redeemed
            self.assertIsNone(st().user("victimswap"))
            # the browser that started it: logged in, and the state cookie is cleared
            s, _, h = call("GET", f"/auth/callback?code=c&state={state}",
                           cookies={"lab_oidc": hashlib.sha256(state.encode()).hexdigest()})
            self.assertEqual((s, h["Location"]), (302, "/"))
            self.assertEqual(len(seen), 1)
            self.assertTrue(any(c.startswith("lab_session=") for c in h["_set_cookies"]))
            self.assertTrue(any(c.startswith("lab_oidc=;") and "Max-Age=0" in c for c in h["_set_cookies"]))
            st().delete_user("victimswap")
        finally:
            call("POST", "/api/login/settings", {"values": {"sso_issuer": None, "sso_client_id": None}}, token=own)

    def test_rolesync_neutral_mode(self):
        old_cfg, old_set = rolesync.CONFIG, rolesync.SETTINGS
        try:
            rolesync.CONFIG, rolesync.SETTINGS = None, GW.app.login
            self.assertEqual(rolesync.mode(), "none")
            s = st()
            s.upsert_user("old-sso", "Old", "", [], "guest")
            s.upsert_user("new-sso", "New", "", [], "guest")
            s.create_local_user("loc", "Loc", "guest", [], auth.hash_password("local password 1"))
            for n, via in (("old-sso", "oidc"), ("new-sso", "oidc"), ("loc", "local")):
                s.new_session(n, 30, via=via)
            s.x("UPDATE sessions SET created=? WHERE username IN ('old-sso', 'loc')", (time.time() - 25 * 3600,))
            r = rolesync.sync_once(s)
            self.assertEqual((r["mode"], r["ended"]), ("none", ["old-sso"]))
            live = {x["username"] for x in s.sessions()}
            self.assertTrue({"new-sso", "loc"} <= live and "old-sso" not in live)  # local sessions are left alone
            GW.app.login.save({"sso_max_age_hours": 1})
            s.x("UPDATE sessions SET created=? WHERE username='new-sso'", (time.time() - 2 * 3600,))
            self.assertEqual(rolesync.sync_once(s)["ended"], ["new-sso"])
            rolesync.CONFIG = lambda m, k: {("authentik", "token"): "t", ("authentik", "url"): "http://ak"}.get((m, k))
            self.assertEqual(rolesync.mode(), "authentik")
            for n in ("old-sso", "new-sso", "loc"):
                s.delete_user(n)
        finally:
            rolesync.CONFIG, rolesync.SETTINGS = old_cfg, old_set
            GW.app.login.save({"sso_max_age_hours": None})


if __name__ == "__main__":
    unittest.main()


class Z_LoginFlood(unittest.TestCase):
    """Security review 2026-11-15 M3: parallel wrong logins from one address can't run more password checks than the
    attempt limit, and the expensive checks never run more than auth.SCRYPT_SLOTS at a time."""

    def test_parallel_attempts_respect_the_limit(self):
        import threading as th
        GW.app.store.x("DELETE FROM login_failures")
        codes, lock = [], th.Lock()
        peak, running = [0], [0]
        real = auth.hashlib.scrypt

        def counting(*a, **k):
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            try:
                return real(*a, **k)
            finally:
                with lock:
                    running[0] -= 1
        auth.hashlib.scrypt = counting
        try:
            def one():
                s = call("POST", "/auth/local", {"username": "nobody", "password": "wrong-password-123"})[0]
                with lock:
                    codes.append(s)
            ts = [th.Thread(target=one) for _ in range(20)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        finally:
            auth.hashlib.scrypt = real
            GW.app.store.x("DELETE FROM login_failures")
        self.assertEqual(codes.count(401), config.LOGIN_ATTEMPTS)
        self.assertEqual(codes.count(429), 20 - config.LOGIN_ATTEMPTS)
        self.assertLessEqual(peak[0], 3)
