"""Tests for the stalwart connector against a fake Stalwart JMAP endpoint. Run: python3 -m unittest discover -s connectors/stalwart"""
import copy
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

GOOD = "API_goodkey"
PW = {"@type": "Password", "secret": "$argon2id$hash", "credentialId": "a", "allowedIps": {}}
SEED = {
    "x:Domain": {"b": {"name": "example.org", "isEnabled": True, "createdAt": "2026-10-16T23:03:47Z",
                       "dkimManagement": {"@type": "Automatic"}, "dnsManagement": {"@type": "Automatic", "publishRecords": {"dkim": True}},
                       "certificateManagement": {"@type": "Automatic"},
                       "dnsZoneFile": 'example.org. IN MX 10 mail.example.org.\nv1-rsa._domainkey.example.org. IN TXT (\n    "v=DKIM1; k=rsa; p=AAA"\n    "BBB"\n)\n_dmarc.example.org. IN TXT "v=DMARC1; p=reject"\n'}},
    "x:Account": {
        "b": {"@type": "User", "name": "admin", "domainId": "b", "emailAddress": "admin@example.org", "roles": {"@type": "Admin"},
              "permissions": {"@type": "Inherit"}, "credentials": {"0": dict(PW)}, "usedDiskQuota": 10},
        "c": {"@type": "User", "name": "alerts", "domainId": "b", "emailAddress": "alerts@example.org", "roles": {"@type": "User"},
              "permissions": {"@type": "Inherit"}, "credentials": {"0": dict(PW), "1": {"@type": "AppPassword", "secret": "app"}}},
        "d": {"@type": "User", "name": "keepme", "domainId": "b", "roles": {"@type": "User"}, "permissions": {"@type": "Inherit"},
              "credentials": {}},
    },
    "x:QueuedMessage": {"q1": {"returnPath": "alerts@example.org", "createdAt": "2026-11-16T10:00:00Z", "size": 1234,
                               "nextRetry": "2026-11-16T11:00:00Z",
                               "recipients": {"x@nowhere.invalid": {"retryCount": 3, "queueName": "remote",
                                                                    "status": {"@type": "TemporaryFailure", "reason": "dns"}}}}},
    "x:BlockedIp": {"bl1": {"address": "192.0.2.9", "reason": "portScanning", "createdAt": "2026-11-01T00:00:00Z"},
                    "bl2": {"address": "198.51.100.7", "reason": "authFailure", "createdAt": "2026-11-02T00:00:00Z"}},
    "x:AllowedIp": {"al1": {"address": "10.9.9.9", "reason": "reverse proxy", "createdAt": "2026-11-02T00:00:00Z"}},
    "x:DmarcExternalReport": {"r1": {"from": "noreply@google.example", "subject": "Report", "receivedAt": "2026-11-15T00:00:00Z",
                                     "report": {"orgName": "google.example", "policyDomain": "example.org",
                                                "records": {"0": {"count": 5, "evaluatedDkim": "pass", "evaluatedSpf": "pass"},
                                                            "1": {"count": 2, "evaluatedDkim": "fail", "evaluatedSpf": "fail"}}}}},
    "x:TlsExternalReport": {}, "x:ArfExternalReport": {}, "x:DmarcInternalReport": {}, "x:TlsInternalReport": {},
    "x:Certificate": {"ce": {"subjectAlternativeNames": {"*.example.org": True}, "notValidAfter": "2027-01-14T22:50:03Z",
                             "privateKey": {"secret": "PEM"}}},
    "x:DkimSignature": {"dk": {"@type": "Dkim1RsaSha256", "selector": "v1-rsa", "stage": "active", "domainId": "b",
                               "privateKey": {"@type": "Text", "secret": "PEM"}}},
    "x:Task": {"t1": {"@type": "AcmeRenewal", "domainId": "b", "due": "2026-12-15T00:00:00Z", "status": {"@type": "Pending"}}},
    "x:Alert": {},
}


class Fake:
    store = {}
    calls = []
    auth_fail = 0
    actions = []


