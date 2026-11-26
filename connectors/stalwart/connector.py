"""Labradoor connector `stalwart`: the Stalwart mail server (0.16+) behind the gateway.

Since 0.16 Stalwart has no REST management API: everything is JMAP on one endpoint (POST /jmap/, capabilities
urn:ietf:params:jmap:core + urn:stalwart:jmap, methods like x:QueuedMessage/query). One URL for reads and writes means
the gateway's path allow-list can't tell them apart, so this connector exposes REST-ish routes and turns each one into a
FIXED set of JMAP calls. Nothing else is ever sent upstream.

It never returns a credential: `secret`, `credentials`, private keys … are dropped from every answer (scrub()), and a
password the owner types for an account goes straight to Stalwart (hashed there) and is never logged or echoed.
Owner-only operations are re-checked here (defence in depth); protected accounts (config, default the built-in
`admin`, plus every account with the Admin role) can't be disabled, re-passworded or deleted through lab, and allowed
IPs (the reverse proxy's address belongs there) can't be removed at all.

Stalwart bans IPs that fail to log in. A refused API key therefore pauses all upstream calls for AUTH_PAUSE_S instead of
retrying every refresh and getting the lab host itself banned.

Config (module config, from the gateway — connectors/README.md):
  url                 Stalwart's HTTP listener as the lab host reaches it (the JMAP endpoint is <url>/jmap/)
  api_key             an API key (Bearer API_…) of an admin account, narrowed to what the module needs
  verify_tls
  protected_accounts  account names lab must not disable, re-password or delete (default: admin)
"""
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

ID = os.environ.get("CONNECTOR_ID", "stalwart")
PORT = int(os.environ.get("PORT", "8121"))
KEY = labconn.load_key(ID)
CACHE_S = 10
AUTH_PAUSE_S = int(os.environ.get("STALWART_AUTH_PAUSE_S", "600"))
USING = ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]
RETRY_NOW = "2000-01-01T00:00:00Z"  # what Stalwart's own web UI sets for "retry now"
log = logging.getLogger(ID)

SECRET_KEYS = {"secret", "credentials", "privatekey", "authsecret", "password", "otpurl", "apikey", "token"}
ID_RE = re.compile(r"^[a-z0-9]{1,40}$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
REPORT_TYPES = {"dmarc": "x:DmarcExternalReport", "tls": "x:TlsExternalReport", "arf": "x:ArfExternalReport",
                "dmarc-out": "x:DmarcInternalReport", "tls-out": "x:TlsInternalReport"}
QUEUE_PROPS = ["returnPath", "createdAt", "nextRetry", "nextNotify", "size", "recipients", "priority", "flags",
               "receivedFromIp", "receivedViaPort", "envId"]


class SwError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def scrub(obj):
    """Drop every credential-looking key, at any depth."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if str(k).lower() not in SECRET_KEYS}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def keys(m):
    """Stalwart's JMAP sets are maps {value: true}; lists are maps {"0": …}. → a plain list."""
    if isinstance(m, dict):
        return [k for k, v in m.items() if v is True] if all(v is True for v in m.values()) else list(m.values())
    return list(m or [])


# --- upstream ----------------------------------------------------------------------------------------------------
class Stalwart:
    def __init__(self, url="", key="", verify=True):
        self.url, self.key = (url or "").rstrip("/"), key or ""
        self.ctx = None if verify else ssl._create_unverified_context()  # noqa: S323 (owner's choice, per config)
        self.paused_until = 0.0
        self.last_ok = 0.0
        self.last_error = ""

    def call(self, calls, timeout=20):
        """calls = [(method, args)] → [args of each answer]; a JMAP method error raises SwError."""
        if not self.url or not self.key:
            raise SwError(503, "no Stalwart URL / API key configured")
        if time.time() < self.paused_until:
            raise SwError(502, f"Stalwart refused the API key; upstream calls paused for "
                               f"{int(self.paused_until - time.time())} s (Stalwart bans IPs that keep failing)")
        body = {"using": USING, "methodCalls": [[m, a, str(i)] for i, (m, a) in enumerate(calls)]}
        req = urllib.request.Request(self.url + "/jmap/", json.dumps(body).encode(), method="POST", headers={
            "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "lab-connector-stalwart/1",
            "Authorization": "Bearer " + self.key})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self.ctx) as r:
                out = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                self.paused_until = time.time() + AUTH_PAUSE_S
                self.last_error = f"API key refused (HTTP {e.code})"
                raise SwError(502, f"Stalwart refused the API key (HTTP {e.code}); pausing {AUTH_PAUSE_S} s") from None
            self.last_error = f"HTTP {e.code}"
            raise SwError(502, f"Stalwart: HTTP {e.code}") from None
        except (OSError, ValueError) as e:
            self.last_error = str(e)[:200]
            raise SwError(502, f"Stalwart unreachable: {str(e)[:150]}") from None
        res = out.get("methodResponses")
        if not isinstance(res, list) or len(res) != len(calls):
            raise SwError(502, "Stalwart: unexpected JMAP answer")
        answers = []
        for (meth, _), r in zip(calls, res):
            if r[0] == "error":
                a = r[1] if isinstance(r[1], dict) else {}
                raise SwError(403 if a.get("type") == "forbidden" else 502,
                              f"{meth}: {a.get('type', 'error')}: {str(a.get('description', ''))[:200]}")
            answers.append(r[1])
        self.last_ok, self.last_error = time.time(), ""
        return answers

    def set(self, typ, args):
        """One x:<Type>/set; a refused create/update/destroy raises SwError with Stalwart's reason."""
        (r,) = self.call([(f"{typ}/set", {"accountId": ACCOUNT, **args})])
        for k in ("notCreated", "notUpdated", "notDestroyed"):
            for _, err in (r.get(k) or {}).items():
                err = err or {}
                code = 404 if err.get("type") == "notFound" else 403 if err.get("type") == "forbidden" else 400
                raise SwError(code, f"Stalwart: {err.get('type', 'refused')}: {str(err.get('description', ''))[:200]}")
        return r


