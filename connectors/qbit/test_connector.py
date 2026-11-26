"""Tests for the qbit connector against a fake qBittorrent 5. Run: python3 -m unittest discover -s connectors/qbit"""
import json
import os
import secrets
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "sdk", "python"))
import labauth  # noqa: E402

H1, H2 = "a" * 40, "b" * 40
TORRENTS = [
    {"hash": H1, "name": "Show S01E01", "category": "tv-sonarr", "state": "downloading", "progress": 0.5, "dlspeed": 1000,
     "upspeed": 0, "size": 100, "tracker": "https://private.example/announce?passkey=SECRET", "magnet_uri": "magnet:?xt=SECRET"},
    {"hash": H2, "name": "Movie", "category": "radarr", "state": "error", "progress": 0.1, "dlspeed": 0, "upspeed": 0, "size": 10},
]


class FakeQbit(BaseHTTPRequestHandler):
    logins = 0
    sid = "s1"
    calls = []
    alt = "0"

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="application/json", cookie=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        return f"QBT_SID_8080={FakeQbit.sid}" in (self.headers.get("Cookie") or "")

    def do_POST(self):
        body = urllib.parse.parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode())
        if self.path == "/api/v2/auth/login":
            if body.get("password") == ["pw"]:
                FakeQbit.logins += 1
                return self._send(204, cookie=f"QBT_SID_8080={FakeQbit.sid}; HttpOnly; path=/")
            return self._send(401)
        if not self._authed():
            return self._send(403)
        if self.path == "/api/v2/torrents/pause":  # 5.x has no pause any more
            return self._send(404)
        FakeQbit.calls.append((self.path, body))
        if self.path == "/api/v2/transfer/toggleSpeedLimitsMode":
            FakeQbit.alt = "1" if FakeQbit.alt == "0" else "0"
        return self._send(200, b"")

    def do_GET(self):
        if not self._authed():
            return self._send(403)
        if self.path == "/api/v2/app/version":
            return self._send(200, b"v5.2.4", "text/plain")
        if self.path == "/api/v2/transfer/info":
            return self._send(200, json.dumps({"dl_info_speed": 1000, "up_info_speed": 5, "connection_status": "connected",
                                               "use_alt_speed_limits": FakeQbit.alt == "1"}).encode())
        if self.path == "/api/v2/transfer/speedLimitsMode":
            return self._send(200, FakeQbit.alt.encode(), "text/plain")
        if self.path == "/api/v2/app/preferences":
            return self._send(200, json.dumps({"alt_dl_limit": 500, "alt_up_limit": 100, "web_ui_password": "SECRET"}).encode())
        if self.path == "/api/v2/torrents/info":
            return self._send(200, json.dumps(TORRENTS).encode())
        if self.path == "/api/v2/torrents/categories":
            return self._send(200, json.dumps({"tv-sonarr": {}, "radarr": {}}).encode())
        if self.path.startswith("/api/v2/torrents/files"):
            return self._send(200, json.dumps([{"name": "a.mkv", "size": 1, "progress": 1, "priority": 1, "index": 0}]).encode())
        return self._send(404)


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class ConnectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = serve(FakeQbit)
        cls.tmp = tempfile.mkdtemp()
        cls.key = secrets.token_bytes(32)
        kf = os.path.join(cls.tmp, "qbit.key")
        with open(kf, "w") as f:
            f.write(cls.key.hex())
        os.environ.update(LAB_KEY_FILE=kf, CONNECTOR_ID="qbit")
        sys.path.insert(0, HERE)
        import connector
        cls.c = connector
        cls.values = {"url": f"http://127.0.0.1:{cls.fake.server_port}", "username": "admin", "password": "pw"}
        connector.CONF.set({"id": "qbit", "ready": True, "values": cls.values, "uses": {}})
        cls.srv = connector.serve(port=0)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"

    def req(self, method, path, body=None, role="admin", key=None):
        h = {"Content-Type": "application/json"}
        if role:
            h[labauth.HEADER] = labauth.sign(key or self.key, {"u": "admin", "r": role, "g": [], "m": "qbit"})
        r = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_validate_with_candidate_values(self):
        self.assertEqual(self.req("POST", "/api/_validate", {"values": self.values}, role="admin")[0], 403)
        s, d = self.req("POST", "/api/_validate", {"values": self.values}, role="owner")
        self.assertEqual((s, d["ok"]), (200, True))
        s, d = self.req("POST", "/api/_validate", {"values": {**self.values, "password": "nope"}}, role="owner")
        self.assertEqual((s, d["ok"]), (200, False))

    def test_needs_setup(self):
        saved = self.c.CONF.raw
        self.c.CONF.raw = {**saved, "ready": False}
        try:
            self.assertEqual(self.req("GET", "/api/overview")[0], 503)
        finally:
            self.c.CONF.raw = saved

    def test_auth(self):
        self.assertEqual(self.req("GET", "/api/overview", role=None)[0], 401)
        self.assertEqual(self.req("GET", "/api/overview", key=secrets.token_bytes(32))[0], 401)
        self.assertEqual(self.req("GET", "/api/overview", role="guest")[0], 403)

    def test_overview_strips_secrets(self):
        s, d = self.req("GET", "/api/overview")
        self.assertEqual(s, 200)
        self.assertEqual(d["version"], "v5.2.4")
        self.assertEqual(len(d["torrents"]), 2)
        self.assertNotIn("SECRET", json.dumps(d))
        self.assertNotIn("tracker", d["torrents"][0])

    def test_relogin_after_session_expiry(self):
        self.req("GET", "/api/overview")
        before = FakeQbit.logins
        FakeQbit.sid = "s2"  # qBittorrent restarted: old cookie is refused with 403
        self.assertEqual(self.req("GET", "/api/overview")[0], 200)
        self.assertEqual(FakeQbit.logins, before + 1)

    def test_verbs(self):
        FakeQbit.calls.clear()
        self.assertEqual(self.req("POST", "/api/torrents/stop", {"hashes": [H1, H2]})[0], 200)
        self.assertEqual(FakeQbit.calls[-1], ("/api/v2/torrents/stop", {"hashes": [f"{H1}|{H2}"]}))
        self.assertEqual(self.req("POST", "/api/torrents/delete", {"hashes": [H1]})[0], 200)
        self.assertEqual(FakeQbit.calls[-1][1]["deleteFiles"], ["false"])
        self.assertEqual(self.req("POST", "/api/torrents/delete-data", {"hashes": [H1]})[0], 200)
        self.assertEqual(FakeQbit.calls[-1][1]["deleteFiles"], ["true"])

    def test_bad_input(self):
        self.assertEqual(self.req("POST", "/api/torrents/stop", {"hashes": ["nothex"]})[0], 400)
        self.assertEqual(self.req("POST", "/api/torrents/stop", {"hashes": []})[0], 400)
        self.assertEqual(self.req("POST", "/api/torrents/stop", {"hashes": [H1] * 301})[0], 400)
        self.assertEqual(self.req("POST", "/api/torrents/setLocation", {"hashes": [H1]})[0], 404)
        self.assertEqual(self.req("POST", "/api/torrents/stop", {"hashes": [H1]}, role="guest")[0], 403)

    def test_files(self):
        s, d = self.req("GET", f"/api/torrents/{H1}/files")
        self.assertEqual((s, d["files"][0]["name"]), (200, "a.mkv"))
        self.assertEqual(self.req("GET", "/api/torrents/zz/files")[0], 404)


    # add / categories / limits / alt speed: everything runs against the fake, never a real qBittorrent
    MAGNET = "magnet:?xt=urn:btih:" + "c" * 40 + "&dn=x"

    def test_overview_has_alt_speed_without_prefs_secrets(self):
        s, d = self.req("GET", "/api/overview")
        self.assertEqual(d["alt_speed"], {"enabled": False, "dl": 500, "up": 100})
        self.assertNotIn("SECRET", json.dumps(d))

    def test_add(self):
        FakeQbit.calls.clear()
        s, d = self.req("POST", "/api/torrents/add", {"urls": f"{self.MAGNET}\nhttps://tracker.example/t.torrent", "category": "radarr", "paused": True})
        self.assertEqual((s, d["count"]), (200, 2))
        path, form = FakeQbit.calls[-1]
        self.assertEqual(path, "/api/v2/torrents/add")
        self.assertEqual(form["urls"], [f"{self.MAGNET}\nhttps://tracker.example/t.torrent"])
        self.assertEqual((form["category"], form["paused"], form["stopped"]), (["radarr"], ["true"], ["true"]))
        self.assertEqual(self.req("POST", "/api/torrents/add", {"urls": [self.MAGNET]})[0], 200)
        self.assertNotIn("category", FakeQbit.calls[-1][1])

    def test_add_refuses(self):
        n = len(FakeQbit.calls)
        for body in ({}, {"urls": ""}, {"urls": "file:///etc/passwd"}, {"urls": "ftp://x/y"}, {"urls": "http://u:p@host/x"},
                     {"urls": "magnet:?dn=nohash"}, {"urls": [1]}, {"urls": [self.MAGNET] * 21},
                     {"urls": self.MAGNET, "category": "nope"}, {"urls": self.MAGNET, "paused": "yes"}):
            self.assertEqual(self.req("POST", "/api/torrents/add", body)[0], 400, body)
        self.assertEqual(self.req("POST", "/api/torrents/add", {"urls": self.MAGNET}, role="guest")[0], 403)
        self.assertEqual(len(FakeQbit.calls), n)

    def test_categories(self):
        s, d = self.req("GET", "/api/categories")
        self.assertEqual([c["name"] for c in d["categories"]], ["radarr", "tv-sonarr"])
        FakeQbit.calls.clear()
        self.assertEqual(self.req("POST", "/api/categories", {"name": "new/sub", "save_path": "/data/new"})[1]["verb"], "created")
        self.assertEqual(FakeQbit.calls[-1], ("/api/v2/torrents/createCategory", {"category": ["new/sub"], "savePath": ["/data/new"]}))
        self.assertEqual(self.req("POST", "/api/categories", {"name": "radarr", "save_path": "/data/r"})[1]["verb"], "edited")
        self.assertEqual(FakeQbit.calls[-1][0], "/api/v2/torrents/editCategory")
        n = len(FakeQbit.calls)
        for body in ({}, {"name": "../x"}, {"name": "a" * 70}, {"name": "ok", "save_path": "rel/path"}, {"name": "ok", "save_path": "/a/../etc"}):
            self.assertEqual(self.req("POST", "/api/categories", body)[0], 400, body)
        self.assertEqual(len(FakeQbit.calls), n)

    def test_limits(self):
        FakeQbit.calls.clear()
        self.assertEqual(self.req("POST", "/api/limits", {"dl": 5000000, "up": 0})[0], 200)
        self.assertEqual(FakeQbit.calls, [("/api/v2/transfer/setDownloadLimit", {"limit": ["5000000"]}),
                                          ("/api/v2/transfer/setUploadLimit", {"limit": ["0"]})])
        n = len(FakeQbit.calls)
        for body in ({}, {"dl": -1}, {"dl": 1.5}, {"dl": "5"}, {"dl": True}, {"dl": 10 ** 12}, {"dl": 1, "other": 2}):
            self.assertEqual(self.req("POST", "/api/limits", body)[0], 400, body)
        self.assertEqual(len(FakeQbit.calls), n)

    def test_alt_speed_is_idempotent(self):
        FakeQbit.calls.clear()
        FakeQbit.alt = "0"
        self.assertEqual(self.req("POST", "/api/alt-speed", {"enabled": True})[0], 200)
        self.assertEqual(self.req("POST", "/api/alt-speed", {"enabled": True})[0], 200)  # already on: no second toggle
        self.assertEqual(sum(1 for c in FakeQbit.calls if c[0].endswith("toggleSpeedLimitsMode")), 1)
        self.assertEqual(self.req("POST", "/api/alt-speed", {"enabled": False})[0], 200)
        self.assertEqual(FakeQbit.alt, "0")
        self.assertEqual(self.req("POST", "/api/alt-speed", {"enabled": "on"})[0], 400)


if __name__ == "__main__":
    unittest.main()
