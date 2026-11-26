"""Tests for the ad connector against an in-memory fake LDAP server (plain TCP; the real one is LDAPS).
Run: python3 -m unittest discover -s connectors/ad"""
import json
import os
import socket
import socketserver
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "sdk", "python"))
import labauth  # noqa: E402
import ldap  # noqa: E402
from ldap import children, integer, enum, octets, read_tlv, seq, tlv, to_int  # noqa: E402

B = "DC=ad,DC=test"
BRUKERE, GRUPPER, TJENESTE = f"OU=Brukere,OU=Homelab,{B}", f"OU=Grupper,OU=Homelab,{B}", f"OU=Tjenestekontoer,OU=Homelab,{B}"
NOW_FT = (1794600000 + 11644473600) * 10_000_000  # 2026-11-13 as FILETIME


def ft(unix):
    return str((unix + 11644473600) * 10_000_000).encode()


def entry(**kw):
    return {k.lower(): [v if isinstance(v, bytes) else str(v).encode() for v in (vs if isinstance(vs, list) else [vs])]
            for k, vs in kw.items()}


def fixture():
    return {
        B: entry(objectClass=["top", "domainDNS"], maxPwdAge="-36288000000000", lockoutThreshold="5",
                 lockoutDuration="-6000000000", minPwdLength="7", pwdHistoryLength="24", pwdProperties="1"),
        f"OU=Homelab,{B}": entry(objectClass="organizationalUnit", ou="Homelab"),
        BRUKERE: entry(objectClass="organizationalUnit", ou="Brukere"),
        GRUPPER: entry(objectClass="organizationalUnit", ou="Grupper"),
        TJENESTE: entry(objectClass="organizationalUnit", ou="Tjenestekontoer"),
        f"CN=Users,{B}": entry(objectClass="container", cn="Users"),
        f"CN=alice,{BRUKERE}": entry(objectClass=["user"], objectCategory="person", cn="alice", sAMAccountName="alice",
                                     displayName="Alice A", userAccountControl="512", pwdLastSet=ft(1793000000),
                                     lockoutTime=ft(1794590000), **{"msDS-User-Account-Control-Computed": "16",
                                                                    "msDS-UserPasswordExpiryTimeComputed": ft(1794900000)},
                                     lastLogonTimestamp=ft(1794500000), memberOf=f"CN=staff,{GRUPPER}", primaryGroupID="513",
                                     whenChanged="20261113090000.0Z"),
        f"CN=owner,{BRUKERE}": entry(objectClass=["user"], objectCategory="person", cn="owner", sAMAccountName="owner",
                                      userAccountControl="512", pwdLastSet="0",
                                      **{"msDS-UserPasswordExpiryTimeComputed": "0"}),
        f"CN=svc-x,{TJENESTE}": entry(objectClass=["user"], objectCategory="person", cn="svc-x", sAMAccountName="svc-x",
                                      userAccountControl="66048", **{"msDS-UserPasswordExpiryTimeComputed": str(ldap_never())}),
        f"CN=Administrator,CN=Users,{B}": entry(objectClass=["user"], objectCategory="person", cn="Administrator",
                                                sAMAccountName="Administrator", userAccountControl="66048", adminCount="1",
                                                isCriticalSystemObject="TRUE"),
        f"CN=staff,{GRUPPER}": entry(objectClass=["group"], cn="staff", sAMAccountName="staff", groupType=str(-2147483646),
                                     member=f"CN=alice,{BRUKERE}"),
        f"CN=Domain Admins,CN=Users,{B}": entry(objectClass=["group"], cn="Domain Admins", groupType=str(-2147483646),
                                                member=f"CN=Administrator,CN=Users,{B}", adminCount="1"),
        f"CN=PC1,OU=Datamaskiner,OU=Homelab,{B}": entry(objectClass=["computer", "user"], cn="PC1", dNSHostName="pc1.ad.test",
                                                        operatingSystem="Windows 11 Pro", userAccountControl="4096",
                                                        lastLogonTimestamp=ft(1794000000)),
    }


def ldap_never():
    return 0x7FFFFFFFFFFFFFFF


class Fake:
    """Shared state of the fake DC."""
    dit = {}
    password = "svc-pw"
    binds = 0
    passwords = {}
    drop_next = False


