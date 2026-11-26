"""Delegation tests (gateway/lab/delegate.py): a `delegate: true` connector (the AI assistant) reads other modules AS
the calling user through /api/delegate — never with more rights than the user, never secret routes, never itself,
never after expiry or logout, never for guests, never writes; answers are redacted.

Imports the gateway lazily and patches lab.config in setUpModule (and restores it): tests/test_gateway.py configures
the same modules through the environment at import time, and both run in one unittest process."""
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
sys.path.insert(0, os.path.join(ROOT, "sdk", "python"))
KEY = bytes(range(32))


def v2(d):
    """A test manifest written the short way → manifest v2 with the same meaning (writes without a role stay open to
    anyone with the module, a backend.auth file becomes a `token` secret in the config; setUpModule stores those)."""
    d = json.loads(json.dumps(d))
    if d.get("manifest") == 2:
        return d
    d.update({"manifest": 2, "version": d.get("version") if isinstance(d.get("version"), str) else "1.0.0"})
    d.setdefault("kind", "community")
    d.setdefault("category", "tools")
    d.pop("contributes", None)
    for r in d.get("routes", []) if isinstance(d.get("routes"), list) else []:
        if isinstance(r, dict) and r.get("method") not in (None, "GET"):
            if "min" not in r and not r.get("owner_only"):
                r["min"] = "guest"
            r.setdefault("label", f"{r['method']} {r.get('path')}")
    be = d.get("backend")
    if isinstance(be, dict) and isinstance(be.get("auth"), dict) and "file" in be["auth"]:
        be["auth"].pop("file")
        be["auth"]["secret"] = "token"
        d.setdefault("config", {"fields": []})["fields"].append({"key": "token", "type": "secret", "label": "token"})
    return d


