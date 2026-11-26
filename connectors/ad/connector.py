"""Labradoor connector `ad`: Active Directory over LDAPS → users, groups, computers, OUs.

Binds as a service account — NOT a Domain Admin. Delegate its rights on ONE OU (create/reset users in the users OU,
change members of the groups OU, read the rest); this connector narrows writes to the same OUs again (defence in depth)
and only for the owner (or an admin request the owner approved).

Reads cover the whole domain (built-ins too) so the DC shows up as a computer and expiring/locked accounts anywhere are
visible. The DC certificate is verified (against the configured CA, else the system's trusted CAs).
Passwords this connector sets are generated here (or typed by the owner), returned once in that response, never logged.

Config (module config, from the gateway — connectors/README.md):
  host           the DC's name as on its certificate (and the address unless `address` is set)
  address        optional: connect here, still verify the certificate for `host`
  port           636
  ca_cert        PEM of the CA that signed the DC certificate (empty: the system's trusted CAs)
  bind_user, bind_password   the service account (user@domain)
  base_dn        DC=example,DC=com
  managed_ou     the OU lab may change things under; users_ou / groups_ou inside it
  protected      sAMAccountNames that can't be disabled or deleted from lab
"""
import calendar
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/opt/lab/sdk/python")
sys.path.insert(0, os.path.join(HERE, "..", "..", "sdk", "python"))
sys.path.insert(0, HERE)
import labauth  # noqa: E402
import labconn  # noqa: E402
import ldap  # noqa: E402

ID = os.environ.get("CONNECTOR_ID", "ad")
PORT = int(os.environ.get("PORT", "8115"))
KEY = labconn.load_key(ID)
# the installation's values (module config, set by configure() once the gateway answered)
HOST = ADDR = CA_PEM = BIND = BIND_PW = BASE = USERS_OU = GROUPS_OU = MANAGED = DOMAIN = ""
LDAP_PORT = 636
PROTECTED = set()
CACHE_S = int(os.environ.get("AD_CACHE_S", "20"))
log = logging.getLogger(ID)

# userAccountControl / msDS-User-Account-Control-Computed bits
UF_DISABLED, UF_LOCKOUT, UF_NORMAL, UF_DONT_EXPIRE, UF_DC, UF_PW_EXPIRED = 0x2, 0x10, 0x200, 0x10000, 0x2000, 0x800000
NEVER = 0x7FFFFFFFFFFFFFFF
PRIMARY = {513: "Domain Users", 514: "Domain Guests", 515: "Domain Computers", 516: "Domain Controllers"}
SAM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,19}$")
EDITABLE = {"displayName": 256, "givenName": 64, "sn": 64, "mail": 256, "description": 1024}

USER_ATTRS = ["sAMAccountName", "cn", "displayName", "givenName", "sn", "mail", "userPrincipalName", "description",
              "userAccountControl", "msDS-User-Account-Control-Computed", "msDS-UserPasswordExpiryTimeComputed",
              "pwdLastSet", "lockoutTime", "lastLogon", "lastLogonTimestamp", "badPwdCount", "badPasswordTime",
              "memberOf", "primaryGroupID", "whenCreated", "whenChanged", "adminCount", "isCriticalSystemObject",
              "accountExpires", "logonCount"]
GROUP_ATTRS = ["cn", "sAMAccountName", "description", "member", "groupType", "whenCreated", "whenChanged",
               "isCriticalSystemObject", "adminCount"]
COMPUTER_ATTRS = ["cn", "dNSHostName", "operatingSystem", "operatingSystemVersion", "description", "userAccountControl",
                  "lastLogon", "lastLogonTimestamp", "pwdLastSet", "whenCreated", "whenChanged", "primaryGroupID"]


class ApiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# --- conversions -------------------------------------------------------------------------------------------------
def filetime(v):
    """AD FILETIME (100 ns since 1601) → unix seconds; 0 / never → None."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    if v <= 0 or v >= NEVER:
        return None
    return int(v / 10_000_000 - 11644473600)


def gentime(v):
    """'20261029213045.0Z' → unix seconds."""
    if not v:
        return None
    try:
        return calendar.timegm(time.strptime(v[:14], "%Y%m%d%H%M%S"))
    except ValueError:
        return None


def interval_s(v):
    """Negative 100 ns interval (maxPwdAge, lockoutDuration) → seconds (None = never)."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return None if v in (0, -NEVER - 1) else abs(v) // 10_000_000


