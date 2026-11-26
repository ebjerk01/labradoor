"""Labradoor connector `ai`: the AI assistant (chat, alert triage, morning summary) on the Claude API.

How it is allowed to see things: the gateway hands this connector a short-lived delegation token with every request
an owner/admin makes to it (manifest `delegate: true`, gateway/lab/delegate.py). Every read the model asks for goes
back through the gateway's /api/delegate as THAT person — their routes, their verdicts, never `secret` routes, answers
redacted, each read audited "<user> via ai". The model cannot write: `propose_action` stores a proposal; the person's
browser runs it on a click through the normal /api/m/... path (confirm + owner-approval rules apply), then reports
the outcome here and it is fed back to the conversation.

Money: every API call is priced from its usage (agent.PRICES) into SQLite; a hard monthly cap (module setting) and a
per-user share are checked before every call. Settings come from the gateway (owner edits them under Settings).

Storage: its state directory (systemd StateDirectory, /var/lib/lab-connectors/ai, its own user): ai.sqlite3 —
conversations (pruned after retention_days), proposals, usage, triage, summaries, the last alert/object snapshot per
user. No credentials: the Claude API key comes with the module config from the gateway (field api_key), stays in memory
only and is never logged or returned.

Runs in its own venv (anthropic SDK + dependencies, hash-locked in requirements.txt next to this file; built by
lab-connector-helper before the connector starts). AI_MAX_CHATS (env, default 3) caps model turns at once."""
import hashlib
import json
import logging
import os
import queue
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
for p in ("/opt/lab/sdk/python", "/opt/lab/gateway", os.path.join(HERE, "..", "..", "sdk", "python"),
          os.path.join(HERE, "..", "..", "gateway"), HERE):
    sys.path.insert(0, p)
import labauth  # noqa: E402
import labconn  # noqa: E402
from lab import redact  # noqa: E402  (the gateway's own redaction, also used for what browsers post here)
import agent as ai  # noqa: E402

E = os.environ.get
ID = E("CONNECTOR_ID", "ai")
PORT = int(E("PORT", "8117"))
DIR = labconn.state_dir(ID, "AI_DIR")
GATEWAY = E("LAB_GATEWAY", "http://127.0.0.1:8100").rstrip("/")
MAX_CHATS = int(E("AI_MAX_CHATS", "3"))           # model turns running at once (all users)
log = logging.getLogger(ID)

DEFAULTS = {"admins": True, "monthly_cap": 90, "owner_share": 100, "admin_share": 25, "reset_day": 1,
            "chat_effort": "medium", "triage": True, "triage_warn": False, "triage_effort": "low",
            "triage_daily_max": 20, "triage_cooldown_hours": 12, "summary": True, "summary_time": "07:30",
            "summary_email": False, "auto_fix": False, "retention_days": 30, "max_tool_calls": 12,
            "tool_result_chars": 12000}
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
LIVE_KEEP = 180          # seconds a finished turn's event list stays for late pollers
MAX_BODY = 512 * 1024


class Refused(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


# --- storage ------------------------------------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, owner TEXT NOT NULL, title TEXT, created REAL,
  updated REAL, catalog TEXT, alerts_hash TEXT DEFAULT '', context TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, conv INTEGER NOT NULL, role TEXT NOT NULL,
  content TEXT NOT NULL, ui TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS messages_conv ON messages(conv, id);
CREATE TABLE IF NOT EXISTS proposals (id INTEGER PRIMARY KEY, conv INTEGER, triage TEXT, tool_id TEXT, owner TEXT,
  module TEXT, method TEXT, path TEXT, query TEXT, body TEXT, label TEXT, why TEXT, allow TEXT,
  status TEXT NOT NULL DEFAULT 'pending', code INTEGER, excerpt TEXT, created REAL, decided REAL, decided_by TEXT);
CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY, ts REAL NOT NULL, user TEXT NOT NULL, kind TEXT NOT NULL,
  model TEXT, input INTEGER, output INTEGER, cache_read INTEGER, cache_write_5m INTEGER, cache_write_1h INTEGER,
  cost REAL NOT NULL, ref TEXT);
CREATE INDEX IF NOT EXISTS usage_ts ON usage(ts);
CREATE TABLE IF NOT EXISTS triage (key TEXT PRIMARY KEY, status TEXT, alert TEXT, text TEXT, created REAL,
  updated REAL, runs INTEGER DEFAULT 0, cost REAL DEFAULT 0, by TEXT, object TEXT);
CREATE TABLE IF NOT EXISTS seen (key TEXT PRIMARY KEY, first REAL, last REAL);
CREATE TABLE IF NOT EXISTS summaries (day TEXT PRIMARY KEY, status TEXT, text TEXT, created REAL, cost REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS snapshots (user TEXT PRIMARY KEY, alerts TEXT, objects TEXT, updated REAL);
"""


class Store:
    """One SQLite connection behind a lock (the pool is small; this keeps the connection count at one)."""

    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.lock = threading.RLock()
        self.c = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=10)
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.executescript(SCHEMA)

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.c.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        r = self.q(sql, args)
        return r[0] if r else None

    def x(self, sql, args=()):
        with self.lock:
            return self.c.execute(sql, args)


# --- settings, budget ---------------------------------------------------------------------------------------------
class Settings:
    """The module's settings as the gateway reports them (owner edits them in lab); cached, defaults until known."""

    def __init__(self):
        self.values, self.at = dict(DEFAULTS), 0.0

    def update(self, values):
        v = dict(DEFAULTS)
        v.update({k: x for k, x in (values or {}).items() if k in DEFAULTS and x is not None})
        self.values, self.at = v, time.time()

    def __getitem__(self, k):
        return self.values.get(k, DEFAULTS[k])


def period_start(now, reset_day):
    """Local midnight of the last reset day (the credit cycle; approximate is fine). Days > 28 act as 28."""
    d = max(1, min(int(reset_day or 1), 28))
    t = datetime.fromtimestamp(now)
    start = t.replace(day=d, hour=0, minute=0, second=0, microsecond=0)
    if t.day < d:
        start = (start.replace(day=1) - timedelta(days=1)).replace(day=d)
    return start.timestamp()


def next_reset(now, reset_day):
    s = datetime.fromtimestamp(period_start(now, reset_day))
    return (s.replace(day=28) + timedelta(days=5)).replace(day=s.day).timestamp()


class Budget:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings

    def spent(self, user=None, now=None):
        start = period_start(now or time.time(), self.settings["reset_day"])
        if user:
            r = self.store.one("SELECT COALESCE(SUM(cost),0) AS c FROM usage WHERE ts>=? AND user=?", (start, user))
        else:
            r = self.store.one("SELECT COALESCE(SUM(cost),0) AS c FROM usage WHERE ts>=?", (start,))
        return float(r["c"])

    def user_cap(self, role):
        share = self.settings["owner_share"] if role == "owner" else self.settings["admin_share"]
        return self.settings["monthly_cap"] * max(0, min(100, int(share))) / 100.0

    def check(self, user, role, personal=True):
        cap = float(self.settings["monthly_cap"])
        if self.spent() >= cap:
            day = datetime.fromtimestamp(next_reset(time.time(), self.settings["reset_day"])).strftime("%d %b")
            raise ai.BudgetExceeded(f"the monthly AI budget (${cap:.2f}) is used up; it resets {day}")
        if personal and self.spent(user) >= self.user_cap(role):
            raise ai.BudgetExceeded(f"your share of this month's AI budget (${self.user_cap(role):.2f}) is used up")

    def record(self, user, kind, model, usd, tok, ref=""):
        self.store.x("INSERT INTO usage(ts,user,kind,model,input,output,cache_read,cache_write_5m,cache_write_1h,cost,ref)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (time.time(), user, kind, model, tok["input"], tok["output"],
                                                       tok["cache_read"], tok["cache_write_5m"], tok["cache_write_1h"],
                                                       round(usd, 6), str(ref)))
        log.info("usage %s %s %s $%.4f in=%d out=%d cr=%d cw=%d", user, kind, model, usd, tok["input"], tok["output"],
                 tok["cache_read"], tok["cache_write_5m"] + tok["cache_write_1h"])


