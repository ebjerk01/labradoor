"""Tests for the seerr connector against a fake Seerr. Run: python3 -m unittest discover -s connectors/seerr"""
import json
import os
import secrets
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "sdk", "python"))
import labauth  # noqa: E402

USERS = [{"id": 1, "displayName": "owner", "jellyfinUsername": "owner", "email": "e@example.org", "requestCount": 2, "permissions": 2, "userType": 3},
         {"id": 3, "displayName": "guest-one", "jellyfinUsername": "guest-one", "email": "m@example.org", "requestCount": 1, "permissions": 32, "userType": 3},
         {"id": 4, "displayName": "guest-two", "jellyfinUsername": "guest-two", "email": "i@example.org", "requestCount": 0, "permissions": 32, "userType": 3}]


def req(rid, uid, status=2, media_status=3, tmdb=10, mtype="movie", dl=None):
    u = next(x for x in USERS if x["id"] == uid)
    return {"id": rid, "status": status, "type": mtype, "createdAt": "2026-11-13T10:00:00.000Z", "updatedAt": "2026-11-13T10:00:00.000Z",
            "media": {"id": 100 + rid, "mediaType": mtype, "tmdbId": tmdb, "status": media_status, "downloadStatus": dl or [], "mediaUrl": None,
                      "serviceUrl": "https://radarr.example/movie/x"},
            "requestedBy": u, "modifiedBy": u, "seasons": [], "serverId": 0, "profileId": 6, "rootFolder": "/m"}


REQS = [req(1, 1, tmdb=10), req(2, 3, status=1, tmdb=11, dl=[{"title": "x", "size": 100, "sizeLeft": 25, "status": "downloading"}]),
        req(3, 1, status=5, media_status=5, tmdb=12), req(4, 4, status=1, tmdb=13)]
RADARR = [{"id": 0, "name": "Radarr", "hostname": "10.0.0.1", "port": 7878, "apiKey": "SECRET-RADARR", "activeProfileId": 6,
           "activeProfileName": "HD", "activeDirectory": "/m", "is4k": False, "isDefault": True}]


