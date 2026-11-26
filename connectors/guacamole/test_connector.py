"""Tests for the guacamole connector against a fake Guacamole. Run: python3 -m unittest discover -s connectors/guacamole"""
import base64
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "sdk", "python"))
import labauth  # noqa: E402

TREE = {"name": "ROOT", "identifier": "ROOT", "childConnectionGroups": [
    {"name": "Servere", "identifier": "1", "childConnections": [
        {"name": "pve1 (Proxmox, 192.0.2.21)", "identifier": "5", "protocol": "ssh", "activeConnections": 0},
        {"name": "Win11VM (RDP, VM 103)", "identifier": "3", "protocol": "rdp", "activeConnections": 1, "lastActive": 1794406020000}]},
    {"name": "Containere", "identifier": "2", "childConnections": [
        {"name": "web / example.com (CT 122)", "identifier": "27", "protocol": "ssh", "activeConnections": 0}]}]}


class FakeGuac(BaseHTTPRequestHandler):
    logins = 0
    valid = {"tok-1"}

    def log_message(self, *a):
        pass

    def _j(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        if self.path == "/api/tokens" and "password=pw" in body:
            FakeGuac.logins += 1
            return self._j(200, {"authToken": "tok-1", "dataSource": "mysql", "availableDataSources": ["mysql"]})
        return self._j(403, {"message": "no"})

    def do_GET(self):
        if self.headers.get("Guacamole-Token") not in FakeGuac.valid:
            return self._j(403, {"message": "token"})
        if self.path == "/api/session/data/mysql/connectionGroups/ROOT/tree":
            return self._j(200, TREE)
        return self._j(404, {})


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class ConnectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guac = serve(FakeGuac)
        cls.key = os.urandom(32)
        keyfile = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"guac-test-{os.getpid()}.key")
        with open(keyfile, "w", encoding="ascii") as f:
            f.write(cls.key.hex())
        os.environ.update(LAB_KEY_FILE=keyfile, CONNECTOR_ID="guacamole")
        sys.path.insert(0, HERE)
        import connector  # noqa: E402
        cls.c = connector
        cls.values = {"url": f"http://127.0.0.1:{cls.guac.server_port}", "username": "lab-svc", "password": "pw",
                      "public_url": "https://remote.example"}
        connector.CONF.set({"id": "guacamole", "ready": True, "values": cls.values, "uses": {}})
        os.unlink(keyfile)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), connector.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.guac.shutdown()

    def get(self, path, role="admin", module="guacamole", key=None):
        h = {labauth.HEADER: labauth.sign(key or self.key, {"u": "admin", "r": role, "g": [], "m": module})}
        req = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_port}{path}", headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_hints(self):
        self.assertEqual(self.c.hints("workstation (CT 112)"), {"label": "workstation", "vmid": 112, "ip": None})
        self.assertEqual(self.c.hints("pve1 (Proxmox, 192.0.2.21)"), {"label": "pve1", "vmid": None, "ip": "192.0.2.21"})
        self.assertEqual(self.c.hints("docker (Portainer, VM 9516, 192.0.2.92)")["vmid"], 9516)
        self.assertEqual(self.c.hints("git / Forgejo (CT 127, 192.0.2.67)")["label"], "git")

    def test_client_url(self):
        url = self.c.client_url("19", "mysql")
        enc = url.split("/#/client/")[1]
        self.assertEqual(base64.b64decode(enc + "=" * (-len(enc) % 4)), b"19\0c\0mysql")

    def test_signed_list(self):
        code, d = self.get("/api/connections")
        self.assertEqual(code, 200)
        names = [c["name"] for c in d["connections"]]
        self.assertEqual(names, sorted(names, key=str.lower))
        win = next(c for c in d["connections"] if c["id"] == "3")
        self.assertEqual((win["vmid"], win["active"], win["group"], win["lastActive"]), (103, 1, "Servere", 1794406020))
        self.assertNotIn("tok-1", json.dumps(d))

    def test_refuses_unsigned_and_wrong_module(self):
        self.assertEqual(self.get("/api/connections", key=os.urandom(32))[0], 401)
        self.assertEqual(self.get("/api/connections", module="proxmox")[0], 401)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.srv.server_port}/healthz") as r:
            self.assertEqual(json.loads(r.read())["connections"], 3)

    def post(self, path, body, role="owner", user=None, approved_by=None):
        claims = {"u": user or ("owner" if role == "owner" else "admin"), "r": role, "g": [], "m": "guacamole"}
        if approved_by:
            claims["a"] = approved_by
        h = {labauth.HEADER: labauth.sign(self.key, claims), "Content-Type": "application/json"}
        req = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_port}{path}", json.dumps(body).encode(), h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_public_url_from_config(self):
        self.assertTrue(self.c.client_url("1", "mysql").startswith("https://remote.example/#/client/"))

    def test_validate_with_candidate_values(self):
        self.assertEqual(self.post("/api/_validate", {"values": self.values}, role="admin")[0], 403)
        code, d = self.post("/api/_validate", {"values": self.values})
        self.assertEqual((code, d["ok"]), (200, True))
        code, d = self.post("/api/_validate", {"values": {**self.values, "password": "wrong"}})
        self.assertEqual((code, d["ok"]), (200, False))
        self.assertNotIn("wrong", json.dumps(d))

    # --- terminals / consoles ------------------------------------------------------------------------------------------
    def setUp(self):
        self.c.SESSIONS.revoke()
        self.c.POLICY.update(admins=False, grant_minutes=30)

    def test_list_has_no_client_urls(self):
        code, d = self.get("/api/connections")
        self.assertEqual(code, 200)
        self.assertNotIn("/#/client/", json.dumps(d))
        self.assertIs(d["admins"], False)
        self.assertEqual({c["id"]: c["terminal"] for c in d["connections"]}, {"5": True, "3": False, "27": True})

    def test_owner_opens_and_it_is_recorded(self):
        code, d = self.post("/api/open/27/web", {})
        self.assertEqual(code, 200)
        enc = d["url"].split("/#/client/")[1]
        self.assertEqual(base64.b64decode(enc + "=" * (-len(enc) % 4)), b"27\0c\0mysql")
        self.assertTrue(d["url"].startswith("https://remote.example/"))
        self.assertEqual((d["window"], d["terminal"], d["object"], d["protocol"]), ("lab-console-27", True, "web", "ssh"))
        self.assertNotIn("tok-1", json.dumps(d))
        code, s = self.get("/api/sessions", role="owner")
        e = s["opened"][0]
        self.assertEqual((e["user"], e["id"], e["object"], e["name"], e["via"]), ("owner", "27", "web", "web / example.com (CT 122)", "owner"))

    def test_unknown_or_bad_ids(self):
        self.assertEqual(self.post("/api/open/99/x", {})[0], 404)
        self.assertEqual(self.post("/api/open/abc/x", {})[0], 400)
        self.assertEqual(self.post("/api/open/27/..", {})[0], 400)

    def test_guest_never(self):
        self.assertEqual(self.post("/api/open/27/web", {}, role="guest", user="guest-two")[0], 403)
        self.c.POLICY["admins"] = True
        self.assertEqual(self.post("/api/grant/27/web", {}, role="guest", user="guest-two", approved_by="owner")[0], 403)

    def test_admin_refused_without_grant(self):
        code, d = self.post("/api/open/27/web", {}, role="admin")
        self.assertEqual(code, 403)
        self.assertIn("owner-only", d["error"])
        self.c.POLICY["admins"] = True
        code, d = self.post("/api/open/27/web", {}, role="admin")
        self.assertEqual(code, 403)
        self.assertIn("ask the owner", d["error"])

    def test_grant_needs_approval_and_setting(self):
        # not approved (an admin calling it directly — the gateway would refuse too: owner_only)
        self.c.POLICY["admins"] = True
        self.assertEqual(self.post("/api/grant/27/web", {}, role="admin")[0], 403)
        # the owner needs none
        self.assertEqual(self.post("/api/grant/27/web", {})[0], 400)
        # setting off: even an approved grant is refused
        self.c.POLICY["admins"] = False
        self.assertEqual(self.post("/api/grant/27/web", {}, role="admin", approved_by="owner")[0], 403)

    def test_admin_with_grant_opens_only_that_connection(self):
        self.c.POLICY["admins"] = True
        code, d = self.post("/api/grant/27/web", {}, role="admin", approved_by="owner")
        self.assertEqual(code, 200)
        self.assertEqual((d["grant"]["user"], d["grant"]["by"], d["grant"]["id"]), ("admin", "owner", "27"))
        self.assertEqual(self.post("/api/open/27/web", {}, role="admin")[0], 200)
        self.assertEqual(self.post("/api/open/5/pve1", {}, role="admin")[0], 403)          # another machine
        self.assertEqual(self.post("/api/open/27/web", {}, role="admin", user="other")[0], 403)  # another admin
        # an approved run of open itself can't hand the admin a window
        self.assertEqual(self.post("/api/open/27/web", {}, role="admin", approved_by="owner")[0], 409)
        # admin sees only own grants/opens; owner sees all
        _, s = self.get("/api/sessions", role="admin")
        self.assertTrue(all(g["user"] == "admin" for g in s["grants"]))
        self.assertTrue(s["opened"][0]["via"].startswith("grant by owner"))
        # the setting switched off again: the grant no longer opens
        self.c.POLICY["admins"] = False
        self.assertEqual(self.post("/api/open/27/web", {}, role="admin")[0], 403)

    def test_grant_expires_and_revoke(self):
        self.c.POLICY["admins"] = True
        self.c.SESSIONS.grant("admin", "27", "owner", "web", "web", 30, now=1000)
        self.assertIsNone(self.c.SESSIONS.granted("admin", "27", now=1000 + 31 * 60))
        self.c.POLICY["grant_minutes"] = 5
        self.post("/api/grant/27/web", {}, role="admin", approved_by="owner")
        g = self.c.SESSIONS.granted("admin", "27")
        self.assertLessEqual(g["until"] - g["at"], 5 * 60)
        self.assertEqual(self.post("/api/sessions/revoke", {"user": "admin"}, role="admin")[0], 403)
        code, d = self.post("/api/sessions/revoke", {"user": "admin", "id": "27"})
        self.assertEqual((code, d["revoked"]), (200, 1))
        self.assertEqual(self.post("/api/open/27/web", {}, role="admin")[0], 403)

    def test_policy_from_config(self):
        self.c.configure({**self.values, "admin_terminals": True, "grant_minutes": 1000})
        self.assertEqual(self.c.POLICY, {"admins": True, "grant_minutes": 240})
        self.c.configure({**self.values, "admin_terminals": False})
        self.assertEqual(self.c.POLICY, {"admins": False, "grant_minutes": 30})
        self.c.GUAC.token = None

    def test_sessions_log_persists(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "opened.jsonl")
            s1 = self.c.Sessions(path)
            for i in range(3):
                s1.record({"ts": i, "user": "owner", "role": "owner", "id": "27", "object": "web", "name": "web",
                           "protocol": "ssh", "via": "owner"})
            s2 = self.c.Sessions(path)
            self.assertEqual([e["ts"] for e in s2.recent()], [2, 1, 0])
            self.assertEqual(s2.recent(conn="5"), [])

    def test_relogin_on_expired_token(self):
        self.c.GUAC.token = "stale"
        n = FakeGuac.logins
        code, _ = self.get("/api/connections?fresh=1")
        self.assertEqual(code, 200)
        self.assertEqual(FakeGuac.logins, n + 1)


if __name__ == "__main__":
    unittest.main()