def rdn(dn):
    """'CN=Doe\\, J,OU=A' → 'Doe, J' (value of the first RDN, unescaped)."""
    rest = parent(dn)
    first = dn[:len(dn) - len(rest) - 1] if rest else dn
    value = first.split("=", 1)[1] if "=" in first else first
    return re.sub(r"\\(.)", r"\1", value)


def parent(dn):
    """Parent DN, split on the first unescaped comma."""
    i = 0
    while i < len(dn):
        if dn[i] == "\\":
            i += 2
            continue
        if dn[i] == ",":
            return dn[i + 1:]
        i += 1
    return ""


def under(dn, ou):
    """dn is somewhere below ou. Walks real (unescaped-comma) parents, so an OU NAMED "x,OU=Brukere" elsewhere in the
    tree ("OU=x\\,OU=Brukere,OU=Homelab,…") doesn't pass for being inside OU=Brukere."""
    want, p = ou.lower(), parent(dn)
    while p:
        if p.lower() == want:
            return True
        p = parent(p)
    return False


def gen_password(n=20):
    """Random AD-complexity password (upper, lower, digit, symbol), no look-alikes."""
    alpha = "ABCDEFGHJKLMNPQRSTUVWXYZ" + "abcdefghijkmnopqrstuvwxyz" + "23456789" + "-_.:+=!?#"
    while True:
        p = "".join(secrets.choice(alpha) for _ in range(n))
        if (any(c.isupper() for c in p) and any(c.islower() for c in p) and any(c.isdigit() for c in p)
                and any(c in "-_.:+=!?#" for c in p)):
            return p


def ad_message(e):
    """A readable reason for an AD refusal (no passwords in AD diagnostics, so diag is safe to show)."""
    diag = e.message or ""
    if e.code in (19, 53) and ("0000052D" in diag or "password" in diag.lower()):
        return "AD refused the password: it does not meet the domain policy (length/complexity/history)"
    if e.code == 50:
        return "svc-lab lacks the delegated right for this (dsacls on OU=Homelab)"
    if e.code == 68:
        return "already exists in AD"
    if e.code == 32:
        return "no such object in AD"
    return f"AD: {e}"


# --- directory -----------------------------------------------------------------------------------------------------
def shape_user(dn, a):
    uac = ldap.number(a, "userAccountControl", 0)
    comp = ldap.number(a, "msDS-User-Account-Control-Computed", 0)
    expiry_raw = ldap.number(a, "msDS-UserPasswordExpiryTimeComputed")
    pls = ldap.number(a, "pwdLastSet")
    sam = ldap.text(a, "sAMAccountName")
    groups = ldap.texts(a, "memberOf")
    lockout = filetime(ldap.number(a, "lockoutTime"))
    last = max([t for t in (filetime(ldap.number(a, "lastLogon")), filetime(ldap.number(a, "lastLogonTimestamp"))) if t] or [0]) or None
    never_expires = bool(uac & UF_DONT_EXPIRE) or expiry_raw == NEVER
    return {
        "sam": sam, "dn": dn, "cn": ldap.text(a, "cn"), "name": ldap.text(a, "displayName") or ldap.text(a, "cn") or sam,
        "given": ldap.text(a, "givenName"), "sn": ldap.text(a, "sn"), "mail": ldap.text(a, "mail"),
        "upn": ldap.text(a, "userPrincipalName"), "description": ldap.text(a, "description"),
        "enabled": not uac & UF_DISABLED, "locked": bool(comp & UF_LOCKOUT), "lockoutTime": lockout,
        "pwdExpired": bool(comp & UF_PW_EXPIRED), "mustChange": pls == 0, "pwdNeverExpires": never_expires,
        "pwdLastSet": filetime(pls), "pwdExpires": None if never_expires else (filetime(expiry_raw) or 0),
        "lastLogon": last, "badPwdCount": ldap.number(a, "badPwdCount", 0),
        "badPasswordTime": filetime(ldap.number(a, "badPasswordTime")), "logonCount": ldap.number(a, "logonCount", 0),
        "groups": [{"dn": g, "name": rdn(g)} for g in groups],
        "primaryGroup": PRIMARY.get(ldap.number(a, "primaryGroupID", 0), ""),
        "created": gentime(ldap.text(a, "whenCreated")), "changed": gentime(ldap.text(a, "whenChanged")),
        "accountExpires": filetime(ldap.number(a, "accountExpires")),
        "protected": bool(ldap.number(a, "adminCount", 0)), "system": ldap.text(a, "isCriticalSystemObject") == "TRUE",
        "ou": parent(dn), "managed": under(dn, USERS_OU), "inHomelab": under(dn, MANAGED),
        "service": "OU=Tjenestekontoer".lower() in dn.lower() or sam.lower().startswith("svc-"),
        "undeletable": sam.lower() in PROTECTED,
    }


