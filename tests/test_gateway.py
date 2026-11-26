"""Gateway tests: signing, manifest routing/permissions, and the HTTP server end to end against a fake backend.

Run:  python3 -m unittest discover -s tests"""
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
TMP = tempfile.mkdtemp(prefix="labtest-")
os.environ.update({
    "LAB_DB": os.path.join(TMP, "lab.sqlite3"), "LAB_MODULES": os.path.join(TMP, "modules"),
    "LAB_KEYS": os.path.join(TMP, "keys"), "LAB_STATIC": os.path.join(TMP, "dist"),
    "LAB_TOPOLOGY": os.path.join(TMP, "topology.json"), "LAB_BACKENDS": os.path.join(TMP, "backends.json"),
    "LAB_MASTER_KEY": os.path.join(TMP, "master.key"),
    "LAB_COOKIE_SECURE": "0", "LAB_TRUST_PROXY": "0", "LAB_HEALTH_INTERVAL": "3600", "LAB_LOGIN_ATTEMPTS": "3",
})
sys.path.insert(0, os.path.join(ROOT, "gateway"))
sys.path.insert(0, os.path.join(ROOT, "sdk", "python"))

import labauth  # noqa: E402
from lab import auth, server  # noqa: E402
from lab.registry import ManifestError, Registry, validate  # noqa: E402

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


KEY = bytes(range(32))
SEEN = []  # requests the fake backend received: (method, path, claims, body)


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _go(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        hdr = self.headers.get(labauth.HEADER)
        claims = labauth.verify(hdr, KEY, "demo") or labauth.verify(hdr, KEY, "guesty")
        if self.headers.get("X-Api-Key") == "PFXs3cret-token":
            claims = {"u": "apikey", "r": "service"}
        if self.headers.get("Authorization") == "Bearer s3cret-token":
            claims = {"u": "bearer", "r": "service"}
        SEEN.append((self.command, self.path, claims, body))
        out = json.dumps({"you": claims and claims["u"], "role": claims and claims["r"], "path": self.path}).encode()
        self.send_response(200 if claims else 401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "evil=1")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _go


def setUpModule():
    global BACKEND, GW, PORT
    BACKEND = HTTPServer(("127.0.0.1", 0), Backend)
    threading.Thread(target=BACKEND.serve_forever, daemon=True).start()
    os.makedirs(os.path.join(TMP, "modules", "demo"))
    os.makedirs(os.path.join(TMP, "modules", "guesty"))
    os.makedirs(os.path.join(TMP, "keys"))
    os.makedirs(os.path.join(TMP, "dist", "assets"))
    with open(os.path.join(TMP, "dist", "index.html"), "w") as f:
        f.write("<!doctype html><title>lab</title>")
    with open(os.path.join(TMP, "dist", "assets", "a.js"), "w") as f:
        f.write("1")
    with open(os.path.join(TMP, "keys", "demo.key"), "w") as f:
        f.write(KEY.hex())
    with open(os.path.join(TMP, "keys", "guesty.key"), "w") as f:
        f.write(KEY.hex())
    with open(os.path.join(TMP, "keys", "third.token"), "w") as f:
        f.write("s3cret-token\n")
    os.makedirs(os.path.join(TMP, "modules", "third"))
    url = f"http://127.0.0.1:{BACKEND.server_address[1]}"
    with open(os.path.join(TMP, "modules", "demo", "manifest.json"), "w") as f:
        json.dump(v2({"id": "demo", "name": "Demo", "backend": {"url": url},
                   "routes": [{"method": "GET", "path": "/api/x"}, {"method": "GET", "path": "/api/items/*"},
                              {"method": "POST", "path": "/api/do", "min": "admin", "label": "do it"},
                              {"method": "POST", "path": "/api/secret", "owner_only": True, "label": "rotate"},
                              {"method": "GET", "path": "/api/key", "owner_only": True, "secret": True, "label": "read key"},
                              {"method": "POST", "path": "/api/mach/40/**", "owner_only": True, "label": "act on 40"},
                              {"method": "POST", "path": "/api/mach/*/act", "min": "admin", "label": "act"},
                              {"method": "PUT", "path": "/api/cfg", "min": "admin", "body_keys": ["cores"], "label": "cfg"},
                              {"method": "POST", "path": "/api/lib", "min": "admin", "query_keys": ["name", "refreshLibrary"],
                               "body_keys": ["LibraryOptions"], "label": "add lib"},
                              {"method": "POST", "path": "/api/noq", "min": "admin", "query_keys": [], "label": "no query"},
                              {"method": "POST", "path": "/api/trig", "min": "admin", "body_list": True, "body_keys": ["Type", "IntervalTicks"],
                               "body_allow": {"Type": ["DailyTrigger", "IntervalTrigger"]}, "label": "triggers"},
                              {"method": "POST", "path": "/api/pw", "owner_only": True, "query_keys": ["userId"],
                               "body_keys": ["NewPw"], "label": "set pw"}]}), f)
    with open(os.path.join(TMP, "modules", "guesty", "manifest.json"), "w") as f:
        json.dump(v2({"id": "guesty", "name": "Guesty", "backend": {"url": url},
                   "access": {"roles": ["owner", "admin"], "groups": ["cdn-admins"]},
                   "routes": [{"method": "GET", "path": "/**"}]}), f)
    with open(os.path.join(TMP, "modules", "third", "manifest.json"), "w") as f:
        json.dump(v2({"id": "third", "name": "Third", "backend": {"url": url, "auth": {"type": "bearer", "file": "third.token"}},
                   "routes": [{"method": "GET", "path": "/api/v3/core/users"}, {"method": "PATCH", "path": "/api/v3/core/users/*", "owner_only": True},
                              {"method": "DELETE", "path": "/api/v3/core/users/*", "owner_only": True}]}), f)
    os.makedirs(os.path.join(TMP, "modules", "hdr"))
    with open(os.path.join(TMP, "modules", "hdr", "manifest.json"), "w") as f:
        json.dump(v2({"id": "hdr", "name": "Hdr", "backend": {"url": url, "auth": {"type": "header", "name": "X-Api-Key", "prefix": "PFX", "file": "third.token"}},
                   "routes": [{"method": "GET", "path": "/api/v1/**"}]}), f)
    os.makedirs(os.path.join(TMP, "modules", "pvelike"))
    with open(os.path.join(TMP, "modules", "pvelike", "manifest.json"), "w") as f:  # a backend that decodes %2F (Proxmox)
        json.dump(v2({"id": "pvelike", "name": "PVE-like", "backend": {"url": url, "decodes_slashes": True, "auth": {
                       "type": "header", "name": "X-Api-Key", "prefix": "PFX", "file": "third.token"}},
                   "routes": [{"method": "GET", "path": "/nodes/*/lxc/*/config"},
                              {"method": "GET", "path": "/nodes/*/tasks/*/status"},
                              {"method": "POST", "path": "/nodes/*/lxc/112/**", "owner_only": True},
                              {"method": "POST", "path": "/nodes/*/lxc/*/status/start", "min": "admin"}]}), f)
    os.makedirs(os.path.join(TMP, "modules", "cfgmod"))
    with open(os.path.join(TMP, "modules", "cfgmod", "manifest.json"), "w") as f:  # manifest v2: config, no URL/secret inside
        json.dump({"manifest": 2, "id": "cfgmod", "name": "Cfg", "version": "1.0.0", "kind": "community", "category": "network",
                   "config": {"fields": [{"key": "url", "type": "url", "label": "URL", "required": True},
                                         {"key": "token", "type": "secret", "label": "API token", "required": True},
                                         {"key": "verify", "type": "bool", "label": "verify TLS", "default": True}],
                              "validate": {"path": "/api/v3/core/users"}},
                   "backend": {"url": "{url}", "tls_verify": "{verify}", "auth": {"type": "bearer", "secret": "token"}},
                   "routes": [{"method": "GET", "path": "/api/v3/core/users"},
                              {"method": "POST", "path": "/api/v3/core/users/*", "min": "admin", "label": "edit user"}]}, f)
    with open(os.environ["LAB_MASTER_KEY"], "w") as f:
        f.write("ab" * 32)
    app = server.App()
    # manifest v2: the backend.auth secrets of third/hdr/pvelike live in the (sealed) module config, as on a gateway
    for mid in ("third", "hdr", "pvelike"):
        app.store.set_module_config(mid, "token", app.box.seal(mid, "token", "s3cret-token"), secret=True)
    app.reload_config()
    GW = server.PooledHTTPServer(("127.0.0.1", 0), server.Handler, app, workers=4)
    PORT = GW.server_address[1]
    threading.Thread(target=GW.serve_forever, daemon=True).start()


def tearDownModule():
    GW.shutdown()
    BACKEND.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)