# --- the gateway, as the user -------------------------------------------------------------------------------------
class Gateway:
    def __init__(self, token, base=GATEWAY):
        self.token, self.base = token, base

    def _get(self, path):
        req = urllib.request.Request(self.base + path, headers={"X-Lab-Delegation": self.token or "",
                                                                "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read() or b"{}")
            except ValueError:
                body = {}
            return e.code, body
        except (OSError, ValueError) as e:
            return 502, {"error": f"gateway unreachable: {type(e).__name__}"}

    def whoami(self):
        return self._get("/api/delegate/whoami")

    def get(self, module, path, query=""):
        return self._get(f"/api/delegate/m/{module}{path}" + (f"?{query}" if query else ""))


# --- the app --------------------------------------------------------------------------------------------------------
def _compile(pattern):
    segs = pattern.strip("/").split("/") if pattern.strip("/") else []
    out = ""
    for i, s in enumerate(segs):
        if s == "**":
            out += "(?:/.*)?"
            break
        out += "/" + ("[^/]+" if s == "*" else re.escape(s))
    return re.compile("^" + out + "/?$")


def match_route(mod, method, path):
    for r in (mod or {}).get("routes", []):
        if r["method"] == method and _compile(r["path"]).match(path):
            return r
    return None


def body_fits(route, body):
    """Early check of a proposed body against the route's allow-lists (the gateway checks again when it runs; a nested
    body_schema is left to the gateway)."""
    keys, allow, many = route.get("body_keys"), route.get("body_allow"), route.get("body_list") is True
    if body is None:
        return not (keys or allow) or many
    items = body if many and isinstance(body, list) else [body]
    for it in items:
        if not isinstance(it, dict):
            return False
        low = {k.lower(): v for k, v in it.items()}
        if keys and not set(low) <= {k.lower() for k in keys}:
            return False
        for k, vals in (allow or {}).items():
            if not any(type(low.get(k.lower())) is type(v) and low.get(k.lower()) == v for v in vals):
                return False
    return True


def _hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def alert_lines(alerts, limit=40):
    lines = []
    for a in (alerts or [])[:limit]:
        g = "■" if a.get("status") == "bad" else "▲"
        since = time.strftime("%d.%m %H:%M", time.localtime(a["since"])) if isinstance(a.get("since"), (int, float)) else "?"
        lines.append(f"{g} [{a.get('module', '?')}] {a.get('title', '')}" + (f" — {a['detail']}" if a.get("detail") else "")
                     + f" (key {a.get('key', '?')}; object {a.get('object') or '-'}; since {since})")
    if len(alerts or []) > limit:
        lines.append(f"... and {len(alerts) - limit} more")
    return "\n".join(lines) or "(no alerts)"


class Turn:
    """A running model turn: events for pollers (the gateway buffers answers, so the browser polls ~3x/s)."""

    def __init__(self, conv):
        self.conv, self.events, self.status, self.done_at = conv, [], "running", None
        self.cancel = False
        self.lock = threading.Lock()

    def add(self, ev):
        with self.lock:
            ev = dict(ev, n=len(self.events) + 1)
            self.events.append(ev)

    def since(self, n):
        with self.lock:
            return self.events[n:] if n >= 0 else list(self.events)


class App:
    def __init__(self, store, client=None, gateway=Gateway):
        self.store, self.client, self.gateway_cls = store, client, gateway
        self.settings = Settings()
        self.budget = Budget(store, self.settings)
        self.turns = {}           # conv id -> Turn
        self.turns_lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(MAX_CHATS)
        self.jobs = queue.Queue()
        self.catalogs = {}        # username -> (time, modules)
        self.worker = None

    # -- helpers -------------------------------------------------------------------------------------------------
    def client_or_refuse(self):
        if self.client is None:
            raise Refused(503, "no Claude API key yet (Settings → ai → connection)")
        return self.client

    def refresh(self, token, user, force=False):
        """Settings + this user's catalog from the gateway (cached briefly)."""
        hit = self.catalogs.get(user)
        if not force and hit and time.time() - hit[0] < 120 and time.time() - self.settings.at < 60:
            return hit[1]
        code, r = self.gateway_cls(token).whoami()
        if code != 200:
            raise Refused(code if code in (401, 403) else 502, f"gateway: {r.get('error', code)}")
        self.settings.update(r.get("settings"))
        self.catalogs[user] = (time.time(), r.get("modules") or [])
        return self.catalogs[user][1]

    def catalog_text(self, modules):
        lines = ["# lab modules you can read (ids for the tools; descriptions are the module authors')"]
        for m in modules:
            d = re.sub(r"\s+", " ", m.get("description") or "")[:160]
            lines.append(f"- {m['id']} — {m['name']}: {d}")
        return "\n".join(lines)

    def snapshot(self, user):
        r = self.store.one("SELECT alerts, objects FROM snapshots WHERE user=?", (user,))
        return (json.loads(r["alerts"]) if r else []), (json.loads(r["objects"]) if r else [])

    def can_chat(self, claims):
        if claims["r"] not in ("owner", "admin"):
            raise Refused(403, "the assistant is for the owner and admins")
        if claims["r"] == "admin" and not self.settings["admins"]:
            raise Refused(403, "the owner has switched the assistant off for admins")

    # -- tools ---------------------------------------------------------------------------------------------------
    def executor(self, gw, user, role, modules, conv=None, triage=None, events=None):
        limit = int(self.settings["tool_result_chars"])
        mods = {m["id"]: m for m in modules}

        def need_module(mid):
            if not (isinstance(mid, str) and ID_RE.match(mid)) or mid not in mods:
                raise ValueError(f"unknown module {mid!r}: use an id from the module list")
            return mods[mid]

        def clean_path(path):
            if not (isinstance(path, str) and path.startswith("/") and len(path) <= 500) or "?" in path or "#" in path \
                    or "*" in path or ".." in path or re.search(r"[\x00-\x20\x7f\\]", path):
                raise ValueError("path must be a concrete backend path starting with / (no ?, *, .., spaces)")
            return path

        def clean_query(q):
            q = (q or "").lstrip("?")
            if len(q) > 600 or re.search(r"[\x00-\x20\x7f#]", q):
                raise ValueError("query must be a plain query string without spaces (url-encode them)")
            return q

        def fetch(mid, path, query=""):
            code, r = gw.get(mid, path, query)
            if code != 200:
                raise ValueError(f"lab refused or failed ({code}): {r.get('error', '')}")
            return r

        def run(name, inp, tool_id):
            try:
                if name == "current_alerts":
                    alerts, _ = self.snapshot(user)
                    return ai.untrusted("lab_alerts", alert_lines(alerts, 60)), False
                if name == "find_objects":
                    _, objs = self.snapshot(user)
                    q = inp["query"].strip().lower()
                    hits = [o for o in objs if (not q and o.get("status") in ("bad", "warn")) or (q and q in " ".join(
                        str(o.get(k) or "") for k in ("id", "name", "kind", "type", "parent", "status")).lower())][:40]
                    text = "\n".join(f"{o.get('status', '?'):7} {o.get('id')} ({o.get('type')}, {o.get('kind') or '-'}"
                                     f"{', on ' + o['parent'] if o.get('parent') else ''}) via {','.join(o.get('sources') or [])}"
                                     for o in hits) or "(no match)"
                    return ai.untrusted("lab_objects", text), False
                if name == "list_routes":
                    m = need_module(inp["module"])
                    return ai.wrap_output("list_routes", m["id"], json.dumps(m["routes"], separators=(",", ":")), limit), False
                if name == "lab_get":
                    m = need_module(inp["module"])
                    path, query = clean_path(inp["path"]), clean_query(inp["query"])
                    r = match_route(m, "GET", path)
                    if not r or r.get("allow") != "yes":
                        raise ValueError("no readable GET route matches; check list_routes")
                    res = fetch(m["id"], path, query)
                    return ai.wrap_output("lab_get", f"{m['id']} GET {path}", json.dumps(res, separators=(",", ":")), limit), False
                if name == "search_logs":
                    need_module("graylog")
                    minutes = max(1, min(int(inp["minutes"]), 10080))
                    lim = max(1, min(int(inp["limit"]), 100))
                    q = urllib.parse.urlencode({"query": inp["query"] or "*", "range": minutes * 60, "limit": lim,
                                                "sort": "timestamp:desc", "decorate": "false",
                                                "fields": "timestamp,source,level,application_name,message"})
                    res = fetch("graylog", "/api/search/universal/relative", q)
                    body = res.get("body") or {}
                    lines = [f"total {body.get('total_results', '?')} in {minutes} min"]
                    for x in body.get("messages") or []:
                        msg = x.get("message") or {}
                        lines.append(f"{str(msg.get('timestamp', ''))[:19]} {msg.get('source', '?')} "
                                     f"{msg.get('application_name') or '-'} L{msg.get('level', '?')} "
                                     + re.sub(r"\s+", " ", str(msg.get("message", "")))[:300])
                    return ai.wrap_output("search_logs", inp["query"][:80], "\n".join(lines), limit), False
                if name == "drift_series":
                    need_module("drift")
                    q = urllib.parse.urlencode({"key": inp["key"], "name": inp["name"], "range": inp["range"]})
                    res = fetch("drift", "/api/series", q)
                    pts = [p[1] for p in ((res.get("body") or {}).get("points") or []) if isinstance(p, list) and len(p) > 1]
                    nums = [float(v) for v in pts if isinstance(v, (int, float)) or (isinstance(v, str) and re.match(r"^-?[\d.]+$", v))]
                    if not nums:
                        return ai.wrap_output("drift_series", f"{inp['key']} {inp['name']}", "no data", limit), False
                    step = max(1, len(nums) // 24)
                    text = (f"{inp['key']} {inp['name']} {inp['range']}: n={len(nums)} min={min(nums):.4g} "
                            f"avg={sum(nums) / len(nums):.4g} max={max(nums):.4g} last={nums[-1]:.4g}\n"
                            f"points (oldest→newest): {', '.join(f'{v:.4g}' for v in nums[::step])}")
                    return ai.wrap_output("drift_series", f"{inp['key']} {inp['name']}", text, limit), False
                if name == "propose_action":
                    return self.propose(user, role, mods, inp, tool_id, conv, triage, events,
                                        need_module, clean_path, clean_query), False
                return f"unknown tool {name}", True
            except ValueError as e:
                return str(e)[:500], True
        return run

    def propose(self, user, role, mods, inp, tool_id, conv, triage, events, need_module, clean_path, clean_query):
        m = need_module(inp["module"])
        path, query = clean_path(inp["path"]), clean_query(inp["query"])
        if inp["module"] == ID:
            raise ValueError("the assistant cannot act on itself")
        r = match_route(m, inp["method"], path)
        if not r:
            raise ValueError(f"no {inp['method']} route matches {path} in {m['id']}; check list_routes")
        body = None
        if inp["body_json"].strip():
            try:
                body = json.loads(inp["body_json"])
            except ValueError:
                raise ValueError("body_json is not valid JSON") from None
        if not body_fits(r, body):
            raise ValueError(f"body does not fit the route's allowed fields: {json.dumps({k: r[k] for k in ('body_keys', 'body_allow', 'body_schema') if k in r})}")
        label = re.sub(r"\s+", " ", inp["label"]).strip()[:80] or r.get("label") or f"{inp['method']} {path}"
        why = re.sub(r"\s+", " ", inp["why"]).strip()[:400]
        bjson = json.dumps(body) if body is not None else ""
        dup = self.store.one("SELECT id FROM proposals WHERE status='pending' AND owner=? AND module=? AND method=? "
                             "AND path=? AND query=? AND body=? AND COALESCE(conv,0)=? AND COALESCE(triage,'')=?",
                             (user, m["id"], inp["method"], path, query, bjson, conv or 0, triage or ""))
        if dup:
            pid = dup["id"]
        else:
            pid = self.store.x("INSERT INTO proposals(conv,triage,tool_id,owner,module,method,path,query,body,label,why,"
                               "allow,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               (conv, triage, tool_id, user, m["id"], inp["method"], path, query, bjson, label, why,
                                r.get("allow", "yes"), time.time())).lastrowid
        if events:
            events({"t": "proposal", "p": self.proposal(pid)})
        ask = " For this person it needs the owner's approval (owner-only route): their click sends a request." \
            if r.get("allow") == "ask" else ""
        auto = ""
        if self.settings["auto_fix"]:
            # the hook stays: delegations are read-only at the gateway, so even with auto_fix on a click is needed
            auto = " (auto_fix is on, but lab never lets the assistant write: it still needs the click.)"
        return (f"Proposal #{pid} recorded and shown to the person as a card ({label}). It has NOT run; it runs only "
                f"if they click run.{ask}{auto} Tell them briefly what it would do and why. You will get a message "
                f"if it runs.")

    def proposal(self, pid):
        p = self.store.one("SELECT * FROM proposals WHERE id=?", (pid,))
        if p:
            p["body"] = json.loads(p["body"]) if p["body"] else None
        return p

    # -- chat ----------------------------------------------------------------------------------------------------
    def new_conversation(self, claims, token, context):
        self.can_chat(claims)
        modules = self.refresh(token, claims["u"])
        ctx = json.dumps(redact.data(context))[:4000] if context else ""
        cid = self.store.x("INSERT INTO conversations(owner,title,created,updated,catalog,context) VALUES (?,?,?,?,?,?)",
                           (claims["u"], "", time.time(), time.time(), self.catalog_text(modules), ctx)).lastrowid
        return cid

    def conversation(self, cid, claims, write=False):
        c = self.store.one("SELECT * FROM conversations WHERE id=?", (cid,))
        if not c or (c["owner"] != claims["u"] and (write or claims["r"] != "owner")):
            raise Refused(404, "no such conversation")
        return c

    def history(self, cid):
        return [{"role": r["role"], "content": json.loads(r["content"])}
                for r in self.store.q("SELECT role, content FROM messages WHERE conv=? ORDER BY id", (cid,))]

    def append(self, cid, msg, ui=None):
        self.store.x("INSERT INTO messages(conv,role,content,ui,ts) VALUES (?,?,?,?,?)",
                     (cid, msg["role"], json.dumps(msg["content"], separators=(",", ":")),
                      json.dumps(ui) if ui else None, time.time()))
        self.store.x("UPDATE conversations SET updated=? WHERE id=?", (time.time(), cid))

    def ask(self, cid, claims, token, text, context=None):
        self.can_chat(claims)
        c = self.conversation(cid, claims, write=True)
        text = (text or "").strip()
        if not text or len(text) > 8000:
            raise Refused(400, "ask something (max 8000 characters)")
        self.budget.check(claims["u"], claims["r"])
        self.client_or_refuse()
        modules = self.refresh(token, claims["u"])
        alerts, _ = self.snapshot(claims["u"])
        parts = [f"<context>\nnow: {ai.now_line()}\nsigned in: {claims['u']} ({claims['r']})\n</context>"]
        obj = context or (json.loads(c["context"]) if c["context"] and not self.store.one(
            "SELECT 1 AS x FROM messages WHERE conv=?", (cid,)) else None)
        if obj:
            parts.append("The person opened the assistant from this lab object:\n"
                         + ai.untrusted("lab_object", json.dumps(redact.data(obj), separators=(",", ":"))[:4000]))
        h = _hash([a.get("key") for a in alerts] + [a.get("status") for a in alerts])
        if h != c["alerts_hash"]:
            parts.append("Current lab alerts:\n" + ai.untrusted("lab_alerts", alert_lines(alerts)))
            self.store.x("UPDATE conversations SET alerts_hash=? WHERE id=?", (h, cid))
        parts.append(text)
        msg = {"role": "user", "content": [{"type": "text", "text": "\n\n".join(parts)}]}
        if not c["title"]:
            self.store.x("UPDATE conversations SET title=? WHERE id=?", (re.sub(r"\s+", " ", text)[:70], cid))
        return self.start_turn(cid, claims, token, msg, {"kind": "question", "text": text}, modules)

    def start_turn(self, cid, claims, token, msg, ui, modules):
        with self.turns_lock:
            t = self.turns.get(cid)
            if t and t.status == "running":
                raise Refused(409, "the assistant is still answering in this conversation")
            if not self.slots.acquire(blocking=False):
                raise Refused(429, "the assistant is busy with other questions; try again in a minute")
            turn = self.turns[cid] = Turn(cid)
        self.append(cid, msg, ui)
        threading.Thread(target=self._run_turn, args=(turn, cid, claims, token, modules), daemon=True,
                         name=f"turn-{cid}").start()
        return {"conversation": cid, "running": True}

    def _run_turn(self, turn, cid, claims, token, modules):
        user, role = claims["u"], claims["r"]
        try:
            c = self.store.one("SELECT catalog FROM conversations WHERE id=?", (cid,))
            hist = self.history(cid)
            gw = self.gateway_cls(token)
            out = ai.Agent(self.client).run(
                system=ai.system_blocks(c["catalog"]), history=hist,
                execute=self.executor(gw, user, role, modules, conv=cid, events=turn.add),
                on_event=turn.add, effort=self.settings["chat_effort"],
                max_iters=int(self.settings["max_tool_calls"]), max_tokens=16000,
                gate=lambda: self.budget.check(user, role),
                on_usage=lambda usd, tok, model: self.budget.record(user, "chat", model, usd, tok, f"conv:{cid}"),
                on_append=lambda m: self.append(cid, m), cancelled=lambda: turn.cancel)
            if out["stop"] == "refusal":
                self.append(cid, {"role": "user", "content": [{"type": "text", "text":
                            "[lab] (the previous request was declined by the safety system; nothing was answered)"}]},
                            {"kind": "note", "text": "declined by the API's safety system" + (f" ({out.get('category')})" if out.get("category") else "")})
            turn.add({"t": "done", "stop": out["stop"]})
            turn.status = "done"
        except ai.BudgetExceeded as e:
            turn.add({"t": "error", "d": str(e)})
            turn.status = "error"
        except ai.Cancelled:
            turn.add({"t": "done", "stop": "cancelled"})
            turn.status = "done"
        except Exception as e:  # noqa: BLE001
            msg = api_error(e)
            log.warning("turn %s failed: %s", cid, msg)
            turn.add({"t": "error", "d": msg})
            turn.status = "error"
        finally:
            turn.done_at = time.time()
            self.slots.release()

    def render(self, cid):
        """A conversation for the UI: questions, answers, tool steps, notes, proposals."""
        props = {p["tool_id"]: p for p in self.store.q("SELECT * FROM proposals WHERE conv=?", (cid,))}
        for p in props.values():
            p["body"] = json.loads(p["body"]) if p["body"] else None
        items, tools = [], {}
        for r in self.store.q("SELECT role, content, ui, ts FROM messages WHERE conv=? ORDER BY id", (cid,)):
            content, ui = json.loads(r["content"]), json.loads(r["ui"]) if r["ui"] else None
            if r["role"] == "user":
                if ui and ui.get("kind") == "question":
                    items.append({"t": "q", "text": ui["text"], "at": r["ts"]})
                elif ui and ui.get("kind") == "note":
                    items.append({"t": "sys", "text": ui["text"], "at": r["ts"]})
                for b in content:
                    if b.get("type") == "tool_result" and b.get("tool_use_id") in tools:
                        it = tools[b["tool_use_id"]]
                        it["ok"] = not b.get("is_error")
                        it["size"] = len(b["content"]) if isinstance(b.get("content"), str) else 0
                        if b.get("is_error") and isinstance(b.get("content"), str):
                            it["err"] = b["content"][:200]
                continue
            for b in content:
                t = b.get("type")
                if t == "thinking" and b.get("thinking"):
                    items.append({"t": "note", "text": b["thinking"]})
                elif t == "text" and b.get("text"):
                    items.append({"t": "a", "text": b["text"]})
                elif t == "tool_use":
                    it = {"t": "tool", "id": b.get("id"), "name": b.get("name"), "args": ai._brief(b.get("input"))}
                    tools[b.get("id")] = it
                    if b.get("name") == "propose_action" and b.get("id") in props:
                        items.append({"t": "proposal", "p": props[b["id"]]})  # the card stands for the call
                    else:
                        items.append(it)
                elif t == "fallback":
                    items.append({"t": "sys", "text": f"answered by fallback model {((b.get('to') or {}).get('model')) or ''}"})
        return items

    # -- proposals: the browser ran (or dismissed) one -------------------------------------------------------------
    def proposal_result(self, pid, claims, token, data):
        p = self.store.one("SELECT * FROM proposals WHERE id=?", (pid,))
        if not p or (p["owner"] != claims["u"] and claims["r"] != "owner"):
            raise Refused(404, "no such proposal")
        outcome = data.get("outcome")
        if outcome not in ("ran", "failed", "asked", "dismissed"):
            raise Refused(400, "outcome: ran | failed | asked | dismissed")
        if p["status"] != "pending" and not (p["status"] == "asked" and outcome in ("ran", "failed")):
            raise Refused(409, f"proposal #{pid} is already {p['status']}")
        code = data.get("code") if isinstance(data.get("code"), int) else None
        excerpt = redact.text(str(data.get("excerpt") or "")[:2000])
        self.store.x("UPDATE proposals SET status=?, code=?, excerpt=?, decided=?, decided_by=? WHERE id=?",
                     (outcome, code, excerpt, time.time(), claims["u"], pid))
        what = f"#{pid} ({p['label']}: {p['method']} {p['module']} {p['path']}{'?' + p['query'] if p['query'] else ''})"
        note = {"ran": f"Proposal {what} was run by {claims['u']}: HTTP {code}.",
                "failed": f"Proposal {what} was clicked by {claims['u']} but failed: HTTP {code}.",
                "asked": f"Proposal {what} needs the owner's approval: {claims['u']}'s click sent approval request "
                         f"#{data.get('approval') if isinstance(data.get('approval'), int) else '?'}. It has NOT run.",
                "dismissed": f"Proposal {what} was dismissed by {claims['u']}; it did not run."}[outcome]
        if p["triage"] or not p["conv"]:
            return {"ok": True, "proposal": self.proposal(pid)}
        text = "[lab] " + note + (("\nResponse excerpt:\n" + ai.untrusted("tool_output", excerpt)) if excerpt else "")
        msg = {"role": "user", "content": [{"type": "text", "text": text}]}
        ui = {"kind": "note", "text": note}
        if outcome in ("ran", "failed") and p["owner"] == claims["u"]:
            try:  # let the assistant look at the outcome (and check the effect) right away
                self.can_chat(claims)
                self.budget.check(claims["u"], claims["r"])
                self.client_or_refuse()
                modules = self.refresh(token, claims["u"])
                self.start_turn(p["conv"], claims, token, msg, ui, modules)
                return {"ok": True, "proposal": self.proposal(pid), "conversation": p["conv"], "running": True}
            except (Refused, ai.BudgetExceeded) as e:
                log.info("no follow-up turn for proposal %s: %s", pid, e)
        self.append(p["conv"], msg, ui)
        return {"ok": True, "proposal": self.proposal(pid)}

    # -- monitoring: snapshots from browsers → triage + morning summary -------------------------------------------
    def sync(self, claims, token, data):
        if claims["r"] not in ("owner", "admin"):
            raise Refused(403, "owner/admin only")
        alerts = [a for a in (data.get("alerts") or []) if isinstance(a, dict)][:300]
        objects = [o for o in (data.get("objects") or []) if isinstance(o, dict)][:1500]
        keep_a = ("key", "module", "status", "title", "detail", "object", "since")
        keep_o = ("id", "type", "name", "kind", "status", "parent", "sources", "meta")
        alerts = redact.data([{k: a.get(k) for k in keep_a if a.get(k) is not None} for a in alerts])
        objects = redact.data([{k: o.get(k) for k in keep_o if o.get(k) is not None} for o in objects])
        first = not self.store.one("SELECT 1 AS x FROM snapshots WHERE user=?", (claims["u"],))
        self.store.x("INSERT INTO snapshots VALUES (?,?,?,?) ON CONFLICT(user) DO UPDATE SET alerts=excluded.alerts, "
                     "objects=excluded.objects, updated=excluded.updated",
                     (claims["u"], json.dumps(alerts), json.dumps(objects), time.time()))
        if claims["r"] == "admin" and not self.settings["admins"]:
            return {"ok": True, "queued": 0}
        try:
            self.refresh(token, claims["u"])
        except Refused:
            pass
        queued = 0
        now = time.time()
        fresh = []
        for a in alerts:
            key = f"{a.get('module')}:{a.get('key')}"
            if not self.store.one("SELECT 1 AS x FROM seen WHERE key=?", (key,)):
                self.store.x("INSERT OR IGNORE INTO seen VALUES (?,?,?)", (key, now, now))
                fresh.append((key, a))
            else:
                self.store.x("UPDATE seen SET last=? WHERE key=?", (now, key))
        if first:  # this person's first snapshot (alerts differ per person): what is already red is not "new"
            fresh = []
        current = {f"{a.get('module')}:{a.get('key')}": a for a in alerts}
        for r in self.store.q("SELECT key FROM triage WHERE status='waiting'"):
            if r["key"] in current:
                fresh.append((r["key"], current[r["key"]]))
        for key, a in fresh:
            if a.get("status") == "bad" or (a.get("status") == "warn" and self.settings["triage_warn"]):
                queued += self.queue_triage(key, a, claims, token, manual=False)
        if self.summary_due(now):
            self.store.x("INSERT OR IGNORE INTO summaries(day,status,created) VALUES (?,?,?)",
                         (time.strftime("%Y-%m-%d", time.localtime(now)), "queued", now))
            self.jobs.put(("summary", None, dict(claims), token))
            queued += 1
        return {"ok": True, "queued": queued}

    def summary_due(self, now):
        if not self.settings["summary"] or self.client is None:
            return False
        m = re.match(r"^(\d{1,2}):(\d{2})$", str(self.settings["summary_time"]).strip())
        hh, mm = (int(m.group(1)), int(m.group(2))) if m else (7, 30)
        t = time.localtime(now)
        if (t.tm_hour, t.tm_min) < (hh, mm):
            return False
        return not self.store.one("SELECT 1 AS x FROM summaries WHERE day=?", (time.strftime("%Y-%m-%d", t),))

    def queue_triage(self, key, alert, claims, token, manual):
        if not self.settings["triage"] and not manual:
            return 0
        if self.client is None:
            if manual:
                raise Refused(503, "no Claude API key on the lab CT")
            return 0
        now = time.time()
        row = self.store.one("SELECT * FROM triage WHERE key=?", (key,))
        if row and row["status"] in ("queued", "running"):
            return 0
        if row and not manual and now - (row["updated"] or 0) < float(self.settings["triage_cooldown_hours"]) * 3600:
            return 0
        day0 = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        n = self.store.one("SELECT COUNT(*) AS n FROM usage WHERE kind='triage' AND ts>=? AND ref LIKE 'start:%'", (day0,))["n"]
        if n >= int(self.settings["triage_daily_max"]):
            if manual:
                raise Refused(429, f"daily triage limit ({self.settings['triage_daily_max']}) reached")
            return 0
        self.store.x("INSERT INTO triage(key,status,alert,created,updated,by,object) VALUES (?,?,?,?,?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET status='queued', alert=excluded.alert, updated=excluded.updated, "
                     "by=excluded.by, object=excluded.object",
                     (key, "queued", json.dumps(alert), now, now, claims["u"], alert.get("object")))
        self.jobs.put(("triage", key, dict(claims), token))
        return 1

    def worker_loop(self):
        while True:
            kind, key, claims, token = self.jobs.get()
            try:
                if kind == "triage":
                    self.run_triage(key, claims, token)
                elif kind == "summary":
                    self.run_summary(claims, token)
            except Exception:  # noqa: BLE001
                log.exception("%s job failed", kind)

    def _background(self, kind, ref, claims, token, prompt, effort, done):
        """One investigation (triage or summary) with a small budget; returns the final text."""
        user, role = claims["u"], claims["r"]
        modules = self.refresh(token, user, force=True)
        hist = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        first = [True]

        def usage(usd, tok, model):
            self.budget.record(f"({kind})", kind, model, usd, tok, ("start:" if first[0] else "") + ref)
            first[0] = False
            done(usd)
        out = ai.Agent(self.client).run(
            system=ai.system_blocks(self.catalog_text(modules)), history=hist,
            execute=self.executor(self.gateway_cls(token), user, role, modules,
                                  triage=ref if kind == "triage" else None),
            on_event=lambda e: None, effort=effort, max_iters=6, max_tokens=8000,
            gate=lambda: self.budget.check(user, role, personal=False), on_usage=usage, task_budget=20000)
        if out["stop"] == "refusal":
            return "(declined by the API's safety system)"
        return out["text"].strip() or "(no answer)"

    def run_triage(self, key, claims, token):
        row = self.store.one("SELECT * FROM triage WHERE key=?", (key,))
        if not row:
            return
        self.store.x("UPDATE triage SET status='running', updated=? WHERE key=?", (time.time(), key))
        self.store.x("UPDATE proposals SET status='expired' WHERE triage=? AND status='pending'", (key,))
        alert = json.loads(row["alert"])
        prompt = ("<task>A new alert appeared in lab. Triage it: find the most likely cause with a few targeted reads "
                  "(at most 5 tool calls: the alert's own module first, then logs/metrics if useful), then answer in at "
                  "most 5 short lines: cause · evidence · suggested fix. If one concrete lab action would fix or "
                  "mitigate it, call propose_action once (the owner decides; it does not run by itself). If it looks "
                  "like noise the owner ignores (a laptop offline, a short blip), say so in one line. Write in English.</task>\n"
                  f"<context>now: {ai.now_line()}</context>\n" + ai.untrusted("alert", json.dumps(alert)))
        cost = [0.0]
        try:
            text = self._background("triage", key, claims, token, prompt, self.settings["triage_effort"],
                                    lambda usd: cost.__setitem__(0, cost[0] + usd))
            status = "done"
        except Refused as e:  # the delegation expired while queued: the next browser sync starts it again
            text, status = f"waiting for a fresh lab session ({e.msg})", "waiting"
        except ai.BudgetExceeded as e:
            text, status = f"not triaged: {e}", "skipped"
        except Exception as e:  # noqa: BLE001
            text, status = f"triage failed: {api_error(e)}", "failed"
        self.store.x("UPDATE triage SET status=?, text=?, updated=?, runs=runs+1, cost=cost+? WHERE key=?",
                     (status, text[:4000], 0 if status == "waiting" else time.time(), cost[0], key))

    def run_summary(self, claims, token):
        day = time.strftime("%Y-%m-%d")
        self.store.x("UPDATE summaries SET status='running' WHERE day=?", (day,))
        alerts, _ = self.snapshot(claims["u"])
        prompt = ("<task>Write lab's morning summary for today. Check briefly (at most 5 tool calls): what is wrong "
                  "now and since when, what happened overnight (errors in the logs since 22:00, backups, updates "
                  "waiting), and what deserves attention today. Answer in at most 10 short markdown lines, the most "
                  "important first, with status glyphs (■ bad, ▲ warn, ● ok). Do not propose actions. Write in English.</task>\n"
                  f"<context>now: {ai.now_line()}</context>\nCurrent lab alerts:\n"
                  + ai.untrusted("lab_alerts", alert_lines(alerts)))
        cost = [0.0]
        try:
            text = self._background("summary", day, claims, token, prompt, "low",
                                    lambda usd: cost.__setitem__(0, cost[0] + usd))
            status = "done"
        except Refused:  # delegation expired while queued: due again at the next sync
            self.store.x("DELETE FROM summaries WHERE day=?", (day,))
            return
        except ai.BudgetExceeded as e:
            text, status = f"no summary: {e}", "skipped"
        except Exception as e:  # noqa: BLE001
            text, status = f"summary failed: {api_error(e)}", "failed"
        self.store.x("UPDATE summaries SET status=?, text=?, created=?, cost=? WHERE day=?",
                     (status, text[:6000], time.time(), cost[0], day))

    # -- views ---------------------------------------------------------------------------------------------------
    def state(self, claims):
        u, role = claims["u"], claims["r"]
        now = time.time()
        start = period_start(now, self.settings["reset_day"])
        by_user = {r["user"]: round(r["c"], 4) for r in self.store.q(
            "SELECT user, SUM(cost) AS c FROM usage WHERE ts>=? GROUP BY user", (start,))}
        by_kind = {r["kind"]: round(r["c"], 4) for r in self.store.q(
            "SELECT kind, SUM(cost) AS c FROM usage WHERE ts>=? GROUP BY kind", (start,))}
        spent = sum(by_user.values())
        where = "" if role == "owner" else " WHERE owner=?"
        convs = self.store.q("SELECT id, owner, title, created, updated FROM conversations" + where +
                             " ORDER BY updated DESC LIMIT 60", () if role == "owner" else (u,))
        for c in convs:
            t = self.turns.get(c["id"])
            c["running"] = bool(t and t.status == "running")
        week = now - 7 * 86400
        triage = self.store.q("SELECT key, status, alert, text, updated, runs, object FROM triage WHERE updated>? "
                              "ORDER BY updated DESC LIMIT 60", (week,))
        for t in triage:
            t["alert"] = json.loads(t["alert"] or "{}")
            t["proposals"] = [self.proposal(p["id"]) for p in self.store.q(
                "SELECT id FROM proposals WHERE triage=? ORDER BY id DESC LIMIT 3", (t["key"],))]
        summ = self.store.one("SELECT * FROM summaries ORDER BY day DESC LIMIT 1")
        s = self.settings
        return {
            "me": {"user": u, "role": role}, "enabled": role == "owner" or bool(s["admins"]),
            "keyed": self.client is not None,
            "month": {"start": start, "reset": next_reset(now, s["reset_day"]), "spent": round(spent, 4),
                      "cap": s["monthly_cap"], "mine": round(by_user.get(u, 0.0), 4), "myCap": self.budget.user_cap(role),
                      "byUser": by_user if role == "owner" else {u: by_user.get(u, 0.0)}, "byKind": by_kind},
            "conversations": convs, "triage": triage, "summary": summ,
            "settings": {k: s[k] for k in ("triage", "triage_warn", "summary", "summary_time", "auto_fix", "admins",
                                           "chat_effort", "triage_daily_max", "retention_days")},
        }

    def usage(self, claims):
        start = period_start(time.time(), self.settings["reset_day"])
        where, args = "WHERE ts>=?", [start]
        if claims["r"] != "owner":
            where += " AND user=?"
            args.append(claims["u"])
        days = self.store.q(f"SELECT date(ts,'unixepoch','localtime') AS day, SUM(cost) AS c, COUNT(*) AS n FROM usage "
                            f"{where} GROUP BY day ORDER BY day", args)
        recent = self.store.q(f"SELECT ts, user, kind, model, input, output, cache_read, cache_write_5m, "
                              f"cache_write_1h, cost FROM usage {where} ORDER BY id DESC LIMIT 50", args)
        return {"days": days, "recent": recent}

    def prune(self):
        days = int(self.settings["retention_days"])
        old = time.time() - days * 86400
        for c in self.store.q("SELECT id FROM conversations WHERE updated<?", (old,)):
            self.delete_conversation(c["id"])
        self.store.x("DELETE FROM triage WHERE updated<?", (time.time() - 30 * 86400,))
        self.store.x("DELETE FROM proposals WHERE conv IS NULL AND created<?", (time.time() - 30 * 86400,))
        self.store.x("DELETE FROM summaries WHERE created<?", (time.time() - 60 * 86400,))
        self.store.x("DELETE FROM usage WHERE ts<?", (time.time() - 400 * 86400,))
        self.store.x("DELETE FROM seen WHERE last<?", (time.time() - 30 * 86400,))
        with self.turns_lock:
            for cid in [k for k, t in self.turns.items() if t.done_at and time.time() - t.done_at > LIVE_KEEP]:
                del self.turns[cid]

    def delete_conversation(self, cid):
        self.store.x("DELETE FROM messages WHERE conv=?", (cid,))
        self.store.x("DELETE FROM proposals WHERE conv=?", (cid,))
        self.store.x("DELETE FROM conversations WHERE id=?", (cid,))


def api_error(e):
    """A short, key-free description of a failed API call."""
    try:
        import anthropic
    except ImportError:  # tests without the SDK
        return f"{type(e).__name__}: {str(e)[:200]}"
    if isinstance(e, anthropic.AuthenticationError):
        return "the Claude API rejected the key"
    if isinstance(e, anthropic.RateLimitError):
        return "rate limited by the Claude API; try again in a minute"
    if isinstance(e, anthropic.BadRequestError):
        return f"request rejected: {getattr(e, 'message', '')[:300]}"
    if isinstance(e, anthropic.APIStatusError):
        return f"Claude API error {e.status_code}" + (" (overloaded)" if e.status_code == 529 else "")
    if isinstance(e, anthropic.APIConnectionError):
        return "cannot reach the Claude API"
    return f"{type(e).__name__}: {str(e)[:200]}"


def make_client(key):
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key, max_retries=2, timeout=anthropic.Timeout(300.0, connect=10.0))


def configure(v, conf=None):
    """The module config from the gateway: the Claude API key (memory only)."""
    key = labconn.text(v, "api_key")
    ai.BACKGROUND = str(v.get("background") or "")
    if APP is not None:
        APP.client = make_client(key)
    if not key:
        log.warning("no Claude API key in the module config: chat/triage answer 503")


def validate(values):
    """Config test: list one model with the CANDIDATE key (free; proves the key works)."""
    key = labconn.text(values, "api_key")
    if not key:
        return {"ok": False, "error": "no API key"}
    try:
        page = make_client(key).models.list(limit=1)
        n = len(getattr(page, "data", []) or [])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": api_error(e)}
    return {"ok": True, "detail": f"the Claude API accepted the key ({n} model listed)"}


# --- HTTP ---------------------------------------------------------------------------------------------------------
KEY = labconn.load_key(ID)
CONF = labconn.Config(ID, KEY, apply=configure)
APP = None
CONV_RE = re.compile(r"^/api/conversations/(\d+)(/messages|/live|/stop)?$")
PROP_RE = re.compile(r"^/api/proposals/(\d+)/result$")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    timeout = 30

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _json(self, code, obj):
        body = json.dumps(obj, separators=(",", ":")).encode()
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
        if n > MAX_BODY:
            raise Refused(413, "request too large")
        try:
            d = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            raise Refused(400, "invalid JSON") from None
        if not isinstance(d, dict):
            raise Refused(400, "expected a JSON object")
        return d

    def _go(self, method):
        url = urllib.parse.urlsplit(self.path)
        path, q = url.path, urllib.parse.parse_qs(url.query)
        if path == "/healthz":
            return self._json(200, {"ok": True, "config": CONF.ready, "keyed": APP.client is not None})
        claims = self._claims()
        if not claims:
            return self._json(401, {"error": "lab signature required"})
        if method == "POST" and path == "/api/_validate":
            try:
                return self._json(200, validate(labconn.candidate(claims, self._body())))
            except PermissionError as e:
                return self._json(403, {"error": str(e)})
            except (ValueError, Refused) as e:
                return self._json(400, {"error": str(e)})
        token = self.headers.get("X-Lab-Delegation") or ""
        try:
            if claims["r"] not in ("owner", "admin"):
                raise Refused(403, "the assistant is for the owner and admins")
            if token and time.time() - APP.settings.at > 60:
                try:
                    APP.refresh(token, claims["u"], force=True)
                except Refused as e:
                    log.info("settings refresh: %s", e.msg)
            return self._json(200, self._route(method, path, q, claims, token))
        except Refused as e:
            return self._json(e.code, {"error": e.msg})
        except ai.BudgetExceeded as e:
            return self._json(402, {"error": str(e), "budget": True})
        except Exception:  # noqa: BLE001
            log.exception("%s %s", method, path)
            return self._json(500, {"error": "internal error"})

    def _route(self, method, path, q, claims, token):
        a = APP
        if method == "GET" and path == "/api/state":
            return a.state(claims)
        if method == "GET" and path == "/api/usage":
            return a.usage(claims)
        if method == "GET" and path == "/api/conversations":
            return {"conversations": a.state(claims)["conversations"]}
        if method == "POST" and path == "/api/conversations":
            d = self._body()
            ctx = d.get("context") if isinstance(d.get("context"), dict) else None
            if isinstance(d.get("text"), str) and d["text"].strip():
                a.can_chat(claims)
                a.budget.check(claims["u"], claims["r"])  # refuse before an empty chat is left behind
            cid = a.new_conversation(claims, token, ctx)
            if isinstance(d.get("text"), str) and d["text"].strip():
                a.ask(cid, claims, token, d["text"], ctx)
            return {"conversation": cid}
        if method == "POST" and path == "/api/sync":
            return a.sync(claims, token, self._body())
        if method == "POST" and path == "/api/triage":
            d = self._body()
            alerts, _ = a.snapshot(claims["u"])
            al = next((x for x in alerts if f"{x.get('module')}:{x.get('key')}" == d.get("key")), None)
            if not al:
                raise Refused(404, "no such current alert (sync first)")
            a.can_chat(claims)
            a.budget.check(claims["u"], claims["r"], personal=False)
            return {"queued": a.queue_triage(d["key"], al, claims, token, manual=True)}
        m = PROP_RE.match(path)
        if m and method == "POST":
            return a.proposal_result(int(m.group(1)), claims, token, self._body())
        m = CONV_RE.match(path)
        if m:
            cid, sub = int(m.group(1)), m.group(2) or ""
            if method == "GET" and not sub:
                c = a.conversation(cid, claims)
                t = a.turns.get(cid)
                return {"conversation": {k: c[k] for k in ("id", "owner", "title", "created", "updated")},
                        "items": a.render(cid), "running": bool(t and t.status == "running"),
                        "events": len(t.events) if t else 0}
            if method == "GET" and sub == "/live":
                a.conversation(cid, claims)
                t = a.turns.get(cid)
                try:
                    since = max(0, int((q.get("since") or ["0"])[0]))
                except ValueError:
                    since = 0
                if not t:
                    return {"status": "idle", "events": []}
                return {"status": t.status, "events": t.since(since)}
            if method == "POST" and sub == "/messages":
                d = self._body()
                return a.ask(cid, claims, token, d.get("text"), d.get("context") if isinstance(d.get("context"), dict) else None)
            if method == "POST" and sub == "/stop":
                a.conversation(cid, claims, write=True)
                t = a.turns.get(cid)
                if t:
                    t.cancel = True
                return {"ok": True}
            if method == "DELETE" and not sub:
                a.conversation(cid, claims, write=claims["r"] != "owner")
                t = a.turns.get(cid)
                if t and t.status == "running":
                    raise Refused(409, "stop it first")
                a.delete_conversation(cid)
                return {"ok": True}
        raise Refused(404, "not found")

    def do_GET(self):
        self._go("GET")

    def do_POST(self):
        self._go("POST")

    def do_DELETE(self):
        self._go("DELETE")


class PooledHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    pool = ThreadPoolExecutor(max_workers=16)

    def process_request(self, request, client_address):
        self.pool.submit(self.process_request_thread, request, client_address)


def main():
    global APP
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its request lines are noise (and never carry the key)
    APP = App(Store(os.path.join(DIR, "ai.sqlite3")), None)  # the client comes with the config (configure)
    threading.Thread(target=APP.worker_loop, name="jobs", daemon=True).start()

    def prune_loop():
        while True:
            try:
                APP.prune()
            except Exception:  # noqa: BLE001
                log.exception("prune failed")
            time.sleep(600)
    threading.Thread(target=prune_loop, name="prune", daemon=True).start()
    log.info("connector %s on 127.0.0.1:%s (key %s)", ID, PORT, "ok" if KEY else "MISSING")
    CONF.start()
    PooledHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
