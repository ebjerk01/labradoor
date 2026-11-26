"""Connectors managed by Labradoor (gateway/lab/connectors.py, sdk/python/labconn.py, deploy/lab-connector-helper,
deploy/lab-connector@.service):

  * a connector gets ITS config from GET /api/connector/config — signed with its own key in the "_config.<id>" scope,
    from 127.0.0.1 only — with secrets opened, and for `uses_credentials_of` only what calling those modules needs;
  * nothing else gets it: another connector's key, a user token, a module that is no connector, another address;
  * the owner's config test is answered by the connector itself, with the CANDIDATE values;
  * saving config restarts the connector, switching the module off stops it (through the root helper);
  * the helper accepts only its fixed commands for shipped connectors;
  * the unit runs each connector as its own user, outside group lab, with /etc/lab and /var/lib/lab out of reach.

Imports the gateway lazily and patches lab.config in setUpModule (see tests/test_gateway_delegation.py for why)."""
import http.client
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gateway"))
sys.path.insert(0, os.path.join(ROOT, "sdk", "python"))
import labauth  # noqa: E402

KEYS = {m: os.urandom(32) for m in ("conn", "own", "other")}
PEM = "-----BEGIN CERTIFICATE-----\nMIIBfake\nline2\n-----END CERTIFICATE-----"
VALIDATED = []   # (body, claims) the fake connector got for its config test
OWN_SEEN = []    # (method, path, claims, body) the "own" backend got (through /api/connector/call)
TMP = None