ACCOUNT = "b"  # the JMAP account the management objects live in (Stalwart answers every x:* call for it)
SW = Stalwart()
PROTECTED = {"admin"}
_cache = {"at": 0.0, "data": None}
_lock = threading.Lock()


def configure(v, conf=None):
    global SW, PROTECTED
    SW = Stalwart(labconn.url(v, "url"), labconn.text(v, "api_key"), v.get("verify_tls") is not False)
    prot = v.get("protected_accounts")
    if isinstance(prot, str):
        prot = [p for p in re.split(r"[\s,]+", prot) if p]
    PROTECTED = {str(p).strip().lower() for p in (prot if prot is not None else ["admin"]) if str(p).strip()}
    invalidate()


CONF = labconn.Config(ID, KEY, apply=configure)


def invalidate():
    _cache.update(at=0.0, data=None)


def validate(values):
    """Config test with the CANDIDATE values: one read (domains) with that key. A refused key is said once; the
    candidate client is thrown away, so a wrong key in the form never pauses the running config."""
    sw = Stalwart(labconn.url(values, "url"), labconn.text(values, "api_key"), values.get("verify_tls") is not False)
    if not sw.url:
        return {"ok": False, "error": "no URL"}
    try:
        d, q = sw.call([("x:Domain/get", {"accountId": ACCOUNT, "properties": ["name"]}),
                        ("x:QueuedMessage/query", {"accountId": ACCOUNT})])
    except SwError as e:
        return {"ok": False, "error": str(e)}
    names = [x.get("name") for x in d.get("list") or []]
    return {"ok": True, "detail": f"API key works: {len(names)} domain(s) ({', '.join(names[:3])}), "
                                  f"{len(q.get('ids') or [])} queued message(s)"}


# --- shaping -----------------------------------------------------------------------------------------------------
def disabled(acc):
    p = acc.get("permissions") or {}
    return p.get("@type") in ("Merge", "Replace") and (p.get("disabledPermissions") or {}).get("authenticate") is True


def protected(acc):
    """Named in protected_accounts, or any role beyond plain User (Admin, custom roles that may hold admin rights)."""
    return (acc.get("name") or "").lower() in PROTECTED or (acc.get("roles") or {}).get("@type", "User") != "User"


def account_row(a, domains):
    dom = domains.get(a.get("domainId"), "")
    return {"id": a.get("id"), "name": a.get("name"), "email": a.get("emailAddress") or (f"{a.get('name')}@{dom}" if dom else a.get("name")),
            "domain": dom, "description": a.get("description") or "", "role": (a.get("roles") or {}).get("@type") or "",
            "kind": a.get("@type") or "User", "disabled": disabled(a), "protected": protected(a), "used": a.get("usedDiskQuota") or 0,
            "quota": (a.get("quotas") or {}).get("maxDiskQuota"), "created": a.get("createdAt"),
            "aliases": len(keys(a.get("aliases"))), "groups": len(keys(a.get("memberGroupIds")))}