def lower_attrs(e):
    return {k: [v.lower() for v in vs] for k, vs in e.items()}


def match(f, e):
    tag, c, _ = read_tlv(f)
    le = lower_attrs(e)
    if tag == 0xA0:
        return all(match(tlv(t, x), e) for t, x in children(c))
    if tag == 0xA1:
        return any(match(tlv(t, x), e) for t, x in children(c))
    if tag == 0xA2:
        return not match(c, e)
    if tag == 0x87:
        return c.decode().lower() in le
    if tag == 0xA3:
        (_, a), (_, v) = children(c)
        return v.lower() in le.get(a.decode().lower(), [])
    raise AssertionError(f"filter tag {tag:#x} not in fake")


def acl_ok(dn, attr):
    d = dn.lower()
    if d.endswith("," + BRUKERE.lower()):
        return attr in ("lockouttime", "pwdlastset", "useraccountcontrol", "unicodepwd", "displayname", "givenname", "sn",
                        "mail", "description")
    if d.endswith("," + GRUPPER.lower()):
        return attr == "member"
    return False


class LdapHandler(socketserver.BaseRequestHandler):
    def reply(self, mid, op, controls=b""):
        self.request.sendall(seq(integer(mid), op, tlv(0xA0, controls) if controls else b""))

    def result(self, mid, tag, code=0, diag=""):
        self.reply(mid, seq(enum(code), octets(""), octets(diag), tag=tag))

    def handle(self):
        buf = b""
        while True:
            try:
                tag, content, end = read_tlv(buf)
            except ValueError:
                chunk = self.request.recv(65536)
                if not chunk:
                    return
                buf += chunk
                continue
            buf = buf[end:]
            parts = children(content)
            mid, (op_tag, op) = to_int(parts[0][1]), parts[1]
            ctrls = next((c for t, c in parts[2:] if t == 0xA0), b"")
            if Fake.drop_next:
                Fake.drop_next = False
                return  # close without answering → client sees ConnectionLost
            getattr(self, f"op_{op_tag:02x}", lambda m, o, c: self.result(m, 0x65, 2, "unsupported"))(mid, op, ctrls)

    def op_60(self, mid, op, ctrls):  # bind
        p = children(op)
        ok = p[2][1].decode() == Fake.password
        Fake.binds += ok
        self.result(mid, 0x61, 0 if ok else 49, "" if ok else "80090308: LdapErr: data 52e")

    def op_42(self, mid, op, ctrls):  # unbind
        self.request.close()

    def op_63(self, mid, op, ctrls):  # search, with paged results
        p = children(op)
        base, scope = p[0][1].decode().lower(), to_int(p[1][1])
        filt = tlv(p[6][0], p[6][1])
        want = [a.decode().lower() for _, a in children(p[7][1])]
        hits = [(dn, e) for dn, e in Fake.dit.items()
                if (dn.lower() == base if scope == 0 else dn.lower() == base or dn.lower().endswith("," + base)) and match(filt, e)]
        size, start = 0, 0
        for _, ctl in children(ctrls):
            cp = children(ctl)
            if cp[0][1] == ldap.PAGED_OID.encode():
                inner = children(read_tlv(next(v for t, v in cp[1:] if t == 0x04))[1])
                size, start = to_int(inner[0][1]), int(inner[1][1] or b"0")
        page = hits[start:start + size] if size else hits
        for dn, e in page:
            attrs = [seq(octets(k), seq(*[octets(v) for v in vs], tag=0x31)) for k, vs in e.items() if k in want]
            self.reply(mid, seq(octets(dn), seq(*attrs), tag=0x64))
        done = seq(enum(0), octets(""), octets(""), tag=0x65)
        nxt = start + size if size and start + size < len(hits) else 0
        ctl = seq(octets(ldap.PAGED_OID), octets(seq(integer(0), octets(str(nxt).encode() if nxt else b"")))) if size else b""
        self.reply(mid, done, ctl)

    def op_66(self, mid, op, ctrls):  # modify
        p = children(op)
        dn = p[0][1].decode()
        e = next((v for k, v in Fake.dit.items() if k.lower() == dn.lower()), None)
        if e is None:
            return self.result(mid, 0x67, 32)
        for _, ch in children(p[1][1]):
            (_, o), (_, pa) = children(ch)
            kind = to_int(o)
            attr_raw, vals = children(pa)
            attr = attr_raw[1].decode().lower()
            vals = [v for _, v in children(vals[1])]
            if not acl_ok(dn, attr):
                return self.result(mid, 0x67, 50, "00002098: SecErr: DSID-03150F94, problem 4003 (INSUFF_ACCESS_RIGHTS)")
            if attr == "unicodepwd":
                pw = vals[0].decode("utf-16-le")
                if len(pw) < 9:  # quoted, so 7 chars minimum
                    return self.result(mid, 0x67, 19, "0000052D: Constraint violation - check_password_restrictions")
                Fake.passwords[dn.lower()] = pw.strip('"')
                continue
            cur = e.setdefault(attr, [])
            if kind == 0:
                if any(v.lower() in [c.lower() for c in cur] for v in vals):
                    return self.result(mid, 0x67, 68, "00000562: UpdErr: DSID-031A1262, problem 6005 (ENTRY_EXISTS)")
                cur.extend(vals)
            elif kind == 1:
                if not all(v.lower() in [c.lower() for c in cur] for v in vals):
                    return self.result(mid, 0x67, 53, "00000561: SvcErr: DSID-031A1262, problem 5003 (WILL_NOT_PERFORM)")
                e[attr] = [c for c in cur if c.lower() not in [v.lower() for v in vals]]
            else:
                e[attr] = vals
            if attr == "member":  # keep memberOf in step like AD does
                for v in vals:
                    u = next((x for k, x in Fake.dit.items() if k.lower() == v.decode().lower()), None)
                    if u is not None:
                        mo = u.setdefault("memberof", [])
                        if kind == 0:
                            mo.append(dn.encode())
                        else:
                            u["memberof"] = [x for x in mo if x.lower() != dn.lower().encode()]
        self.result(mid, 0x67)

    def op_68(self, mid, op, ctrls):  # add
        p = children(op)
        dn = p[0][1].decode()
        if not dn.lower().endswith("," + BRUKERE.lower()):
            return self.result(mid, 0x69, 50)
        if any(k.lower() == dn.lower() for k in Fake.dit):
            return self.result(mid, 0x69, 68)
        e = {}
        for _, a in children(p[1][1]):
            k, vs = children(a)
            e[k[1].decode().lower()] = [v for _, v in children(vs[1])]
        Fake.passwords[dn.lower()] = e.pop("unicodepwd")[0].decode("utf-16-le").strip('"')
        e["objectcategory"] = [b"person"]
        Fake.dit[dn] = e
        self.result(mid, 0x69)

    def op_4a(self, mid, op, ctrls):  # delete
        dn = op.decode()
        if not dn.lower().endswith("," + BRUKERE.lower()):
            return self.result(mid, 0x6B, 50)
        key = next((k for k in Fake.dit if k.lower() == dn.lower()), None)
        if not key:
            return self.result(mid, 0x6B, 32)
        del Fake.dit[key]
        self.result(mid, 0x6B)


