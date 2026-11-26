"""Labradoor connector `unifi`: the UniFi Network app on a UniFi OS console (cookie + CSRF login) behind the gateway.

Read: clients (known + active, with fixed-IP reservations), devices, networks/VLANs, WAN health — whitelisted fields only
(network configs carry WireGuard/IPsec keys and Wi-Fi passphrases live in wlanconf; neither ever leaves here).
Write: DHCP reservations (admin: add/change; owner: remove), client names, block/unblock a client and restart an
access point (admin), port forwards (list: admin; add/remove: owner). Reservations are checked against the subnet,
other reservations and active leases first (a ping is not enough: a sleeping client doesn't answer); a port
forward must point at an address inside one of our LAN networks.

Config (module config, from the gateway — connectors/README.md): url (the console, e.g. https://192.168.1.1),
username, password (a local console account), site (default "default"), verify_tls.
"""
import http.cookiejar
import ipaddress
import json
import logging
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/opt/lab/sdk/python")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdk", "python"))
import labauth  # noqa: E402
import labconn  # noqa: E402

ID = os.environ.get("CONNECTOR_ID", "unifi")
PORT = int(os.environ.get("PORT", "8111"))
KEY = labconn.load_key(ID)
CACHE_S = 10
log = logging.getLogger(ID)
MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


class UnifiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


class Unifi:
    def __init__(self, url="", user="", password="", site="default", verify=True):
        self.url, self.user, self.password, self.site = (url or "").rstrip("/"), user, password, site or "default"
        ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx),
                                              urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf, self.logged, self.last_ok = "", 0.0, 0.0
        self.lock = threading.Lock()

    def _raw(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "lab-connector-unifi/1"}
        if self.csrf:
            h["X-CSRF-Token"] = self.csrf
        if not self.url:
            raise UnifiError(503, "no UniFi console URL configured")
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=h)
        try:
            with self.op.open(req, timeout=20) as r:
                new = r.headers.get("X-Updated-CSRF-Token") or r.headers.get("x-csrf-token")
                if new:
                    self.csrf = new
                raw = r.read()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read()[:2000]
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"meta": {"msg": raw.decode("utf-8", "replace")[:200]}}
        except (OSError, ValueError) as e:
            raise UnifiError(502, f"unifi unreachable: {e}") from None

    def login(self):
        if not (self.user and self.password):
            raise UnifiError(503, "no UniFi login configured")
        self.jar.clear()
        self.csrf = ""
        code, _ = self._raw("POST", "/api/auth/login", {"username": self.user, "password": self.password, "remember": True})
        if code != 200:
            raise UnifiError(502, f"unifi login failed ({code})")
        self.logged = time.time()

    def call(self, method, path, body=None):
        """path relative to the Network app, e.g. 'api/s/{site}/rest/user' → /proxy/network/api/s/default/rest/user."""
        full = "/proxy/network/" + path.format(site=self.site)
        with self.lock:
            if not self.logged or time.time() - self.logged > 3600:
                self.login()
        code, r = self._raw(method, full, body)
        if code == 401:
            with self.lock:
                self.login()
            code, r = self._raw(method, full, body)
        if code >= 400 or (isinstance(r, dict) and (r.get("meta") or {}).get("rc") == "error"):
            msg = (r.get("meta") or {}).get("msg") if isinstance(r, dict) else None
            raise UnifiError(code if 400 <= code < 500 else 502, msg or f"unifi {code}")
        self.last_ok = time.time()
        return r.get("data", r) if isinstance(r, dict) and "data" in r else r


def client(v):
    return Unifi(labconn.url(v, "url"), labconn.text(v, "username"), labconn.text(v, "password"),
                 labconn.text(v, "site", "default") or "default", v.get("verify_tls") is not False)


UNIFI = Unifi()


def configure(v, conf=None):
    global UNIFI
    UNIFI = client(v)


CONF = labconn.Config(ID, KEY, apply=configure)


def validate(values):
    """Config test: log in with the CANDIDATE values and read the site's health."""
    u = client(values)
    try:
        u.login()
        u.call("GET", "api/s/{site}/stat/health")
    except UnifiError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "detail": f"logged in, site {u.site}"}