def status_text(st):
    st = st or {}
    rest = {k: v for k, v in st.items() if k != "@type"}
    return (json.dumps(scrub(rest), separators=(",", ":"))[:300] if rest else "")


def queue_row(m):
    rcpts = []
    for addr, r in (m.get("recipients") or {}).items():
        st = (r or {}).get("status") or {}
        rcpts.append({"to": addr, "status": st.get("@type") or "Scheduled", "detail": status_text(st),
                      "retries": r.get("retryCount") or 0, "retryDue": r.get("retryDue"), "queue": r.get("queueName"),
                      "expires": scrub(r.get("expires"))})
    worst = "PermanentFailure" if any(r["status"] == "PermanentFailure" for r in rcpts) else \
        "TemporaryFailure" if any(r["status"] == "TemporaryFailure" for r in rcpts) else \
        "Scheduled" if any(r["status"] == "Scheduled" for r in rcpts) else "Completed"
    return {"id": m.get("id"), "from": m.get("returnPath") or "<>", "size": m.get("size") or 0, "created": m.get("createdAt"),
            "nextRetry": m.get("nextRetry"), "priority": m.get("priority") or 0, "status": worst,
            "retries": max([r["retries"] for r in rcpts] or [0]), "recipients": rcpts,
            "fromIp": m.get("receivedFromIp"), "port": m.get("receivedViaPort")}


def report_summary(kind, r):
    rep = r.get("report") or {}
    out = {"id": r.get("id"), "kind": kind, "from": r.get("from"), "subject": r.get("subject"),
           "received": r.get("receivedAt") or r.get("createdAt"), "expires": r.get("expiresAt"),
           "deliver": r.get("deliverAt"), "domain": r.get("domain")}
    if kind.startswith("dmarc"):
        recs = list((rep.get("records") or {}).values())
        n = sum(int(x.get("count") or 0) for x in recs)
        bad = sum(int(x.get("count") or 0) for x in recs
                  if x.get("evaluatedDkim") != "pass" and x.get("evaluatedSpf") != "pass")
        out.update(org=rep.get("orgName"), policyDomain=rep.get("policyDomain"), begin=rep.get("dateRangeBegin"),
                   end=rep.get("dateRangeEnd"), messages=n, failed=bad, sources=len(recs))
    elif kind.startswith("tls"):
        pols = list((rep.get("policies") or {}).values())
        out.update(org=rep.get("organizationName"), begin=rep.get("dateRangeStart"), end=rep.get("dateRangeEnd"),
                   policies=len(pols), ok=sum(int(p.get("totalSuccessfulSessions") or 0) for p in pols),
                   failed=sum(int(p.get("totalFailedSessions") or 0) for p in pols),
                   policyDomain=", ".join(sorted({p.get("policyDomain") or "" for p in pols}))[:120])
    else:
        out.update(feedbackType=rep.get("feedbackType"), sourceIp=rep.get("sourceIp"), incidents=rep.get("incidents"),
                   reported=keys(rep.get("reportedDomains"))[:5], arrival=rep.get("arrivalDate"))
    return out


