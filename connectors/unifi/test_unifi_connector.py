"""Offline tests for connectors/unifi (your router is stubbed). Run: python3 -m unittest discover -s connectors/unifi"""
import importlib.util
import os
import secrets
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_kf = tempfile.NamedTemporaryFile("w", suffix=".key", delete=False)
_kf.write(secrets.token_hex(32))
_kf.close()
os.environ.update(LAB_KEY_FILE=_kf.name, CONNECTOR_ID="unifi")
spec = importlib.util.spec_from_file_location("unifi_connector", os.path.join(HERE, "connector.py"))
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)
C.CONF.set({"id": "unifi", "ready": True, "uses": {},  # what the gateway hands it (GET /api/connector/config)
            "values": {"url": "https://console.test", "username": "x", "password": "y", "site": "default", "verify_tls": False}})

MGMT = {"_id": "m", "name": "Management", "purpose": "corporate", "ip_subnet": "192.0.2.1/24", "x_wireguard_private_key": "SECRET"}
NETS = [MGMT, {"_id": "w", "name": "WG", "purpose": "remote-user-vpn", "ip_subnet": "192.168.2.1/24", "x_wireguard_private_key": "SECRET"}]
KNOWN = [{"_id": "u1", "mac": "aa:aa:aa:aa:aa:01", "name": "lab (CT 132)", "use_fixedip": True, "fixed_ip": "192.0.2.73", "network_id": "m"},
         {"_id": "u2", "mac": "aa:aa:aa:aa:aa:02", "name": "old", "last_ip": "192.0.2.80", "last_seen": time.time() - 3600},
         {"_id": "u3", "mac": "aa:aa:aa:aa:aa:03", "name": "new"}]
ACTIVE = [{"mac": "aa:aa:aa:aa:aa:04", "ip": "192.0.2.90", "network_id": "m"}]
DEVICES = [{"mac": "dd:dd:dd:dd:dd:01", "name": "ap-1", "type": "uap", "state": 1}, {"mac": "dd:dd:dd:dd:dd:02", "name": "udr", "type": "udm", "state": 1}]
PFWDS = [{"_id": "d" * 24, "name": "mail", "enabled": True, "proto": "tcp_udp", "dst_port": "25,465,587", "fwd_port": "25,465,587", "fwd": "192.0.2.27"},
         {"_id": "a" * 24, "name": "https", "enabled": True, "proto": "tcp", "dst_port": "443", "fwd_port": "443", "fwd": "192.0.2.20", "src": "any", "pfwd_interface": "wan"},
         {"_id": "b" * 24, "name": "off", "enabled": False, "proto": "tcp", "dst_port": "8080", "fwd_port": "80", "fwd": "192.0.2.21"},
         {"_id": "c" * 24, "name": "game", "enabled": True, "proto": "udp", "dst_port": "27000-27010", "fwd_port": "27000-27010", "fwd": "192.0.2.22"}]


class Stub:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET":
            return {"api/s/{site}/rest/networkconf": NETS, "api/s/{site}/rest/user": KNOWN, "api/s/{site}/stat/sta": ACTIVE,
                    "api/s/{site}/stat/device": DEVICES, "api/s/{site}/rest/portforward": PFWDS}.get(path, [])
        return [{}]