# --- translation -------------------------------------------------------------------------------------------------
def net_out(n):
    out = {"id": n["_id"], "name": n.get("name"), "purpose": n.get("purpose"), "vlan": n.get("vlan"),
           "enabled": n.get("enabled", True), "subnet": n.get("ip_subnet")}
    if n.get("purpose") in ("corporate", "guest"):
        out.update({"dhcp": bool(n.get("dhcpd_enabled")), "dhcpStart": n.get("dhcpd_start"), "dhcpStop": n.get("dhcpd_stop"),
                    "domain": n.get("domain_name"), "isolated": bool(n.get("network_isolation_enabled")),
                    "internet": n.get("internet_access_enabled", True), "igmp": bool(n.get("igmp_snooping"))})
    if n.get("purpose") == "wan":
        out.update({"wanType": n.get("wan_type"), "wanName": n.get("wan_networkgroup")})
    return out


def dev_out(d):
    ss = d.get("system-stats") or {}
    return {"mac": d.get("mac"), "name": d.get("name") or d.get("model"), "model": d.get("model"), "type": d.get("type"),
            "ip": d.get("ip") if d.get("type") != "udm" else None, "state": d.get("state"), "online": d.get("state") == 1,
            "version": d.get("version"), "upgradable": bool(d.get("upgradable")), "uptime": d.get("uptime"),
            "clients": d.get("num_sta"), "cpu": _num(ss.get("cpu")), "mem": _num(ss.get("mem")),
            "lastSeen": d.get("last_seen"), "adopted": d.get("adopted")}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def client_out(known, active, nets):
    k, a = known or {}, active or {}
    nid = a.get("network_id") or k.get("network_id") or k.get("last_connection_network_id")
    net = nets.get(nid) or {}
    return {
        "mac": (a.get("mac") or k.get("mac") or "").lower(), "id": k.get("_id") or a.get("user_id"),
        "name": a.get("name") or k.get("name"), "hostname": a.get("hostname") or k.get("hostname"),
        "ip": a.get("ip") or k.get("last_ip"), "online": bool(a), "reserved": bool(k.get("use_fixedip") or a.get("use_fixedip")),
        "fixedIp": k.get("fixed_ip") or a.get("fixed_ip"), "networkId": nid,
        "network": net.get("name") or a.get("network") or k.get("last_connection_network_name"), "vlan": net.get("vlan"),
        "wired": bool(a.get("is_wired", k.get("is_wired"))), "guest": bool(a.get("is_guest", k.get("is_guest"))),
        "blocked": bool(k.get("blocked") or a.get("blocked")),
        "vendor": a.get("oui") or k.get("oui"), "note": k.get("note") or "",
        "firstSeen": k.get("first_seen") or a.get("first_seen"), "lastSeen": a.get("last_seen") or k.get("last_seen"),
        "uptime": a.get("uptime"), "essid": a.get("essid"), "signal": a.get("signal"), "satisfaction": a.get("satisfaction"),
        "uplink": a.get("last_uplink_name") or k.get("last_uplink_name"), "swPort": a.get("sw_port"),
        "rxRate": a.get("rx_rate"), "txRate": a.get("tx_rate"), "rxBytes": a.get("rx_bytes"), "txBytes": a.get("tx_bytes"),
    }


def health_out(hs):
    out = {}
    for h in hs or []:
        sub = h.get("subsystem")
        if sub == "wan":
            out["wan"] = {"status": h.get("status"), "latency": h.get("latency") or (h.get("uptime_stats") or {}).get("WAN", {}).get("latency_average"),
                          "uptime": (h.get("gw_system-stats") or {}).get("uptime") or h.get("uptime"), "isp": h.get("isp_name"),
                          "drops": h.get("drops"), "rx": h.get("rx_bytes-r"), "tx": h.get("tx_bytes-r"),
                          "gwVersion": h.get("gw_version"), "clients": h.get("num_sta")}
        elif sub in ("lan", "wlan", "www", "vpn"):
            out[sub] = {"status": h.get("status"), "clients": h.get("num_user", h.get("num_sta")),
                        "guests": h.get("num_guest"), "aps": h.get("num_ap"), "switches": h.get("num_sw"),
                        "latency": h.get("latency"), "speedtest": h.get("xput_down"), "remoteUsers": h.get("remote_user_num_active")}
    return out