def group_kind(gt):
    gt = gt or 0
    scope = "global" if gt & 0x2 else "domain local" if gt & 0x4 else "universal" if gt & 0x8 else "builtin" if gt & 0x1 else "?"
    return scope, "security" if gt & 0x80000000 else "distribution"


def shape_group(dn, a):
    scope, kind = group_kind(ldap.number(a, "groupType", 0))
    return {"name": ldap.text(a, "cn"), "sam": ldap.text(a, "sAMAccountName"), "dn": dn, "description": ldap.text(a, "description"),
            "members": ldap.texts(a, "member"), "scope": scope, "kind": kind,
            "created": gentime(ldap.text(a, "whenCreated")), "changed": gentime(ldap.text(a, "whenChanged")),
            "system": ldap.text(a, "isCriticalSystemObject") == "TRUE", "protected": bool(ldap.number(a, "adminCount", 0)),
            "ou": parent(dn), "managed": under(dn, GROUPS_OU)}


def shape_computer(dn, a):
    uac = ldap.number(a, "userAccountControl", 0)
    last = max([t for t in (filetime(ldap.number(a, "lastLogon")), filetime(ldap.number(a, "lastLogonTimestamp"))) if t] or [0]) or None
    return {"name": ldap.text(a, "cn"), "dns": ldap.text(a, "dNSHostName"), "os": ldap.text(a, "operatingSystem"),
            "osVersion": ldap.text(a, "operatingSystemVersion"), "description": ldap.text(a, "description"), "dn": dn,
            "enabled": not uac & UF_DISABLED, "dc": bool(uac & UF_DC), "lastLogon": last,
            "pwdLastSet": filetime(ldap.number(a, "pwdLastSet")), "created": gentime(ldap.text(a, "whenCreated")),
            "changed": gentime(ldap.text(a, "whenChanged")), "ou": parent(dn), "inHomelab": under(dn, MANAGED)}