def patch(obj, key, val):
    if "/" not in key:
        obj[key] = val
        return
    parts = key.split("/")
    cur = obj
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = val


class FakeStalwart(BaseHTTPRequestHandler):
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
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        if self.headers.get("Authorization") != "Bearer " + GOOD:
            Fake.auth_fail += 1
            return self._j(401, {"type": "about:blank", "status": 401})
        if self.path != "/jmap/" or req.get("using") != ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]:
            return self._j(400, {})
        out, results = [], {}
        for meth, args, cid in req["methodCalls"]:
            Fake.calls.append((meth, copy.deepcopy(args)))
            typ, op = meth.split("/")
            if typ == "x:ApiKey":
                out.append(["error", {"type": "forbidden", "description": "You are not authorized"}, cid])
                continue
            st = Fake.store.setdefault(typ, {})
            if op == "query":
                res = {"accountId": "b", "ids": list(st)[: args.get("limit", 10 ** 6)], "total": len(st)}
            elif op == "get":
                ids = args.get("ids")
                if "#ids" in args:
                    ids = results[args["#ids"]["resultOf"]]["ids"]
                ids = list(st) if ids is None else ids
                props = args.get("properties")
                lst = []
                for i in ids:
                    if i in st:
                        o = {k: v for k, v in st[i].items() if props is None or k in props}
                        lst.append({**copy.deepcopy(o), "id": i})
                res = {"accountId": "b", "list": lst, "notFound": [i for i in ids if i not in st]}
            elif op == "set":
                res = {"accountId": "b"}
                for k, v in (args.get("create") or {}).items():
                    if typ == "x:Action":
                        Fake.actions.append(v["@type"])
                        res.setdefault("created", {})[k] = {"id": "act"}
                        continue
                    if typ == "x:Account" and any(a.get("name") == v.get("name") for a in st.values()):
                        res.setdefault("notCreated", {})[k] = {"type": "invalidProperties", "description": "name taken"}
                        continue
                    nid = f"n{len(st)}"
                    st[nid] = copy.deepcopy(v)
                    res.setdefault("created", {})[k] = {"id": nid}
                for i, v in (args.get("update") or {}).items():
                    if i not in st:
                        res.setdefault("notUpdated", {})[i] = {"type": "notFound"}
                        continue
                    for kk, vv in v.items():
                        patch(st[i], kk, vv)
                    res.setdefault("updated", {})[i] = None
                for i in args.get("destroy") or []:
                    if st.pop(i, None) is None:
                        res.setdefault("notDestroyed", {})[i] = {"type": "notFound"}
                    else:
                        res.setdefault("destroyed", []).append(i)
            else:
                out.append(["error", {"type": "unknownMethod"}, cid])
                continue
            results[cid] = res
            out.append([meth, res, cid])
        return self._j(200, {"methodResponses": out, "sessionState": "x"})


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class ConnectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.up = serve(FakeStalwart)
        cls.key = os.urandom(32)
        keyfile = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"stalwart-test-{os.getpid()}.key")
        with open(keyfile, "w", encoding="ascii") as f:
            f.write(cls.key.hex())
        os.environ.update(LAB_KEY_FILE=keyfile, CONNECTOR_ID="stalwart")
        sys.path.insert(0, HERE)
        import connector  # noqa: E402
        cls.c = connector
        os.unlink(keyfile)
        cls.values = {"url": f"http://127.0.0.1:{cls.up.server_port}", "api_key": GOOD, "verify_tls": True,
                      "protected_accounts": ["admin", "keepme"]}
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), connector.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.up.shutdown()

    def setUp(self):
        Fake.store = copy.deepcopy(SEED)
        Fake.calls, Fake.actions, Fake.auth_fail = [], [], 0
        self.c.CONF.set({"id": "stalwart", "ready": True, "values": dict(self.values), "uses": {}})

    def req(self, method, path, body=None, role="owner", approved=None, key=None):
        claims = {"u": "tester", "r": role, "g": [], "m": "stalwart"}
        if approved:
            claims["a"] = approved
        h = {labauth.HEADER: labauth.sign(key or self.key, claims), "Content-Type": "application/json"}
        data = json.dumps(body).encode() if body is not None else (b"" if method != "GET" else None)
        r = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_port}{path}", data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    # --- reads ---
    def test_overview_shapes_and_never_leaks_credentials(self):
        code, d = self.req("GET", "/api/overview", role="admin")
        self.assertEqual(code, 200, d)
        blob = json.dumps(d)
        for bad in ("argon2", "PEM", '"secret"', "credentials", "privateKey", GOOD):
            self.assertNotIn(bad, blob)
        self.assertEqual(d["counts"]["queue"], 1)
        self.assertEqual(d["counts"]["failing"], 1)
        self.assertEqual(d["counts"]["blocked"], 2)
        self.assertEqual(d["queue"][0]["recipients"][0]["status"], "TemporaryFailure")
        acc = {a["name"]: a for a in d["accounts"]}
        self.assertTrue(acc["admin"]["protected"])      # Admin role
        self.assertTrue(acc["keepme"]["protected"])     # protected_accounts
        self.assertFalse(acc["alerts"]["protected"])
        self.assertEqual(acc["alerts"]["email"], "alerts@example.org")
        self.assertEqual(d["domains"][0]["dkim"][0]["selector"], "v1-rsa")
        self.assertEqual(d["reports"]["dmarc"], 1)
        self.assertEqual(d["certificates"][0]["names"], ["*.example.org"])
        # one JMAP request, nothing but reads
        self.assertTrue(all(m.endswith(("/get", "/query")) for m, _ in Fake.calls), Fake.calls)

    def test_reports_list_and_detail(self):
        code, d = self.req("GET", "/api/reports?kind=dmarc", role="admin")
        self.assertEqual(code, 200, d)
        r = d["reports"][0]
        self.assertEqual((r["org"], r["messages"], r["failed"]), ("google.example", 7, 2))
        code, d = self.req("GET", "/api/reports/dmarc/r1", role="admin")
        self.assertEqual((code, d["summary"]["policyDomain"]), (200, "example.org"))
        self.assertEqual(self.req("GET", "/api/reports?kind=bogus", role="admin")[0], 400)
        self.assertEqual(self.req("GET", "/api/reports/dmarc/nope", role="admin")[0], 404)

    def test_domain_dns_records(self):
        code, d = self.req("GET", "/api/domains/b/dns", role="admin")
        self.assertEqual(code, 200, d)
        recs = {(r["type"], r["name"]): r["value"] for r in d["records"]}
        self.assertEqual(recs[("TXT", "v1-rsa._domainkey.example.org.")], '"v=DKIM1; k=rsa; p=AAABBB"')
        self.assertIn(("MX", "example.org."), recs)

    def test_refuses_unsigned_wrong_module_and_guests(self):
        self.assertEqual(self.req("GET", "/api/overview", key=os.urandom(32))[0], 401)
        self.assertEqual(self.req("GET", "/api/overview", role="guest")[0], 403)
        h = {labauth.HEADER: labauth.sign(self.key, {"u": "x", "r": "owner", "g": [], "m": "npm"})}
        r = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_port}/api/overview", headers=h)
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(r)
        self.assertEqual(e.exception.code, 401)

    # --- queue ---
    def test_queue_retry_admin_delete_owner(self):
        code, _ = self.req("POST", "/api/queue/q1/retry", {}, role="admin")
        self.assertEqual(code, 200)
        self.assertEqual(Fake.store["x:QueuedMessage"]["q1"]["nextRetry"], "2000-01-01T00:00:00Z")
        self.assertEqual(self.req("DELETE", "/api/queue/q1", role="admin")[0], 403)
        self.assertEqual(self.req("DELETE", "/api/queue/q1", role="admin", approved="boss")[0], 200)
        self.assertNotIn("q1", Fake.store["x:QueuedMessage"])
        self.assertEqual(self.req("POST", "/api/queue/q1/retry", {}, role="admin")[0], 404)

    def test_pause_resume_owner_only(self):
        self.assertEqual(self.req("POST", "/api/queue/pause", {}, role="admin")[0], 403)
        self.assertEqual(self.req("POST", "/api/queue/pause", {})[0], 200)
        self.assertEqual(self.req("POST", "/api/queue/resume", {})[0], 200)
        self.assertEqual(Fake.actions, ["PauseMtaQueue", "ResumeMtaQueue"])

    # --- accounts ---
    def test_account_lifecycle(self):
        code, d = self.req("POST", "/api/accounts", {"name": "LabTest-1", "domain": "b", "description": "t",
                                                    "password": "correct horse battery"})
        self.assertEqual(code, 200, d)
        nid = d["id"]
        acc = Fake.store["x:Account"][nid]
        self.assertEqual((acc["name"], acc["roles"], acc["credentials"]["0"]["secret"]),
                         ("labtest-1", {"@type": "User"}, "correct horse battery"))
        self.assertNotIn("correct horse", json.dumps(d))
        self.assertEqual(self.req("POST", f"/api/accounts/{nid}/disable", {})[0], 200)
        self.assertEqual(Fake.store["x:Account"][nid]["permissions"],
                         {"@type": "Merge", "enabledPermissions": {}, "disabledPermissions": {"authenticate": True}})
        code, d = self.req("GET", "/api/overview?fresh=1", role="admin")
        self.assertTrue(next(a for a in d["accounts"] if a["id"] == nid)["disabled"])
        self.assertEqual(self.req("POST", f"/api/accounts/{nid}/enable", {})[0], 200)
        self.assertEqual(Fake.store["x:Account"][nid]["permissions"], {"@type": "Inherit"})
        self.assertEqual(self.req("POST", f"/api/accounts/{nid}/password", {"password": "another long secret"})[0], 200)
        self.assertEqual(Fake.store["x:Account"][nid]["credentials"]["0"]["secret"], "another long secret")
        self.assertEqual(self.req("DELETE", f"/api/accounts/{nid}")[0], 200)
        self.assertNotIn(nid, Fake.store["x:Account"])

    def test_password_reset_keeps_app_passwords_and_adds_when_missing(self):
        self.assertEqual(self.req("POST", "/api/accounts/c/password", {"password": "a brand new password"})[0], 200)
        creds = Fake.store["x:Account"]["c"]["credentials"]
        self.assertEqual((creds["0"]["secret"], creds["1"]["secret"]), ("a brand new password", "app"))
        sets = [a for m, a in Fake.calls if m == "x:Account/set"]
        self.assertEqual(sets[-1]["update"], {"c": {"credentials/0/secret": "a brand new password"}})

    def test_disable_keeps_other_merge_rules(self):
        Fake.store["x:Account"]["c"]["permissions"] = {"@type": "Merge", "enabledPermissions": {"x": True},
                                                       "disabledPermissions": {"emailSend": True}}
        self.req("POST", "/api/accounts/c/disable", {})
        p = Fake.store["x:Account"]["c"]["permissions"]
        self.assertEqual(p["disabledPermissions"], {"emailSend": True, "authenticate": True})
        self.req("POST", "/api/accounts/c/enable", {})
        p = Fake.store["x:Account"]["c"]["permissions"]
        self.assertEqual((p["@type"], p["disabledPermissions"]), ("Merge", {"emailSend": True}))

    def test_accounts_owner_only_and_protected(self):
        self.assertEqual(self.req("POST", "/api/accounts/c/disable", {}, role="admin")[0], 403)
        for path, method, body in (("/api/accounts/b/disable", "POST", {}), ("/api/accounts/b", "DELETE", None),
                                   ("/api/accounts/b/password", "POST", {"password": "x" * 20}),
                                   ("/api/accounts/d", "DELETE", None)):
            code, d = self.req(method, path, body)
            self.assertEqual(code, 403, (path, d))
            self.assertIn("protected", d["error"])
        self.assertIn("b", Fake.store["x:Account"])
        self.assertEqual(Fake.store["x:Account"]["b"]["permissions"], {"@type": "Inherit"})

    def test_approved_request_never_carries_a_password(self):
        code, d = self.req("POST", "/api/accounts/c/password", {"password": "x" * 20}, role="admin", approved="boss")
        self.assertEqual(code, 400)
        code, d = self.req("POST", "/api/accounts", {"name": "z", "domain": "b", "password": "x" * 20}, role="admin", approved="boss")
        self.assertEqual(code, 400)
        code, d = self.req("POST", "/api/accounts", {"name": "z", "domain": "b"}, role="admin", approved="boss")
        self.assertEqual(code, 200, d)

    def test_input_checks(self):
        self.assertEqual(self.req("POST", "/api/accounts", {"name": "bad name", "domain": "b"})[0], 400)
        self.assertEqual(self.req("POST", "/api/accounts", {"name": "ok", "domain": "../x"})[0], 400)
        self.assertEqual(self.req("POST", "/api/accounts", {"name": "ok", "domain": "zz"})[0], 404)
        self.assertEqual(self.req("POST", "/api/accounts/c/password", {"password": "short"})[0], 400)
        code, d = self.req("POST", "/api/accounts", {"name": "alerts", "domain": "b"})
        self.assertEqual(code, 400)
        self.assertIn("name taken", d["error"])

    # --- IPs ---
    def test_unblock_owner_only_and_allowed_ips_cannot_be_removed(self):
        self.assertEqual(self.req("DELETE", "/api/blocked/bl1", role="admin")[0], 403)
        code, d = self.req("DELETE", "/api/blocked/bl1")
        self.assertEqual((code, d.get("address")), (200, "192.0.2.9"))
        self.assertNotIn("bl1", Fake.store["x:BlockedIp"])
        self.assertEqual(self.req("DELETE", "/api/blocked/al1")[0], 404)   # an allowed IP's id is not a blocked one
        self.assertEqual(self.req("DELETE", "/api/allowed/al1")[0], 404)   # no such route at all
        self.assertIn("al1", Fake.store["x:AllowedIp"])
        self.assertFalse(any(m == "x:AllowedIp/set" for m, _ in Fake.calls))

    # --- config + upstream auth ---
    def test_validate_with_candidate_values(self):
        self.assertEqual(self.req("POST", "/api/_validate", {"values": self.values}, role="admin")[0], 403)
        code, d = self.req("POST", "/api/_validate", {"values": self.values})
        self.assertEqual((code, d["ok"]), (200, True), d)
        code, d = self.req("POST", "/api/_validate", {"values": {**self.values, "api_key": "API_wrong"}})
        self.assertEqual((code, d["ok"]), (200, False))
        self.assertNotIn("API_wrong", json.dumps(d))
        self.assertEqual(self.req("GET", "/api/overview?fresh=1", role="admin")[0], 200)  # the running config is not paused

    def test_refused_key_pauses_upstream_calls(self):
        self.c.CONF.set({"id": "stalwart", "ready": True, "values": {**self.values, "api_key": "API_bad"}, "uses": {}})
        for _ in range(4):
            code, d = self.req("GET", "/api/overview?fresh=1", role="admin")
            self.assertEqual(code, 502)
        self.assertEqual(Fake.auth_fail, 1)     # one try, then paused: Stalwart bans IPs that keep failing
        self.assertIn("paused", d["error"])
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"http://127.0.0.1:{self.srv.server_port}/healthz")
        self.assertEqual(e.exception.code, 502)
        self.assertEqual(Fake.auth_fail, 1)

    def test_healthz_unsigned(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.srv.server_port}/healthz") as r:
            d = json.loads(r.read())
        self.assertEqual((d["ok"], d["queue"]), (True, 1))

    def test_scrub(self):
        self.assertEqual(self.c.scrub({"a": [{"Secret": 1, "b": {"credentials": 2, "c": 3}}]}), {"a": [{"b": {"c": 3}}]})


if __name__ == "__main__":
    unittest.main()