_cache = {"at": 0.0, "data": None, "raw": None}
_lock = threading.Lock()


def fetch(force=False):
    with _lock:
        if not force and _cache["data"] and time.time() - _cache["at"] < CACHE_S:
            return _cache["data"], _cache["raw"]
    nets_raw = UNIFI.call("GET", "api/s/{site}/rest/networkconf")
    known = UNIFI.call("GET", "api/s/{site}/rest/user")
    active = UNIFI.call("GET", "api/s/{site}/stat/sta")
    devs = UNIFI.call("GET", "api/s/{site}/stat/device")
    health = UNIFI.call("GET", "api/s/{site}/stat/health")
    nets = {n["_id"]: n for n in nets_raw}
    by_mac = {}
    for k in known:
        if k.get("mac"):
            by_mac[k["mac"].lower()] = [k, None]
    for a in active:
        if a.get("mac"):
            by_mac.setdefault(a["mac"].lower(), [None, None])[1] = a
    clients = [client_out(k, a, nets) for k, a in by_mac.values()]
    data = {"at": int(time.time()), "networks": [net_out(n) for n in nets_raw], "devices": [dev_out(d) for d in devs],
            "clients": sorted(clients, key=lambda c: (not c["online"], not c["reserved"], c["name"] or c["hostname"] or c["mac"])),
            "health": health_out(health)}
    raw = {"known": {k["mac"].lower(): k for k in known if k.get("mac")}, "active": active, "nets": nets,
           "devices": {d["mac"].lower(): d for d in devs if d.get("mac")}}
    with _lock:
        _cache.update(at=time.time(), data=data, raw=raw)
    return data, raw


def invalidate():
    with _lock:
        _cache["at"] = 0.0


# --- reservations ------------------------------------------------------------------------------------------------
def check_reservation(raw, mac, ip, network_id=None):
    """→ the network the IP belongs to; raises when the address is not a sane, free host address."""
    try:
        addr = ipaddress.IPv4Address(str(ip).strip())
    except ValueError:
        raise UnifiError(400, "ip: an IPv4 address") from None
    net = None
    for n in raw["nets"].values():
        if n.get("purpose") not in ("corporate", "guest") or not n.get("ip_subnet"):
            continue
        iface = ipaddress.IPv4Interface(n["ip_subnet"])
        if addr in iface.network:
            net = n
            if addr in (iface.ip, iface.network.network_address, iface.network.broadcast_address):
                raise UnifiError(400, f"{addr} is the gateway/network/broadcast address of {n.get('name')}")
            break
    if not net:
        raise UnifiError(400, f"{addr} is not in any of our LAN networks")
    if network_id and network_id != net["_id"]:
        raise UnifiError(400, f"{addr} belongs to {net.get('name')}, not the chosen network")
    for kmac, k in raw["known"].items():
        if kmac != mac and k.get("use_fixedip") and k.get("fixed_ip") == str(addr):
            raise UnifiError(409, f"{addr} is already reserved for {k.get('name') or k.get('hostname') or kmac}")
    for a in raw["active"]:
        if (a.get("mac") or "").lower() != mac and a.get("ip") == str(addr):
            raise UnifiError(409, f"{addr} is in use right now by {a.get('name') or a.get('hostname') or a.get('mac')}")
    day = time.time() - 86400
    for kmac, k in raw["known"].items():
        if kmac != mac and k.get("last_ip") == str(addr) and (k.get("last_seen") or 0) > day:
            raise UnifiError(409, f"{addr} was leased to {k.get('name') or k.get('hostname') or kmac} in the last 24 h")
    return net


def clean_mac(m):
    m = str(m or "").strip().lower().replace("-", ":")
    if not MAC_RE.match(m):
        raise UnifiError(400, "mac: aa:bb:cc:dd:ee:ff")
    return m


def clean_name(n):
    n = str(n or "").strip()
    if len(n) > 80 or any(ord(ch) < 32 for ch in n):
        raise UnifiError(400, "name: up to 80 printable characters")
    return n