class AD:
    """One bound LDAPS session, re-used and serialized; reconnect once when the DC dropped it."""

    def __init__(self, factory=None):
        self.lock = threading.Lock()
        self.conn = None
        self.factory = factory or (lambda: ldap.connect_tls(HOST, LDAP_PORT, cadata=CA_PEM or None, addr=ADDR or None))
        self.cache = (0.0, None)
        self.last_error = ""
        self.peer = {}

    def _connect(self):
        if not (HOST and BIND and BIND_PW):
            raise ApiError(503, "no AD connection configured")
        sock = self.factory()
        try:
            cert = sock.getpeercert() if hasattr(sock, "getpeercert") else None
            self.peer = {"tls": sock.version() if hasattr(sock, "version") else "", "certExpires": cert.get("notAfter") if cert else None}
        except (ValueError, AttributeError):
            self.peer = {}
        c = ldap.Connection(sock)
        try:
            c.bind(BIND, BIND_PW)
        except ldap.LdapError as e:
            c.close()
            raise ApiError(502, f"bind as {BIND.split('@')[0]} refused ({ldap.RESULT.get(e.code, e.code)})") from None
        self.conn = c

    def run(self, fn):
        """fn(conn) under the lock; one reconnect on a dropped connection. Maps transport errors to 502."""
        with self.lock:
            for attempt in (0, 1):
                try:
                    if self.conn is None:
                        self._connect()
                    return fn(self.conn)
                except (ldap.ConnectionLost, OSError, ValueError) as e:
                    if self.conn:
                        self.conn.close()
                    self.conn = None
                    if attempt:
                        self.last_error = str(e)[:200]
                        raise ApiError(502, f"AD unreachable: {self.last_error}") from None
                except ldap.LdapError as e:
                    if e.code in (1, 51, 52, 80) and attempt == 0:  # busy/unavailable: fresh session once
                        if self.conn:
                            self.conn.close()
                        self.conn = None
                        continue
                    raise
        raise ApiError(502, "AD unreachable")

    def directory(self, fresh=False):
        at, data = self.cache
        if data is not None and not fresh and time.time() - at < CACHE_S:
            return data

        def load(c):
            users = c.search(BASE, ldap.SUBTREE, "(&(objectCategory=person)(objectClass=user))", USER_ATTRS)
            groups = c.search(BASE, ldap.SUBTREE, "(objectClass=group)", GROUP_ATTRS)
            comps = c.search(BASE, ldap.SUBTREE, "(objectClass=computer)", COMPUTER_ATTRS)
            ous = c.search(BASE, ldap.SUBTREE, "(|(objectClass=organizationalUnit)(objectClass=container))",
                           ["ou", "cn", "description", "whenChanged", "objectClass"])
            dom = c.search(BASE, ldap.BASE, "(objectClass=*)", ["maxPwdAge", "minPwdAge", "minPwdLength", "pwdHistoryLength",
                                                                "lockoutThreshold", "lockoutDuration", "lockOutObservationWindow",
                                                                "pwdProperties"])
            return users, groups, comps, ous, dom

        try:
            users, groups, comps, ous, dom = self.run(load)
        except ldap.LdapError as e:
            self.last_error = str(e)[:200]
            raise ApiError(502, ad_message(e)) from None
        now = time.time()
        d = dom[0][1] if dom else {}
        keep_ou = lambda dn: dn.lower().startswith("ou=") or dn.lower() in (f"cn=users,{BASE}".lower(), f"cn=computers,{BASE}".lower(), f"cn=builtin,{BASE}".lower())  # noqa: E731
        data = {
            "users": sorted((shape_user(dn, a) for dn, a in users), key=lambda u: u["sam"].lower()),
            "groups": sorted((shape_group(dn, a) for dn, a in groups), key=lambda g: g["name"].lower()),
            "computers": sorted((shape_computer(dn, a) for dn, a in comps), key=lambda x: x["name"].lower()),
            "ous": sorted(({"dn": dn, "name": ldap.text(a, "ou") or ldap.text(a, "cn"), "description": ldap.text(a, "description"),
                            "changed": gentime(ldap.text(a, "whenChanged")), "container": not dn.lower().startswith("ou=")}
                           for dn, a in ous if keep_ou(dn)), key=lambda o: list(reversed(o["dn"].lower().split(",")))),
            "policy": {"maxPwdAge": interval_s(ldap.number(d, "maxPwdAge")), "minPwdAge": interval_s(ldap.number(d, "minPwdAge")),
                       "minPwdLength": ldap.number(d, "minPwdLength", 0), "history": ldap.number(d, "pwdHistoryLength", 0),
                       "lockoutThreshold": ldap.number(d, "lockoutThreshold", 0),
                       "lockoutDuration": interval_s(ldap.number(d, "lockoutDuration")),
                       "complexity": bool(ldap.number(d, "pwdProperties", 0) & 1)},
            "domain": DOMAIN, "base": BASE, "usersOu": USERS_OU, "groupsOu": GROUPS_OU, "managedOu": MANAGED,
            "dc": HOST, "bind": BIND.split("@")[0], "fetched": int(now),
        }
        self.last_error = ""
        self.cache = (time.time(), data)
        return data

    def invalidate(self):
        self.cache = (0.0, None)

    def close(self):
        """New config: drop the session and the cache (the next call binds with the new values)."""
        with self.lock:
            if self.conn:
                try:
                    self.conn.close()
                except OSError:
                    pass
            self.conn = None
        self.invalidate()

    # --- lookups for writes
    def _find(self, c, cls_filter, attr, value, attrs):
        r = c.search(BASE, ldap.SUBTREE, f"(&{cls_filter}({attr}={ldap.escape_filter(value)}))", attrs, page=0)
        return r[0] if r else (None, None)

    def user(self, c, sam, need_managed=True):
        dn, a = self._find(c, "(objectCategory=person)(objectClass=user)", "sAMAccountName", sam,
                           ["sAMAccountName", "userAccountControl", "memberOf"])
        if not dn:
            raise ApiError(404, f"no AD user {sam}")
        if need_managed and not under(dn, USERS_OU):
            raise ApiError(403, f"{sam} is outside {USERS_OU.split(',')[0]} — lab only changes users there")
        return dn, a

    def group(self, c, name):
        dn, _ = self._find(c, "(objectClass=group)", "cn", name, ["cn"])
        if not dn:
            raise ApiError(404, f"no AD group {name}")
        if not under(dn, GROUPS_OU):
            raise ApiError(403, f"{name} is outside {GROUPS_OU.split(',')[0]} — lab only changes groups there")
        return dn