class FakeSeerr(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def _j(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else None

    def _rec(self, method):
        body = self._body()
        FakeSeerr.calls.append((method, self.path, self.headers.get("X-Api-User"), body))
        return body

    def do_GET(self):
        p = self.path
        if p.startswith("/imageproxy/tmdb/t/p/w185/abcdef.jpg"):  # Seerr's image proxy needs no key
            b = b"\x89PNG fake"
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            return self.wfile.write(b)
        if self.headers.get("X-Api-Key") != "k":
            return self._j(403, {"message": "key"})
        FakeSeerr.calls.append(("GET", self.path, self.headers.get("X-Api-User"), None))
        page = lambda rs: {"pageInfo": {"results": len(rs)}, "results": rs}  # noqa: E731
        if p.startswith("/api/v1/user?"):
            return self._j(200, page(USERS))
        if p.endswith("/quota"):
            return self._j(200, {"movie": {"limit": 5, "days": 7, "used": 1, "restricted": False}, "tv": {"limit": 0, "days": 0, "used": 0}})
        if p.endswith("/settings/main") and p.startswith("/api/v1/user/"):
            return self._j(200, {"username": None, "email": "m@example.org", "locale": "en", "movieQuotaLimit": None})
        if p.startswith("/api/v1/user/"):
            uid = int(p.split("/")[4])
            return self._j(200, page([r for r in REQS if r["requestedBy"]["id"] == uid]))
        if p.startswith("/api/v1/request/count"):
            return self._j(200, {"total": 4, "pending": 2, "processing": 1, "available": 0, "completed": 1, "declined": 0})
        if p.startswith("/api/v1/request/"):
            rid = int(p.split("/")[4].split("?")[0])
            return self._j(200, next(r for r in REQS if r["id"] == rid))
        if p.startswith("/api/v1/request?"):
            rs = [r for r in REQS if "filter=pending" not in p or r["status"] == 1]
            if "requestedBy=" in p:
                uid = int(p.split("requestedBy=")[1].split("&")[0])
                rs = [r for r in rs if r["requestedBy"]["id"] == uid]
            return self._j(200, page(rs))
        if p.startswith("/api/v1/issue/count"):
            return self._j(200, {"total": 1, "open": 1, "closed": 0})
        if p.startswith("/api/v1/media?"):
            return self._j(200, page([{"mediaType": "movie", "tmdbId": 12, "status": 5, "mediaAddedAt": "2026-11-13T10:00:00Z", "mediaUrl": "https://stream/x"}]))
        if p.startswith("/api/v1/movie/"):
            tm = int(p.split("/")[4])
            mi = {"id": 200, "status": 3, "mediaUrl": None, "serviceUrl": "https://radarr.example/x",
                  "requests": [r for r in REQS if r["media"]["tmdbId"] == tm] + [req(9, 1, tmdb=tm)]}
            return self._j(200, {"title": f"Movie {tm}", "releaseDate": "2020-01-01", "posterPath": "/abcdef.jpg", "mediaInfo": mi})
        if p.startswith("/api/v1/search?"):
            return self._j(200, {"page": 1, "totalPages": 1, "totalResults": 2, "results": [
                {"id": 11, "mediaType": "movie", "title": "Movie 11", "posterPath": "/p11xx.jpg"},
                {"id": 5, "mediaType": "person", "name": "Some One", "profilePath": None}]})
        if p == "/api/v1/status":
            return self._j(200, {"version": "3.5.1", "updateAvailable": True, "commitsBehind": 3})
        if p == "/api/v1/settings/public":
            return self._j(200, {"movie4kEnabled": False, "series4kEnabled": False, "partialRequestsEnabled": True})
        if p == "/api/v1/settings/main":
            return self._j(200, {"apiKey": "SECRET-MAIN", "applicationTitle": "Seerr", "localLogin": True, "defaultPermissions": 32})
        if p == "/api/v1/settings/jellyfin":
            return self._j(200, {"name": "jf", "ip": "10.0.0.2", "port": 8096, "apiKey": "SECRET-JF", "libraries": []})
        if p == "/api/v1/settings/radarr":
            return self._j(200, RADARR)
        if p == "/api/v1/settings/sonarr":
            return self._j(200, [])
        if p.startswith("/api/v1/settings/notifications/"):
            return self._j(200, {"enabled": False, "types": 0, "options": {"webhookUrl": "https://hooks.example/SECRET-HOOK", "botAPI": "SECRET-BOT"}})
        if p == "/api/v1/settings/jobs":
            return self._j(200, [{"id": "radarr-scan", "name": "Radarr Scan", "running": False}])
        if p == "/api/v1/settings/cache":
            return self._j(200, {"apiCaches": [{"id": "tmdb", "name": "TMDB", "stats": {"keys": 3}}]})
        if p == "/api/v1/settings/about":
            return self._j(200, {"version": "3.5.1", "totalMediaItems": 3, "totalRequests": 4})
        if p.startswith("/api/v1/service/radarr/0"):
            return self._j(200, {"profiles": [{"id": 6, "name": "HD"}, {"id": 7, "name": "Bluray"}], "rootFolders": [{"path": "/m"}, {"path": "/m2"}]})
        return self._j(404, {})

    def do_POST(self):
        self._rec("POST")
        if self.path == "/api/v1/request":
            return self._j(201, {"id": 77, "status": 1})
        return self._j(200, {})

    def do_PUT(self):
        self._rec("PUT")
        return self._j(200, {"apiKey": "SECRET-RADARR"})

    def do_DELETE(self):
        self._rec("DELETE")
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()


class ConnectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeSeerr)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.key = secrets.token_bytes(32)
        kf = os.path.join(tempfile.mkdtemp(), "seerr.key")
        with open(kf, "w") as f:
            f.write(cls.key.hex())
        os.environ.update(LAB_KEY_FILE=kf, CONNECTOR_ID="seerr")
        sys.path.insert(0, HERE)
        import connector
        cls.mod = connector
        cls.values = {"url": f"http://127.0.0.1:{cls.fake.server_port}", "api_key": "k",
                      "public_url": "https://seerr.example", "users": ["owner=owner", "guest-one.olufsen=guest-one"]}
        connector.CONF.set({"id": "seerr", "ready": True, "values": cls.values, "uses": {}})
        cls.srv = connector.serve(port=0)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"

    def setUp(self):
        self.mod.CACHE.drop("")
        FakeSeerr.calls.clear()

    def call(self, method, path, user="owner", role="owner", key=None, body=None, approved=None):
        h = {}
        if user:
            c = {"u": user, "r": role, "g": [], "m": "seerr"}
            if approved:
                c["a"] = approved
            h[labauth.HEADER] = labauth.sign(key or self.key, c)
        data = json.dumps(body).encode() if body is not None else (b"{}" if method in ("POST", "PUT") else None)
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if resp.headers.get("Content-Type") == "application/json" else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def writes(self):
        return [c for c in FakeSeerr.calls if c[0] != "GET"]

    def test_config_and_validate(self):
        self.assertEqual(self.mod.USERS, {"owner": "owner", "guest-one.olufsen": "guest-one"})
        self.assertEqual(self.mod.PUBLIC, "https://seerr.example")
        self.assertEqual(self.call("POST", "/api/_validate", role="admin", body={"values": self.values})[0], 403)
        s, d = self.call("POST", "/api/_validate", body={"values": self.values})
        self.assertEqual((s, d["ok"]), (200, True))
        s, d = self.call("POST", "/api/_validate", body={"values": {**self.values, "api_key": "wrong"}})
        self.assertEqual((s, d["ok"]), (200, False))
        self.assertNotIn("wrong", json.dumps(d))

    def test_needs_signature(self):
        self.assertEqual(self.call("GET", "/api/overview", user=None)[0], 401)
        self.assertEqual(self.call("GET", "/api/overview", key=secrets.token_bytes(32))[0], 401)

    def test_guest_sees_only_own(self):
        s, d = self.call("GET", "/api/overview", user="guest-one.olufsen", role="guest")
        self.assertEqual(s, 200)
        self.assertTrue(d["me"]["linked"])
        self.assertEqual([r["id"] for r in d["mine"]], [2])
        self.assertEqual(d["mine"][0]["title"], "Movie 11")
        self.assertEqual(d["mine"][0]["downloads"][0]["progress"], 0.75)
        self.assertEqual(d["me"]["quota"]["movie"]["limit"], 5)
        for k in ("all", "counts", "pending", "issues", "users"):
            self.assertNotIn(k, d)
        self.assertNotIn("@", json.dumps(d))  # no e-mail addresses
        self.assertNotIn("service", d["mine"][0])  # no *arr links for guests
        self.assertEqual(len(d["recent"]), 1)

    def test_unmapped_guest_gets_nothing(self):
        s, d = self.call("GET", "/api/overview", user="stranger", role="guest")
        self.assertEqual((s, d["me"]["linked"], d["mine"], d["recent"]), (200, False, [], []))
        self.assertEqual(self.call("GET", "/api/search?q=matrix", user="stranger", role="guest")[0], 403)
        self.assertEqual(self.call("GET", "/api/requests", user="stranger", role="guest")[0], 403)
        self.assertEqual(self.call("POST", "/api/requests", user="stranger", role="guest", body={"type": "movie", "tmdb": 5})[0], 403)

    def test_admin_sees_all_without_emails(self):
        s, d = self.call("GET", "/api/overview", user="admin", role="admin")
        self.assertEqual(s, 200)
        self.assertEqual(len(d["all"]), 4)
        self.assertEqual([r["id"] for r in d["pending"]], [2, 4])
        self.assertEqual(d["pending"][0]["by"], "guest-one")
        self.assertEqual(d["issues"]["open"], 1)
        self.assertTrue(d["updateAvailable"])
        self.assertNotIn("@", json.dumps(d))

    def test_guest_request_list_is_forced_to_self(self):
        s, d = self.call("GET", "/api/requests?filter=all&by=1", user="guest-one.olufsen", role="guest")
        self.assertEqual(s, 200)
        self.assertEqual({r["byId"] for r in d["results"]}, {3})
        self.assertIn("requestedBy=3", [c for c in FakeSeerr.calls if c[1].startswith("/api/v1/request?")][-1][1])
        self.assertEqual(self.call("GET", "/api/requests?filter=bogus")[0], 400)
        s, d = self.call("GET", "/api/requests?filter=pending&by=4", user="admin", role="admin")
        self.assertEqual([r["id"] for r in d["results"]], [4])

    def test_guest_request_as_self_without_advanced_fields(self):
        s, d = self.call("POST", "/api/requests", user="guest-one.olufsen", role="guest",
                         body={"type": "movie", "tmdb": 55, "userId": 1, "serverId": 0, "profileId": 1, "rootFolder": "/evil"})
        self.assertEqual((s, d["id"]), (200, 77))
        m, path, as_user, body = self.writes()[-1]
        self.assertEqual((m, path, as_user), ("POST", "/api/v1/request", "3"))
        self.assertEqual(body, {"mediaType": "movie", "mediaId": 55})
        s, _ = self.call("POST", "/api/requests", user="guest-one.olufsen", role="guest", body={"type": "tv", "tmdb": 9, "seasons": [1, 2]})
        self.assertEqual(self.writes()[-1][3], {"mediaType": "tv", "mediaId": 9, "seasons": [1, 2]})
        self.assertEqual(self.call("POST", "/api/requests", user="guest-one.olufsen", role="guest", body={"type": "tv", "tmdb": 9, "seasons": []})[0], 400)
        self.assertEqual(self.call("POST", "/api/requests", user="guest-one.olufsen", role="guest", body={"type": "music", "tmdb": 9})[0], 400)

    def test_admin_request_on_behalf(self):
        s, _ = self.call("POST", "/api/requests", body={"type": "movie", "tmdb": 55, "userId": 3, "serverId": 0, "profileId": 7, "rootFolder": "/m2"})
        self.assertEqual(s, 200)
        _, _, as_user, body = self.writes()[-1]
        self.assertEqual(as_user, "1")
        self.assertEqual(body, {"mediaType": "movie", "mediaId": 55, "serverId": 0, "profileId": 7, "rootFolder": "/m2", "userId": 3})
        self.assertEqual(self.call("POST", "/api/requests", body={"type": "movie", "tmdb": 55, "userId": 99})[0], 400)

    def test_guest_cancel_only_own_pending(self):
        self.assertEqual(self.call("DELETE", "/api/requests/4", user="guest-one.olufsen", role="guest")[0], 403)  # guest-two's
        self.assertEqual(self.call("DELETE", "/api/requests/1", user="guest-one.olufsen", role="guest")[0], 403)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.call("DELETE", "/api/requests/2", user="guest-one.olufsen", role="guest")[0], 200)
        self.assertEqual(self.writes()[-1][:3], ("DELETE", "/api/v1/request/2", "3"))

    def test_guest_detail_hides_others(self):
        s, d = self.call("GET", "/api/movie/11", user="guest-one.olufsen", role="guest")
        self.assertEqual(s, 200)
        self.assertEqual({r["byId"] for r in d["media"]["requests"]}, {3})
        self.assertNotIn("service", d["media"])
        self.assertEqual(d["poster"], "/api/m/seerr/api/img/w185/abcdef.jpg")
        s, d = self.call("GET", "/api/movie/11", user="admin", role="admin")
        self.assertEqual({r["byId"] for r in d["media"]["requests"]}, {1, 3})
        self.assertEqual(d["media"]["service"], "https://radarr.example/x")

    def test_search_and_image(self):
        s, d = self.call("GET", "/api/search?q=movie", user="guest-one.olufsen", role="guest")
        self.assertEqual([r["type"] for r in d["results"]], ["movie", "person"])
        s, raw = self.call("GET", "/api/img/w185/abcdef.jpg", user="guest-one.olufsen", role="guest")
        self.assertEqual((s, raw), (200, b"\x89PNG fake"))
        self.assertEqual(self.call("GET", "/api/img/w9999/abcdef.jpg")[0], 404)
        self.assertEqual(self.call("GET", "/api/img/w185/..%2fx.jpg")[0], 404)

    def test_admin_only_routes(self):
        for m, p in (("POST", "/api/requests/2/approve"), ("GET", "/api/users"), ("GET", "/api/settings"), ("GET", "/api/issues"),
                     ("POST", "/api/media/5/clear"), ("POST", "/api/jobs/radarr-scan/run"), ("POST", "/api/requests/bulk")):
            self.assertEqual(self.call(m, p, user="guest-one.olufsen", role="guest")[0], 403, p)
        self.assertEqual(self.writes(), [])

    def test_owner_only_routes(self):
        for m, p, b in (("POST", "/api/users/import", {"ids": ["a" * 32]}), ("DELETE", "/api/users/3", None),
                        ("POST", "/api/users/3/permissions/full", {"permissions": 2}), ("POST", "/api/settings/main/access", {"localLogin": False})):
            self.assertEqual(self.call(m, p, user="admin", role="admin", body=b)[0], 403, p)
        self.assertEqual(self.writes(), [])
        # an owner-approved admin request carries the "a" claim
        self.assertEqual(self.call("DELETE", "/api/users/3", user="admin", role="admin", approved="owner")[0], 200)
        self.assertEqual(self.call("DELETE", "/api/users/1")[0], 403)  # Seerr's owner account

    def test_approve_and_bulk(self):
        s, d = self.call("POST", "/api/requests/2/approve")
        self.assertEqual(s, 200)
        self.assertEqual(self.writes()[-1][1:3], ("/api/v1/request/2/approve", "1"))  # acting as owner's Seerr id
        self.assertEqual(self.call("POST", "/api/requests/2/delete")[0], 404)
        self.assertEqual(self.call("POST", "/api/requests/x/approve")[0], 404)
        s, d = self.call("POST", "/api/requests/bulk", user="admin", role="admin", body={"verb": "approve", "ids": [2, 4]})
        self.assertEqual((s, d["done"]), (200, [2, 4]))
        self.assertIsNone(self.writes()[-1][2])  # admin has no Seerr account: no X-Api-User
        self.assertEqual(self.call("POST", "/api/requests/bulk", body={"verb": "delete", "ids": [2]})[0], 400)

    def test_permissions_split(self):
        # guest-one has REQUEST (32): adding AUTO_APPROVE is fine for an admin, adding ADMIN is not
        self.assertEqual(self.call("POST", "/api/users/3/permissions", user="admin", role="admin", body={"permissions": 32 | 128})[0], 200)
        self.assertEqual(self.writes()[-1][3], {"permissions": 160})
        self.assertEqual(self.call("POST", "/api/users/3/permissions", user="admin", role="admin", body={"permissions": 2})[0], 403)
        self.assertEqual(self.call("POST", "/api/users/3/permissions", body={"permissions": 1 << 40})[0], 400)
        self.assertEqual(self.call("POST", "/api/users/3/permissions/full", body={"permissions": 2})[0], 200)
        self.assertEqual(self.call("POST", "/api/users/1/permissions", body={"permissions": 32})[0], 403)

    def test_quota_merges_user_settings(self):
        s, _ = self.call("POST", "/api/users/3/quota", user="admin", role="admin", body={"movieLimit": 3, "movieDays": 7, "tvLimit": 0, "tvDays": None})
        self.assertEqual(s, 200)
        _, path, _, body = self.writes()[-1]
        self.assertEqual(path, "/api/v1/user/3/settings/main")
        self.assertEqual((body["email"], body["locale"], body["movieQuotaLimit"], body["movieQuotaDays"], body["tvQuotaLimit"]),
                         ("m@example.org", "en", 3, 7, None))
        self.assertEqual(self.call("POST", "/api/users/3/quota", body={"movieLimit": -1})[0], 400)

    def test_settings_never_leak_credentials(self):
        s, d = self.call("GET", "/api/settings", user="admin", role="admin")
        self.assertEqual(s, 200)
        text = json.dumps(d)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("apiKey", text)
        n = {x["agent"]: x for x in d["notifications"]}
        self.assertTrue(n["discord"]["configured"])   # webhookUrl set (value never shown)
        self.assertFalse(n["email"]["configured"])    # no smtpHost
        self.assertEqual(len(n), 10)
        self.assertEqual(d["radarr"][0]["activeProfileName"], "HD")

    def test_server_edit_keeps_key_server_side(self):
        s, d = self.call("POST", "/api/settings/radarr/0", user="admin", role="admin", body={"activeProfileId": 7, "activeDirectory": "/m2"})
        self.assertEqual(s, 200)
        self.assertNotIn("SECRET", json.dumps(d))
        m, path, _, body = self.writes()[-1]
        self.assertEqual((m, path), ("PUT", "/api/v1/settings/radarr/0"))
        self.assertEqual((body["apiKey"], body["activeProfileId"], body["activeProfileName"], body["activeDirectory"]), ("SECRET-RADARR", 7, "Bluray", "/m2"))
        self.assertEqual(self.call("POST", "/api/settings/radarr/0", body={"apiKey": "x"})[0], 400)
        self.assertEqual(self.call("POST", "/api/settings/radarr/0", body={"hostname": "evil"})[0], 400)
        self.assertEqual(self.call("POST", "/api/settings/radarr/0", body={"activeProfileId": 99})[0], 400)
        self.assertEqual(self.call("POST", "/api/settings/radarr/0", body={"activeDirectory": "/etc"})[0], 400)

    def test_main_settings_split(self):
        self.assertEqual(self.call("POST", "/api/settings/main", user="admin", role="admin", body={"applicationTitle": "Media"})[0], 200)
        self.assertEqual(self.call("POST", "/api/settings/main", user="admin", role="admin", body={"localLogin": False})[0], 400)
        self.assertEqual(self.call("POST", "/api/settings/main", body={"apiKey": "x"})[0], 400)
        self.assertEqual(self.call("POST", "/api/settings/main/access", body={"defaultPermissions": 2})[0], 400)  # never admin by default
        self.assertEqual(self.call("POST", "/api/settings/main/access", body={"defaultPermissions": 32, "localLogin": True})[0], 200)

    def test_notification_test_uses_stored_settings(self):
        self.assertEqual(self.call("POST", "/api/settings/notifications/discord/test", user="admin", role="admin")[0], 200)
        _, path, _, body = self.writes()[-1]
        self.assertEqual(path, "/api/v1/settings/notifications/discord/test")
        self.assertEqual(body["options"]["botAPI"], "SECRET-BOT")  # server side only
        self.assertEqual(self.call("POST", "/api/settings/notifications/evil/test")[0], 404)
        self.assertEqual(self.call("POST", "/api/settings/notifications/email/enabled", body={"enabled": True})[0], 400)  # not configured
        self.assertEqual(self.call("POST", "/api/settings/notifications/discord/enabled", body={"enabled": True})[0], 200)


if __name__ == "__main__":
    unittest.main()