def reserve(claims, mac, b):
    _, raw = fetch(force=True)
    net = check_reservation(raw, mac, b.get("ip"), b.get("networkId"))
    body = {"use_fixedip": True, "fixed_ip": str(ipaddress.IPv4Address(str(b["ip"]).strip())), "network_id": net["_id"]}
    if b.get("name"):
        body["name"] = clean_name(b["name"])
    k = raw["known"].get(mac)
    if k:
        UNIFI.call("PUT", f"api/s/{{site}}/rest/user/{k['_id']}", body)
    else:
        UNIFI.call("POST", "api/s/{site}/rest/user", {"mac": mac, **body})
    log.info("%s reserved %s → %s (%s)", claims["u"], mac, body["fixed_ip"], net.get("name"))
    invalidate()
    return {"ok": True, "mac": mac, "ip": body["fixed_ip"], "network": net.get("name")}


# --- block / restart ---------------------------------------------------------------------------------------------
def _known_client(raw, mac):
    return raw["known"].get(mac) or next((a for a in raw["active"] if (a.get("mac") or "").lower() == mac), None)


def set_blocked(claims, mac, blocked):
    _, raw = fetch(force=True)
    if mac in raw["devices"]:
        raise UnifiError(400, "that is a UniFi device, not a client")
    c = _known_client(raw, mac)
    if not c:
        raise UnifiError(404, "unknown client")
    UNIFI.call("POST", "api/s/{site}/cmd/stamgr", {"cmd": "block-sta" if blocked else "unblock-sta", "mac": mac})
    log.info("%s %s client %s (%s)", claims["u"], "BLOCKED" if blocked else "unblocked", mac, c.get("name") or c.get("hostname") or "-")
    invalidate()
    return {"ok": True, "mac": mac, "blocked": blocked}


def restart_ap(claims, mac):
    _, raw = fetch(force=True)
    d = raw["devices"].get(mac)
    if not d:
        raise UnifiError(404, "unknown device")
    if d.get("type") != "uap":
        raise UnifiError(400, f"only access points can be restarted here (this is a {d.get('type') or 'device'})")
    UNIFI.call("POST", "api/s/{site}/cmd/devmgr", {"cmd": "restart", "mac": mac})
    log.info("%s restarted access point %s (%s)", claims["u"], mac, d.get("name") or "-")
    invalidate()
    return {"ok": True, "mac": mac}


# --- port forwards -----------------------------------------------------------------------------------------------
PROTOS = ("tcp", "udp", "tcp_udp")
ID_RE = re.compile(r"^[0-9a-f]{24}$")


def pf_out(p):
    return {"id": p.get("_id"), "name": p.get("name"), "enabled": bool(p.get("enabled", True)), "proto": p.get("proto"),
            "dstPort": str(p.get("dst_port", "")), "fwdPort": str(p.get("fwd_port", "")), "fwdIp": p.get("fwd"),
            "src": p.get("src"), "iface": p.get("pfwd_interface"), "log": bool(p.get("log"))}


def clean_port(v, what):
    """ports → the string UniFi stores: 'a', 'a-b' or a comma list of those ('80,443', '25,465,587')"""
    out = []
    for part in str(v if v is not None else "").split(","):
        m = re.fullmatch(r"(\d{1,5})(?:-(\d{1,5}))?", part.strip())
        lo, hi = (int(m.group(1)), int(m.group(2) or m.group(1))) if m else (0, 0)
        if not (1 <= lo <= hi <= 65535):
            raise UnifiError(400, f"{what}: ports 1-65535, a range like 8000-8010, or a list like 80,443")
        out.append(f"{lo}-{hi}" if m.group(2) else str(lo))
    return ",".join(out)


def _spans(ports):
    spans = []
    for part in str(ports).split(","):
        lo, _, hi = part.strip().partition("-")
        spans.append((int(lo), int(hi or lo)))
    return spans


def _count(ports):
    return sum(hi - lo + 1 for lo, hi in _spans(ports))


def _lan_target(raw, ip):
    """the LAN network a forward target lives in (not the gateway, network or broadcast address)"""
    try:
        addr = ipaddress.IPv4Address(str(ip).strip())
    except ValueError:
        raise UnifiError(400, "ip: an IPv4 address") from None
    for n in raw["nets"].values():
        if n.get("purpose") not in ("corporate", "guest") or not n.get("ip_subnet"):
            continue
        iface = ipaddress.IPv4Interface(n["ip_subnet"])
        if addr in iface.network:
            if addr in (iface.ip, iface.network.network_address, iface.network.broadcast_address):
                raise UnifiError(400, f"{addr} is the gateway/network/broadcast address of {n.get('name')}")
            return str(addr)
    raise UnifiError(400, f"{addr} is not in any of our LAN networks")