AD_CONN = AD()


def settings_of(v):
    """Module config → the connector's values (shared by configure() and the config test)."""
    base = labconn.text(v, "base_dn")
    port = v.get("port")
    return {"host": labconn.text(v, "host"), "addr": labconn.text(v, "address"),
            "port": port if isinstance(port, int) and 0 < port < 65536 else 636,
            "ca": labconn.text(v, "ca_cert"), "bind": labconn.text(v, "bind_user"), "pw": v.get("bind_password") or "",
            "base": base, "users": labconn.text(v, "users_ou"), "groups": labconn.text(v, "groups_ou"),
            "managed": labconn.text(v, "managed_ou"),
            "domain": ".".join(p.split("=", 1)[1] for p in base.split(",") if p.strip().upper().startswith("DC=")),
            "protected": {str(x).strip().lower() for x in v.get("protected") or [] if str(x).strip()}}


def scope_problem(st):
    """lab only writes inside managed_ou: the users and groups OUs must be in it, and it in the domain."""
    if not (st["base"] and st["managed"] and st["users"] and st["groups"]):
        return "base_dn, managed_ou, users_ou and groups_ou are required"
    if not (under(st["managed"], st["base"])):
        return "managed_ou must be inside base_dn"
    for k in ("users", "groups"):
        if not (under(st[k], st["managed"]) or st[k].lower() == st["managed"].lower()):
            return f"{k}_ou must be inside managed_ou"
    return None


def configure(v, conf=None):
    global HOST, ADDR, LDAP_PORT, CA_PEM, BIND, BIND_PW, BASE, USERS_OU, GROUPS_OU, MANAGED, DOMAIN, PROTECTED
    st = settings_of(v)
    HOST, ADDR, LDAP_PORT, CA_PEM, BIND, BIND_PW = st["host"], st["addr"], st["port"], st["ca"], st["bind"], st["pw"]
    BASE, USERS_OU, GROUPS_OU, MANAGED, DOMAIN = st["base"], st["users"], st["groups"], st["managed"], st["domain"]
    PROTECTED = st["protected"]
    bad = scope_problem(st) if HOST else None
    if bad:
        log.error("config: %s", bad)
    AD_CONN.close()


CONF = labconn.Config(ID, KEY, apply=configure)


def validate(values):
    """Config test: connect + verify the certificate + bind with the CANDIDATE values, then read base and managed OU."""
    st = settings_of(values)
    if not (st["host"] and st["bind"] and st["pw"]):
        return {"ok": False, "error": "host, bind_user and bind_password are required"}
    bad = scope_problem(st)
    if bad:
        return {"ok": False, "error": bad}
    try:
        sock = ldap.connect_tls(st["host"], st["port"], cadata=st["ca"] or None, addr=st["addr"] or None)
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"LDAPS to {st['host']}: {str(e)[:200]}"}
    c = ldap.Connection(sock)
    try:
        c.bind(st["bind"], st["pw"])
        for dn in (st["base"], st["managed"]):
            c.search(dn, ldap.BASE, "(objectClass=*)", ["distinguishedName"], page=0)
    except ldap.LdapError as e:
        return {"ok": False, "error": f"refused: {ldap.RESULT.get(e.code, e.code)}"}
    except OSError as e:
        return {"ok": False, "error": f"connection dropped: {str(e)[:150]}"}
    finally:
        c.close()
    return {"ok": True, "detail": f"bound as {st['bind'].split('@')[0]}, {st['managed'].split(',')[0]} readable"}