def overview(force=False):
    with _lock:
        if not force and _cache["data"] is not None and time.time() - _cache["at"] < CACHE_S:
            return _cache["data"]
    A = {"accountId": ACCOUNT}
    ref = lambda i, name: {"resultOf": str(i), "name": name, "path": "/ids"}  # noqa: E731
    (qq, qg, blocked, allowed, doms, accs, dx, tx, ax, di, ti, certs, dkim, tasks, alerts) = SW.call([
        ("x:QueuedMessage/query", {**A, "limit": 500}),
        ("x:QueuedMessage/get", {**A, "#ids": ref(0, "x:QueuedMessage/query"), "properties": QUEUE_PROPS}),
        ("x:BlockedIp/get", {**A, "ids": None}),
        ("x:AllowedIp/get", {**A, "ids": None}),
        ("x:Domain/get", {**A, "properties": ["name", "isEnabled", "createdAt", "description", "aliases", "catchAllAddress",
                                              "dkimManagement", "dnsManagement", "certificateManagement", "allowRelaying"]}),
        ("x:Account/get", A),  # every property (@type is only sent then); scrub() drops the credentials
        ("x:DmarcExternalReport/query", A), ("x:TlsExternalReport/query", A), ("x:ArfExternalReport/query", A),
        ("x:DmarcInternalReport/query", A), ("x:TlsInternalReport/query", A),
        ("x:Certificate/get", {**A, "properties": ["subjectAlternativeNames", "notValidAfter", "notValidBefore", "issuer"]}),
        ("x:DkimSignature/get", {**A, "properties": ["selector", "stage", "domainId", "createdAt", "nextTransitionAt"]}),
        ("x:Task/get", A),
        ("x:Alert/query", A),
    ])
    domains = {d["id"]: d.get("name") for d in doms.get("list") or []}
    queue = sorted((queue_row(m) for m in qg.get("list") or []), key=lambda m: m["created"] or "", reverse=True)
    ips = lambda lst: sorted(({"id": x.get("id"), "address": x.get("address"), "reason": x.get("reason") or "",  # noqa: E731
                               "created": x.get("createdAt"), "expires": x.get("expiresAt")} for x in lst.get("list") or []),
                             key=lambda x: x["created"] or "", reverse=True)
    accounts = sorted((account_row(a, domains) for a in accs.get("list") or []), key=lambda a: a["email"] or "")
    dk = {}
    for s in dkim.get("list") or []:
        dk.setdefault(s.get("domainId"), []).append({"selector": s.get("selector"), "stage": s.get("stage"),
                                                       "algorithm": s.get("@type"), "created": s.get("createdAt"),
                                                       "next": s.get("nextTransitionAt")})
    cert_rows = [{"id": c.get("id"), "names": keys(c.get("subjectAlternativeNames")), "notAfter": c.get("notValidAfter"),
                  "notBefore": c.get("notValidBefore"), "issuer": c.get("issuer")} for c in certs.get("list") or []]
    dom_rows = []
    for d in doms.get("list") or []:
        dns, dkm, crt = d.get("dnsManagement") or {}, d.get("dkimManagement") or {}, d.get("certificateManagement") or {}
        dom_rows.append({"id": d["id"], "name": d.get("name"), "enabled": d.get("isEnabled") is not False,
                         "description": d.get("description") or "", "created": d.get("createdAt"),
                         "aliases": keys(d.get("aliases")), "catchAll": d.get("catchAllAddress"),
                         "dns": dns.get("@type") or "Manual", "publish": keys(dns.get("publishRecords")),
                         "dkimMode": dkm.get("@type") or "Manual", "dkim": dk.get(d["id"], []), "cert": crt.get("@type") or "",
                         "relaying": bool(d.get("allowRelaying")),
                         "accounts": sum(1 for a in accs.get("list") or [] if a.get("domainId") == d["id"])})
    task_rows = sorted(({"id": t.get("id"), "type": t.get("@type"), "due": t.get("due") or (t.get("status") or {}).get("due"),
                         "status": (t.get("status") or {}).get("@type"), "domain": domains.get(t.get("domainId"))}
                        for t in tasks.get("list") or []), key=lambda t: t["due"] or "")
    data = scrub({
        "fetched": int(time.time()),
        "queue": queue,
        "blocked": ips(blocked), "allowed": ips(allowed),
        "domains": dom_rows, "accounts": accounts, "certificates": cert_rows, "tasks": task_rows,
        "reports": {"dmarc": len(dx.get("ids") or []), "tls": len(tx.get("ids") or []), "arf": len(ax.get("ids") or []),
                    "dmarcOut": len(di.get("ids") or []), "tlsOut": len(ti.get("ids") or [])},
        "alerts": len(alerts.get("ids") or []),
        "counts": {"queue": len(qq.get("ids") or []), "queueTotal": qq.get("total"),
                   "failing": sum(1 for m in queue if m["status"] in ("TemporaryFailure", "PermanentFailure")),
                   "blocked": len(blocked.get("list") or []), "allowed": len(allowed.get("list") or []),
                   "domains": len(dom_rows), "accounts": len(accounts),
                   "disabled": sum(1 for a in accounts if a["disabled"])},
    })
    with _lock:
        _cache.update(at=time.time(), data=data)
    return data