TMP = None
GOT = []        # (path, claims) the fake backend saw
TOKENS = []     # X-Lab-Delegation values the fake connector received


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        import labauth
        claims = labauth.verify(self.headers.get(labauth.HEADER), KEY, "demo")
        GOT.append((self.path, claims))
        if self.path.startswith("/api/creds"):
            body = {"password": "hunter22", "apiKey": "abcdef123456", "has_password": True,
                    "msg": "login ok token=abcd1234efgh", "name": "pve1"}
        else:
            body = {"you": claims and claims["u"], "role": claims and claims["r"], "path": self.path}
        out = json.dumps(body).encode()
        self.send_response(200 if claims else 401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_POST = do_GET


class Connector(BaseHTTPRequestHandler):  # stands in for connectors/ai: records the delegation it is handed
    def log_message(self, *a):
        pass

    def do_GET(self):
        TOKENS.append(self.headers.get("X-Lab-Delegation"))
        out = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_POST = do_GET


def setUpModule():
    global TMP, BACKEND, CONN, GW, PORT, SAVED, server, config, auth
    from lab import auth, config, server  # noqa: F811  (lazy: see the module docstring)
    TMP = tempfile.mkdtemp(prefix="labdeleg-")
    BACKEND = HTTPServer(("127.0.0.1", 0), Backend)
    CONN = HTTPServer(("127.0.0.1", 0), Connector)
    for s in (BACKEND, CONN):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    for d in ("modules/demo", "modules/aid", "modules/aid2", "keys", "dist"):
        os.makedirs(os.path.join(TMP, d))
    for mid in ("demo", "aid", "aid2"):
        with open(os.path.join(TMP, "keys", f"{mid}.key"), "w") as f:
            f.write(KEY.hex())
    url = f"http://127.0.0.1:{BACKEND.server_address[1]}"
    with open(os.path.join(TMP, "modules", "demo", "manifest.json"), "w") as f:
        json.dump(v2({"id": "demo", "name": "Demo", "backend": {"url": url}, "routes": [
            {"method": "GET", "path": "/api/x"},
            {"method": "GET", "path": "/api/creds"},
            {"method": "GET", "path": "/api/oo", "owner_only": True},
            {"method": "GET", "path": "/api/sec", "owner_only": True, "secret": True, "label": "read key"},
            {"method": "GET", "path": "/api/own", "min": "owner"},
            {"method": "GET", "path": "/api/q", "query_keys": ["n"]},
            {"method": "POST", "path": "/api/do", "min": "admin", "label": "do it", "body_keys": ["a"]},
            {"method": "POST", "path": "/api/rot", "owner_only": True, "label": "rotate"}]}), f)
    for mid in ("aid", "aid2"):
        with open(os.path.join(TMP, "modules", mid, "manifest.json"), "w") as f:
            json.dump(v2({"id": mid, "name": mid, "delegate": True,
                       "backend": {"url": f"http://127.0.0.1:{CONN.server_address[1]}"},
                       "settings": [{"key": "cap", "type": "int", "default": 90}],
                       "routes": [{"method": "GET", "path": "/api/**"}, {"method": "POST", "path": "/api/**", "min": "admin"}]}), f)
    SAVED = {k: getattr(config, k) for k in ("DB", "MODULES_DIR", "KEYS_DIR", "STATIC_DIR", "BACKENDS_FILE",
                                             "DELEGATION_KEY", "COOKIE_SECURE", "TRUST_PROXY", "HEALTH_INTERVAL")}
    config.DB = os.path.join(TMP, "lab.sqlite3")
    config.MODULES_DIR = os.path.join(TMP, "modules")
    config.KEYS_DIR = os.path.join(TMP, "keys")
    config.STATIC_DIR = os.path.join(TMP, "dist")
    config.BACKENDS_FILE = os.path.join(TMP, "backends.json")
    config.DELEGATION_KEY = os.path.join(TMP, "delegation.key")
    config.COOKIE_SECURE, config.TRUST_PROXY, config.HEALTH_INTERVAL = False, False, 3600
    app = server.App()
    GW = server.PooledHTTPServer(("127.0.0.1", 0), server.Handler, app, workers=4)
    PORT = GW.server_address[1]
    threading.Thread(target=GW.serve_forever, daemon=True).start()


def tearDownModule():
    GW.shutdown()
    BACKEND.shutdown()
    CONN.shutdown()
    for k, v in SAVED.items():
        setattr(config, k, v)
    shutil.rmtree(TMP, ignore_errors=True)


def call(method, path, token=None, deleg=None, body=None, source=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10, source_address=(source, 0) if source else None)
    h = {}
    if token:
        h["Cookie"] = f"lab_session={token}"
    if deleg:
        h["X-Lab-Delegation"] = deleg
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    c.request(method, path, data, h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, raw.decode()


def session(username, groups):
    st = GW.app.store
    st.upsert_user(username, username.title(), "", groups, auth.role_for(groups))
    return st.new_session(username, 1)


def token_for(sess, module="aid"):
    """What the connector gets: a request through the normal proxy hands it the delegation."""
    TOKENS.clear()
    code, _ = call("GET", f"/api/m/{module}/api/state", token=sess)
    assert code == 200, code
    return TOKENS[-1]


class Delegation(unittest.TestCase):
    def setUp(self):
        self.owner = session("owner", ["lab-owners"])
        self.admin = session("admin", ["lab-admins"])
        GW.app.store.set_role("admin", "admin")

    def test_connector_gets_a_token_for_owner_and_admin(self):
        self.assertTrue(token_for(self.owner).startswith("d1."))
        self.assertTrue(token_for(self.admin).startswith("d1."))

    def test_whoami_catalog_has_no_secret_routes_and_no_delegators(self):
        code, r = call("GET", "/api/delegate/whoami", deleg=token_for(self.owner))
        self.assertEqual(code, 200)
        self.assertEqual(r["user"]["username"], "owner")
        self.assertEqual(r["settings"]["cap"], 90)
        ids = [m["id"] for m in r["modules"]]
        self.assertIn("demo", ids)
        self.assertNotIn("aid", ids)
        self.assertNotIn("aid2", ids)
        demo = next(m for m in r["modules"] if m["id"] == "demo")
        paths = {(x["method"], x["path"]): x for x in demo["routes"]}
        self.assertNotIn(("GET", "/api/sec"), paths)
        self.assertEqual(paths[("POST", "/api/do")]["body_keys"], ["a"])
        code, r = call("GET", "/api/delegate/whoami", deleg=token_for(self.admin))
        demo = next(m for m in r["modules"] if m["id"] == "demo")
        paths = {(x["method"], x["path"]): x["allow"] for x in demo["routes"]}
        self.assertEqual(paths[("POST", "/api/rot")], "ask")      # admin: owner-only write = ask the owner
        self.assertNotIn(("GET", "/api/own"), paths)               # min owner: not even listed for an admin

    def test_read_runs_as_the_user_and_is_audited(self):
        GOT.clear()
        code, r = call("GET", "/api/delegate/m/demo/api/x", deleg=token_for(self.admin))
        self.assertEqual(code, 200)
        self.assertEqual(r["status"], 200)
        self.assertEqual(r["body"]["you"], "admin")
        self.assertEqual(GOT[-1][1]["r"], "admin")
        row = GW.app.store.audit_list(5)[0]
        self.assertEqual((row["username"], row["action"], row["module"]), ("admin", "read via aid", "demo"))
        self.assertIn("admin via aid", row["detail"])

    def test_secret_route_refused_even_for_owner(self):
        code, _ = call("GET", "/api/delegate/m/demo/api/sec", deleg=token_for(self.owner))
        self.assertEqual(code, 403)
        code, _ = call("GET", "/api/m/demo/api/sec", token=self.owner)  # (the owner's own browser may)
        self.assertEqual(code, 200)

    def test_admin_cannot_escalate(self):
        tok = token_for(self.admin)
        self.assertEqual(call("GET", "/api/delegate/m/demo/api/own", deleg=tok)[0], 403)
        self.assertEqual(call("GET", "/api/delegate/m/demo/api/oo", deleg=tok)[0], 200)  # global reader, as in the UI
        v, p, m = tok.split(".")
        import base64
        claims = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
        claims["r"] = "owner"
        forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
        self.assertEqual(call("GET", "/api/delegate/m/demo/api/own", deleg=f"{v}.{forged}.{m}")[0], 401)

    def test_role_drop_after_mint_counts(self):
        tok = token_for(self.owner)
        self.assertEqual(call("GET", "/api/delegate/m/demo/api/own", deleg=tok)[0], 200)
        GW.app.store.set_role("owner", "admin")
        try:
            self.assertEqual(call("GET", "/api/delegate/m/demo/api/own", deleg=tok)[0], 403)
            GW.app.store.set_role("owner", "guest")
            self.assertEqual(call("GET", "/api/delegate/m/demo/api/x", deleg=tok)[0], 403)
        finally:
            GW.app.store.set_role("owner", "owner")

    def test_expired_token_cannot_be_replayed(self):
        d = GW.app.delegation
        u = GW.app.store.user("owner")
        from lab.delegate import session_hash
        old = d.mint(u, "aid", session_hash(self.owner), now=time.time() - d.ttl - 5)
        self.assertEqual(call("GET", "/api/delegate/m/demo/api/x", deleg=old)[0], 401)
        self.assertIsNone(d.verify(token_for(self.owner), now=time.time() + d.ttl + 1))
        self.assertEqual(call("GET", "/api/delegate/whoami", deleg="garbage")[0], 401)
        self.assertEqual(call("GET", "/api/delegate/whoami")[0], 401)

    def test_logout_ends_the_delegation(self):
        sess = session("owner", ["lab-owners"])
        tok = token_for(sess)
        self.assertEqual(call("GET", "/api/delegate/m/demo/api/x", deleg=tok)[0], 200)
        call("POST", "/auth/logout", token=sess)
        self.assertEqual(call("GET", "/api/delegate/m/demo/api/x", deleg=tok)[0], 401)

    def test_guest_gets_nothing(self):
        guest = session("guest-one", ["knit-brukere"])
        TOKENS.clear()
        self.assertEqual(call("GET", "/api/m/aid/api/state", token=guest)[0], 404)
        self.assertEqual(TOKENS, [])
        u = GW.app.store.user("guest-one")
        from lab.delegate import session_hash
        tok = GW.app.delegation.mint(u, "aid", session_hash(guest))  # even a gateway-minted guest token is refused
        self.assertEqual(call("GET", "/api/delegate/m/demo/api/x", deleg=tok)[0], 401)

    def test_assistant_cannot_call_itself_or_another_delegator(self):
        tok = token_for(self.owner)
        self.assertEqual(call("GET", "/api/delegate/m/aid/api/state", deleg=tok)[0], 403)
        self.assertEqual(call("GET", "/api/delegate/m/aid2/api/state", deleg=tok)[0], 403)

    def test_no_writes_and_only_from_localhost(self):
        tok = token_for(self.owner)
        self.assertEqual(call("POST", "/api/delegate/m/demo/api/do", deleg=tok, body={"a": 1})[0], 405)
        self.assertEqual(call("GET", "/api/delegate/m/demo/api/x", deleg=tok, source="127.0.0.2")[0], 403)

    def test_rules_still_apply(self):
        tok = token_for(self.owner)
        self.assertEqual(call("GET", "/api/delegate/m/demo/api/q?n=1", deleg=tok)[0], 200)
        self.assertEqual(call("GET", "/api/delegate/m/demo/api/q?evil=1", deleg=tok)[0], 403)
        self.assertEqual(call("GET", "/api/delegate/m/demo/api/x/../creds", deleg=tok)[0], 400)
        self.assertEqual(call("GET", "/api/delegate/m/demo/api/nope", deleg=tok)[0], 403)

    def test_answers_are_redacted(self):
        code, r = call("GET", "/api/delegate/m/demo/api/creds", deleg=token_for(self.owner))
        self.assertEqual(code, 200)
        b = r["body"]
        self.assertEqual((b["password"], b["apiKey"], b["has_password"], b["name"]), ("[redacted]", "[redacted]", True, "pve1"))
        self.assertNotIn("abcd1234efgh", b["msg"])

    def test_switched_off_module_stops_delegating(self):
        tok = token_for(self.owner)
        GW.app.registry.overrides = {"aid": {"_enabled": False}}
        try:
            self.assertEqual(call("GET", "/api/delegate/m/demo/api/x", deleg=tok)[0], 403)
        finally:
            GW.app.registry.overrides = {}

    def test_manifest_delegate_only_for_local_connectors(self):
        from lab.registry import ManifestError, validate
        with self.assertRaises(ManifestError):
            validate(v2({"id": "x1", "name": "X", "delegate": True, "backend": {"url": "http://192.0.2.50:8080"}}))
        with self.assertRaises(ManifestError):
            validate(v2({"id": "x1", "name": "X", "delegate": "yes", "backend": {"url": "http://127.0.0.1:8117"}}))
        self.assertTrue(validate(v2({"id": "x1", "name": "X", "delegate": True, "backend": {"url": "http://127.0.0.1:8117"}})))



class RedactionWords(unittest.TestCase):
    """Review L8: credential field names the first version let through (tracker passkeys, short or hashed password
    names, secret*/token*/api key spellings, WireGuard and enrollment keys) — in JSON and in text."""

    def test_more_credential_names(self):
        from lab import redact
        leak = {"passkey": "abcdef123456", "pass": "hunter2hunter2", "pw_hash": "$scrypt$n=32768$abc", "pw": "pw-value-1",
                "secretValue": "sv-123456", "secret_access": "sa-123456", "client_secret2": "cs-123456",
                "tokenId": "tid-123456", "token_v2": "tv-123456", "refreshTokens": "rt-123456", "APIKEY": "ak-1",
                "api_key2": "ak-2", "Api-Key": "ak-3", "xApiKey": "ak-4", "apikeys": ["ak-5"], "enrollKey": "ek-1",
                "wg_private": "wg-1", "passwordHash": "ph-1", "nested": [{"Passkey": "pk-2"}]}
        out = redact.data({**leak, "has_password": True, "token_count": 3, "name": "pve1", "keyboard": "us",
                           "passive": "yes", "monkey": "banana"})
        for k in leak:
            if k != "nested":
                self.assertEqual(out[k], redact.MARK, k)
        self.assertEqual(out["nested"][0]["Passkey"], redact.MARK)
        self.assertEqual((out["has_password"], out["token_count"], out["name"], out["keyboard"], out["passive"],
                          out["monkey"]), (True, 3, "pve1", "us", "yes", "banana"))   # not everything is a secret
        txt = redact.text('announce?passkey=abcdef123456 pw_hash: "s3cr3tH4sh" secretValue=zz-998877 '
                          'token_v2=tt-445566 enroll_key=ee-112233 wg_private_key=wgk-778899')
        for v in ("abcdef123456", "s3cr3tH4sh", "zz-998877", "tt-445566", "ee-112233", "wgk-778899"):
            self.assertNotIn(v, txt)


if __name__ == "__main__":
    unittest.main()