# --- writes --------------------------------------------------------------------------------------------------------
def w_unlock(c, sam, body):
    dn, _ = AD_CONN.user(c, sam)
    c.modify(dn, [("replace", "lockoutTime", ["0"])])
    return {"ok": True, "sam": sam, "unlocked": True}


def w_enable(c, sam, body, on=True):
    dn, a = AD_CONN.user(c, sam)
    if not on and sam.lower() in PROTECTED:
        raise ApiError(403, f"{sam} is protected (module config) — disable it on the DC if you really mean it")
    uac = ldap.number(a, "userAccountControl", UF_NORMAL)
    new = (uac & ~UF_DISABLED) if on else (uac | UF_DISABLED)  # only the disable bit changes
    if new != uac:
        c.modify(dn, [("replace", "userAccountControl", [str(new)])])
    return {"ok": True, "sam": sam, "enabled": on}


def w_password(c, sam, body):
    dn, _ = AD_CONN.user(c, sam)
    pw, generated = body.get("password") or "", False
    if not pw:
        pw, generated = gen_password(), True
    if not isinstance(pw, str) or len(pw) > 256:
        raise ApiError(400, "bad password")
    must = bool(body.get("mustChange", True))
    c.modify(dn, [("replace", "unicodePwd", [ldap.ad_password(pw)])])
    c.modify(dn, [("replace", "pwdLastSet", ["0" if must else "-1"])])
    if body.get("unlock", True):
        c.modify(dn, [("replace", "lockoutTime", ["0"])])
    out = {"ok": True, "sam": sam, "mustChange": must}
    if generated:
        out["password"] = pw  # shown once to the owner; never logged or cached
    return out


def w_group(c, sam, group, add):
    udn, _ = AD_CONN.user(c, sam, need_managed=False)
    if not under(udn, MANAGED):
        raise ApiError(403, f"{sam} is outside OU=Homelab")
    gdn = AD_CONN.group(c, group)
    try:
        c.modify(gdn, [("add" if add else "delete", "member", [udn])])
    except ldap.LdapError as e:
        if e.code == 68 or (e.code == 53 and add) or e.code == 20:  # already a member
            return {"ok": True, "sam": sam, "group": group, "member": True, "noop": True}
        if e.code in (16, 53) and not add:  # not a member
            return {"ok": True, "sam": sam, "group": group, "member": False, "noop": True}
        raise
    return {"ok": True, "sam": sam, "group": group, "member": add}


def w_edit(c, sam, body):
    dn, _ = AD_CONN.user(c, sam)
    changes = []
    for k, v in body.items():
        if k not in EDITABLE:
            raise ApiError(400, f"can't edit {k} (allowed: {', '.join(EDITABLE)})")
        if not isinstance(v, str) or len(v) > EDITABLE[k]:
            raise ApiError(400, f"bad {k}")
        changes.append(("replace", k, [v.strip()]) if v.strip() else ("replace", k, []))
    if not changes:
        raise ApiError(400, "nothing to change")
    c.modify(dn, changes)
    return {"ok": True, "sam": sam, "changed": sorted(body)}