class Reservations(unittest.TestCase):
    def setUp(self):
        self.stub = Stub()
        C.UNIFI.call = self.stub
        C.invalidate()
        _, self.raw = C.fetch(force=True)

    def test_secrets_never_leave(self):
        data, _ = C.fetch(force=True)
        self.assertNotIn("SECRET", repr(data))

    def test_checks(self):
        mac = "aa:aa:aa:aa:aa:03"
        for ip, code in (("192.0.2.73", 409), ("192.0.2.90", 409), ("192.0.2.80", 409), ("192.0.2.1", 400), ("192.0.2.255", 400),
                         ("192.168.50.4", 400), ("nonsense", 400)):
            with self.assertRaises(C.UnifiError) as e:
                C.check_reservation(self.raw, mac, ip)
            self.assertEqual(e.exception.code, code, ip)
        self.assertEqual(C.check_reservation(self.raw, mac, "192.0.2.74")["_id"], "m")
        self.assertEqual(C.check_reservation(self.raw, "aa:aa:aa:aa:aa:01", "192.0.2.73")["_id"], "m")  # its own address

    def test_reserve_put_or_post(self):
        C.reserve({"u": "t"}, "aa:aa:aa:aa:aa:03", {"ip": "192.0.2.74", "name": "x"})
        self.assertIn(("PUT", "api/s/{site}/rest/user/u3", {"use_fixedip": True, "fixed_ip": "192.0.2.74", "network_id": "m", "name": "x"}), self.stub.calls)
        C.reserve({"u": "t"}, "bb:bb:bb:bb:bb:01", {"ip": "192.0.2.75"})
        self.assertIn(("POST", "api/s/{site}/rest/user", {"mac": "bb:bb:bb:bb:bb:01", "use_fixedip": True, "fixed_ip": "192.0.2.75", "network_id": "m"}), self.stub.calls)
        with self.assertRaises(C.UnifiError):
            C.clean_mac("zz:zz")


class Setup(unittest.TestCase):
    def setUp(self):
        self.stub = Stub()
        C.UNIFI.call = self.stub
        C.invalidate()

    def posts(self):
        return [c for c in self.stub.calls if c[0] != "GET"]

    def code(self, fn, *a):
        with self.assertRaises(C.UnifiError) as e:
            fn(*a)
        return e.exception.code


class BlockRestart(Setup):
    T = {"u": "t"}

    def test_block_unblock(self):
        C.set_blocked(self.T, "aa:aa:aa:aa:aa:03", True)
        C.set_blocked(self.T, "aa:aa:aa:aa:aa:04", False)  # active-only client
        self.assertEqual(self.posts(), [("POST", "api/s/{site}/cmd/stamgr", {"cmd": "block-sta", "mac": "aa:aa:aa:aa:aa:03"}),
                                        ("POST", "api/s/{site}/cmd/stamgr", {"cmd": "unblock-sta", "mac": "aa:aa:aa:aa:aa:04"})])

    def test_block_refusals(self):
        self.assertEqual(self.code(C.set_blocked, self.T, "ee:ee:ee:ee:ee:ee", True), 404)
        self.assertEqual(self.code(C.set_blocked, self.T, "dd:dd:dd:dd:dd:02", True), 400)  # the gateway itself
        self.assertEqual(self.posts(), [])

    def test_restart_only_access_points(self):
        C.restart_ap(self.T, "dd:dd:dd:dd:dd:01")
        self.assertEqual(self.posts(), [("POST", "api/s/{site}/cmd/devmgr", {"cmd": "restart", "mac": "dd:dd:dd:dd:dd:01"})])
        self.stub.calls.clear()
        self.assertEqual(self.code(C.restart_ap, self.T, "dd:dd:dd:dd:dd:02"), 400)  # your router
        self.assertEqual(self.code(C.restart_ap, self.T, "ee:ee:ee:ee:ee:ee"), 404)
        self.assertEqual(self.posts(), [])