def call(method, path, body=None, token=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    h = dict(headers or {})
    if token:
        h["Cookie"] = f"lab_session={token}"
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
    return r.status, payload, dict(r.getheaders())


def session(username, groups):
    st = GW.app.store
    st.upsert_user(username, username.title(), "", groups, auth.role_for(groups))
    return st.new_session(username, 1)


class Signing(unittest.TestCase):
    def test_roundtrip(self):
        h = labauth.sign(KEY, {"u": "owner", "r": "owner", "m": "demo"})
        self.assertEqual(labauth.verify(h, KEY, "demo")["u"], "owner")

    def test_wrong_module_key_tamper_expiry(self):
        h = labauth.sign(KEY, {"u": "owner", "r": "owner", "m": "demo"})
        self.assertIsNone(labauth.verify(h, KEY, "other"))
        self.assertIsNone(labauth.verify(h, b"x" * 32, "demo"))
        v, p, m = h.split(".")
        self.assertIsNone(labauth.verify(f"{v}.{p[:-2]}AA.{m}", KEY, "demo"))
        self.assertIsNone(labauth.verify(h, KEY, "demo", now=time.time() + 120))
        self.assertIsNone(labauth.verify(labauth.sign(KEY, {"u": "x", "r": "god", "m": "demo"}), KEY, "demo"))
        self.assertIsNone(labauth.verify("garbage", KEY, "demo"))


class Routing(unittest.TestCase):
    def mod(self, **kw):
        return validate(v2({"id": "m1", "name": "M", "backend": {"url": "http://x"}, **kw}))

    def test_patterns(self):
        m = self.mod(routes=[{"method": "GET", "path": "/a/*/b"}, {"method": "GET", "path": "/files/**"}])
        self.assertTrue(Registry.find_route(m, "GET", "/a/1/b"))
        self.assertFalse(Registry.find_route(m, "GET", "/a/1/2/b"))
        self.assertTrue(Registry.find_route(m, "GET", "/files"))
        self.assertTrue(Registry.find_route(m, "GET", "/files/x/y.txt"))
        self.assertFalse(Registry.find_route(m, "POST", "/files/x"))
        self.assertFalse(Registry.find_route(m, "GET", "/a/1/b/../../etc"))

    def test_permissions(self):
        m = self.mod(routes=[{"method": "GET", "path": "/r"}, {"method": "POST", "path": "/w", "min": "admin"},
                             {"method": "POST", "path": "/s", "owner_only": True}])
        g, a, o = ({"username": n, "role": n} for n in ("guest", "admin", "owner"))
        r = lambda p, meth="POST": Registry.find_route(m, meth, p)  # noqa: E731
        self.assertEqual([Registry.permission(r("/r", "GET"), u) for u in (g, a, o)], ["yes"] * 3)
        self.assertEqual([Registry.permission(r("/w"), u) for u in (g, a, o)], ["no", "yes", "yes"])
        self.assertEqual([Registry.permission(r("/s"), u) for u in (g, a, o)], ["no", "ask", "yes"])
        m3 = self.mod(routes=[{"method": "POST", "path": "/cmd", "body_allow": {"name": ["Ok"]}}])
        r3 = Registry.find_route(m3, "POST", "/cmd")
        self.assertTrue(Registry.body_ok(r3, b'{"name": "Ok", "x": 1}'))
        self.assertFalse(Registry.body_ok(r3, b'{"name": "Bad"}'))
        self.assertFalse(Registry.body_ok(r3, b'[1]'))
        self.assertFalse(Registry.body_ok(r3, b'not json'))
        m2 = self.mod(routes=[{"method": "GET", "path": "/oo", "owner_only": True}, {"method": "GET", "path": "/sec", "owner_only": True, "secret": True}])
        self.assertEqual([Registry.permission(Registry.find_route(m2, "GET", "/oo"), u) for u in (g, a, o)], ["no", "yes", "yes"])
        self.assertEqual([Registry.permission(Registry.find_route(m2, "GET", "/sec"), u) for u in (g, a, o)], ["no", "ask", "yes"])
        self.assertEqual(Registry.permission(None, o), "no")

    def test_access_and_validation(self):
        m = self.mod(access={"roles": ["owner"], "groups": ["cdn-admins"]})
        reg = Registry("/nonexistent")
        self.assertTrue(reg.can_use(m, {"role": "admin", "groups": []}))  # admins are global readers
        self.assertFalse(reg.can_use(m, {"role": "guest", "groups": []}))
        self.assertTrue(reg.can_use(m, {"role": "guest", "groups": ["cdn-admins"]}))
        self.assertTrue(reg.can_use(m, {"role": "owner", "groups": []}))
        reg.overrides = {"m1": {"_groups": ["knit-brukere"]}}
        self.assertTrue(reg.can_use(m, {"role": "guest", "groups": ["knit-brukere"]}))
        reg.overrides = {"m1": {"_enabled": False}}
        self.assertFalse(reg.can_use(m, {"role": "owner", "groups": []}))
        with self.assertRaises(ManifestError):
            validate(v2({"id": "Bad", "name": "x"}))
        with self.assertRaises(ManifestError):
            validate(v2({"id": "ok", "name": "x", "routes": [{"method": "GET", "path": "/x"}]}))  # no backend

    def test_real_manifests_valid(self):
        reg = Registry(os.path.join(ROOT, "modules"))
        self.assertIn("proxmox", reg.modules)  # a module that is always present (private modules may be absent)
        self.assertEqual(reg.errors, {})

    def test_roles(self):
        self.assertEqual(auth.role_for(["lab-owners", "lab-admins"]), "owner")
        self.assertEqual(auth.role_for(["lab-admins"]), "admin")
        self.assertEqual(auth.role_for(["cdn-admins"]), "guest")


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = session("owner", ["lab-owners", "homelab-admins"])
        cls.admin = session("admin", ["lab-admins"])
        cls.guest = session("guest-one", ["cdn-admins"])
        cls.nobody = session("guest-two", [])

    def test_health_and_static(self):
        self.assertEqual(call("GET", "/healthz")[0], 200)
        s, body, h = call("GET", "/some/client/route")
        self.assertEqual(s, 200)
        self.assertIn("lab", body)
        self.assertIn("Content-Security-Policy", h)
        self.assertIn("immutable", call("GET", "/assets/a.js")[2]["Cache-Control"])
        self.assertEqual(call("GET", "/assets/missing.js")[0], 404)
        self.assertEqual(call("GET", "/../../etc/passwd")[0] in (200, 404), True)

    def test_needs_login(self):
        self.assertEqual(call("GET", "/api/registry")[0], 401)
        self.assertEqual(call("GET", "/api/m/demo/api/x")[0], 401)
        self.assertIsNone(call("GET", "/api/me")[1]["user"])

    def test_registry_per_role(self):
        _, r, _ = call("GET", "/api/registry", token=self.owner)
        self.assertEqual({m["id"] for m in r["modules"]}, {"demo", "guesty", "third", "hdr", "pvelike"})
        self.assertEqual(r["user"]["role"], "owner")
        _, r, _ = call("GET", "/api/registry", token=self.admin)
        demo = next(m for m in r["modules"] if m["id"] == "demo")
        self.assertEqual({x["path"]: x["allow"] for x in demo["routes"]}["/api/secret"], "ask")
        _, r, _ = call("GET", "/api/registry", token=self.guest)
        self.assertEqual([m["id"] for m in r["modules"]], ["guesty"])
        _, r, _ = call("GET", "/api/registry", token=self.nobody)
        self.assertEqual(r["modules"], [])

    def test_proxy_signs_and_filters(self):
        s, r, h = call("GET", "/api/m/demo/api/x?q=1", token=self.admin)
        self.assertEqual((s, r["you"], r["role"], r["path"]), (200, "admin", "admin", "/api/x?q=1"))
        self.assertNotIn("Set-Cookie", h)  # backend cookies never reach the browser
        self.assertEqual(call("GET", "/api/m/demo/api/items/7", token=self.admin)[0], 200)
        self.assertEqual(call("GET", "/api/m/demo/api/other", token=self.owner)[0], 403)  # not in manifest
        self.assertEqual(call("GET", "/api/m/demo/api/x", token=self.guest)[0], 404)  # module hidden
        self.assertEqual(call("GET", "/api/m/nope/x", token=self.owner)[0], 404)
        self.assertEqual(call("GET", "/api/m/guesty/anything/at/all", token=self.guest)[0], 200)

    def test_write_roles_and_csrf(self):
        self.assertEqual(call("POST", "/api/m/demo/api/do", {}, token=self.admin)[0], 200)
        self.assertEqual(call("POST", "/api/m/demo/api/do", {}, token=self.admin,
                              headers={"Origin": "https://evil.example", "Host": "lab.example.com"})[0], 403)
        self.assertEqual(call("POST", "/api/m/demo/api/do", {}, token=self.admin,
                              headers={"Origin": "http://lab.example.com", "Host": "lab.example.com"})[0], 200)
        audit = GW.app.store.audit_list(20)
        self.assertTrue(any(a["action"] == "do it" and a["username"] == "admin" for a in audit))

    def test_owner_only_approval_flow(self):
        SEEN.clear()
        s, r, _ = call("POST", "/api/m/demo/api/secret", {"x": 1}, token=self.admin)
        self.assertEqual((s, r.get("approval")), (403, True))
        self.assertEqual(SEEN, [])  # never reached the backend
        self.assertEqual(call("POST", "/api/m/demo/api/secret", {"x": 1}, token=self.owner)[0], 200)
        # admin asks; guest/owner cannot ask; a non-owner-only route cannot be "asked"
        s, r, _ = call("POST", "/api/approvals", {"module": "demo", "method": "POST", "path": "/api/secret",
                                                  "body": {"x": 2}, "reason": "rotate it"}, token=self.admin)
        self.assertEqual(s, 200)
        aid = r["approval"]["id"]
        self.assertEqual(call("POST", "/api/approvals", {"module": "demo", "method": "POST", "path": "/api/do"},
                              token=self.admin)[0], 400)
        self.assertEqual(call("POST", "/api/approvals", {"module": "demo", "method": "POST", "path": "/api/secret"},
                              token=self.owner)[0], 403)
        # admin sees only own; cannot approve
        self.assertEqual(call("POST", f"/api/approvals/{aid}/approve", {}, token=self.admin)[0], 403)
        _, r, _ = call("GET", "/api/registry", token=self.owner)
        self.assertGreaterEqual(r["approvalsPending"], 1)
        SEEN.clear()
        s, r, _ = call("POST", f"/api/approvals/{aid}/approve", {}, token=self.owner)
        self.assertEqual((s, r["approval"]["status"], r["approval"]["result_code"]), (200, "done", 200))
        self.assertEqual(len(SEEN), 1)
        method, path, claims, body = SEEN[0]
        self.assertEqual((method, path, claims["u"], claims["r"], claims["a"], json.loads(body)),
                         ("POST", "/api/secret", "admin", "admin", "owner", {"x": 2}))
        _, mine, _ = call("GET", "/api/approvals", token=self.admin)
        self.assertTrue(all(x["result_body"] is None for x in mine["approvals"]))  # results never reach the requester
        # one-time: cannot approve again
        self.assertEqual(call("POST", f"/api/approvals/{aid}/approve", {}, token=self.owner)[0], 409)

    def test_deny_and_cancel(self):
        _, r, _ = call("POST", "/api/approvals", {"module": "demo", "method": "POST", "path": "/api/secret"}, token=self.admin)
        a1 = r["approval"]["id"]
        _, r, _ = call("POST", "/api/approvals", {"module": "demo", "method": "POST", "path": "/api/secret"}, token=self.admin)
        a2 = r["approval"]["id"]
        self.assertEqual(call("POST", f"/api/approvals/{a1}/deny", {}, token=self.owner)[1]["approval"]["status"], "denied")
        self.assertEqual(call("POST", f"/api/approvals/{a2}/cancel", {}, token=self.owner)[0], 403)
        self.assertEqual(call("POST", f"/api/approvals/{a2}/cancel", {}, token=self.admin)[1]["approval"]["status"], "cancelled")

    def test_local_login_and_throttle(self):
        st = GW.app.store
        st.upsert_user("breakglass", "BG", "", [], "owner")
        st.set_password_hash("breakglass", auth.hash_password("correct horse battery"))
        hdr = {"X-Real-IP": "1.2.3.4"}
        s, r, h = call("POST", "/auth/local", {"username": "breakglass", "password": "correct horse battery"}, headers=hdr)
        self.assertEqual((s, r["user"]["role"]), (200, "owner"))
        self.assertIn("lab_session=", h["Set-Cookie"])
        self.assertIn("HttpOnly", h["Set-Cookie"])
        for _ in range(3):
            self.assertEqual(call("POST", "/auth/local", {"username": "breakglass", "password": "nope"})[0], 401)
        self.assertEqual(call("POST", "/auth/local", {"username": "breakglass", "password": "correct horse battery"})[0], 429)

    def test_prefs_users_metrics(self):
        self.assertEqual(call("POST", "/api/prefs", {"key": "wall.hidden", "value": ["a"]}, token=self.guest)[0], 200)
        self.assertEqual(call("GET", "/api/prefs", token=self.guest)[1]["prefs"], {"wall.hidden": ["a"]})
        self.assertEqual(call("POST", "/api/prefs", {"key": "../x", "value": 1}, token=self.guest)[0], 400)
        self.assertEqual(call("GET", "/api/users", token=self.guest)[0], 403)
        self.assertEqual(call("GET", "/api/users", token=self.admin)[0], 200)
        self.assertEqual(call("POST", "/api/users/guest-one/logout", {}, token=self.admin)[0], 403)
        s, body, _ = call("GET", "/metrics")
        self.assertEqual(s, 200)
        self.assertIn("lab_up 1", body)

    def test_bearer_backend_and_trailing_slash(self):
        SEEN.clear()
        s, r, _ = call("GET", "/api/m/third/api/v3/core/users/?page_size=5", token=self.admin)
        self.assertEqual((s, r["you"]), (200, "bearer"))
        self.assertIsNone(labauth.verify(None, KEY, "third"))
        self.assertEqual(call("PATCH", "/api/m/third/api/v3/core/users/6/", {"name": "x"}, token=self.admin)[1].get("approval"), True)
        self.assertEqual(call("PATCH", "/api/m/third/api/v3/core/users/6/", {"name": "x"}, token=self.owner)[0], 200)
        self.assertEqual(call("DELETE", "/api/m/third/api/v3/core/users/6/", token=self.owner)[0], 200)
        self.assertEqual(SEEN[-1][0], "DELETE")
        self.assertEqual(call("GET", "/api/m/third/api/v3/core/tokens/", token=self.owner)[0], 403)  # not in manifest
        self.assertEqual(call("GET", "/api/m/hdr/api/v1/queue", token=self.owner)[1]["you"], "apikey")
        with self.assertRaises(ManifestError):
            validate(v2({"id": "bad", "name": "x", "backend": {"url": "http://x", "auth": {"type": "header", "name": "Cookie", "file": "a"}}}))

    def test_keepalive_never_mixes_users(self):
        # one TCP connection, alternating users (what the reverse proxy does): each request must see its own user
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
        try:
            for tok, who in [(self.owner, "owner"), (self.admin, "admin"), (None, None), (self.guest, "guest-one"), (self.owner, "owner")]:
                c.request("GET", "/api/me", headers={"Cookie": f"lab_session={tok}"} if tok else {})
                r = c.getresponse()
                me = json.loads(r.read())["user"]
                self.assertEqual(me and me["username"], who)
        finally:
            c.close()

    def test_module_settings(self):
        s, r, _ = call("GET", "/api/settings", token=self.admin)
        self.assertEqual((s, r["editable"]), (200, False))
        self.assertIn("_ticker", {x["key"] for x in r["modules"][0]["schema"]})
        self.assertEqual(call("GET", "/api/settings", token=self.guest)[0], 403)
        self.assertEqual(call("POST", "/api/settings/module", {"module": "demo", "enabled": False}, token=self.admin)[0], 403)
        self.assertEqual(call("POST", "/api/settings/module", {"module": "demo", "values": {"_ticker": "yes"}}, token=self.owner)[0], 400)
        self.assertEqual(call("POST", "/api/settings/module", {"module": "demo", "values": {"nope": 1}}, token=self.owner)[0], 400)
        s, r, _ = call("POST", "/api/settings/module", {"module": "demo", "values": {"_ticker": False}}, token=self.owner)
        self.assertEqual((s, r["values"]["_ticker"]), (200, False))
        _, reg, _ = call("GET", "/api/registry", token=self.admin)
        self.assertFalse(next(m for m in reg["modules"] if m["id"] == "demo")["settings"]["_ticker"])
        # off → gone for everyone, proxy too; extra group → a guest gets in
        call("POST", "/api/settings/module", {"module": "demo", "enabled": False}, token=self.owner)
        self.assertEqual(call("GET", "/api/m/demo/api/x", token=self.owner)[0], 404)
        call("POST", "/api/settings/module", {"module": "demo", "enabled": True, "extraGroups": ["cdn-admins"], "values": {"_ticker": None}}, token=self.owner)
        self.assertEqual(call("GET", "/api/m/demo/api/x", token=self.guest)[0], 200)
        call("POST", "/api/settings/module", {"module": "demo", "extraGroups": []}, token=self.owner)
        self.assertEqual(call("GET", "/api/m/demo/api/x", token=self.guest)[0], 404)
        # shared-credential (backend.auth) modules refuse guest groups
        s, r, _ = call("POST", "/api/settings/module", {"module": "third", "extraGroups": ["cdn-admins"]}, token=self.owner)
        self.assertEqual(s, 400)

    def test_role_sync(self):
        from lab import rolesync
        st = GW.app.store
        st.upsert_user("rs-admin", "RS", "", ["lab-admins"], "admin")
        st.upsert_user("rs-gone", "Gone", "", ["lab-admins"], "admin")
        st.upsert_user("rs-local", "Local", "", ["lab-owners"], "owner")
        st.new_session("rs-admin", 1, via="oidc")
        st.new_session("rs-gone", 1, via="oidc")
        st.new_session("rs-local", 1, via="local")
        world = {"rs-admin": {"active": True, "groups": ["cdn-admins"]}, "rs-gone": {"active": False, "groups": []}}
        same = lambda n: {"active": True, "groups": sorted(st.user(n)["groups"])}  # noqa: E731 — everyone else unchanged
        r = rolesync.sync_once(st, lookup=lambda n, t: world.get(n) or same(n), token="x")
        self.assertIn("rs-admin", r["changed"])
        self.assertIn("rs-gone", r["ended"])
        self.assertEqual(st.user("rs-admin")["role"], "guest")
        self.assertEqual([s for s in st.sessions() if s["username"] == "rs-gone"], [])
        self.assertTrue([s for s in st.sessions() if s["username"] == "rs-local"])  # break-glass untouched
        def boom(n, t):
            raise OSError("authentik down")
        self.assertIn("error", rolesync.sync_once(st, lookup=boom, token="x"))  # fails open
        # the token + URL come from the authentik module's (v2) config when the gateway provides it
        old = rolesync.CONFIG
        try:
            rolesync.CONFIG = lambda m, k: {("authentik", "token"): "cfg-token", ("authentik", "url"): "http://ak:9000/"}.get((m, k))
            self.assertEqual((rolesync._token(), rolesync._api()), ("cfg-token", "http://ak:9000/api/v3"))
        finally:
            rolesync.CONFIG = old

    def test_logout(self):
        tok = session("temp", [])
        self.assertEqual(call("GET", "/api/registry", token=tok)[0], 200)
        call("POST", "/auth/logout", {}, token=tok)
        self.assertEqual(call("GET", "/api/registry", token=tok)[0], 401)


class SecurityReview(unittest.TestCase):
    """Regressions for the 2026-11-14 security review (SECURITY-REVIEW.md)."""

    @classmethod
    def setUpClass(cls):
        cls.owner = session("owner", ["lab-owners", "homelab-admins"])
        cls.admin = session("admin", ["lab-admins"])
        cls.admin2 = session("second", ["lab-admins"])
        cls.guest = session("guest2", ["cdn-admins"])

    # --- matching -------------------------------------------------------------------------------------------------
    def test_path_problem(self):
        from lab.registry import path_problem
        for bad in ("/a/../b", "/a/./b", "/a/%2e%2e/b", "/a/%2E%2e", "/a/%252e%252e/b", "/a/..;/b", "/a/..%3b/b",
                    "//x", "/a//b", "/a\\b", "/a/%5cb", "/a/%00", "/a/%0d%0aX:1", "/a?b", "/a#b", "a", "/a/..%2f..%2fb"):
            self.assertIsNotNone(path_problem(bad), bad)
        for ok in ("/", "/a/b/", "/api/v3/core/users/", "/nodes/x/tasks/UPID%3Apve%3A0001%3Avzdump%3A112%3Alab%40pve%21lab%3A/log",
                   "/api/views/search/65a1b2", "/api/users/jo%20doe/groups/Homelab%20Admins", "/Items/abc/Refresh"):
            self.assertIsNone(path_problem(ok), ok)

    def test_non_canonical_ids_hit_the_stricter_route(self):
        m = validate(v2({"id": "m1", "name": "M", "backend": {"url": "http://x"}, "routes": [
            {"method": "POST", "path": "/api/machines/40/**", "owner_only": True},
            {"method": "POST", "path": "/api/machines/*/system", "min": "admin"},
            {"method": "GET", "path": "/api/machines/40/commands", "owner_only": True, "secret": True},
            {"method": "GET", "path": "/api/machines/*/commands"},
            {"method": "POST", "path": "/Users/*/Policy", "owner_only": True},
            {"method": "POST", "path": "/**", "min": "admin"}]}))
        admin = {"username": "w", "role": "admin"}
        f = lambda meth, p: Registry.permission(Registry.find_route(m, meth, p), admin)  # noqa: E731
        self.assertEqual(f("POST", "/api/machines/41/system"), "yes")
        for p in ("/api/machines/40/system", "/api/machines/040/system", "/api/machines/+40/system",
                  "/api/machines/4_0/system", "/api/machines/%D9%A4%D9%A0/system", "/api/machines/%2B40/system"):
            self.assertEqual(f("POST", p), "ask", p)
        self.assertEqual(f("GET", "/api/machines/0040/commands"), "ask")  # secret: admins ask even to read
        self.assertEqual(f("GET", "/api/machines/41/commands"), "yes")
        self.assertEqual(f("POST", "/users/x/policy"), "ask")  # .NET routes ignore case
        self.assertEqual(f("POST", "/Users/x/Policy;v=1"), "ask")
        self.assertEqual(f("POST", "/Items/x/Refresh"), "yes")

    def test_body_rules(self):
        r = validate(v2({"id": "m1", "name": "M", "backend": {"url": "http://x"}, "routes": [
            {"method": "POST", "path": "/cmd", "body_allow": {"name": ["CheckHealth"]}},
            {"method": "PUT", "path": "/cfg", "body_keys": ["cores", "memory"]}]}))["routes"]
        cmd, cfg = r
        self.assertTrue(Registry.body_ok(cmd, b'{"name": "CheckHealth", "x": 1}'))
        self.assertTrue(Registry.body_ok(cmd, b'{"Name": "CheckHealth"}'))
        self.assertFalse(Registry.body_ok(cmd, b'{"name": "CheckHealth", "Name": "ResetApiKey"}'))  # last one wins in .NET
        self.assertFalse(Registry.body_ok(cmd, b'{"name": "CheckHealth", "name": "ResetApiKey"}'))
        self.assertFalse(Registry.body_ok(cmd, '{"name": "CheckHealth"}'.encode("utf-16")))
        self.assertFalse(Registry.body_ok(cmd, b'{"name": ["CheckHealth"]}'))
        self.assertTrue(Registry.body_ok(cfg, b'{"cores": 2}'))
        self.assertFalse(Registry.body_ok(cfg, b'{"cores": 2, "hookscript": "local:snippets/x.pl"}'))
        self.assertFalse(Registry.body_ok(cfg, b'{"cores": 2, "Cores": 64}'))
        with self.assertRaises(ManifestError):
            validate(v2({"id": "m2", "name": "M", "backend": {"url": "http://x"}, "routes": [{"method": "PUT", "path": "/x", "body_keys": []}]}))
        with self.assertRaises(ManifestError):
            validate(v2({"id": "m2", "name": "M", "backend": {"url": "http://x"}, "routes": [{"method": "PUT", "path": "/x", "max_body": 1 << 30}]}))

    def test_backend_errors_read_like_advice(self):
        """Step-20 finding 15: a self-signed certificate says what to do, not a Python repr."""
        import ssl, urllib.error
        from lab.health import friendly_error
        e = urllib.error.URLError(ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"))
        self.assertIn("turn off Verify TLS", friendly_error(e))
        self.assertIn("connection refused", friendly_error(urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))))
        self.assertIn("timed out", friendly_error(TimeoutError("timed out")))

    def test_proxmox_backup_needs_a_configured_storage(self):
        """No default backup storage (step-20 finding 7): until the owner names one, 'back up now' matches nothing."""
        reg = Registry(os.path.join(ROOT, "modules"))
        reg.apply(overrides={}, config={"proxmox": {"url": "https://pve.example:8006", "api_token": "<set>", "verify_tls": False}})
        dump = Registry.find_route(reg.get("proxmox"), "POST", "/nodes/pve1/vzdump")
        self.assertFalse(Registry.body_ok(dump, b'{"vmid": "104", "storage": "pbs", "mode": "snapshot"}'))
        self.assertFalse(Registry.body_ok(dump, b'{"vmid": "104", "storage": "", "mode": "snapshot"}'))

    def test_guacamole_console_routes(self):
        """Consoles: open = admin+ (the connector wants a grant from admins), grant = owner-only (admins: approval),
        guests can't use the module; _protect makes a machine's open owner-only (admins: ask → no window)."""
        reg = Registry(os.path.join(ROOT, "modules"))
        reg.apply(overrides={"guacamole": {"_protect": ["/api/open/19/**"]}},
                  config={"guacamole": {"url": "http://guac.example:8080", "username": "svc", "password": "<set>"}})
        m = reg.get("guacamole")
        admin, owner = {"username": "w", "role": "admin"}, {"username": "o", "role": "owner"}
        perm = lambda meth, p, u: Registry.permission(Registry.find_route(m, meth, p), u)  # noqa: E731
        self.assertEqual(perm("POST", "/api/open/27/web", admin), "yes")
        self.assertEqual(perm("POST", "/api/open/19/workstation", admin), "ask")
        self.assertEqual(perm("POST", "/api/open/019/workstation", admin), "ask")  # canonical form
        self.assertEqual(perm("POST", "/api/open/19/workstation", owner), "yes")
        self.assertEqual(perm("POST", "/api/grant/27/web", admin), "ask")
        self.assertEqual(perm("POST", "/api/grant/27/web", owner), "yes")
        self.assertEqual(perm("POST", "/api/sessions/revoke", admin), "ask")
        self.assertIsNone(Registry.find_route(m, "POST", "/api/open/27"))        # both segments
        self.assertIsNone(Registry.find_route(m, "GET", "/api/open/27/web"))
        self.assertFalse(reg.can_use(m, {"username": "g", "role": "guest", "groups": ["lab-admins", "cdn-admins"]}))
        self.assertFalse(Registry.query_ok(Registry.find_route(m, "POST", "/api/open/27/web"), "x=1"))

    def test_real_manifests_tightened(self):
        reg = Registry(os.path.join(ROOT, "modules"))
        # proxmox is manifest v2: its backend and workstation/vault/authentik protection come from THIS installation's
        # config + _protect setting (as on the live gateway), not from the manifest
        # manage (v2 too): the workstation machine (#40) is a _protect pattern; its command history is owner-only+secret for every machine
        reg.apply(overrides={"proxmox": {"_protect": ["/nodes/*/lxc/112/**", "/nodes/*/lxc/109/**", "/nodes/*/lxc/106/**"],
                                         "backup_storage": "pbs"},
                             "manage": {"_protect": ["/api/machines/40/**", "GET /api/machines/40/commands"]}},
                  config={"proxmox": {"url": "https://pve.example:8006", "api_token": "<set>", "verify_tls": False},
                          "manage": {"url": "http://manage.example:8090"}})
        admin = {"username": "w", "role": "admin"}
        perm = lambda mid, meth, p: Registry.permission(Registry.find_route(reg.get(mid), meth, p), admin)  # noqa: E731
        if "manage" in reg.modules:  # manage is a private module; present only in the original lab's tree
            self.assertEqual(perm("manage", "POST", "/api/machines/040/system"), "ask")
            self.assertEqual(perm("manage", "GET", "/api/machines/040/commands"), "ask")
            self.assertEqual(perm("manage", "GET", "/api/machines/41/commands"), "yes")  # only #40's history is protected
        self.assertEqual(perm("proxmox", "POST", "/nodes/pve1/lxc/0112/status/stop"), "ask")
        self.assertEqual(perm("proxmox", "PUT", "/nodes/pve1/lxc/109/config"), "ask")
        self.assertEqual(perm("proxmox", "POST", "/nodes/pve1/lxc/113/status/stop"), "yes")
        self.assertEqual(reg.get("proxmox")["backend"]["url"], "https://pve.example:8006/api2/json")
        self.assertFalse(reg.get("proxmox")["backend"]["tls_verify"])
        self.assertEqual(perm("npm", "GET", "/api/hosts/3/advanced"), "ask")
        cfg = Registry.find_route(reg.get("proxmox"), "PUT", "/nodes/pve1/qemu/101/config")
        self.assertTrue(Registry.body_ok(cfg, b'{"cores": 2, "digest": "x"}'))
        self.assertFalse(Registry.body_ok(cfg, b'{"hookscript": "local:snippets/x.pl"}'))
        dump = Registry.find_route(reg.get("proxmox"), "POST", "/nodes/pve1/vzdump")
        self.assertTrue(Registry.body_ok(dump, b'{"vmid": "104", "storage": "pbs", "mode": "snapshot", "notes-template": "x"}'))
        self.assertFalse(Registry.body_ok(dump, b'{"vmid": "104", "storage": "local", "dumpdir": "/tmp"}'))
        self.assertFalse(Registry.body_ok(dump, b'{"vmid": "104", "storage": "local", "mode": "snapshot"}'))  # not the configured storage
        # mode stop/suspend would stop workstation (owner-only to stop) through "back up now"; the UI only sends snapshot
        self.assertFalse(Registry.body_ok(dump, b'{"vmid": "112", "storage": "pbs", "mode": "stop"}'))
        self.assertFalse(Registry.body_ok(dump, b'{"vmid": "112", "storage": "pbs", "mode": "suspend"}'))
        self.assertTrue(reg.get("proxmox")["backend"].get("decodes_slashes"))
        self.assertEqual(reg.path_problem(reg.get("proxmox"), "/nodes/pve1%2Flxc%2F112/status"), "encoded slash in path")

    # --- server -----------------------------------------------------------------------------------------------------
    def test_proxy_refuses_tricky_paths(self):
        SEEN.clear()
        for p in ("/api/m/demo/api/items/..%2Fsecret", "/api/m/demo/api/items/%2e%2e", "/api/m/demo/api//x",
                  "/api/m/demo/api/items/a%5Cb"):
            self.assertEqual(call("GET", p, token=self.owner)[0], 400, p)
        self.assertEqual(SEEN, [])
        s, r, _ = call("POST", "/api/m/demo/api/mach/040/act", {}, token=self.admin)
        self.assertEqual((s, r.get("approval")), (403, True))
        self.assertEqual(call("POST", "/api/m/demo/api/mach/41/act", {}, token=self.admin)[0], 200)

    def test_encoded_slash_refused_for_decoding_backends(self):
        # Proxmox turns %2F into "/" before routing: GET /lxc/116%2Fsnapshot%2F/config reached .../snapshot//config
        # (found 2026-11-14 testing lab's proxmox module on CT 116), so one `*` could cover several backend segments.
        from lab.registry import path_problem
        for bad in ("/nodes/a/lxc/116%2Fsnapshot%2F/config", "/nodes/a%2flxc%2f112/status", "/x/%252F/y"):
            self.assertIsNotNone(path_problem(bad, encoded_slash=False), bad)
            self.assertIsNone(path_problem(bad.replace("..", "")), bad)  # other backends: still fine
        upid = "/nodes/pve1/tasks/UPID%3Apve1%3A000C2C4C%3A00FBCC00%3A6AF8A32F%3Avzstart%3A116%3Alab%40pve%21lab%3A/status"
        self.assertIsNone(path_problem(upid, encoded_slash=False))
        SEEN.clear()
        self.assertEqual(call("GET", "/api/m/pvelike/nodes/pve1/lxc/116%2Fsnapshot%2F/config", token=self.admin)[0], 400)
        self.assertEqual(call("POST", "/api/m/pvelike/nodes/pve1%2Flxc%2F112%2Fstatus%2Fstop%2Fx/lxc/116/status/start", {},
                              token=self.admin)[0], 400)
        self.assertEqual(SEEN, [])
        self.assertEqual(call("GET", "/api/m/pvelike" + upid, token=self.admin)[0], 200)
        self.assertEqual(call("GET", "/api/m/demo/api/items/a%2Fb", token=self.owner)[0], 200)  # demo doesn't decode
        s, r, _ = call("POST", "/api/approvals", {"module": "pvelike", "method": "POST",
                                                   "path": "/nodes/pve1%2F/lxc/112/status/stop"}, token=self.admin)
        self.assertEqual(s, 400)
        with self.assertRaises(ManifestError):
            validate(v2({"id": "m3", "name": "M", "backend": {"url": "http://x", "decodes_slashes": "yes"}}))

    def test_body_keys_on_the_wire(self):
        SEEN.clear()
        self.assertEqual(call("PUT", "/api/m/demo/api/cfg", {"cores": 2}, token=self.admin)[0], 200)
        self.assertEqual(call("PUT", "/api/m/demo/api/cfg", {"cores": 2, "args": "-x"}, token=self.admin)[0], 403)
        self.assertEqual(call("PUT", "/api/m/demo/api/cfg?args=-x", {"cores": 2}, token=self.admin)[0], 403)
        self.assertEqual(len(SEEN), 1)

    def test_proxied_answers_are_sandboxed_and_secret_reads_audited(self):
        GW.app._secret_reads = {}
        before = len([a for a in GW.app.store.audit_list(500) if a["action"] == "read key"])
        s, _, h = call("GET", "/api/m/demo/api/key", token=self.owner)
        self.assertEqual(s, 200)
        self.assertIn("sandbox", h["Content-Security-Policy"])
        self.assertNotIn("sandbox", call("GET", "/", token=self.owner)[2]["Content-Security-Policy"])
        self.assertTrue(any(a["action"] == "read key" for a in GW.app.store.audit_list(20)))
        call("GET", "/api/m/demo/api/key", token=self.owner)  # again within the hour: not audited a second time
        self.assertEqual(len([a for a in GW.app.store.audit_list(500) if a["action"] == "read key"]), before + 1)

    def test_csrf_sec_fetch_site(self):
        self.assertEqual(call("POST", "/api/prefs", {"key": "k", "value": 1}, token=self.guest,
                              headers={"Sec-Fetch-Site": "same-site"})[0], 403)  # a sibling *.example.com page
        self.assertEqual(call("POST", "/api/prefs", {"key": "k", "value": 1}, token=self.guest,
                              headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(call("POST", "/api/prefs", {"key": "k", "value": 1}, token=self.guest,
                              headers={"Sec-Fetch-Site": "same-origin", "Origin": server.config.PUBLIC_URL})[0], 200)

    def test_bodies(self):
        self.assertEqual(call("POST", "/auth/local", headers={"Content-Length": "-1"})[0], 400)
        self.assertEqual(call("POST", "/auth/local", headers={"Content-Length": "100000"})[0], 413)
        self.assertEqual(call("POST", "/api/prefs", [1, 2], token=self.guest)[0], 400)

    def test_next_and_client_ip(self):
        for bad in ("//evil.com", "/\\evil.com", "/x\r\nSet-Cookie: a=1", "https://evil.com", "/x y"):
            self.assertIsNone(server.NEXT_RE.match(bad), bad)
        for ok in ("/", "/?approvals=1", "/#/map/workstation"):
            self.assertTrue(server.NEXT_RE.match(ok), ok)
        h = server.Handler.__new__(server.Handler)
        h.headers = {"X-Real-IP": "6.6.6.6"}
        h.client_address = ("192.0.2.99", 5555)
        old = (server.config.TRUST_PROXY, server.config.TRUSTED_PROXIES, server.config.PROXY_SECRET)
        try:
            server.config.TRUST_PROXY, server.config.TRUSTED_PROXIES = True, {"192.0.2.36", "127.0.0.1"}
            self.assertEqual(h.client_ip(), "192.0.2.99")  # not the proxy: its own header is ignored
            h.client_address = ("192.0.2.36", 5555)
            self.assertEqual(h.client_ip(), "6.6.6.6")
            # review L6: loopback is shared with the connectors (own users on this host) — listed or not, its headers
            # don't count without the proxy secret
            h.client_address = ("127.0.0.1", 5555)
            self.assertEqual(h.client_ip(), "127.0.0.1")
            server.config.PROXY_SECRET = "s3cret-proxy"
            self.assertEqual(h.client_ip(), "127.0.0.1")              # secret set, header missing
            h.headers = {"X-Real-IP": "6.6.6.6", "X-Lab-Proxy-Secret": "wrong"}
            self.assertEqual(h.client_ip(), "127.0.0.1")
            h.headers = {"X-Real-IP": "6.6.6.6", "X-Lab-Proxy-Secret": "s3cret-proxy"}
            self.assertEqual(h.client_ip(), "6.6.6.6")                # a local proxy with the secret
            h.client_address = ("192.0.2.36", 5555)
            h.headers = {"X-Real-IP": "6.6.6.6"}
            self.assertEqual(h.client_ip(), "192.0.2.36")              # with a secret set, every proxy must send it
            h.client_address = ("192.0.2.99", 5555)
            h.headers = {"X-Real-IP": "6.6.6.6", "X-Lab-Proxy-Secret": "s3cret-proxy"}
            self.assertEqual(h.client_ip(), "192.0.2.99")              # the secret alone does not make a proxy
        finally:
            server.config.TRUST_PROXY, server.config.TRUSTED_PROXIES, server.config.PROXY_SECRET = old

    def test_oidc_error_text_is_ours(self):
        from lab import oidc
        o = oidc.OIDC("https://auth.example/app/", "c", "s", "https://lab.example/auth/callback")
        with self.assertRaises(oidc.OIDCError) as e:
            o.finish({"error": "access_denied", "error_description": "Call +47 000 to unlock your account"})
        self.assertIn(str(e.exception), oidc.MESSAGES)

    def test_health_filtered_per_user(self):
        GW.app.health.state = {"demo": {"up": True, "ms": 1, "checked": 0, "error": ""},
                               "guesty": {"up": True, "ms": 1, "checked": 0, "error": ""}}
        try:
            self.assertEqual(set(call("GET", "/api/health", token=self.guest)[1]["modules"]), {"guesty"})
            self.assertEqual(set(call("GET", "/api/health", token=self.owner)[1]["modules"]), {"demo", "guesty"})
        finally:
            GW.app.health.state = {}

    def test_approvals_store_exactly_what_runs(self):
        ask = lambda **kw: call("POST", "/api/approvals", {"module": "demo", "method": "POST", **kw}, token=self.admin2)  # noqa: E731
        self.assertEqual(ask(path="/api/secret?x=1")[0], 400)
        self.assertEqual(ask(path="/api/mach/40/../41/act")[0], 400)
        self.assertEqual(ask(path="/api/secret", query="a=1 b")[0], 400)
        s, r, _ = ask(path="/api/mach/040/act", body={"pw": "hunter2"})
        self.assertEqual(s, 200)
        aid = r["approval"]["id"]
        mine = {a["id"]: a for a in call("GET", "/api/approvals", token=self.admin2)[1]["approvals"]}
        other = {a["id"]: a for a in call("GET", "/api/approvals", token=self.admin)[1]["approvals"]}
        own = {a["id"]: a for a in call("GET", "/api/approvals", token=self.owner)[1]["approvals"]}
        self.assertIn("hunter2", mine[aid]["body"])
        self.assertIsNone(other[aid]["body"])  # another admin: global reader, but not of what someone typed
        self.assertIn("hunter2", own[aid]["body"])
        call("POST", f"/api/approvals/{aid}/cancel", {}, token=self.admin2)

    def test_old_approval_bodies_purged(self):
        """Review L3: request and result bodies of decided approvals go after 30 days (the row stays)."""
        st = GW.app.store
        old = st.add_approval("someone", "demo", "POST", "/api/x", "", '{"pw": "typed-secret"}', "l", "r", 24)
        new = st.add_approval("someone", "demo", "POST", "/api/x", "", '{"pw": "fresh-secret"}', "l", "r", 24)
        pend = st.add_approval("someone", "demo", "POST", "/api/x", "", '{"pw": "waiting"}', "l", "r", 24)
        for a in (old, new):
            st.decide_approval(a["id"], "approved", "boss", 200, '{"key": "answer-secret"}')
        long_ago = time.time() - 31 * 86400
        st.x("UPDATE approvals SET created=?, decided_at=? WHERE id=?", (long_ago, long_ago, old["id"]))
        st.x("UPDATE approvals SET created=? WHERE id=?", (long_ago, pend["id"]))   # pending: never touched
        st.prune()
        o, n, p = st.approval(old["id"]), st.approval(new["id"]), st.approval(pend["id"])
        self.assertEqual((o["status"], o["body"], o["result_body"], o["decided_by"]), ("approved", "", None, "boss"))
        self.assertIn("fresh-secret", n["body"])
        self.assertIn("answer-secret", n["result_body"])
        self.assertIn("waiting", p["body"])
        st.x("DELETE FROM approvals WHERE id IN (?,?,?)", (old["id"], new["id"], pend["id"]))

    def test_pending_asks_capped(self):
        tok = session("asker", ["lab-admins"])
        codes = [call("POST", "/api/approvals", {"module": "demo", "method": "POST", "path": "/api/secret"}, token=tok)[0]
                 for _ in range(server.MAX_PENDING_ASKS + 1)]
        self.assertEqual(codes[-1], 429)
        self.assertTrue(all(c == 200 for c in codes[:-1]))

    def test_slow_headers_are_cut(self):
        import socket as so
        old = server.HEAD_SECONDS
        server.HEAD_SECONDS = 1
        try:
            s = so.create_connection(("127.0.0.1", PORT), timeout=10)
            s.sendall(b"GET /healthz HTTP/1.1\r\nX-Slow: ")
            t0 = time.time()
            self.assertEqual(s.recv(100), b"")  # closed by the reaper, not after the 30 s socket timeout
            self.assertLess(time.time() - t0, 6)
            s.close()
        finally:
            server.HEAD_SECONDS = old
        self.assertEqual(call("GET", "/healthz")[0], 200)


class QueryKeysAndBodyLists(unittest.TestCase):
    """query_keys / body_list (2026-11-14, jellyfin module): .NET APIs take most write parameters in the query string
    (Jellyfin: POST /Library/VirtualFolders?name=…&collectionType=…) and some bodies are arrays (task triggers)."""

    @classmethod
    def setUpClass(cls):
        cls.owner = session("owner", ["lab-owners", "homelab-admins"])
        cls.admin = session("admin", ["lab-admins"])

    def test_query_ok(self):
        r = validate(v2({"id": "m1", "name": "M", "backend": {"url": "http://x"}, "routes": [
            {"method": "POST", "path": "/lib", "query_keys": ["name", "refreshLibrary"], "body_keys": ["LibraryOptions"]},
            {"method": "POST", "path": "/noq", "query_keys": []},
            {"method": "PUT", "path": "/cfg", "body_keys": ["cores"]},
            {"method": "POST", "path": "/free"}]}))["routes"]
        lib, noq, cfg, free = r
        q = Registry.query_ok
        self.assertTrue(q(lib, "name=Movies&refreshLibrary=true"))
        self.assertTrue(q(lib, "NAME=a%20b&RefreshLibrary="))  # .NET binds names case-insensitively
        self.assertTrue(q(lib, ""))
        self.assertFalse(q(lib, "name=a&collectionType=movies"))
        self.assertFalse(q(lib, "name=a&LibraryOptions=x"))
        self.assertFalse(q(lib, "name"))  # not k=v
        self.assertTrue(q(lib, "name=a;paths=/etc"))  # ';' is no separator (not here, not in .NET): one value of "name"
        self.assertFalse(q(lib, "x;name=a"))
        self.assertFalse(q(lib, "na%6De=x&paths=/etc"))
        self.assertTrue(q(noq, ""))
        self.assertFalse(q(noq, "a=1"))
        self.assertFalse(q(cfg, "cores=2"))  # body-restricted without query_keys: no query (unchanged rule)
        self.assertTrue(q(free, "anything=1"))  # no rules: passed on as before
        for bad in ({"query_keys": "name"}, {"query_keys": [""]}, {"query_keys": ["Name"], "body_keys": ["name"]},
                    {"body_list": True}, {"body_list": "yes", "body_keys": ["a"]}):
            with self.assertRaises(ManifestError, msg=bad):
                validate(v2({"id": "m2", "name": "M", "backend": {"url": "http://x"}, "routes": [{"method": "POST", "path": "/x", **bad}]}))

    def test_body_list(self):
        trig = validate(v2({"id": "m1", "name": "M", "backend": {"url": "http://x"}, "routes": [
            {"method": "POST", "path": "/t", "body_list": True, "body_keys": ["Type", "IntervalTicks"],
             "body_allow": {"Type": ["DailyTrigger", "IntervalTrigger"]}}]}))["routes"][0]
        ok = Registry.body_ok
        self.assertTrue(ok(trig, b'[{"Type": "IntervalTrigger", "IntervalTicks": 864000000000}, {"Type": "DailyTrigger"}]'))
        self.assertTrue(ok(trig, b"[]"))
        self.assertTrue(ok(trig, b""))
        self.assertFalse(ok(trig, b'{"Type": "DailyTrigger"}'))  # an object where a list belongs
        self.assertFalse(ok(trig, b'[{"Type": "DailyTrigger"}, 1]'))
        self.assertFalse(ok(trig, b'[{"Type": "DailyTrigger", "Script": "x"}]'))
        self.assertFalse(ok(trig, b'[{"Type": "BootTrigger"}]'))
        self.assertFalse(ok(trig, b'[{"Type": "DailyTrigger", "type": "IntervalTrigger"}]'))
        self.assertFalse(ok(trig, json.dumps([{"Type": "DailyTrigger"}] * 101).encode()))

    def test_on_the_wire(self):
        SEEN.clear()
        good = {"LibraryOptions": {"Enabled": True}}
        self.assertEqual(call("POST", "/api/m/demo/api/lib?name=Test&refreshLibrary=false", good, token=self.admin)[0], 200)
        self.assertEqual(SEEN[-1][1], "/api/lib?name=Test&refreshLibrary=false")  # the query reaches the backend as sent
        self.assertEqual(call("POST", "/api/m/demo/api/lib?name=Test&paths=/etc", good, token=self.admin)[0], 403)
        self.assertEqual(call("POST", "/api/m/demo/api/lib?name=Test", {**good, "x": 1}, token=self.admin)[0], 403)
        self.assertEqual(call("POST", "/api/m/demo/api/noq", {}, token=self.admin)[0], 200)
        self.assertEqual(call("POST", "/api/m/demo/api/noq?x=1", {}, token=self.admin)[0], 403)
        self.assertEqual(call("POST", "/api/m/demo/api/trig", [{"Type": "DailyTrigger"}], token=self.admin)[0], 200)
        self.assertEqual(call("POST", "/api/m/demo/api/trig", [{"Type": "Nope"}], token=self.admin)[0], 403)
        self.assertEqual(len(SEEN), 3)
        self.assertTrue(any(a["target"] == "POST /api/noq" and a["result"] == "query" for a in GW.app.store.audit_list(30)))

    def test_approvals_check_query_keys(self):
        ask = lambda **kw: call("POST", "/api/approvals", {"module": "demo", "method": "POST", "path": "/api/pw", **kw},  # noqa: E731
                                token=self.admin)
        self.assertEqual(ask(query="userId=abc&isAdmin=true", body={"NewPw": "x"})[0], 403)
        self.assertEqual(ask(query="userId=abc", body={"NewPw": "x", "CurrentPw": "y"})[0], 403)
        s, r, _ = ask(query="userId=abc", body={"NewPw": "x"})
        self.assertEqual(s, 200)
        SEEN.clear()
        s, r, _ = call("POST", f"/api/approvals/{r['approval']['id']}/approve", {}, token=self.owner)
        self.assertEqual((s, r["approval"]["status"]), (200, "done"))
        self.assertEqual(SEEN[-1][1], "/api/pw?userId=abc")

    def test_real_jellyfin_manifest(self):
        m = Registry(os.path.join(ROOT, "modules")).get("jellyfin")
        admin, owner = {"username": "w", "role": "admin"}, {"username": "e", "role": "owner"}
        rt = lambda meth, p: Registry.find_route(m, meth, p)  # noqa: E731
        perm = lambda meth, p, u=admin: Registry.permission(rt(meth, p), u)  # noqa: E731
        # identity, secrets, code sources and shutdown: owner (admins ask, even to read API keys)
        for meth, p in (("GET", "/Auth/Keys"), ("POST", "/Auth/Keys"), ("DELETE", "/Auth/Keys/abc"), ("POST", "/System/Shutdown"),
                        ("POST", "/Repositories"), ("POST", "/Users/New"), ("POST", "/Users/abc/Policy"),
                        ("POST", "/Users/Password"), ("DELETE", "/Users/abc")):
            self.assertEqual(perm(meth, p), "ask", (meth, p))
            self.assertEqual(perm(meth, p, owner), "yes", (meth, p))
        for meth, p in (("POST", "/System/Restart"), ("POST", "/Library/VirtualFolders"), ("DELETE", "/Items/abc"),
                        ("POST", "/Items/abc"), ("POST", "/Items/RemoteSearch/Movie"), ("POST", "/Plugins/a/1.0/Disable"),
                        ("POST", "/Packages/Installed/Webhook"), ("DELETE", "/Devices"), ("POST", "/Sessions/s1/Playing/Stop"),
                        ("POST", "/ScheduledTasks/t1/Triggers"), ("POST", "/System/Configuration/encoding"), ("GET", "/Devices")):
            self.assertEqual(perm(meth, p), "yes", (meth, p))
        self.assertNotEqual(perm("POST", "/users/ABC/policy"), "yes")
        self.assertIsNone(rt("POST", "/Sessions/s1/Playing/Seek"))
        self.assertIsNone(rt("POST", "/System/Configuration"))  # only the encoding section
        self.assertIsNone(rt("GET", "/Plugins/abc/Configuration"))  # plugin settings can hold their own secrets
        self.assertEqual(rt("POST", "/Items/RemoteSearch/Movie")["label"], "jellyfin: identify (search movie)")
        q, b = Registry.query_ok, Registry.body_ok
        lib = rt("POST", "/Library/VirtualFolders")
        self.assertTrue(q(lib, "name=Test&collectionType=movies&paths=%2Fsrv%2Fx&refreshLibrary=true"))
        self.assertTrue(b(lib, b'{"LibraryOptions": {"EnableRealtimeMonitor": true}}'))
        self.assertFalse(q(rt("POST", "/Packages/Installed/x"), "version=1.0&repositoryUrl=https://evil.example/manifest.json"))
        self.assertFalse(q(rt("POST", "/Items/x/Refresh"), "Recursive=true&metadataRefreshMode=FullRefresh&x=1"))
        self.assertTrue(q(rt("POST", "/Items/x/Refresh"), "metadataRefreshMode=FullRefresh&replaceAllImages=false"))
        enc = rt("POST", "/System/Configuration/encoding")
        self.assertTrue(b(enc, b'{"HardwareAccelerationType": "nvenc", "EncoderAppPathDisplay": "/usr/lib/jellyfin-ffmpeg/ffmpeg"}'))
        self.assertFalse(b(enc, b'{"HardwareAccelerationType": "nvenc", "EncoderAppPath": "/tmp/evil"}'))
        pol = rt("POST", "/Users/abc/Policy")
        self.assertTrue(b(pol, b'{"IsDisabled": false, "MaxParentalRating": 12, "RemoteClientBitrateLimit": 8000000}'))
        self.assertFalse(b(pol, b'{"IsDisabled": false, "Password": "x"}'))
        trig = rt("POST", "/ScheduledTasks/abc/Triggers")
        self.assertTrue(b(trig, b'[{"Type": "DailyTrigger", "TimeOfDayTicks": 72000000000}]'))
        self.assertFalse(b(trig, b'[{"Type": "DailyTrigger", "Command": "x"}]'))
        for r in m["routes"]:  # every write says exactly which query parameters it takes
            if r["method"] != "GET":
                self.assertIsInstance(r.get("query_keys"), list, r["path"])


if __name__ == "__main__":
    unittest.main()


class SchemaMigrations(unittest.TestCase):
    def test_versions(self):
        import sqlite3
        from lab.store import Store, SchemaTooNew
        c = sqlite3.connect(":memory:", isolation_level=None)
        c.execute("CREATE TABLE t (a INTEGER)")
        self.assertEqual(Store.migrate(c, []), 1)  # a pre-versioning database = baseline v1
        steps = [(2, "ALTER TABLE t ADD COLUMN b TEXT"), (3, ["CREATE TABLE u (x)", "INSERT INTO u VALUES (1)"])]
        self.assertEqual(Store.migrate(c, steps), 3)
        self.assertEqual(Store.migrate(c, steps), 3)  # idempotent
        self.assertEqual(c.execute("SELECT x FROM u").fetchone()[0], 1)
        with self.assertRaises(SchemaTooNew):  # older code on a newer database refuses to start
            Store.migrate(c, steps[:1])
        bad = steps + [(4, "ALTER TABLE nope ADD COLUMN z")]
        with self.assertRaises(sqlite3.OperationalError):
            Store.migrate(c, bad)
        self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 3)  # a failed step leaves the old version



class ManifestV2(unittest.TestCase):
    BASE = {"manifest": 2, "id": "m2", "name": "M2", "version": "1.0.0", "kind": "community", "category": "media",
            "config": {"fields": [{"key": "url", "type": "url", "label": "URL", "required": True},
                                  {"key": "key", "type": "secret", "label": "key", "required": True}]},
            "backend": {"url": "{url}/api", "auth": {"type": "header", "name": "X-Api-Key", "secret": "key"}},
            "routes": [{"method": "GET", "path": "/x"}, {"method": "POST", "path": "/y", "min": "admin", "label": "y"}]}

    def m(self, **change):
        m = json.loads(json.dumps(self.BASE))
        for k, v in change.items():
            m[k] = v
        return m

    def test_strict(self):
        validate(self.m())
        bad = [self.m(owner_only=True),                                                    # unknown top-level key
               self.m(routes=[{"method": "POST", "path": "/y", "label": "y"}]),            # write without min/owner_only
               self.m(routes=[{"method": "POST", "path": "/y", "min": "admin"}]),          # write without label
               self.m(routes=[{"method": "GET", "path": "/y", "owner-only": True}]),       # typo'd key
               self.m(routes=[{"method": "GET", "path": "/y", "secret": True}]),           # secret without owner_only
               self.m(version="1"), self.m(kind="mine"), self.m(category="stuff"),
               self.m(backend={"url": "{nope}/api"}),                                     # placeholder not a field
               self.m(backend={"url": "{url}", "auth": {"type": "bearer", "secret": "url"}}),  # auth from a non-secret
               self.m(backend={"url": "{url}", "auth": {"type": "bearer", "file": "x.token"}}),  # no files in v2
               self.m(backend={"url": "{url}", "headers": {"Authorization": "x"}}),
               self.m(config={"fields": [{"key": "k", "type": "secret", "default": "x", "label": "k"}]})]
        for b in bad:
            with self.assertRaises(ManifestError, msg=json.dumps(b)[:200]):
                validate(b)
        # v1 manifests are no longer accepted (removed 2026-11-15): a clear error, not a half-loaded module
        with self.assertRaises(ManifestError):
            validate({"id": "old", "name": "Old", "routes": []})
        validate(v2({"id": "old", "name": "Old", "category": "media", "routes": []}))
        with self.assertRaises(ManifestError):
            validate(v2({"id": "old", "name": "Old", "category": "nope"}))

    def test_validate_json_and_placeholders(self):
        m = self.m(config={"fields": [{"key": "url", "type": "url", "label": "u", "required": True},
                                      {"key": "key", "type": "secret", "label": "k", "required": True},
                                      {"key": "store", "type": "text", "label": "s", "default": "pbs"}],
                           "validate": {"path": "/whoami", "json": {"status": "ok"}}},
                   routes=[{"method": "POST", "path": "/dump", "min": "admin", "label": "dump",
                            "body_allow": {"storage": ["{store}"]}}])
        validate(m)
        with self.assertRaises(ManifestError):
            validate(self.m(routes=[{"method": "POST", "path": "/d", "min": "admin", "label": "d", "body_allow": {"s": ["{nope}"]}}]))
        with self.assertRaises(ManifestError):
            validate(self.m(config={"fields": [], "validate": {"path": "/w", "json": {"a": [1]}}}))
        from lab.manifest2 import render_routes
        r = render_routes(m, {"url": "http://x", "key": "<set>", "store": "backup1"})[0]
        self.assertEqual(r["body_allow"], {"storage": ["backup1"]})
        self.assertEqual(render_routes(m, {})[0]["body_allow"], {"storage": ["pbs"]})  # the field's default

    def test_basic_fixed_password_and_path_placeholders(self):
        validate(self.m(backend={"url": "{url}", "auth": {"type": "basic", "secret": "key", "password": "token"}}))
        for bad in ({"type": "basic", "secret": "key"}, {"type": "basic", "secret": "key", "password": ""},
                    {"type": "bearer", "secret": "key", "password": "x"}):
            with self.assertRaises(ManifestError, msg=bad):
                validate(self.m(backend={"url": "{url}", "auth": bad}))
        from lab.proxy import Keys
        k = Keys("/nonexistent", lookup=lambda m, f: {"key": "TOK"}.get(f))
        import base64
        _, hdr = k.credentials({"id": "m2", "backend": {"auth": {"type": "basic", "secret": "key", "password": "token"}}})
        self.assertEqual(base64.b64decode(hdr["Authorization"][6:]), b"TOK:token")
        # a whole path segment from a setting
        m = self.m(settings=[{"key": "store", "type": "text", "default": "main"}],
                   routes=[{"method": "DELETE", "path": "/ds/{store}/snaps", "min": "admin", "label": "del"}])
        validate(m)
        for bad in ("/ds/x{store}/s", "/ds/{nope}/s"):
            with self.assertRaises(ManifestError, msg=bad):
                validate(self.m(settings=[{"key": "store", "type": "text"}], routes=[{"method": "GET", "path": bad}]))
        from lab.manifest2 import render_routes
        r = render_routes(m, {"store": "homelab"})[0]
        self.assertTrue(r["_re"].match("/ds/homelab/snaps") and not r["_re"].match("/ds/other/snaps"))
        self.assertTrue(render_routes(m, {})[0]["_re"].match("/ds/main/snaps"))          # the default
        self.assertFalse(render_routes(m, {"store": "../x"})[0]["_re"].match("/ds/../x/snaps"))  # unsafe → never

    def test_secretbox(self):
        from lab.secretbox import SecretBox, SecretError
        box = SecretBox(bytes(32))
        sealed = box.seal("mod", "token", "hunter2-ÆØÅ")
        self.assertTrue(sealed.startswith("v1:"))
        self.assertNotIn("hunter2", sealed)
        self.assertEqual(box.open("mod", "token", sealed), "hunter2-ÆØÅ")
        self.assertNotEqual(sealed, box.seal("mod", "token", "hunter2-ÆØÅ"))  # random nonce
        for args in (("other", "token", sealed), ("mod", "other", sealed), ("mod", "token", sealed[:-4] + "AAAA")):
            with self.assertRaises(SecretError):
                box.open(*args)
        with self.assertRaises(SecretError):
            SecretBox(bytes(range(32))).open("mod", "token", sealed)  # another master key

    def test_config_flow(self):
        owner = session("owner", ["lab-owners", "homelab-admins"])
        admin = session("admin", ["lab-admins"])
        url = f"http://127.0.0.1:{BACKEND.server_address[1]}"
        try:
            # not configured: nobody can use it, owner sees what's missing
            self.assertNotIn("cfgmod", {m["id"] for m in call("GET", "/api/registry", token=owner)[1]["modules"]})
            self.assertEqual(call("GET", "/api/m/cfgmod/api/v3/core/users", token=owner)[0], 404)
            self.assertEqual(call("GET", "/api/config/cfgmod", token=admin)[0], 403)
            s, v, _ = call("GET", "/api/config/cfgmod", token=owner)
            self.assertEqual((s, v["needsSetup"], v["fields"][1]["set"]), (200, True, False))
            settings = {m["id"]: m for m in call("GET", "/api/settings", token=owner)[1]["modules"]}
            self.assertTrue(settings["cfgmod"]["needsSetup"])
            self.assertEqual(settings["cfgmod"]["missing"], ["url", "token"])
            # bad input is refused before anything is tried
            self.assertEqual(call("POST", "/api/config/cfgmod", {"values": {"url": "ftp://x"}}, token=owner)[0], 400)
            self.assertEqual(call("POST", "/api/config/cfgmod", {"values": {"url": "http://u:p@h"}}, token=owner)[0], 400)
            self.assertEqual(call("POST", "/api/config/cfgmod", {"values": {"nope": 1}}, token=owner)[0], 400)
            # the test call uses the candidate values; a wrong token fails it and nothing is saved
            s, r, _ = call("POST", "/api/config/cfgmod/test", {"values": {"url": url, "token": "wrong"}}, token=owner)
            self.assertEqual((s, r["ok"], r["test"]["status"]), (200, False, 401))
            s, r, _ = call("POST", "/api/config/cfgmod", {"values": {"url": url, "token": "wrong"}}, token=owner)
            self.assertEqual(s, 422)
            self.assertTrue(call("GET", "/api/config/cfgmod", token=owner)[1]["needsSetup"])
            s, r, _ = call("POST", "/api/config/cfgmod", {"values": {"url": url + "/", "token": "s3cret-token"}}, token=owner)
            self.assertEqual((s, r["test"]["ok"], r["needsSetup"]), (200, True, False))
            self.assertNotIn("s3cret-token", json.dumps(r))
            stored = GW.app.store.module_config("cfgmod")
            self.assertTrue(stored["token"][0].startswith("v1:") and stored["token"][1])
            self.assertNotIn("s3cret", stored["token"][0])
            self.assertEqual(stored["url"][0], url)  # trailing slash trimmed
            self.assertNotIn("s3cret", json.dumps(GW.app.store.audit_list(5)))
            # configured: the proxy uses the opened secret; the browser never sees it
            s, r, _ = call("GET", "/api/m/cfgmod/api/v3/core/users", token=owner)
            self.assertEqual((s, r["you"]), (200, "bearer"))
            v = call("GET", "/api/config/cfgmod", token=owner)[1]
            self.assertTrue(v["fields"][1]["set"])
            self.assertNotIn("value", v["fields"][1])
            self.assertIn("cfgmod", {m["id"] for m in call("GET", "/api/registry", token=admin)[1]["modules"]})
            # keeping the stored secret: post only the url
            s, r, _ = call("POST", "/api/config/cfgmod", {"values": {"url": url}}, token=owner)
            self.assertEqual((s, r["test"]["ok"]), (200, True))
            # a stored secret never follows a new address (review M4): test and save both refuse until it is retyped
            for path in ("/api/config/cfgmod/test", "/api/config/cfgmod"):
                s, r, _ = call("POST", path, {"values": {"url": "http://127.0.0.1:9"}}, token=owner)
                self.assertEqual(s, 400, path)
                self.assertIn("token", r["error"])
        finally:  # back to unconfigured (other tests count the owner's modules)
            for k in ("url", "token", "verify"):
                GW.app.store.set_module_config("cfgmod", k, None)
            GW.app.reload_config()

    def test_protect_policy(self):
        owner = session("owner", ["lab-owners", "homelab-admins"])
        admin = session("admin", ["lab-admins"])
        self.assertEqual(call("POST", "/api/m/demo/api/mach/5/act", token=admin)[0], 200)
        try:
            self.assertEqual(call("POST", "/api/settings/module", {"module": "demo", "values": {"_protect": ["/api/mach/[x"]}},
                                  token=owner)[0], 200)  # "[x" is a literal segment: a valid pattern
            self.assertEqual(call("POST", "/api/settings/module", {"module": "demo", "values": {"_protect": ["no-slash"]}},
                                  token=owner)[0], 400)
            self.assertEqual(call("POST", "/api/settings/module", {"module": "demo", "values": {"_protect": ["/api/mach/5/**"]}},
                                  token=admin)[0], 403)
            self.assertEqual(call("POST", "/api/settings/module", {"module": "demo", "values": {"_protect": ["/api/mach/5/**"]}},
                                  token=owner)[0], 200)
            self.assertEqual(call("POST", "/api/m/demo/api/mach/5/act", token=admin)[0], 403)   # now owner-only here
            self.assertEqual(call("POST", "/api/m/demo/api/mach/05/act", token=admin)[0], 403)  # canonical form too
            self.assertEqual(call("POST", "/api/m/demo/api/mach/6/act", token=admin)[0], 200)
            self.assertEqual(call("POST", "/api/m/demo/api/mach/5/act", token=owner)[0], 200)
            self.assertEqual(call("POST", "/api/m/demo/api/mach/5/other", token=owner)[1]["error"], "not allowed")  # policy adds no routes
        finally:
            call("POST", "/api/settings/module", {"module": "demo", "values": {"_protect": None}}, token=owner)
        self.assertEqual(call("POST", "/api/m/demo/api/mach/5/act", token=admin)[0], 200)


class Requires(unittest.TestCase):
    """`requires` (module SDK, step 4): the peers a module may read through ctx.peer()/ctx.via(). Validated in v1 and
    v2 manifests and sent to the browser by visible(), which enforces it."""

    def test_validate(self):
        man = json.loads(json.dumps(ManifestV2.BASE))
        man["requires"] = ["proxmox", {"id": "unifi", "optional": True}]
        self.assertEqual(validate(man)["requires"], [{"id": "proxmox", "optional": False}, {"id": "unifi", "optional": True}])
        self.assertEqual(validate(v2({"id": "old", "name": "Old", "requires": ["drift"]}))["requires"],
                         [{"id": "drift", "optional": False}])
        self.assertEqual(validate(v2({"id": "old", "name": "Old"}))["requires"], [])
        for bad in (["Bad Id"], [{"id": "x", "optinal": True}], "drift", ["old"], ["a1", "a1"], ["*"]):
            with self.assertRaises(ManifestError, msg=repr(bad)):
                validate(v2({"id": "old", "name": "Old", "requires": bad}))
        # "*" only for a delegating connector (it reads every module as the user anyway)
        m = validate(v2({"id": "aiish", "name": "AI", "delegate": True, "backend": {"url": "http://127.0.0.1:8117"},
                      "requires": ["*"]}))
        self.assertEqual(m["requires"], [{"id": "*", "optional": False}])

    def test_visible_sends_requires(self):
        d = tempfile.mkdtemp(prefix="labreq-")
        try:
            for mid, man in (("hub", {"id": "hub", "name": "Hub", "requires": ["leaf", {"id": "gone", "optional": True}]}),
                             ("leaf", {"manifest": 2, "id": "leaf", "name": "Leaf", "version": "1.0.0", "kind": "community",
                                       "category": "tools"})):
                os.makedirs(os.path.join(d, mid))
                with open(os.path.join(d, mid, "manifest.json"), "w") as f:
                    json.dump(v2(man), f)
            reg = Registry(d)
            self.assertEqual(reg.errors, {})
            vis = {m["id"]: m for m in reg.visible({"username": "o", "role": "owner", "groups": []})}
            self.assertEqual(vis["hub"]["requires"], [{"id": "leaf", "optional": False}, {"id": "gone", "optional": True}])
            self.assertEqual((vis["hub"]["manifest"], vis["leaf"]["manifest"]), (2, 2))  # v1 is gone
            self.assertEqual(vis["leaf"]["requires"], [])
        finally:
            shutil.rmtree(d, ignore_errors=True)



class SpeedCacheAndEvents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = session("owner", ["lab-owners", "homelab-admins"])
        cls.admin = session("admin", ["lab-admins"])
        cls.guest = session("guest-one", ["cdn-admins"])

    def test_shared_cache(self):
        GW.app.cache.invalidate("third")
        n = len(SEEN)
        s1, _, h1 = call("GET", "/api/m/third/api/v3/core/users", token=self.admin)
        s2, b2, h2 = call("GET", "/api/m/third/api/v3/core/users", token=self.owner)  # another user: same entry
        self.assertEqual((s1, s2, h1["X-Lab-Cache"], h2["X-Lab-Cache"]), (200, 200, "miss", "hit"))
        self.assertEqual(len(SEEN), n + 1)
        self.assertEqual(b2["you"], "bearer")
        # a write through the gateway drops the module's entries
        self.assertEqual(call("PATCH", "/api/m/third/api/v3/core/users/5", {}, token=self.owner)[0], 200)
        self.assertEqual(call("GET", "/api/m/third/api/v3/core/users", token=self.admin)[2]["X-Lab-Cache"], "miss")
        # permission is still checked before the cache: a user without the module gets nothing from it
        self.assertIn(call("GET", "/api/m/third/api/v3/core/users", token=self.guest)[0], (403, 404))
        # own-backend modules (signed per user) are not cached by default
        self.assertNotIn("X-Lab-Cache", call("GET", "/api/m/demo/api/x", token=self.owner)[2])
        # secret routes never
        self.assertNotIn("X-Lab-Cache", call("GET", "/api/m/demo/api/key", token=self.owner)[2])

    def test_single_flight(self):
        from lab.cache import ProxyCache
        c, calls, started = ProxyCache(), [], threading.Event()

        def slow():
            calls.append(1)
            started.set()
            time.sleep(0.3)
            return 200, {}, b"x"
        out = []
        ts = [threading.Thread(target=lambda: out.append(c.get(("m", "/p", "", ""), 5, slow))) for _ in range(5)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(1 for _, hit in out if hit), 4)

    def _stream(self, token):
        import socket as so
        s = so.create_connection(("127.0.0.1", PORT), timeout=5)
        s.sendall(f"GET /api/events HTTP/1.0\r\nCookie: lab_session={token}\r\n\r\n".encode())
        buf = b""
        while b"\n\n" not in buf.split(b"\r\n\r\n", 1)[-1] or b"\r\n\r\n" not in buf:
            buf += s.recv(4096)
        self.assertIn(b"text/event-stream", buf)
        return s

    def _read_event(self, s, timeout=3):
        s.settimeout(timeout)
        buf = b""
        try:
            while b"data:" not in buf or not buf.rstrip().endswith(b"}"):
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        except OSError:
            pass
        return [json.loads(l[5:]) for l in buf.decode().splitlines() if l.startswith("data:")]

    def test_events(self):
        a, g = self._stream(self.admin), self._stream(self.guest)
        try:
            # streams don't hold pool threads: the test gateway has 4 workers, 6 open streams + normal requests work
            extra = [self._stream(self.owner) for _ in range(4)]
            self.assertEqual(call("GET", "/healthz")[0], 200)
            self.assertEqual(call("POST", "/api/m/demo/api/do", {}, token=self.admin)[0], 200)
            ev = self._read_event(a)
            self.assertIn({"t": "invalidate", "m": "demo"}, ev)
            self.assertEqual([e for e in self._read_event(g, 1) if e.get("m") == "demo"], [])  # guest can't use demo
            self.assertEqual(call("GET", "/api/events")[0], 401)  # not logged in
            for x in extra:
                x.close()
        finally:
            a.close()
            g.close()



class ProtectReadsAndBodies(unittest.TestCase):
    def setUp(self):
        self.owner = session("owner", ["lab-owners", "homelab-admins"])
        self.admin = session("admin", ["lab-admins"])

    def _set(self, value):
        return call("POST", "/api/settings/module", {"module": "demo", "values": {"_protect": value}}, token=self.owner)[0]

    def test_parse(self):
        from lab.registry import parse_protect
        self.assertEqual(parse_protect("/a/**")[0], ("POST", "PUT", "PATCH", "DELETE"))
        self.assertEqual(parse_protect("GET /a/b"), (("GET",), "/a/b", {}))
        self.assertEqual(parse_protect("post,delete /a numbers=ether2"), (("POST", "DELETE"), "/a", {"numbers": "ether2"}))
        for bad in ("", "FETCH /a", "GET", "GET a", "POST /a novalue", "POST /a/**/b"):
            with self.assertRaises(ManifestError, msg=bad):
                parse_protect(bad)

    def test_protected_read(self):
        try:
            self.assertEqual(call("GET", "/api/m/demo/api/items/5", token=self.admin)[0], 200)
            self.assertEqual(self._set(["GET /api/items/5"]), 200)
            s, b, _ = call("GET", "/api/m/demo/api/items/5", token=self.admin)
            self.assertEqual((s, b.get("approval")), (403, True))            # admins ask for this one read
            self.assertEqual(call("GET", "/api/m/demo/api/items/6", token=self.admin)[0], 200)   # not the others
            self.assertEqual(call("GET", "/api/m/demo/api/items/5", token=self.owner)[0], 200)
            self.assertEqual(self._set(["FETCH /x"]), 400)
        finally:
            self._set(None)

    def test_body_condition_bypasses_are_closed(self):
        """Security review 2026-11-15 M1: every variant of the protected value asks the owner."""
        from lab.registry import Registry
        m = GW.app.registry.get("demo")
        try:
            self.assertEqual(self._set(["PUT /api/cfg cores=64", "PUT /api/cfg flag=true", "PUT /api/cfg vm=112"]), 200)
            m = GW.app.registry.get("demo")
            hit = lambda body, q="", ct="application/json": bool(Registry.body_protected(m, "PUT", "/api/cfg", body, q, ct))  # noqa: E731
            self.assertTrue(hit(b"", "cores=64"))                          # in the query string
            self.assertTrue(hit(b'{"cores": 2, "Cores": 64}'))             # case-variant duplicate
            self.assertTrue(hit(b'{"cores": 2, "cores": 64}'))             # duplicate
            self.assertTrue(hit(b'{"flag": true}'))                        # JSON true vs "true"
            self.assertTrue(hit(b'{"vm": "0112"}') and hit(b'{"vm": 112.0}') and hit(b'{"vm": "112"}'))
            self.assertTrue(hit(b'{"cores": 2}', ct="application/x-www-form-urlencoded"))  # not read as JSON
            self.assertTrue(hit(b'{"cores": 2,'))                          # unparsable
            self.assertTrue(hit(b'[{"vm": 1}, {"vm": 112}]'))              # a list item
            self.assertFalse(hit(b'{"cores": 2, "vm": 113, "flag": false}'))
            s, b2, _ = call("PUT", "/api/m/demo/api/cfg?cores=64", {"cores": 2}, token=self.admin)
            self.assertEqual((s, b2.get("approval") if isinstance(b2, dict) else None), (403, True))
        finally:
            self._set(None)

    def test_protected_body_value(self):
        try:
            self.assertEqual(self._set(["PUT /api/cfg cores=64"]), 200)
            self.assertEqual(call("PUT", "/api/m/demo/api/cfg", {"cores": 2}, token=self.admin)[0], 200)
            s, b, _ = call("PUT", "/api/m/demo/api/cfg", {"cores": 64}, token=self.admin)
            self.assertEqual((s, b.get("approval")), (403, True))
            self.assertEqual(call("PUT", "/api/m/demo/api/cfg", {"cores": 64}, token=self.owner)[0], 200)
            # the admin can ask for exactly that request …
            s, b, _ = call("POST", "/api/approvals", {"module": "demo", "method": "PUT", "path": "/api/cfg",
                                                      "body": {"cores": 64}, "label": "64 cores"}, token=self.admin)
            self.assertEqual(s, 201 if s == 201 else 200)
            # … but not for one that needs no approval
            s, _, _ = call("POST", "/api/approvals", {"module": "demo", "method": "PUT", "path": "/api/cfg",
                                                      "body": {"cores": 2}}, token=self.admin)
            self.assertEqual(s, 400)
            # a protected write is still an ordinary route: the condition adds no route of its own
            self.assertEqual(call("PUT", "/api/m/demo/api/other", {"cores": 64}, token=self.owner)[1]["error"], "not allowed")
        finally:
            self._set(None)
            for ap in GW.app.store.approvals("pending"):
                GW.app.store.decide_approval(ap["id"], "cancelled", "test")


class RouteTimeout(unittest.TestCase):
    """Route `timeout` (manifest v2): a slow route (an interactive indexer search) gets longer than the backend's default,
    every other route keeps the short one; a backend that is too slow is a readable 502, not a hung thread."""

    @classmethod
    def setUpClass(cls):
        class Slow(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                time.sleep(1.3)
                out = b'{"ok": true}'
                try:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(out)))
                    self.end_headers()
                    self.wfile.write(out)
                except OSError:
                    pass
        from http.server import ThreadingHTTPServer
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.mod = {"id": "slow", "backend": {"url": f"http://127.0.0.1:{cls.srv.server_address[1]}", "timeout": 1}}

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_route_timeout_wins(self):
        from lab.proxy import BackendError, forward
        user = {"username": "u", "role": "owner", "groups": []}
        with self.assertRaises(BackendError) as e:
            forward(self.mod, None, user, "GET", "/search")
        self.assertEqual(str(e.exception), "slow did not answer within 1 s")
        code, _, data = forward(self.mod, None, user, "GET", "/search", timeout=3)
        self.assertEqual((code, json.loads(data)), (200, {"ok": True}))

    def test_manifest_route_timeout(self):
        base = {"manifest": 2, "id": "tmo", "name": "T", "version": "1.0.0", "kind": "community", "category": "tools",
                "config": {"fields": [{"key": "url", "type": "url", "label": "URL", "required": True}]},
                "backend": {"url": "{url}", "timeout": 30}}
        ok = validate({**base, "routes": [{"method": "GET", "path": "/release", "timeout": 95}]}, "tmo")
        self.assertEqual(ok["routes"][0]["timeout"], 95)
        for bad in (0, 301, "95", True, None):
            with self.assertRaises(ManifestError):
                validate({**base, "routes": [{"method": "GET", "path": "/release", "timeout": bad}]}, "tmo")

    def test_arr_searches_fit_under_cloudflare(self):
        """Behind Cloudflare a request ends at 100 s (524): slow routes stay below it so the gateway answers first."""
        for mid in ("sonarr", "radarr", "prowlarr"):
            with open(os.path.join(ROOT, "modules", mid, "manifest.json")) as f:
                m = json.load(f)
            self.assertLessEqual(m["backend"]["timeout"], 60, mid)
            slow = [r for r in m["routes"] if "timeout" in r]
            self.assertTrue(slow, mid)
            self.assertTrue(all(r["timeout"] < 100 for r in slow), mid)
        with open(os.path.join(ROOT, "modules", "sonarr", "manifest.json")) as f:
            rel = [r for r in json.load(f)["routes"] if r["path"] == "/api/v3/release" and r["method"] == "GET"]
        self.assertEqual(rel[0]["timeout"], 95)