def w_create(c, body):
    sam = str(body.get("sam") or "").strip()
    if not SAM_RE.match(sam):
        raise ApiError(400, "sam: 1–20 chars, letters/digits/._- (starts with a letter or digit)")
    given, sn = str(body.get("given") or "").strip(), str(body.get("sn") or "").strip()
    name = str(body.get("name") or "").strip() or " ".join(x for x in (given, sn) if x) or sam
    mail, desc = str(body.get("mail") or "").strip(), str(body.get("description") or "").strip()
    for k, v in (("given", given), ("sn", sn), ("name", name), ("mail", mail), ("description", desc)):
        if len(v) > 256:
            raise ApiError(400, f"{k} too long")
    if mail and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", mail):
        raise ApiError(400, "bad mail")
    groups = body.get("groups") or []
    if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
        raise ApiError(400, "groups must be a list of names")
    existing, _ = AD_CONN._find(c, "(objectClass=user)", "sAMAccountName", sam, ["cn"])
    if existing:
        raise ApiError(409, f"{sam} already exists in AD")
    gdns = [AD_CONN.group(c, g) for g in groups]  # validate before creating anything
    pw, generated = body.get("password") or "", False
    if not pw:
        pw, generated = gen_password(), True
    if not isinstance(pw, str) or len(pw) > 256:
        raise ApiError(400, "bad password")
    enabled, must = bool(body.get("enabled", True)), bool(body.get("mustChange", True))
    dn = f"CN={ldap.escape_dn(sam)},{USERS_OU}"
    attrs = {"objectClass": ["top", "person", "organizationalPerson", "user"], "cn": sam, "sAMAccountName": sam,
             "userPrincipalName": f"{sam}@{DOMAIN}", "displayName": name,
             "userAccountControl": str(UF_NORMAL | (0 if enabled else UF_DISABLED)), "unicodePwd": ldap.ad_password(pw)}
    for k, v in (("givenName", given), ("sn", sn), ("mail", mail), ("description", desc)):
        if v:
            attrs[k] = v
    c.add(dn, attrs)
    warnings = []
    try:
        if must:
            c.modify(dn, [("replace", "pwdLastSet", ["0"])])
    except ldap.LdapError as e:
        warnings.append(f"must-change not set: {ad_message(e)}")
    for g, gdn in zip(groups, gdns):
        try:
            c.modify(gdn, [("add", "member", [dn])])
        except ldap.LdapError as e:
            warnings.append(f"{g}: {ad_message(e)}")
    out = {"ok": True, "sam": sam, "dn": dn, "enabled": enabled, "mustChange": must, "groups": groups, "warnings": warnings}
    if generated:
        out["password"] = pw
    return out


def w_delete(c, sam, query, body):
    """Needs the sAMAccountName repeated as ?confirm= or body {"confirm": …} (an approval carries the body, not the query)."""
    if (query.get("confirm") or [""])[0] != sam and body.get("confirm") != sam:
        raise ApiError(400, f"confirm: pass ?confirm={sam} or {{\"confirm\": \"{sam}\"}}")
    if sam.lower() in PROTECTED:
        raise ApiError(403, f"{sam} is protected (module config)")
    dn, _ = AD_CONN.user(c, sam)
    c.delete(dn)
    return {"ok": True, "sam": sam, "deleted": True}