def one(typ, oid, props=None):
    if not ID_RE.match(oid or ""):
        raise SwError(400, "bad id")
    args = {"accountId": ACCOUNT, "ids": [oid]}
    if props:
        args["properties"] = props
    (r,) = SW.call([(f"{typ}/get", args)])
    lst = r.get("list") or []
    if not lst:
        raise SwError(404, "not found")
    return lst[0]


def get_account(aid):
    a = one("x:Account", aid)  # all properties (so @type is there); credentials never leave this process
    if a.get("@type", "User") != "User":
        raise SwError(400, f"{a.get('name')} is a {a.get('@type')}, not a user account")
    return a


def guard_account(aid, what):
    a = get_account(aid)
    if protected(a):
        why = "protected_accounts" if (a.get("name") or "").lower() in PROTECTED else f"role {(a.get('roles') or {}).get('@type')}"
        raise SwError(403, f"{a.get('name')} is protected ({why}): {what} it in Stalwart itself")
    return a


def check_password(pw):
    if not isinstance(pw, str) or not 12 <= len(pw) <= 200 or pw.strip() != pw:
        raise SwError(400, "password: 12–200 characters, no leading/trailing spaces")
    return pw


def no_password_in_approved(claims, body):
    # an admin's request sits in lab's approval table (body included): it must never carry a password
    if claims.get("a") and body.get("password"):
        raise SwError(400, "an approved request can't carry a password: the owner sets it directly")


def who(c):
    return c["u"] + (f" (approved by {c['a']})" if c.get("a") else "")


# --- routes ------------------------------------------------------------------------------------------------------
ROUTES = []


def route(method, pattern, min_role="admin", owner=False):
    rx = re.compile("^" + pattern + "/?$")

    def deco(fn):
        ROUTES.append((method, rx, min_role, owner, fn))
        return fn
    return deco


def owner_ok(claims):
    return claims.get("r") == "owner" or bool(claims.get("a"))


@route("GET", "/api/overview")
def r_overview(c, m, b, q):
    return 200, overview(force=q.get("fresh") == ["1"])


@route("GET", r"/api/queue/([a-z0-9]+)")
def r_queue_one(c, m, b, q):
    return 200, scrub(queue_row(one("x:QueuedMessage", m[0], QUEUE_PROPS)))


@route("POST", r"/api/queue/([a-z0-9]+)/retry")
def r_queue_retry(c, m, b, q):
    one("x:QueuedMessage", m[0], ["size"])
    SW.set("x:QueuedMessage", {"update": {m[0]: {"nextRetry": RETRY_NOW}}})
    log.info("%s: retry queued message %s now", who(c), m[0])
    invalidate()
    return 200, {"ok": True}


@route("DELETE", r"/api/queue/([a-z0-9]+)", owner=True)
def r_queue_delete(c, m, b, q):
    msg = one("x:QueuedMessage", m[0], ["returnPath", "recipients"])
    SW.set("x:QueuedMessage", {"destroy": [m[0]]})
    log.info("%s: cancelled delivery of queued message %s from %s to %d recipient(s)", who(c), m[0],
             msg.get("returnPath"), len(msg.get("recipients") or {}))
    invalidate()
    return 200, {"ok": True}


@route("POST", r"/api/queue/(pause|resume)", owner=True)
def r_queue_pause(c, m, b, q):
    SW.set("x:Action", {"create": {"a": {"@type": "PauseMtaQueue" if m[0] == "pause" else "ResumeMtaQueue"}}})
    log.info("%s: %s the outgoing mail queue", who(c), "paused" if m[0] == "pause" else "resumed")
    invalidate()
    return 200, {"ok": True, "queue": "paused" if m[0] == "pause" else "running"}


@route("GET", r"/api/reports")
def r_reports(c, m, b, q):
    kind = (q.get("kind") or ["dmarc"])[0]
    if kind not in REPORT_TYPES:
        raise SwError(400, f"kind: one of {', '.join(REPORT_TYPES)}")
    typ = REPORT_TYPES[kind]
    qq, g = SW.call([(f"{typ}/query", {"accountId": ACCOUNT, "limit": 200}),
                     (f"{typ}/get", {"accountId": ACCOUNT, "#ids": {"resultOf": "0", "name": f"{typ}/query", "path": "/ids"}})])
    rows = sorted((report_summary(kind, r) for r in g.get("list") or []), key=lambda r: r["received"] or "", reverse=True)
    return 200, scrub({"kind": kind, "total": qq.get("total") or len(qq.get("ids") or []), "reports": rows})