def add_portforward(claims, b):
    _, raw = fetch(force=True)
    name = clean_name(b.get("name"))
    if not name:
        raise UnifiError(400, "name: required")
    proto = b.get("proto", "tcp")
    if proto not in PROTOS:
        raise UnifiError(400, f"proto: one of {', '.join(PROTOS)}")
    dst, fwd = clean_port(b.get("dstPort"), "dstPort"), clean_port(b.get("fwdPort", b.get("dstPort")), "fwdPort")
    if _count(dst) != _count(fwd):
        raise UnifiError(400, "dstPort and fwdPort must cover the same number of ports")
    ip = _lan_target(raw, b.get("fwdIp"))
    for p in UNIFI.call("GET", "api/s/{site}/rest/portforward") or []:
        pp = p.get("proto")
        if not p.get("enabled", True) or not (proto == pp or "tcp_udp" in (proto, pp)):
            continue
        try:
            theirs = _spans(p.get("dst_port", "0"))
        except ValueError:
            continue
        if any(a[0] <= c[1] and c[0] <= a[1] for a in _spans(dst) for c in theirs):
            raise UnifiError(409, f"WAN port {dst} overlaps the forward '{p.get('name')}' ({p.get('dst_port')})")
    body = {"name": name, "enabled": b.get("enabled", True) is not False, "pfwd_interface": "wan", "src": "any", "dst_port": dst,
            "fwd_port": fwd, "fwd": ip, "proto": proto, "log": False}
    UNIFI.call("POST", "api/s/{site}/rest/portforward", body)
    log.info("%s ADDED port forward %s :%s → %s:%s (%s)", claims["u"], proto, dst, ip, fwd, name)
    return {"ok": True, "name": name, "dstPort": dst, "fwdIp": ip, "fwdPort": fwd, "proto": proto}


def remove_portforward(claims, pid):
    p = next((x for x in UNIFI.call("GET", "api/s/{site}/rest/portforward") or [] if x.get("_id") == pid), None)
    if not p:
        raise UnifiError(404, "no such port forward")
    UNIFI.call("DELETE", f"api/s/{{site}}/rest/portforward/{pid}")
    log.info("%s REMOVED port forward %s :%s → %s (%s, approved by %s)", claims["u"], p.get("proto"), p.get("dst_port"),
             p.get("fwd"), p.get("name"), claims.get("a") or "-")
    return {"ok": True}


# --- HTTP --------------------------------------------------------------------------------------------------------
ROUTES = []


def route(method, pattern, min_role="guest", owner=False):
    rx = re.compile("^" + pattern + "/?$")

    def deco(fn):
        ROUTES.append((method, rx, min_role, owner, fn))
        return fn
    return deco


@route("GET", "/api/overview")
def r_overview(c, m, b, q):
    return 200, fetch(force=q.get("fresh") == ["1"])[0]


@route("POST", "/api/reservations", "admin")
def r_add(c, m, b, q):
    return 200, reserve(c, clean_mac(b.get("mac")), b)


@route("PUT", r"/api/reservations/([0-9a-fA-F:-]{17})", "admin")
def r_change(c, m, b, q):
    mac = clean_mac(m[0])
    _, raw = fetch(force=True)
    k = raw["known"].get(mac)
    if not k or not k.get("use_fixedip"):
        raise UnifiError(404, "no reservation for that MAC")
    b = {"ip": b.get("ip") or k.get("fixed_ip"), "name": b.get("name"), "networkId": b.get("networkId")}
    return 200, reserve(c, mac, b)


@route("DELETE", r"/api/reservations/([0-9a-fA-F:-]{17})", owner=True)
def r_remove(c, m, b, q):
    mac = clean_mac(m[0])
    _, raw = fetch(force=True)
    k = raw["known"].get(mac)
    if not k or not k.get("use_fixedip"):
        raise UnifiError(404, "no reservation for that MAC")
    UNIFI.call("PUT", f"api/s/{{site}}/rest/user/{k['_id']}", {"use_fixedip": False})
    log.info("%s REMOVED reservation %s (%s, approved by %s)", c["u"], mac, k.get("fixed_ip"), c.get("a") or "-")
    invalidate()
    return 200, {"ok": True}