# --- HTTP ----------------------------------------------------------------------------------------------------------
USER_PATH = re.compile(r"^/api/users/([^/]+)(?:/(unlock|enable|disable|password|groups/([^/]+)))?$")


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
        # per request, never cached on the handler (keep-alive connections carry many users)
        if self.client_address[0] != "127.0.0.1":
            return None
        return labauth.verify(self.headers.get(labauth.HEADER), KEY, ID)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 16384:
            raise ApiError(413, "body too large")
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            d = json.loads(raw)
        except ValueError:
            raise ApiError(400, "body must be JSON") from None
        if not isinstance(d, dict):
            raise ApiError(400, "body must be a JSON object")
        return d

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        path, q = url.path.rstrip("/") or "/", urllib.parse.parse_qs(url.query)
        if path == "/healthz":
            if not CONF.ready:
                return self._json(503, {"ok": False, "config": False, "error": CONF.why()})
            try:
                AD_CONN.directory()
                return self._json(200, {"ok": True})
            except (ApiError, ldap.LdapError) as e:
                return self._json(502, {"ok": False, "error": str(e)})
        claims = self._claims()
        if not claims or not labauth.at_least(claims, "admin"):
            return self._json(401, {"error": "lab signature required"})
        if not CONF.ready:
            return self._json(503, {"error": CONF.why()})
        try:
            if path == "/api/directory":
                return self._json(200, AD_CONN.directory(fresh=q.get("fresh") == ["1"]))
            if path == "/api/status":
                d = AD_CONN.directory()
                return self._json(200, {"connector": ID, "you": claims["u"], "role": claims["r"], "dc": HOST,
                                        "bind": d["bind"], "base": BASE, "usersOu": USERS_OU, "groupsOu": GROUPS_OU,
                                        "users": len(d["users"]), "groups": len(d["groups"]),
                                        "computers": len(d["computers"]), **AD_CONN.peer})
        except ApiError as e:
            return self._json(e.code, {"error": str(e)})
        return self._json(404, {"error": "not found"})

    def _write(self, method):
        url = urllib.parse.urlsplit(self.path)
        path, q = url.path.rstrip("/"), urllib.parse.parse_qs(url.query)
        claims = self._claims()
        if not claims:
            return self._json(401, {"error": "lab signature required"})
        if method == "POST" and path == "/api/_validate":
            try:
                return self._json(200, validate(labconn.candidate(claims, self._body())))
            except PermissionError as e:
                return self._json(403, {"error": str(e)})
            except (ValueError, ApiError) as e:
                return self._json(400, {"error": str(e)})
        if not CONF.ready:
            return self._json(503, {"error": CONF.why()})
        # identity changes: the owner, or an admin's request the owner approved (claim "a")
        if claims["r"] != "owner" and not claims.get("a"):
            return self._json(403, {"error": "owner only"})
        who = claims["u"] + (f" (approved by {claims['a']})" if claims.get("a") else "")
        try:
            body = self._body()
            if claims.get("a") and body.get("password"):
                # an admin's request sits in lab's approval table: it must not carry a password — let one be generated
                raise ApiError(400, "an approved request can't carry a password (the connector generates one for the owner)")
            if method == "POST" and path == "/api/users":
                what, fn = f"create user {body.get('sam')}", lambda c: w_create(c, body)
            else:
                m = USER_PATH.match(path)
                if not m:
                    return self._json(404, {"error": "not found"})
                sam, verb, group = urllib.parse.unquote(m.group(1)), m.group(2), m.group(3)
                group = urllib.parse.unquote(group) if group else None
                if not SAM_RE.match(sam):
                    raise ApiError(400, "bad sAMAccountName")
                table = {
                    ("POST", "unlock"): lambda c: w_unlock(c, sam, body),
                    ("POST", "enable"): lambda c: w_enable(c, sam, body, True),
                    ("POST", "disable"): lambda c: w_enable(c, sam, body, False),
                    ("POST", "password"): lambda c: w_password(c, sam, body),
                    ("PATCH", None): lambda c: w_edit(c, sam, body),
                    ("DELETE", None): lambda c: w_delete(c, sam, q, body),
                }
                if verb and verb.startswith("groups/"):
                    if method not in ("POST", "DELETE"):
                        return self._json(405, {"error": "method not allowed"})
                    fn = lambda c: w_group(c, sam, group, method == "POST")  # noqa: E731
                    what = f"{'add' if method == 'POST' else 'remove'} {sam} {'to' if method == 'POST' else 'from'} {group}"
                else:
                    fn = table.get((method, verb))
                    if not fn:
                        return self._json(405, {"error": "method not allowed"})
                    what = f"{verb or {'PATCH': 'edit', 'DELETE': 'delete'}[method]} {sam}"
            try:
                out = AD_CONN.run(fn)
            except ldap.LdapError as e:
                log.warning("%s by %s refused: %s", what, who, e)
                code = 409 if e.code in (20, 68) else 404 if e.code == 32 else 403 if e.code == 50 else 422
                return self._json(code, {"error": ad_message(e)})
            AD_CONN.invalidate()
            log.info("%s by %s", what, who)
            return self._json(200, out)
        except ApiError as e:
            return self._json(e.code, {"error": str(e)})

    def do_POST(self):
        return self._write("POST")

    def do_PATCH(self):
        return self._write("PATCH")

    def do_DELETE(self):
        return self._write("DELETE")


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