@route("GET", r"/api/reports/(dmarc|tls|arf|dmarc-out|tls-out)/([a-z0-9]+)")
def r_report(c, m, b, q):
    r = one(REPORT_TYPES[m[0]], m[1])
    return 200, scrub({"summary": report_summary(m[0], r), "report": r.get("report") or {},
                       "to": keys(r.get("to")), "rua": keys(r.get("rua")) + keys(r.get("httpRua")) + keys(r.get("mailRua"))})


DNS_LINE = re.compile(r"^(\S+)\s+IN\s+([A-Z]+)\s+(.*)$")


def zone_records(text):
    """Stalwart's dnsZoneFile → [{name, type, value}] (multi-line ( … ) records joined)."""
    out, cur = [], None
    for line in (text or "").splitlines():
        if cur is not None:
            cur += " " + line.strip()
            if ")" in line:
                out.append(cur)
                cur = None
            continue
        if "(" in line and ")" not in line:
            cur = line.strip()
            continue
        if line.strip():
            out.append(line.strip())
    recs = []
    for r in out:
        mm = DNS_LINE.match(r)
        if mm:
            val = mm.group(3).replace("(", "").replace(")", "").strip()
            val = re.sub(r'"\s+"', "", val)
            recs.append({"name": mm.group(1), "type": mm.group(2), "value": re.sub(r"\s+", " ", val)})
    return recs


@route("GET", r"/api/domains/([a-z0-9]+)/dns")
def r_domain_dns(c, m, b, q):
    d = one("x:Domain", m[0], ["name", "dnsZoneFile"])
    zone = d.get("dnsZoneFile") or ""
    return 200, {"domain": d.get("name"), "zone": zone, "records": zone_records(zone)}


@route("POST", r"/api/accounts", owner=True)
def r_account_create(c, m, b, q):
    no_password_in_approved(c, b)
    name = str(b.get("name") or "").strip().lower()
    if not NAME_RE.match(name):
        raise SwError(400, "name: the local part (a-z 0-9 . _ -)")
    dom = str(b.get("domain") or "")
    if not ID_RE.match(dom):
        raise SwError(400, "domain: a domain id")
    one("x:Domain", dom, ["name"])
    acc = {"@type": "User", "name": name, "domainId": dom, "description": str(b.get("description") or "")[:200] or None,
           "roles": {"@type": "User"}, "permissions": {"@type": "Inherit"}}
    if b.get("password"):
        acc["credentials"] = {"0": {"@type": "Password", "secret": check_password(b["password"])}}
    if b.get("disabled"):
        acc["permissions"] = {"@type": "Merge", "enabledPermissions": {}, "disabledPermissions": {"authenticate": True}}
    r = SW.set("x:Account", {"create": {"n": acc}})
    new = ((r.get("created") or {}).get("n") or {}).get("id")
    log.info("%s: created mail account %s (id %s)%s", who(c), name, new, " with a password" if b.get("password") else "")
    invalidate()
    return 200, {"ok": True, "id": new}


@route("POST", r"/api/accounts/([a-z0-9]+)/(disable|enable)", owner=True)
def r_account_toggle(c, m, b, q):
    a = guard_account(m[0], m[1])
    p = a.get("permissions") or {"@type": "Inherit"}
    if m[1] == "disable":
        if disabled(a):
            return 200, {"ok": True, "unchanged": True}
        if p.get("@type") in ("Merge", "Replace"):
            new = {**p, "disabledPermissions": {**(p.get("disabledPermissions") or {}), "authenticate": True}}
        else:
            new = {"@type": "Merge", "enabledPermissions": {}, "disabledPermissions": {"authenticate": True}}
    else:
        if not disabled(a):
            return 200, {"ok": True, "unchanged": True}
        dis = {k: v for k, v in (p.get("disabledPermissions") or {}).items() if k != "authenticate"}
        new = {**p, "disabledPermissions": dis}
        if p.get("@type") == "Merge" and not dis and not p.get("enabledPermissions"):
            new = {"@type": "Inherit"}
    SW.set("x:Account", {"update": {m[0]: {"permissions": new}}})
    log.info("%s: %sd sign-in of mail account %s", who(c), m[1], a.get("name"))
    invalidate()
    return 200, {"ok": True}