class OwnBackend(BaseHTTPRequestHandler):
    """A module backend that verifies X-Lab-Auth with its own key (like npm/manage/drift)."""

    def log_message(self, *a):
        pass

    def _answer(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        claims = labauth.verify(self.headers.get(labauth.HEADER), KEYS["own"], "own")
        OWN_SEEN.append((self.command, self.path, claims, raw))
        out = json.dumps({"claims": claims}).encode()
        self.send_response(200 if claims else 401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = _answer


class FakeConnector(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        claims = labauth.verify(self.headers.get(labauth.HEADER), KEYS["conn"], "conn")
        body = json.loads(raw or b"{}")
        VALIDATED.append((body, claims))
        ok = claims and claims["r"] == "owner" and body["values"].get("password") == "right"
        out = json.dumps({"ok": True, "detail": "logged in"} if ok else {"ok": False, "error": "login refused"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


def manifest(mid, **kw):
    return {"manifest": 2, "id": mid, "name": mid, "version": "1.0.0", "kind": "community", "category": "tools", **kw}


def setUpModule():
    global TMP, CONN, OWN, GW, PORT, SAVED, server, config, auth, HELPER_CALLS
    from lab import auth, config, server  # noqa: F811
    TMP = tempfile.mkdtemp(prefix="labconn-")
    CONN = HTTPServer(("127.0.0.1", 0), FakeConnector)
    threading.Thread(target=CONN.serve_forever, daemon=True).start()
    cport = CONN.server_address[1]
    OWN = HTTPServer(("127.0.0.1", 0), OwnBackend)
    threading.Thread(target=OWN.serve_forever, daemon=True).start()
    for d in ("modules", "keys", "dist"):
        os.makedirs(os.path.join(TMP, d))
    for mid, key in KEYS.items():
        with open(os.path.join(TMP, "keys", f"{mid}.key"), "w") as f:
            f.write(key.hex())
    mods = {
        "conn": manifest("conn", requires=[{"id": "third", "optional": True}, "own", "other"],
                         config={"fields": [{"key": "url", "type": "url", "label": "URL", "required": True},
                                            {"key": "username", "type": "text", "label": "user"},
                                            {"key": "password", "type": "secret", "label": "pw", "required": True},
                                            {"key": "pem", "type": "text", "multiline": True, "label": "CA"}],
                                 "validate": {"method": "POST", "path": "/api/_validate"}},
                         backend={"url": f"http://127.0.0.1:{cport}", "health": "/healthz"},
                         connector={"uses_credentials_of": ["third", "own"]},
                         routes=[{"method": "GET", "path": "/api/x"}]),
        "other": manifest("other", config={"fields": [{"key": "token", "type": "secret", "label": "t", "required": True}]},
                          backend={"url": "http://127.0.0.1:9999"}, connector={}, routes=[{"method": "GET", "path": "/x"}]),
        "third": manifest("third", config={"fields": [{"key": "url", "type": "url", "label": "u", "required": True},
                                                      {"key": "token", "type": "secret", "label": "t", "required": True},
                                                      {"key": "unrelated", "type": "secret", "label": "x"}]},
                          backend={"url": "{url}/api", "auth": {"type": "bearer", "secret": "token"}},
                          routes=[{"method": "GET", "path": "/x"}]),
        "own": manifest("own", config={"fields": [{"key": "url", "type": "url", "label": "u", "required": True}]},
                        backend={"url": "{url}"},
                        routes=[{"method": "GET", "path": "/x"},
                                {"method": "POST", "path": "/w", "min": "admin", "label": "write",
                                 "body_keys": ["name"]},
                                {"method": "POST", "path": "/o", "owner_only": True, "label": "owner thing"},
                                {"method": "GET", "path": "/s", "owner_only": True, "secret": True}]),
    }
    for mid, m in mods.items():
        os.makedirs(os.path.join(TMP, "modules", mid))
        with open(os.path.join(TMP, "modules", mid, "manifest.json"), "w") as f:
            json.dump(m, f)
    with open(os.path.join(TMP, "master.key"), "w") as f:
        f.write("ab" * 32)
    SAVED = {k: getattr(config, k) for k in ("DB", "MODULES_DIR", "KEYS_DIR", "STATIC_DIR", "BACKENDS_FILE", "MASTER_KEY",
                                             "DELEGATION_KEY", "COOKIE_SECURE", "TRUST_PROXY", "HEALTH_INTERVAL")}
    config.DB = os.path.join(TMP, "lab.sqlite3")
    config.MODULES_DIR = os.path.join(TMP, "modules")
    config.KEYS_DIR = os.path.join(TMP, "keys")
    config.STATIC_DIR = os.path.join(TMP, "dist")
    config.BACKENDS_FILE = os.path.join(TMP, "backends.json")
    config.MASTER_KEY = os.path.join(TMP, "master.key")
    config.DELEGATION_KEY = os.path.join(TMP, "delegation.key")
    config.COOKIE_SECURE, config.TRUST_PROXY, config.HEALTH_INTERVAL = False, False, 3600
    with open(os.path.join(TMP, "backends.v2.json"), "w") as f:  # the old published view: removed at start
        f.write("{}")
    app = server.App()
    HELPER_CALLS = []
    app.connectors.call = lambda req: HELPER_CALLS.append(req) or {"ok": True, "state": "active"}
    box, st = app.box, app.store
    for mid, k, v in (("conn", "url", "http://up.example"), ("conn", "username", "svc"), ("conn", "pem", PEM),
                      ("third", "url", "http://third.example"),
                      ("own", "url", f"http://127.0.0.1:{OWN.server_address[1]}")):
        st.set_module_config(mid, k, v)
    for mid, k, v in (("conn", "password", "right"), ("third", "token", "T0KEN"), ("third", "unrelated", "NOT-FOR-CONN")):
        st.set_module_config(mid, k, box.seal(mid, k, v), secret=True)
    app.reload_config()
    GW = server.PooledHTTPServer(("127.0.0.1", 0), server.Handler, app, workers=4)
    PORT = GW.server_address[1]
    threading.Thread(target=GW.serve_forever, daemon=True).start()


def tearDownModule():
    GW.shutdown()
    CONN.shutdown()
    OWN.shutdown()
    for k, v in SAVED.items():
        setattr(config, k, v)
    shutil.rmtree(TMP, ignore_errors=True)


def call(method, path, headers=None, body=None, source=None, token=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=15, source_address=(source, 0) if source else None)
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
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, raw.decode()


def config_request(mid, key=None, scope=None, user="connector", source=None, header_id=None):
    claims = {"u": user, "r": "guest", "m": scope or f"_config.{mid}"}
    return call("GET", "/api/connector/config", {"X-Lab-Connector": header_id or mid,
                                                 labauth.HEADER: labauth.sign(key or KEYS[mid], claims)}, source=source)


def owner_session():
    st = GW.app.store
    st.upsert_user("boss", "Boss", "", ["lab-owners"], auth.role_for(["lab-owners"]))
    st.set_role("boss", "owner")
    return st.new_session("boss", 1)


class ConfigDelivery(unittest.TestCase):
    def test_own_config_with_secrets_opened(self):
        code, d = config_request("conn")
        self.assertEqual(code, 200, d)
        self.assertEqual((d["id"], d["ready"]), ("conn", True))
        self.assertEqual(d["values"], {"url": "http://up.example", "username": "svc", "password": "right", "pem": PEM})

    def test_uses_gives_only_what_calling_that_module_needs(self):
        _, d = config_request("conn")
        self.assertEqual(sorted(d["uses"]), ["own", "third"])  # not "other", although it is in requires
        third = d["uses"]["third"]
        self.assertEqual(third["backend"]["url"], "http://third.example/api")
        self.assertEqual(third["values"], {"token": "T0KEN"})  # the auth secret only: not "unrelated", not the URL
        self.assertIsNone(third["key"])
        own = d["uses"]["own"]
        # an own backend: NOT its HMAC key (that would sign any user/approval for it, and fetch its config if it is a
        # connector — review L4) and not its URL: the connector calls it through the gateway, as a user
        self.assertEqual((own["ready"], own["via"], own["values"], own["key"]), (True, "gateway", {}, None))
        self.assertNotIn("url", own["backend"])
        self.assertNotIn(KEYS["own"].hex(), json.dumps(d))
        self.assertNotIn("NOT-FOR-CONN", json.dumps(d))

    def test_no_credentials_of_a_module_that_is_off(self):
        GW.app.store.set_module_setting("third", "_enabled", False)
        GW.app.reload_config()
        try:
            _, d = config_request("conn")
            self.assertEqual(d["uses"]["third"], {"ready": False})
            self.assertNotIn("T0KEN", json.dumps(d))
        finally:
            GW.app.store.set_module_setting("third", "_enabled", None)
            GW.app.reload_config()

    def test_needs_setup_is_said(self):
        code, d = config_request("other")
        self.assertEqual((code, d["ready"], d["missing"]), (200, False, ["token"]))

    def test_refused_without_its_own_key_scope_or_address(self):
        self.assertEqual(config_request("conn", key=KEYS["other"])[0], 403)          # another connector's key
        self.assertEqual(config_request("conn", header_id="other")[0], 403)          # claims for conn, asks as other
        self.assertEqual(config_request("conn", scope="conn")[0], 403)               # a user-scope token (gateway → connector)
        self.assertEqual(config_request("conn", user="owner")[0], 403)
        self.assertEqual(config_request("own")[0], 403)                              # not a connector (own backend key)
        self.assertEqual(config_request("nope", key=os.urandom(32))[0], 403)
        self.assertEqual(config_request("conn", source="127.0.0.2")[0], 403)         # only from 127.0.0.1
        code, _ = call("POST", "/api/connector/config", {"X-Lab-Connector": "conn", labauth.HEADER: labauth.sign(
            KEYS["conn"], {"u": "connector", "r": "guest", "m": "_config.conn"})}, body={})
        self.assertEqual(code, 403)

    def test_old_published_view_is_gone(self):
        self.assertFalse(os.path.exists(os.path.join(TMP, "backends.v2.json")))

    def test_sdk_round_trip(self):
        import labconn
        seen = []
        conf = labconn.Config("conn", KEYS["conn"], apply=lambda v, c: seen.append(v["password"]),
                              gateway=f"http://127.0.0.1:{PORT}")
        conf.load_once()
        self.assertTrue(conf.ready)
        self.assertEqual(seen, ["right"])
        self.assertEqual(conf.uses["third"]["values"]["token"], "T0KEN")
        bad = labconn.Config("conn", KEYS["other"], gateway=f"http://127.0.0.1:{PORT}")
        with self.assertRaises(OSError):  # HTTPError 403
            bad.load_once()
        self.assertFalse(bad.ready)
        self.assertIn("starting", bad.why())


class OwnerActions(unittest.TestCase):
    def setUp(self):
        self.tok = owner_session()
        HELPER_CALLS.clear()
        VALIDATED.clear()

    def post(self, path, body):
        return call("POST", path, {"Origin": f"http://127.0.0.1:{PORT}"}, body=body, token=self.tok)

    def test_config_test_is_answered_by_the_connector_with_the_candidate(self):
        code, d = self.post("/api/config/conn/test", {"values": {"password": "right"}})
        self.assertEqual((code, d["ok"]), (200, True), d)
        body, claims = VALIDATED[-1]
        self.assertEqual(body["values"]["password"], "right")
        self.assertEqual(body["values"]["url"], "http://up.example")   # stored values fill what wasn't typed
        self.assertEqual((claims["u"], claims["r"], claims["m"]), ("boss", "owner", "conn"))
        code, d = self.post("/api/config/conn/test", {"values": {"password": "wrong"}})
        self.assertEqual((code, d["ok"], d["test"]["error"]), (200, False, "login refused"))

    def test_saving_config_restarts_the_connector(self):
        code, d = self.post("/api/config/conn", {"values": {"username": "svc2"}, "test": False})
        self.assertEqual(code, 200, d)
        self.assertEqual(HELPER_CALLS, [{"op": "restart", "id": "conn"}])
        self.assertEqual(GW.app.config_value("conn", "username"), "svc2")

    def test_multiline_only_where_declared(self):
        code, _ = self.post("/api/config/conn", {"values": {"pem": PEM + "\r\n"}, "test": False})
        self.assertEqual(code, 200)
        self.assertEqual(GW.app.config_value("conn", "pem"), PEM)
        code, d = self.post("/api/config/conn", {"values": {"username": "a\nb"}, "test": False})
        self.assertEqual(code, 400, d)

    def test_switching_the_module_off_and_on(self):
        try:
            code, _ = self.post("/api/settings/module", {"module": "conn", "enabled": False})
            self.assertEqual(code, 200)
            code, _ = self.post("/api/settings/module", {"module": "conn", "enabled": True})
            self.assertEqual(code, 200)
            self.assertEqual(HELPER_CALLS, [{"op": "stop", "id": "conn"}, {"op": "ensure", "id": "conn"}])
            HELPER_CALLS.clear()
            self.post("/api/settings/module", {"module": "own", "enabled": True})  # not a connector: no helper call
            self.assertEqual(HELPER_CALLS, [])
        finally:
            GW.app.store.set_module_setting("conn", "_enabled", None)
            GW.app.reload_config()

    def test_reconcile_at_start(self):
        GW.app.store.set_module_setting("other", "_enabled", False)
        GW.app.reload_config()
        try:
            GW.app.connectors.reconcile()
            self.assertEqual(sorted(HELPER_CALLS, key=lambda r: r["id"]),
                             [{"op": "ensure", "id": "conn"}, {"op": "stop", "id": "other"}])
        finally:
            GW.app.store.set_module_setting("other", "_enabled", None)
            GW.app.reload_config()


def act_for(username, role, session_token, via="conn", approved_by=None, **kw):
    from lab.delegate import session_hash
    return GW.app.act.mint({"username": username, "role": role}, via, session_hash(session_token),
                           approved_by=approved_by, **kw)


def connector_call(method, path, act=None, key=None, cid="conn", scope=None, body=None, source=None):
    h = {"X-Lab-Connector": cid, labauth.HEADER: labauth.sign(key or KEYS[cid], {"u": "connector", "r": "guest",
                                                                                   "m": scope or f"_call.{cid}"})}
    if act:
        h["X-Lab-Act"] = act
    return call(method, "/api/connector/call/" + path, h, body=body, source=source)


class ConnectorCall(unittest.TestCase):
    """Review L4: a connector reaches a module with an own backend only through the gateway, as the user it acts for."""

    def setUp(self):
        self.tok = owner_session()
        st = GW.app.store
        st.upsert_user("adm", "Adm", "", ["lab-admins"], "admin")
        st.set_role("adm", "admin")
        self.adm = st.new_session("adm", 1)
        OWN_SEEN.clear()

    def test_owner_reads_and_writes_as_himself(self):
        code, d = connector_call("GET", "own/x", act_for("boss", "owner", self.tok))
        self.assertEqual(code, 200, d)
        c = OWN_SEEN[-1][2]
        self.assertEqual((c["u"], c["r"], c["m"], c.get("a")), ("boss", "owner", "own", None))
        code, d = connector_call("POST", "own/o", act_for("boss", "owner", self.tok), body={"z": 1})
        self.assertEqual(code, 200, d)
        audit = GW.app.store.audit_list(5)
        self.assertTrue(any(r["action"] == "owner thing via conn" for r in audit), audit)

    def test_admin_gets_admin_rules(self):
        act = act_for("adm", "admin", self.adm)
        self.assertEqual(connector_call("POST", "own/w", act, body={"name": "x"})[0], 200)
        self.assertEqual(connector_call("POST", "own/w", act, body={"name": "x", "evil": 1})[0], 403)  # body allow-list
        self.assertEqual(connector_call("POST", "own/o", act, body={})[0], 403)     # owner-only: "ask" = refused here
        self.assertEqual(connector_call("GET", "own/s", act)[0], 403)
        self.assertEqual(connector_call("GET", "own/nope", act)[0], 403)            # no such route
        # a token minted as owner for someone who is admin now acts as admin
        self.assertEqual(connector_call("POST", "own/o", act_for("adm", "owner", self.adm), body={})[0], 403)

    def test_owner_approval_carries_over(self):
        act = act_for("adm", "admin", self.adm, approved_by="boss")
        code, d = connector_call("POST", "own/o", act, body={})
        self.assertEqual(code, 200, d)
        self.assertEqual(OWN_SEEN[-1][2].get("a"), "boss")
        # an "approval" by someone who is not an active owner counts for nothing
        self.assertEqual(connector_call("POST", "own/o", act_for("adm", "admin", self.adm, approved_by="adm"),
                                        body={})[0], 403)

    def test_refused(self):
        good = act_for("boss", "owner", self.tok)
        self.assertEqual(connector_call("GET", "own/x")[0], 401)                                    # no act token
        self.assertEqual(connector_call("GET", "own/x", good + "x")[0], 401)                       # forged
        self.assertEqual(connector_call("GET", "own/x", act_for("boss", "owner", self.tok, via="other"))[0], 401)
        d_tok = GW.app.delegation.mint({"username": "boss", "role": "owner"}, "conn", "")
        self.assertEqual(connector_call("GET", "own/x", d_tok)[0], 401)       # a delegation token is not an act token
        self.assertEqual(connector_call("GET", "own/x", good, key=KEYS["other"])[0], 403)          # another key
        self.assertEqual(connector_call("GET", "own/x", good, scope="_config.conn")[0], 403)       # config scope
        self.assertEqual(connector_call("GET", "own/x", good, source="127.0.0.2")[0], 403)         # not 127.0.0.1
        self.assertEqual(connector_call("GET", "other/x", good)[0], 403)      # not in uses_credentials_of
        self.assertEqual(connector_call("GET", "own/../x", good)[0], 400)
        GW.app.store.end_session(self.tok)
        self.assertEqual(connector_call("GET", "own/x", good)[0], 401)                             # logged out
        self.assertEqual(OWN_SEEN, [])

    def test_gateway_hands_the_act_token_with_a_request(self):
        seen = []
        orig = server.forward
        server.forward = lambda *a, **kw: seen.append(kw.get("extra") or (a[10] if len(a) > 10 else None)) or (200, {}, b"{}")
        try:
            code, _ = call("GET", "/api/m/conn/api/x", token=self.tok)
        finally:
            server.forward = orig
        self.assertEqual(code, 200)
        claims = GW.app.act.verify(seen[-1]["X-Lab-Act"])
        self.assertEqual((claims["u"], claims["v"]), ("boss", "conn"))
        self.assertIsNone(GW.app.delegation.verify(seen[-1]["X-Lab-Act"]))   # never valid as a delegation

    def test_sdk_call(self):
        import labconn
        code, _, data = labconn.call("conn", KEYS["conn"], act_for("boss", "owner", self.tok), "own", "GET", "/x",
                                     gateway=f"http://127.0.0.1:{PORT}")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data)["claims"]["u"], "boss")


class Manifest(unittest.TestCase):
    def check(self, **kw):
        from lab.manifest2 import validate_v2
        m = manifest("cx", requires=["xx"], backend={"url": "http://127.0.0.1:8119"}, connector={},
                     routes=[{"method": "GET", "path": "/a"}])
        m.update(kw)
        return validate_v2(m)

    def test_rules(self):
        from lab.registry import ManifestError
        self.assertEqual(self.check()["connector"], {"uses_credentials_of": [], "port": 8119})
        self.assertEqual(self.check(connector={"uses_credentials_of": ["xx"]})["connector"]["uses_credentials_of"], ["xx"])
        for bad in ({"connector": {"uses_credentials_of": ["yy"]}},             # not in requires
                    {"connector": {"uses_credentials_of": ["cx"]}},             # itself
                    {"connector": {"uses": ["xx"]}},                            # unknown key
                    {"backend": {"url": "http://10.0.0.5:8119"}},               # not on this host
                    {"backend": {"url": "http://127.0.0.1:8119", "auth": {"type": "bearer", "secret": "t"}},
                     "config": {"fields": [{"key": "t", "type": "secret", "label": "t"}]}},
                    {"config": {"fields": [{"key": "n", "type": "int", "label": "n", "multiline": True}]}}):
            with self.assertRaises(ManifestError, msg=bad):
                self.check(**bad)

    def test_real_connector_manifests(self):
        from lab.registry import Registry
        reg = Registry(os.path.join(ROOT, "modules"))
        conns = {mid for mid, m in reg.modules.items() if m.get("connector")}
        shipped = {d for d in os.listdir(os.path.join(ROOT, "connectors")) if not d.startswith("_")
                   and os.path.isfile(os.path.join(ROOT, "connectors", d, "connector.py"))}
        self.assertEqual(conns, shipped)  # every shipped connector is a module that says so, and vice versa
        for mid in conns:
            m = reg.get(mid)
            self.assertEqual(m["config"]["validate"], {"method": "POST", "path": "/api/_validate"}, mid)
            self.assertTrue(reg.needs_setup(m), f"{mid}: a fresh install must need setup (no built-in defaults)")


def load_helper():
    loader = importlib.machinery.SourceFileLoader("lab_connector_helper", os.path.join(ROOT, "deploy", "lab-connector-helper"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Helper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = load_helper()
        cls.dir = tempfile.mkdtemp(prefix="labhelper-")
        for d in ("npm", "ai", "_template", "Bad"):
            os.makedirs(os.path.join(cls.dir, d))
            with open(os.path.join(cls.dir, d, "connector.py"), "w") as f:
                f.write("")
        os.makedirs(os.path.join(cls.dir, "nocode"))
        cls.h.CONNECTORS_DIR = cls.dir

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_only_fixed_commands_for_shipped_connectors(self):
        self.assertEqual(self.h.shipped(), ["ai", "npm"])
        self.assertEqual(self.h.check({"op": "restart", "id": "npm"}), ("restart", "npm"))
        self.assertEqual(self.h.check({"op": "status"}), ("status", None))
        for bad in (None, [], "npm", {"op": "restart"}, {"op": "rm", "id": "npm"}, {"op": "restart", "id": "npm", "x": 1},
                    {"op": "restart", "id": "../npm"}, {"op": "restart", "id": "npm\n"}, {"op": "restart", "id": "nocode"},
                    {"op": "restart", "id": "_template"}, {"op": "restart", "id": "Bad"}, {"op": "start", "id": "npm"},
                    {"op": "status", "id": "npm"}, {"op": "restart", "id": "a" * 27}, {"op": "restart", "id": 5}):
            with self.assertRaises(self.h.Fail, msg=bad):
                self.h.check(bad)

    def test_names(self):
        self.assertEqual((self.h.user("npm"), self.h.unit("npm")), ("lab-c-npm", "lab-connector@npm.service"))
        self.assertLessEqual(len(self.h.user("a" * 26)), 32)

    def test_venv_only_when_needed_and_pinned(self):
        """Review L9: a connector's venv is built before its start, only when its hash-locked requirements changed."""
        h, saved = self.h, (self.h.VENV_DIR, self.h.PYTHON)
        h.VENV_DIR = os.path.join(self.dir, "venvs")
        try:
            self.assertEqual(h.venv("npm"), "none")                     # no requirements.txt: nothing to build
            with open(os.path.join(self.dir, "ai", "requirements.txt"), "w") as f:
                f.write("x==1.0 \\\n    --hash=sha256:" + "0" * 64 + "\n")
            os.makedirs(os.path.join(h.VENV_DIR, "ai"))
            with open(os.path.join(h.VENV_DIR, "ai", h.STAMP), "w") as f:
                f.write(h._want(os.path.join(self.dir, "ai", "requirements.txt")) + "\n")
            self.assertEqual(h.venv("ai"), "current")                   # stamp matches: no pip, no network
            # what a build leaves (under the unit's UMask=0077) is readable by the connector's own user
            t = os.path.join(self.dir, "perm")
            os.makedirs(os.path.join(t, "bin"), mode=0o700)
            for n, mode in (("bin/python3", 0o700), ("lib.py", 0o600)):
                with open(os.path.join(t, n), "w") as f:
                    f.write("")
                os.chmod(os.path.join(t, n), mode)
            os.symlink("python3", os.path.join(t, "bin", "python"))
            os.chmod(t, 0o700)
            h._readable(t)
            self.assertEqual([oct(os.stat(os.path.join(t, n)).st_mode & 0o777) for n in ("", "bin", "bin/python3", "lib.py")],
                             ["0o755", "0o755", "0o755", "0o644"])
            with open(os.path.join(self.dir, "ai", "requirements.txt"), "a") as f:
                f.write("# changed\n")
            h.PYTHON = "/bin/false"                                     # the build fails (think: no network)
            with self.assertRaises(h.Fail):
                h.venv("ai")
            self.assertTrue(os.path.isdir(os.path.join(h.VENV_DIR, "ai")))   # the old venv stays in place
            self.assertFalse(os.path.exists(os.path.join(h.VENV_DIR, ".build-ai")))
            with self.assertRaises(h.Fail) as e:                       # and is not retried on every restart tick
                h.venv("ai")
            self.assertIn("less than", str(e.exception))
            for bad in ("../ai", "", "Bad", "a" * 27):
                with self.assertRaises(h.Fail):
                    h.venv(bad)
        finally:
            h.VENV_DIR, h.PYTHON = saved
            for p in ("requirements.txt",):
                if os.path.exists(os.path.join(self.dir, "ai", p)):
                    os.unlink(os.path.join(self.dir, "ai", p))

    def test_protocol_refuses_garbage(self):
        for line in (b"not json\n", b'{"op": "rm", "id": "npm"}\n', b"", b"[1]\n"):
            out, saved = io.StringIO(), (sys.stdin, sys.stdout, sys.stderr)
            sys.stdin = io.TextIOWrapper(io.BytesIO(line))
            sys.stdout, sys.stderr = out, io.StringIO()
            try:
                self.h.main()
            finally:
                sys.stdin, sys.stdout, sys.stderr = saved
            self.assertFalse(json.loads(out.getvalue())["ok"])


class Isolation(unittest.TestCase):
    """What the unit and the installer promise; verified on the host with `sudo -u lab-c-<id> cat …` (README)."""

    def read(self, *p):
        with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
            return f.read()

    def test_unit_runs_each_connector_as_its_own_user_without_lab_files(self):
        u = self.read("deploy", "lab-connector@.service")
        lines = {ln.split("=", 1)[0]: ln.split("=", 1)[1] for ln in u.splitlines() if "=" in ln and not ln.startswith("#")}
        self.assertEqual((lines["User"], lines["Group"]), ("lab-c-%i", "lab-c-%i"))
        self.assertNotIn("SupplementaryGroups", lines)
        self.assertNotIn("EnvironmentFile", lines)
        self.assertEqual(lines["LoadCredential"], "key:/etc/lab/keys/%i.key")
        inacc = lines["InaccessiblePaths"].split()
        for p in ("-/etc/lab", "-/var/lib/lab", "-/run/lab-connector-helper.sock"):
            self.assertIn(p, inacc)
        self.assertEqual(lines["StateDirectory"], "lab-connectors/%i")
        self.assertEqual((lines["ProtectSystem"], lines["NoNewPrivileges"]), ("strict", "yes"))

    def test_installer_keeps_connectors_out_of_group_lab(self):
        s = self.read("deploy", "install.sh")
        for line in s.splitlines():
            if "useradd" in line and "lab-c-" in line:
                self.assertNotRegex(line, r"(-G|--groups)\s")
        self.assertIn("gpasswd -d lab-conn lab", s)
        self.assertNotIn("SupplementaryGroups=lab", s)
        self.assertIn("rm -f /var/lib/lab/backends.v2.json", s)
        self.assertRegex(s, r"chown root:lab /etc/lab/master.key; chmod 640 /etc/lab/master.key")

    def test_no_network_pip_at_install_and_pins_are_hash_locked(self):
        s = self.read("deploy", "install.sh")
        self.assertNotRegex(s, r"pip3? install|-m pip")             # review L9: no pip at core install
        self.assertIn("ExecStartPre=+/usr/local/sbin/lab-connector-helper venv $id", s)
        self.assertIn("ExecStart=/var/lib/lab-venvs/$id/bin/python connector.py", s)
        helper = self.read("deploy", "lab-connector-helper")
        self.assertRegex(helper, r'"--require-hashes",\s+"--only-binary", ":all:", "--no-deps"')
        for cid in os.listdir(os.path.join(ROOT, "connectors")):
            req = os.path.join(ROOT, "connectors", cid, "requirements.txt")
            if not os.path.isfile(req):
                continue
            text = self.read("connectors", cid, "requirements.txt")
            reqs = re.findall(r"^([A-Za-z0-9._-]+)==[\w.+-]+ \\$", text, re.M)
            self.assertTrue(reqs, cid)
            blocks = re.split(r"^(?=[A-Za-z0-9._-]+==)", text, flags=re.M)[1:]
            self.assertEqual(len(blocks), len(reqs), f"{cid}: every requirement pinned with ==")
            for b in blocks:
                self.assertRegex(b, r"--hash=sha256:[0-9a-f]{64}", f"{cid}: {b.split()[0]} has no hash")
            self.assertNotRegex(text, r"(?m)^\s*-(-index-url|-extra-index-url|-find-links|e |-editable)", cid)

    def test_helper_socket_is_for_the_gateway_only(self):
        s = self.read("deploy", "lab-connector-helper.socket")
        self.assertIn("SocketGroup=lab", s)
        self.assertIn("SocketMode=0660", s)
        self.assertIn("Accept=yes", s)

    def test_connectors_read_no_key_files_or_env(self):
        for cid in os.listdir(os.path.join(ROOT, "connectors")):
            path = os.path.join(ROOT, "connectors", cid, "connector.py")
            if not os.path.isfile(path):
                continue
            src = self.read("connectors", cid, "connector.py")
            self.assertNotRegex(src, r"/etc/lab/(keys|connectors|wizard)|published_lookup|LAB_RESOLVED|master\.key", cid)
            self.assertNotRegex(src, r"\b10\.0\.\d+\.\d+|owner\.no\b", f"{cid}: an installation's address in code")
            self.assertTrue(re.search(r"labconn\.", src), f"{cid}: uses the connector SDK")


if __name__ == "__main__":
    unittest.main()
