"""Offline tests for connectors/npm (NPMplus is stubbed). Run: python3 -m unittest discover -s connectors/npm"""
import importlib.util
import json
import os
import secrets
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "sdk", "python"))
import labauth  # noqa: E402

KEY_HEX = secrets.token_hex(32)
_kf = tempfile.NamedTemporaryFile("w", suffix=".key", delete=False)
_kf.write(KEY_HEX)
_kf.close()
os.environ.update(LAB_KEY_FILE=_kf.name, CONNECTOR_ID="npm")
spec = importlib.util.spec_from_file_location("npm_connector", os.path.join(HERE, "connector.py"))
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)
# what the gateway hands it (GET /api/connector/config)
CONFIG = {"id": "npm", "ready": True, "values": {"url": "https://npm.test:81", "username": "x", "password": "y",
                                                 "verify_tls": False}, "uses": {}}

HOSTS = [{"id": 1, "domain_names": ["a.example.com"], "forward_scheme": "http", "forward_host": "192.0.2.5", "forward_port": 8080,
          "certificate_id": 1, "enabled": True, "meta": {"nginx_online": True}, "locations": None,
          "advanced_config": "ssl_verify_client on;\nproxy_set_header Authorization \"Basic abc\";\nlocation /ws/ { proxy_pass http://192.0.2.5:8091; }",
          "npmplus_access_list_ids": [], "npmplus_access_list_type": "public", "npmplus_auth_request": "none"}]


class Stub:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path == "/nginx/proxy-hosts":
            return HOSTS
        if method == "GET" and path.startswith("/nginx/proxy-hosts/"):
            return HOSTS[0]
        if method == "GET" and path.startswith("/nginx/access-lists"):
            return [{"id": 1, "name": "LAN", "items": [{"username": "u", "password": "secret-pw"}], "clients": [{"address": "10.0.0.0/8", "directive": "allow"}]}]
        if method == "GET":
            return []
        if method == "POST" and path == "/nginx/proxy-hosts":
            return {"id": 42}
        return {}


class Units(unittest.TestCase):
    def test_safe_fields(self):
        out = C.safe_fields({"domains": ["X.example.com"], "scheme": "http", "host": "192.0.2.9", "port": "80", "websockets": 1}, creating=True)
        self.assertEqual(out, {"domain_names": ["x.example.com"], "forward_scheme": "http", "forward_host": "192.0.2.9",
                               "forward_port": 80, "allow_websocket_upgrade": True})
        for bad in ({"domains": ["not a host"]}, {"port": 0}, {"host": "a b"}, {"scheme": "ftp"}, {"domains": []}):
            with self.assertRaises(C.NpmError):
                C.safe_fields(bad)
        self.assertNotIn("advanced_config", C.safe_fields({"advanced_config": "x", "port": 1}))

    def test_translation_hides_secrets(self):
        h = C.host_out(HOSTS[0])
        self.assertTrue(h["originLock"])
        self.assertNotIn("Basic abc", h["advanced"])
        self.assertEqual(h["extra"], [{"scheme": "http", "host": "192.0.2.5", "port": 8091}])
        a = C.acl_out(Stub()("GET", "/nginx/access-lists")[0])
        self.assertEqual(a["authUsers"], 1)
        self.assertNotIn("secret-pw", json.dumps(a))
        self.assertEqual(C.ts("2026-11-19 05:47:04"), 1795067224)


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        C.CONF.set(CONFIG)
        cls.stub = Stub()
        C.NPM.call = cls.stub
        C.PROBES.refresh = lambda targets: None  # no real TCP probes from tests
        cls.srv = C.PooledHTTPServer(("127.0.0.1", 0), C.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def req(self, method, path, body=None, role="admin", approved=None, sign=True):
        h = {"Content-Type": "application/json"}
        if sign:
            c = {"u": "t", "r": role, "g": [], "m": "npm"}
            if approved:
                c["a"] = approved
            h[labauth.HEADER] = labauth.sign(bytes.fromhex(KEY_HEX), c)
        r = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None, h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=10) as x:
                return x.status, json.loads(x.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_auth_and_roles(self):
        self.assertEqual(self.req("GET", "/healthz", sign=False)[0], 200)
        self.assertEqual(self.req("GET", "/api/overview", sign=False)[0], 401)
        code, d = self.req("GET", "/api/overview", role="guest")
        self.assertEqual(code, 200)
        self.assertEqual(d["hosts"][0]["domains"], ["a.example.com"])
        self.assertEqual(self.req("POST", "/api/hosts/1/disable", {}, role="guest")[0], 403)
        self.assertEqual(self.req("DELETE", "/api/hosts/1", role="admin")[0], 403)
        self.assertEqual(self.req("GET", "/api/hosts/1/advanced", role="admin")[0], 403)
        self.assertEqual(self.req("DELETE", "/api/hosts/1", role="admin", approved="owner")[0], 200)
        self.assertIn(("DELETE", "/nginx/proxy-hosts/1", None), self.stub.calls)

    def test_create_and_edit(self):
        code, d = self.req("POST", "/api/hosts", {"domains": ["n.example.com"], "scheme": "http", "host": "192.0.2.7", "port": 8080,
                                                  "certId": 1, "accessLists": [1]})
        self.assertEqual((code, d["id"]), (200, 42))
        create = [c for c in self.stub.calls if c[:2] == ("POST", "/nginx/proxy-hosts")][-1][2]
        self.assertEqual(create["locations"], [])
        self.assertNotIn("npmplus_access_list_ids", create)
        self.assertIn(("PUT", "/nginx/proxy-hosts/42", {"npmplus_access_list_ids": [1], "npmplus_access_list_type": "custom"}), self.stub.calls)
        self.assertEqual(self.req("PUT", "/api/hosts/1", {"advanced_config": "x"})[0], 400)  # unknown fields don't pass
        self.assertEqual(self.req("PUT", "/api/hosts/1", {"port": 9090})[0], 200)
        self.assertEqual(self.req("PUT", "/api/hosts/1/advanced", {"advanced": "x"}, role="owner")[0], 200)


    def test_config_from_the_gateway(self):
        self.assertEqual(C.NPM.url, "https://npm.test:81/api")
        self.assertEqual((C.NPM.user, C.NPM.password), ("x", "y"))
        self.assertEqual(C.api_url("https://n:81/api/"), "https://n:81/api")

    def test_needs_setup_answers_503(self):
        saved = C.CONF.raw
        try:
            C.CONF.raw = {**CONFIG, "ready": False, "missing": ["password"]}
            code, d = self.req("GET", "/api/overview", role="owner")
            self.assertEqual(code, 503)
            self.assertIn("needs setup", d["error"])
        finally:
            C.CONF.raw = saved

    def test_validate_is_owner_only_and_uses_the_candidate(self):
        self.assertEqual(self.req("POST", "/api/_validate", {"values": {}}, role="admin")[0], 403)
        seen = []

        def fake_login(n):
            seen.append((n.url, n.user, n.password))
            raise C.NpmError(502, "npmplus login failed (401)")
        orig = C.Npm.login
        C.Npm.login = fake_login
        try:
            code, d = self.req("POST", "/api/_validate", {"values": {"url": "https://other:81", "username": "u",
                                                                     "password": "p"}}, role="owner")
        finally:
            C.Npm.login = orig
        self.assertEqual((code, d["ok"]), (200, False))
        self.assertEqual(seen, [("https://other:81/api", "u", "p")])
        self.assertNotIn("password", json.dumps(d))


if __name__ == "__main__":
    unittest.main()