@route("POST", r"/api/accounts/([a-z0-9]+)/password", owner=True)
def r_account_password(c, m, b, q):
    if c.get("a"):  # an admin's request sits in lab's approval table with its body: never with a password
        raise SwError(400, "an approved request can't set a password: the owner sets it directly")
    pw = check_password(b.get("password"))
    a = guard_account(m[0], "re-password")
    creds = a.get("credentials") or {}
    slot = next((k for k, v in creds.items() if (v or {}).get("@type") == "Password"), None)
    if slot is not None:
        upd = {f"credentials/{slot}/secret": pw}  # only the password: app passwords / API keys stay
    else:
        slot = str(max([int(k) for k in creds if str(k).isdigit()] or [-1]) + 1)
        upd = {f"credentials/{slot}": {"@type": "Password", "secret": pw}}
    SW.set("x:Account", {"update": {m[0]: upd}})
    log.info("%s: set a new password on mail account %s", who(c), a.get("name"))
    invalidate()
    return 200, {"ok": True}


@route("DELETE", r"/api/accounts/([a-z0-9]+)", owner=True)
def r_account_delete(c, m, b, q):
    a = guard_account(m[0], "delete")
    SW.set("x:Account", {"destroy": [m[0]]})
    log.info("%s: deleted mail account %s (id %s)", who(c), a.get("name"), m[0])
    invalidate()
    return 200, {"ok": True}


@route("DELETE", r"/api/blocked/([a-z0-9]+)", owner=True)
def r_unblock(c, m, b, q):
    ip = one("x:BlockedIp", m[0], ["address", "reason"])
    SW.set("x:BlockedIp", {"destroy": [m[0]]})
    log.info("%s: unblocked %s (%s)", who(c), ip.get("address"), ip.get("reason"))
    invalidate()
    return 200, {"ok": True, "address": ip.get("address")}


@route("GET", "/api/status")
def r_status(c, m, b, q):
    return 200, {"connector": ID, "you": c["u"], "role": c["r"], "stalwart": SW.url, "lastOk": int(SW.last_ok) or None,
                 "error": SW.last_error or None, "protected": sorted(PROTECTED)}


# --- HTTP --------------------------------------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _json(self, code, obj):
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _claims(self):
        # per request, never cached on the handler (keep-alive connections carry many users)
        if self.client_address[0] != "127.0.0.1":
            return None
        return labauth.verify(self.headers.get(labauth.HEADER), KEY, ID)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 64 * 1024:
            raise SwError(413, "body too large")
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            b = json.loads(raw)
        except ValueError:
            raise SwError(400, "body must be JSON") from None
        if not isinstance(b, dict):
            raise SwError(400, "body must be a JSON object")
        return b

    def _handle(self, method):
        url = urllib.parse.urlsplit(self.path)
        path = url.path
        try:
            body = self._body() if method in ("POST", "PUT", "PATCH", "DELETE") else {}
        except SwError as e:
            return self._json(e.code, {"error": str(e)})
        if path == "/healthz" and method == "GET":
            if not CONF.ready:
                return self._json(503, {"ok": False, "config": False, "error": CONF.why()})
            try:
                d = overview()
                return self._json(200, {"ok": True, "queue": d["counts"]["queue"], "domains": d["counts"]["domains"]})
            except SwError as e:
                return self._json(502, {"ok": False, "error": str(e)})
        claims = self._claims()
        if not claims:
            return self._json(401, {"error": "lab signature required"})
        if method == "POST" and path == "/api/_validate":
            try:
                return self._json(200, validate(labconn.candidate(claims, body)))
            except PermissionError as e:
                return self._json(403, {"error": str(e)})
            except ValueError as e:
                return self._json(400, {"error": str(e)})
        if not CONF.ready:
            return self._json(503, {"error": CONF.why()})
        try:
            for meth, rx, min_role, owner, fn in ROUTES:
                mm = rx.match(path)
                if meth != method or not mm:
                    continue
                if owner and not owner_ok(claims):
                    return self._json(403, {"error": "owner only"})
                if not labauth.at_least(claims, min_role):
                    return self._json(403, {"error": "not allowed"})
                code, obj = fn(claims, mm.groups(), body, urllib.parse.parse_qs(url.query))
                return self._json(code, scrub(obj))
            return self._json(404, {"error": "not found"})
        except SwError as e:
            return self._json(e.code, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            log.exception("request failed")
            return self._json(500, {"error": f"connector error: {type(e).__name__}"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

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