class PortForwards(Setup):
    T = {"u": "t"}
    ok = {"name": "web", "proto": "tcp", "dstPort": "8443", "fwdPort": "443", "fwdIp": "192.0.2.30"}

    def test_list_shape(self):
        out = [C.pf_out(p) for p in PFWDS]
        self.assertEqual(out[1], {"id": "a" * 24, "name": "https", "enabled": True, "proto": "tcp", "dstPort": "443", "fwdPort": "443",
                                  "fwdIp": "192.0.2.20", "src": "any", "iface": "wan", "log": False})
        self.assertFalse(out[2]["enabled"])

    def test_add(self):
        C.add_portforward(self.T, self.ok)
        self.assertEqual(self.posts(), [("POST", "api/s/{site}/rest/portforward", {
            "name": "web", "enabled": True, "pfwd_interface": "wan", "src": "any", "dst_port": "8443", "fwd_port": "443",
            "fwd": "192.0.2.30", "proto": "tcp", "log": False})])

    def test_refused(self):
        bad = {"missing name": ({**self.ok, "name": " "}, 400), "port 0": ({**self.ok, "dstPort": "0"}, 400),
               "port 70000": ({**self.ok, "dstPort": "70000"}, 400), "text port": ({**self.ok, "dstPort": "80; drop"}, 400),
               "reversed range": ({**self.ok, "dstPort": "90-80"}, 400), "proto": ({**self.ok, "proto": "icmp"}, 400),
               "range sizes": ({**self.ok, "dstPort": "100-110", "fwdPort": "100"}, 400),
               "outside the LAN": ({**self.ok, "fwdIp": "8.8.8.8"}, 400), "gateway": ({**self.ok, "fwdIp": "192.0.2.1"}, 400),
               "broadcast": ({**self.ok, "fwdIp": "192.0.2.255"}, 400), "not an ip": ({**self.ok, "fwdIp": "web"}, 400),
               "taken tcp": ({**self.ok, "dstPort": "443"}, 409), "inside a range": ({**self.ok, "proto": "udp", "dstPort": "27005"}, 409),
               "in a list": ({**self.ok, "dstPort": "465"}, 409), "list overlap": ({**self.ok, "dstPort": "1,587", "fwdPort": "1,2"}, 409),
               "bad list": ({**self.ok, "dstPort": "80,,443", "fwdPort": "80,443"}, 400), "list sizes": ({**self.ok, "dstPort": "9000,9001", "fwdPort": "9000"}, 400),
               "tcp_udp vs udp": ({**self.ok, "proto": "tcp_udp", "dstPort": "27001-27002", "fwdPort": "100-101"}, 409)}
        for what, (b, code) in bad.items():
            self.assertEqual(self.code(C.add_portforward, self.T, b), code, what)
        self.assertEqual(self.posts(), [])

    def test_list_ports_are_normalised(self):
        C.add_portforward(self.T, {**self.ok, "dstPort": "9000, 9002-9003", "fwdPort": "9000,9002-9003"})
        self.assertEqual(self.posts()[0][2]["dst_port"], "9000,9002-9003")

    def test_disabled_forward_does_not_block_its_port(self):
        C.add_portforward(self.T, {**self.ok, "dstPort": "8080", "fwdPort": "8080"})
        self.assertEqual(len(self.posts()), 1)

    def test_remove(self):
        C.remove_portforward({"u": "t", "a": "owner"}, "a" * 24)
        self.assertEqual(self.posts(), [("DELETE", f"api/s/{{site}}/rest/portforward/{'a' * 24}", None)])
        self.stub.calls.clear()
        self.assertEqual(self.code(C.remove_portforward, self.T, "f" * 24), 404)
        self.assertEqual(self.posts(), [])


class Policy(unittest.TestCase):
    def test_who_may_call_what(self):
        table = {(m, rx.pattern): (role, owner) for m, rx, role, owner, _ in C.ROUTES}
        want = {("POST", "^/api/clients/([0-9a-fA-F:-]{17})/block/?$"): ("admin", False),
                ("POST", "^/api/clients/([0-9a-fA-F:-]{17})/unblock/?$"): ("admin", False),
                ("POST", "^/api/devices/([0-9a-fA-F:-]{17})/restart/?$"): ("admin", False),
                ("GET", "^/api/portforwards/?$"): ("admin", False),
                ("POST", "^/api/portforwards/?$"): ("guest", True),
                ("DELETE", "^/api/portforwards/([0-9a-f]{24})/?$"): ("guest", True)}
        for k, v in want.items():
            self.assertEqual(table.get(k), v, k)

    def test_owner_gate(self):
        self.assertTrue(C.owner_ok({"r": "owner"}))
        self.assertTrue(C.owner_ok({"r": "admin", "a": "owner"}))  # approved by the owner
        self.assertFalse(C.owner_ok({"r": "admin"}))


if __name__ == "__main__":
    unittest.main()