@route("PUT", r"/api/clients/([0-9a-fA-F:-]{17})/name", "admin")
def r_name(c, m, b, q):
    mac = clean_mac(m[0])
    _, raw = fetch(force=True)
    k = raw["known"].get(mac)
    if not k:
        raise UnifiError(404, "unknown client")
    UNIFI.call("PUT", f"api/s/{{site}}/rest/user/{k['_id']}", {"name": clean_name(b.get("name"))})
    log.info("%s renamed client %s", c["u"], mac)
    invalidate()
    return 200, {"ok": True}


@route("POST", r"/api/clients/([0-9a-fA-F:-]{17})/block", "admin")
def r_block(c, m, b, q):
    return 200, set_blocked(c, clean_mac(m[0]), True)


@route("POST", r"/api/clients/([0-9a-fA-F:-]{17})/unblock", "admin")
def r_unblock(c, m, b, q):
    return 200, set_blocked(c, clean_mac(m[0]), False)


@route("POST", r"/api/devices/([0-9a-fA-F:-]{17})/restart", "admin")
def r_restart(c, m, b, q):
    return 200, restart_ap(c, clean_mac(m[0]))


@route("GET", "/api/portforwards", "admin")
def r_pf_list(c, m, b, q):
    return 200, [pf_out(p) for p in UNIFI.call("GET", "api/s/{site}/rest/portforward") or []]


@route("POST", "/api/portforwards", owner=True)
def r_pf_add(c, m, b, q):
    return 200, add_portforward(c, b)


@route("DELETE", r"/api/portforwards/([0-9a-f]{24})", owner=True)
def r_pf_remove(c, m, b, q):
    return 200, remove_portforward(c, m[0])


def owner_ok(claims):
    return claims.get("r") == "owner" or bool(claims.get("a"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _claims(self):
        if self.client_address[0] != "127.0.0.1":
            return None
        return labauth.verify(self.headers.get(labauth.HEADER), KEY, ID)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 16 * 1024:
            raise UnifiError(413, "body too large")
        raw = self.rfile.read(n) if n else b""
        try:
            b = json.loads(raw) if raw else {}
        except ValueError:
            raise UnifiError(400, "body must be JSON") from None
        if not isinstance(b, dict):
            raise UnifiError(400, "body must be a JSON object")
        return b

    def _handle(self, method):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/healthz":
            return self._json(200, {"ok": True, "config": CONF.ready, "unifi": bool(UNIFI.last_ok), "lastOk": int(UNIFI.last_ok) or None})
        claims = self._claims()
        if not claims:
            return self._json(401, {"error": "lab signature required"})
        try:
            body = self._body() if method in ("POST", "PUT") else {}
            if method == "POST" and url.path == "/api/_validate":
                try:
                    return self._json(200, validate(labconn.candidate(claims, body)))
                except PermissionError as e:
                    return self._json(403, {"error": str(e)})
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
            if not CONF.ready:
                return self._json(503, {"error": CONF.why()})
            for meth, rx, min_role, owner, fn in ROUTES:
                mm = rx.match(url.path)
                if meth != method or not mm:
                    continue
                if owner and not owner_ok(claims):
                    return self._json(403, {"error": "owner only"})
                if not labauth.at_least(claims, min_role):
                    return self._json(403, {"error": "not allowed"})
                code, obj = fn(claims, mm.groups(), body, urllib.parse.parse_qs(url.query))
                return self._json(code, obj)
            return self._json(404, {"error": "not found"})
        except UnifiError as e:
            return self._json(e.code, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            log.exception("request failed")
            return self._json(500, {"error": f"connector error: {type(e).__name__}"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


class PooledHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    pool = ThreadPoolExecutor(max_workers=8)

    def process_request(self, request, client_address):
        self.pool.submit(self.process_request_thread, request, client_address)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    log.info("connector %s on 127.0.0.1:%s (key %s)", ID, PORT, "ok" if KEY else "MISSING")
    CONF.start()
    PooledHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