class TCP(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class ConnectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ldap_srv = TCP(("127.0.0.1", 0), LdapHandler)
        threading.Thread(target=cls.ldap_srv.serve_forever, daemon=True).start()
        cls.key = os.urandom(32)
        keyfile = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"ad-test-{os.getpid()}.key")
        with open(keyfile, "w", encoding="ascii") as f:
            f.write(cls.key.hex())
        os.environ.update(LAB_KEY_FILE=keyfile, CONNECTOR_ID="ad", AD_CACHE_S="0")
        import connector  # noqa: E402
        cls.c = connector
        cls.values = {"host": "dc.ad.test", "address": "", "port": 636, "ca_cert": "", "bind_user": "svc@ad.test",
                      "bind_password": "svc-pw", "base_dn": B, "managed_ou": f"OU=Homelab,{B}", "users_ou": BRUKERE,
                      "groups_ou": GRUPPER, "protected": ["owner"]}
        connector.CONF.set({"id": "ad", "ready": True, "values": cls.values, "uses": {}})
        os.unlink(keyfile)
        port = cls.ldap_srv.server_address[1]
        connector.AD_CONN.factory = lambda: socket.create_connection(("127.0.0.1", port), timeout=5)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), connector.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.ldap_srv.shutdown()

    def setUp(self):
        Fake.dit = fixture()
        Fake.passwords = {}
        self.c.AD_CONN.invalidate()

    def call(self, method, path, body=None, role="owner", approved=None, key=None, module="ad"):
        claims = {"u": "owner" if role == "owner" else "admin", "r": role, "g": [], "m": module}
        if approved:
            claims["a"] = approved
        h = {labauth.HEADER: labauth.sign(key or self.key, claims), "Content-Type": "application/json"}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_port}{path}", data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def directory(self):
        code, d = self.call("GET", "/api/directory?fresh=1")
        self.assertEqual(code, 200, d)
        return d

    def user(self, sam):
        return next((u for u in self.directory()["users"] if u["sam"] == sam), None)

    # --- reads
    def test_directory_shape(self):
        d = self.directory()
        self.assertEqual([u["sam"] for u in d["users"]], ["Administrator", "alice", "owner", "svc-x"])
        a = next(u for u in d["users"] if u["sam"] == "alice")
        self.assertTrue(a["locked"] and a["enabled"] and a["managed"])
        self.assertEqual((a["pwdExpires"], a["lastLogon"], a["lockoutTime"]), (1794900000, 1794500000, 1794590000))
        self.assertEqual(([g["name"] for g in a["groups"]], a["primaryGroup"], a["changed"]), (["staff"], "Domain Users", 1794560400))
        e = next(u for u in d["users"] if u["sam"] == "owner")
        self.assertTrue(e["mustChange"] and e["undeletable"])
        self.assertEqual(e["pwdExpires"], 0)
        s = next(u for u in d["users"] if u["sam"] == "svc-x")
        self.assertTrue(s["pwdNeverExpires"] and s["service"] and not s["managed"])
        self.assertIsNone(s["pwdExpires"])
        adm = next(u for u in d["users"] if u["sam"] == "Administrator")
        self.assertTrue(adm["system"] and adm["protected"])
        self.assertEqual([(c["name"], c["os"], c["lastLogon"], c["inHomelab"]) for c in d["computers"]],
                         [("PC1", "Windows 11 Pro", 1794000000, True)])
        staff = next(g for g in d["groups"] if g["name"] == "staff")
        self.assertEqual((staff["managed"], staff["scope"], staff["kind"]), (True, "global", "security"))
        self.assertEqual(d["policy"]["maxPwdAge"], 42 * 86400)
        self.assertEqual(d["policy"]["lockoutThreshold"], 5)
        self.assertIn(f"OU=Brukere,OU=Homelab,{B}", [o["dn"] for o in d["ous"]])
        self.assertNotIn("svc-pw", json.dumps(d))

    def test_paging(self):
        for i in range(1203):
            Fake.dit[f"CN=g{i},{GRUPPER}"] = entry(objectClass="group", cn=f"g{i}", groupType="-2147483646")
        self.assertEqual(len(self.directory()["groups"]), 1205)

    def test_auth(self):
        self.assertEqual(self.call("GET", "/api/directory", key=os.urandom(32))[0], 401)
        self.assertEqual(self.call("GET", "/api/directory", module="authentik")[0], 401)
        self.assertEqual(self.call("GET", "/api/directory", role="guest")[0], 401)
        self.assertEqual(self.call("GET", "/api/directory", role="admin")[0], 200)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.srv.server_port}/healthz") as r:
            self.assertEqual(json.loads(r.read()), {"ok": True})

    def test_writes_owner_only(self):
        self.assertEqual(self.call("POST", "/api/users/alice/unlock", role="admin"), (403, {"error": "owner only"}))
        self.assertEqual(self.call("POST", "/api/users/alice/unlock", role="guest")[0], 403)
        self.assertEqual(self.call("POST", "/api/users/alice/password", {"password": "Typed-Pass-1"}, role="admin", approved="owner")[0], 400)
        code, r = self.call("POST", "/api/users/alice/unlock", role="admin", approved="owner")
        self.assertEqual(code, 200, r)
        self.assertEqual(Fake.dit[f"CN=alice,{BRUKERE}"]["lockouttime"], [b"0"])

    # --- writes
    def test_enable_disable_keeps_other_bits(self):
        Fake.dit[f"CN=alice,{BRUKERE}"]["useraccountcontrol"] = [b"66048"]
        self.assertEqual(self.call("POST", "/api/users/alice/disable")[0], 200)
        self.assertEqual(Fake.dit[f"CN=alice,{BRUKERE}"]["useraccountcontrol"], [b"66050"])
        self.assertEqual(self.call("POST", "/api/users/alice/enable")[0], 200)
        self.assertEqual(Fake.dit[f"CN=alice,{BRUKERE}"]["useraccountcontrol"], [b"66048"])

    def test_password_generated_and_typed(self):
        code, r = self.call("POST", "/api/users/alice/password", {})
        self.assertEqual(code, 200, r)
        self.assertEqual(Fake.passwords[f"cn=alice,{BRUKERE}".lower()], r["password"])
        self.assertEqual(len(r["password"]), 20)
        self.assertEqual(Fake.dit[f"CN=alice,{BRUKERE}"]["pwdlastset"], [b"0"])
        code, r = self.call("POST", "/api/users/alice/password", {"password": "Typed-Pass-1", "mustChange": False})
        self.assertEqual((code, "password" in r), (200, False))
        self.assertEqual(Fake.dit[f"CN=alice,{BRUKERE}"]["pwdlastset"], [b"-1"])
        code, r = self.call("POST", "/api/users/alice/password", {"password": "short"})
        self.assertEqual(code, 422)
        self.assertIn("policy", r["error"])

    def test_scope_enforced_by_connector(self):
        self.assertEqual(self.call("POST", "/api/users/svc-x/disable")[0], 403)
        self.assertEqual(self.call("POST", "/api/users/Administrator/password", {})[0], 403)
        self.assertEqual(self.call("POST", "/api/users/alice/groups/Domain%20Admins")[0], 403)
        self.assertEqual(self.call("POST", "/api/users/nobody/unlock")[0], 404)
        self.assertEqual(self.call("POST", "/api/users/owner/disable")[0], 403)
        self.assertEqual(self.call("POST", "/api/users/bad*sam/unlock")[0], 400)

    def test_groups(self):
        self.assertEqual(self.call("DELETE", "/api/users/alice/groups/staff")[1]["member"], False)
        self.assertEqual(self.user("alice")["groups"], [])
        self.assertTrue(self.call("DELETE", "/api/users/alice/groups/staff")[1]["noop"])
        self.assertEqual(self.call("POST", "/api/users/alice/groups/staff")[1]["member"], True)
        self.assertTrue(self.call("POST", "/api/users/alice/groups/staff")[1]["noop"])

    def test_edit(self):
        self.assertEqual(self.call("PATCH", "/api/users/alice", {"displayName": "Alice B", "mail": "a@x.no"})[0], 200)
        self.assertEqual((self.user("alice")["name"], self.user("alice")["mail"]), ("Alice B", "a@x.no"))
        self.assertEqual(self.call("PATCH", "/api/users/alice", {"userAccountControl": "0"})[0], 400)

    def test_create_and_delete(self):
        code, r = self.call("POST", "/api/users", {"sam": "lab-test-1", "given": "Lab", "sn": "Test", "groups": ["staff"]})
        self.assertEqual(code, 200, r)
        self.assertEqual((r["dn"], r["mustChange"], r["warnings"]), (f"CN=lab-test-1,{BRUKERE}", True, []))
        e = Fake.dit[r["dn"]]
        self.assertEqual((e["userprincipalname"], e["useraccountcontrol"], e["pwdlastset"], e["displayname"]),
                         ([b"lab-test-1@ad.test"], [b"512"], [b"0"], [b"Lab Test"]))
        self.assertEqual(Fake.passwords[r["dn"].lower()], r["password"])
        self.assertIn(r["dn"].encode(), Fake.dit[f"CN=staff,{GRUPPER}"]["member"])
        self.assertEqual(self.call("POST", "/api/users", {"sam": "lab-test-1"})[0], 409)
        self.assertEqual(self.call("POST", "/api/users", {"sam": "x", "groups": ["Domain Admins"]})[0], 403)
        self.assertNotIn(f"CN=x,{BRUKERE}", Fake.dit)  # nothing created when a group is refused
        self.assertEqual(self.call("POST", "/api/users", {"sam": "bad name"})[0], 400)
        self.assertEqual(self.call("DELETE", "/api/users/lab-test-1")[0], 400)
        self.assertEqual(self.call("DELETE", "/api/users/lab-test-1", {"confirm": "lab-test-2"})[0], 400)
        self.assertEqual(self.call("DELETE", "/api/users/lab-test-1?confirm=lab-test-1")[0], 200)
        self.assertIsNone(self.user("lab-test-1"))
        self.assertEqual(self.call("DELETE", "/api/users/owner?confirm=owner")[0], 403)
        code, r = self.call("POST", "/api/users", {"sam": "lab-test-2", "enabled": False, "mustChange": False, "password": "Given-Pass-9"})
        self.assertEqual((code, "password" in r), (200, False))
        self.assertEqual(Fake.dit[r["dn"]]["useraccountcontrol"], [b"514"])
        code, r = self.call("DELETE", "/api/users/lab-test-2", {"confirm": "lab-test-2"}, role="admin", approved="owner")
        self.assertEqual(code, 200, r)

    def test_reconnect_after_drop(self):
        self.directory()
        n = Fake.binds
        Fake.drop_next = True
        self.directory()
        self.assertEqual(Fake.binds, n + 1)

    def test_bad_bind(self):
        Fake.password = "other"
        self.c.AD_CONN.conn and self.c.AD_CONN.conn.close()
        self.c.AD_CONN.conn = None
        try:
            code, r = self.call("GET", "/api/directory?fresh=1")
            self.assertEqual(code, 502)
            self.assertIn("bind as svc refused", r["error"])
            self.assertNotIn("svc-pw", r["error"])
        finally:
            Fake.password = "svc-pw"

    def test_config_scope_and_validate(self):
        self.assertEqual((self.c.DOMAIN, self.c.MANAGED, self.c.PROTECTED), ("ad.test", f"OU=Homelab,{B}", {"owner"}))
        st = self.c.settings_of({**self.values, "users_ou": f"OU=Elsewhere,{B}"})
        self.assertIn("inside managed_ou", self.c.scope_problem(st))
        self.assertIsNone(self.c.scope_problem(self.c.settings_of(self.values)))
        code, r = self.call("POST", "/api/_validate", body={"values": self.values}, role="admin")
        self.assertEqual(code, 403)
        # the candidate is used as given: an unreachable DC is a failed test, not an error, and no password comes back
        code, r = self.call("POST", "/api/_validate", body={"values": {**self.values, "host": "127.0.0.1", "port": 1}})
        self.assertEqual((code, r["ok"]), (200, False))
        self.assertNotIn("svc-pw", json.dumps(r))

    def test_helpers(self):
        self.assertIsNone(self.c.filetime("0"))
        self.assertIsNone(self.c.filetime(str(ldap_never())))
        self.assertEqual(self.c.filetime(ft(1794600000)), 1794600000)
        self.assertEqual(self.c.gentime("20261113090000.0Z"), 1794560400)
        self.assertEqual(self.c.parent("CN=Doe\\, J,OU=A,DC=x"), "OU=A,DC=x")
        self.assertEqual(self.c.rdn("CN=Doe\\, J,OU=A,DC=x"), "Doe, J")
        self.assertTrue(self.c.under("CN=a,OU=Brukere,OU=Homelab,DC=x", "OU=Brukere,OU=Homelab,DC=x"))
        self.assertTrue(self.c.under("CN=a,OU=Sub,OU=Brukere,OU=Homelab,DC=x", "ou=brukere,ou=homelab,dc=x"))
        self.assertFalse(self.c.under("OU=Brukere,OU=Homelab,DC=x", "OU=Brukere,OU=Homelab,DC=x"))
        # an OU named "Sub,OU=Brukere" directly under Homelab is NOT inside Brukere (security review 2026-11-14)
        self.assertFalse(self.c.under("CN=a,OU=Sub\\,OU=Brukere,OU=Homelab,DC=x", "OU=Brukere,OU=Homelab,DC=x"))
        p = self.c.gen_password()
        self.assertTrue(any(ch.isupper() for ch in p) and any(ch.isdigit() for ch in p) and len(p) == 20)


if __name__ == "__main__":
    unittest.main()
