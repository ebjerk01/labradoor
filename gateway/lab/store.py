"""SQLite store: users (local accounts and/or as last seen from the SSO login service), sessions, first-run setup tokens,
login settings, audit log, owner approvals, per-user prefs.

One connection per thread (threading.local); the server runs a fixed thread pool, so the count stays bounded."""
import hashlib
import json
import secrets
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY, name TEXT, email TEXT, groups TEXT NOT NULL DEFAULT '[]',
  role TEXT NOT NULL DEFAULT 'guest', pw_hash TEXT, created REAL NOT NULL, last_seen REAL);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL,
  ua TEXT, ip TEXT, via TEXT);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(username);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, ts REAL NOT NULL, username TEXT, role TEXT, action TEXT NOT NULL,
  module TEXT, target TEXT, result TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS audit_ts ON audit(ts);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY, created REAL NOT NULL, expires REAL NOT NULL, requester TEXT NOT NULL,
  module TEXT NOT NULL, method TEXT NOT NULL, path TEXT NOT NULL, query TEXT, body TEXT,
  label TEXT, reason TEXT, status TEXT NOT NULL DEFAULT 'pending',
  decided_by TEXT, decided_at REAL, result_code INTEGER, result_body TEXT);
CREATE INDEX IF NOT EXISTS approvals_status ON approvals(status);
CREATE TABLE IF NOT EXISTS prefs (
  username TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (username, key));
CREATE TABLE IF NOT EXISTS login_failures (ip TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS module_settings (
  module TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (module, key));
"""

AUDIT_KEEP_DAYS = 365
# review L3: what an approval carried (a typed password in the body, a secret GET's answer in result_body) is kept for
# this long after the decision; the row itself (who asked what, who decided) stays for the record
APPROVAL_BODY_DAYS = 30

# Schema changes after the baseline above: append (version, sql or [sql, ...]) — never edit or reorder an applied step.
# The database records its version in PRAGMA user_version; code older than the database refuses to start
# (roll back with `lab-admin rollback --with-db`, which restores the copy taken before that deploy).
MIGRATIONS = [
    # v2 modules: their per-installation config (URL, options) and sealed secrets (secretbox.py; value = "v1:…")
    (2, ["CREATE TABLE IF NOT EXISTS module_config (module TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
         "secret INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL, PRIMARY KEY (module, key))"]),
    # step 14, login: local accounts as a normal login (disable, TOTP + recovery codes), which accounts SSO may log in
    # to (every account that existed before was an SSO or SSO-linked one: sso=1), first-run setup tokens (hashed, one
    # use) and the gateway's own settings (Login: SSO config with a sealed client secret, 2FA policy, session lengths)
    (3, ["ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0",
         "ALTER TABLE users ADD COLUMN totp TEXT",
         "ALTER TABLE users ADD COLUMN totp_step INTEGER NOT NULL DEFAULT 0",
         "ALTER TABLE users ADD COLUMN recovery TEXT NOT NULL DEFAULT '[]'",
         "ALTER TABLE users ADD COLUMN sso INTEGER NOT NULL DEFAULT 0",
         "UPDATE users SET sso=1",
         "CREATE TABLE IF NOT EXISTS setup_tokens (token_hash TEXT PRIMARY KEY, created REAL NOT NULL, "
         "expires REAL NOT NULL, used REAL)",
         "CREATE TABLE IF NOT EXISTS gateway_config (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
         "secret INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL)"]),
]
SCHEMA_VERSION = 1 + len(MIGRATIONS)


class SchemaTooNew(RuntimeError):
    pass


SETUP_CLOSED_KEY = "setup_closed"   # gateway_config: an owner has existed (setup only via lab-admin setup-link --recover)


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.path = path
        self._local = threading.local()
        with self._conn() as c:
            c.executescript(SCHEMA)
            self.migrate(c)

    @staticmethod
    def migrate(c, migrations=None):
        steps = MIGRATIONS if migrations is None else migrations
        latest = 1 + len(steps)
        cur = c.execute("PRAGMA user_version").fetchone()[0] or 1  # 0 = a database from before versioning = baseline
        if cur > latest:
            raise SchemaTooNew(f"database schema v{cur} is newer than this code (v{latest}): "
                               "deploy newer code or `lab-admin rollback --with-db`")
        for version, sql in steps:
            if version <= cur:
                continue
            c.execute("BEGIN IMMEDIATE")
            try:
                for stmt in ([sql] if isinstance(sql, str) else sql):  # one statement, or a list of them
                    c.execute(stmt)
                c.execute(f"PRAGMA user_version={int(version)}")
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
            cur = version
        if c.execute("PRAGMA user_version").fetchone()[0] != cur:
            c.execute(f"PRAGMA user_version={int(cur)}")
        return cur

    def _conn(self):
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=5000")
            self._local.c = c
        return c

    def q(self, sql, args=()):
        return [dict(r) for r in self._conn().execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        r = self._conn().execute(sql, args).fetchone()
        return dict(r) if r else None

    def x(self, sql, args=()):
        return self._conn().execute(sql, args)

    # --- users -------------------------------------------------------------------------------------------
    def upsert_user(self, username, name, email, groups, role):
        now = time.time()
        self.x("""INSERT INTO users(username, name, email, groups, role, created, last_seen) VALUES (?,?,?,?,?,?,?)
                  ON CONFLICT(username) DO UPDATE SET name=excluded.name, email=excluded.email,
                  groups=excluded.groups, role=excluded.role, last_seen=excluded.last_seen""",
               (username, name, email, json.dumps(sorted(groups)), role, now, now))
        if role == "owner":
            self.close_setup()
        return self.user(username)

    def user(self, username):
        u = self.one("SELECT * FROM users WHERE username=?", (username,))
        if u:
            u["groups"] = json.loads(u["groups"] or "[]")
        return u

    def user_casefold(self, username):
        """Another account whose name equals this one ignoring case, or None."""
        r = self.one("SELECT username FROM users WHERE lower(username)=lower(?) AND username<>?", (username, username))
        return r["username"] if r else None

    def users(self):
        rows = self.q("SELECT username, name, email, groups, role, created, last_seen, pw_hash IS NOT NULL AS local, "
                      "disabled, totp IS NOT NULL AS totp, recovery, sso FROM users ORDER BY last_seen DESC")
        for r in rows:
            r["groups"] = json.loads(r["groups"] or "[]")
            r["local"], r["disabled"], r["totp"], r["sso"] = (bool(r[k]) for k in ("local", "disabled", "totp", "sso"))
            r["recovery_left"] = len(json.loads(r.pop("recovery") or "[]"))
        return rows

    def create_local_user(self, username, name, role, groups, pw_hash, sso=False):
        """A new local account; False when the username is taken."""
        now = time.time()
        cur = self.x("INSERT OR IGNORE INTO users(username, name, email, groups, role, pw_hash, created, last_seen, sso) "
                     "VALUES (?,?,?,?,?,?,?,?,?)",
                     (username, name or username, "", json.dumps(sorted(set(groups or []))), role, pw_hash, now, None,
                      int(bool(sso))))
        if role == "owner" and cur.rowcount == 1:
            self.close_setup()
        return cur.rowcount == 1

    def update_user(self, username, **fields):
        """name, role, groups (list), disabled, sso — only the given ones."""
        cols = {"name": str, "role": str, "groups": lambda g: json.dumps(sorted(set(g))), "disabled": int, "sso": int}
        sets = [(k, cols[k](v)) for k, v in fields.items() if k in cols and v is not None]
        if sets:
            self.x(f"UPDATE users SET {', '.join(k + '=?' for k, _ in sets)} WHERE username=?",
                   (*[v for _, v in sets], username))
            if fields.get("role") == "owner":
                self.close_setup()

    def delete_user(self, username):
        self.end_sessions_for(username)
        self.x("DELETE FROM prefs WHERE username=?", (username,))
        return self.x("DELETE FROM users WHERE username=?", (username,)).rowcount

    def active_owners(self):
        return [r["username"] for r in self.q("SELECT username FROM users WHERE role='owner' AND disabled=0")]

    def set_totp(self, username, sealed_secret, step=0, recovery_hashes=None):
        """sealed_secret None turns TOTP off (and drops the recovery codes)."""
        self.x("UPDATE users SET totp=?, totp_step=?, recovery=? WHERE username=?",
               (sealed_secret, int(step or 0), json.dumps(recovery_hashes or []), username))

    def totp_used(self, username, step):
        """Records the accepted time step; False when another request already used this step or a later one."""
        return self.x("UPDATE users SET totp_step=? WHERE username=? AND totp_step<?", (int(step), username, int(step))).rowcount == 1

    def set_recovery(self, username, hashes):
        self.x("UPDATE users SET recovery=? WHERE username=?", (json.dumps(hashes), username))

    def use_recovery(self, username, code_hash):
        """Spends one recovery code; False when it is not (or no longer) one of the user's."""
        c = self._conn()
        c.execute("BEGIN IMMEDIATE")
        try:
            row = c.execute("SELECT recovery FROM users WHERE username=?", (username,)).fetchone()
            left = json.loads((row and row["recovery"]) or "[]")
            if code_hash not in left:
                c.execute("ROLLBACK")
                return False
            left.remove(code_hash)
            c.execute("UPDATE users SET recovery=? WHERE username=?", (json.dumps(left), username))
            c.execute("COMMIT")
            return True
        except Exception:
            c.execute("ROLLBACK")
            raise

    # --- first-run setup tokens (only hashes are stored) -------------------------------------------------------------
    def new_setup_token(self, seconds=3600):
        """A fresh one-time token; every earlier one stops working."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        self.x("DELETE FROM setup_tokens")
        self.x("INSERT INTO setup_tokens VALUES (?,?,?,NULL)", (_hash(token), now, now + seconds))
        return token

    def setup_token_valid(self, token):
        return bool(token) and self.one("SELECT 1 AS ok FROM setup_tokens WHERE token_hash=? AND used IS NULL AND expires>?",
                                        (_hash(str(token)), time.time())) is not None

    def setup_token_pending(self):
        return self.one("SELECT 1 AS ok FROM setup_tokens WHERE used IS NULL AND expires>?", (time.time(),)) is not None

    def use_setup_token(self, token):
        """Atomically spends the token (True once); the caller creates the owner right after."""
        return bool(token) and self.x("UPDATE setup_tokens SET used=? WHERE token_hash=? AND used IS NULL AND expires>?",
                                      (time.time(), _hash(str(token)), time.time())).rowcount == 1

    def drop_setup_tokens(self):
        self.x("DELETE FROM setup_tokens")

    def setup_closed(self):
        """Has this installation ever had an owner? Then first-run setup never reopens by itself — not when the last
        owner is demoted (an IdP group change, rolesync) or disabled: only a link root makes on purpose
        (`lab-admin setup-link --recover`) opens it (review 2026-11-15, L2). A flag in gateway_config, set the first
        time an owner is seen; installations from before the flag get it from their users table."""
        if self.one("SELECT 1 AS ok FROM gateway_config WHERE key=?", (SETUP_CLOSED_KEY,)):
            return True
        if self.one("SELECT 1 AS ok FROM users WHERE role='owner'"):
            self.set_gateway_config(SETUP_CLOSED_KEY, True)
            return True
        return False

    def close_setup(self):
        self.set_gateway_config(SETUP_CLOSED_KEY, True)

    def setup_open(self):
        """Is the first-run setup route open? Never with an active owner. A fresh installation (no owner ever): yes,
        for whoever holds root's link. After that: only while a root-made link is pending."""
        closed = self.setup_closed()   # first: an owner row present now sets the flag for good
        if self.active_owners():
            return False
        return not closed or self.setup_token_pending()

    # --- gateway settings (Login) ----------------------------------------------------------------------------------
    def gateway_config(self):
        """{key: (value, is_secret)} — secrets stay sealed here; values are JSON."""
        return {r["key"]: (r["value"] if r["secret"] else json.loads(r["value"]), bool(r["secret"]))
                for r in self.q("SELECT key, value, secret FROM gateway_config")}

    def set_gateway_config(self, key, value, secret=False):
        if value is None:
            self.x("DELETE FROM gateway_config WHERE key=?", (key,))
            return
        self.x("INSERT INTO gateway_config VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
               "secret=excluded.secret, updated=excluded.updated",
               (key, value if secret else json.dumps(value), int(bool(secret)), time.time()))

    def set_password_hash(self, username, pw_hash):
        self.x("UPDATE users SET pw_hash=? WHERE username=?", (pw_hash, username))

    def set_role(self, username, role):
        self.x("UPDATE users SET role=? WHERE username=?", (role, username))
        if role == "owner":
            self.close_setup()

    # --- sessions ----------------------------------------------------------------------------------------
    def new_session(self, username, days, ua="", ip="", via="oidc", seconds=None):
        token = secrets.token_urlsafe(32)
        now = time.time()
        self.x("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
               (_hash(token), username, now, now + (seconds if seconds is not None else days * 86400), (ua or "")[:200], ip, via))
        return token

    def end_sessions_older(self, via, seconds):
        """Ends `via` sessions started more than `seconds` ago; returns the usernames affected."""
        cutoff = time.time() - seconds
        names = sorted({r["username"] for r in self.q("SELECT username FROM sessions WHERE via=? AND created<?", (via, cutoff))})
        self.x("DELETE FROM sessions WHERE via=? AND created<?", (via, cutoff))
        return names

    def session_user(self, token):
        if not token:
            return None
        row = self.one("SELECT s.username, s.via FROM sessions s WHERE token_hash=? AND expires>?",
                       (_hash(token), time.time()))
        if not row:
            return None
        u = self.user(row["username"])
        if not u or u.get("disabled"):
            return None
        u["via"] = row["via"]
        return u

    def session_alive(self, token_hash):
        return bool(token_hash) and self.one("SELECT 1 AS ok FROM sessions WHERE token_hash=? AND expires>?",
                                             (token_hash, time.time())) is not None

    def end_session(self, token):
        if token:
            self.x("DELETE FROM sessions WHERE token_hash=?", (_hash(token),))

    def end_sessions_for(self, username, keep=None):
        """Ends every session of username — except the one whose token is `keep` (the caller's own)."""
        if keep:
            return self.x("DELETE FROM sessions WHERE username=? AND token_hash<>?", (username, _hash(keep))).rowcount
        return self.x("DELETE FROM sessions WHERE username=?", (username,)).rowcount

    def sessions(self):
        return self.q("SELECT username, created, expires, ua, ip, via FROM sessions WHERE expires>? "
                      "ORDER BY created DESC", (time.time(),))

    # --- login throttling --------------------------------------------------------------------------------
    def login_failures(self, ip, window=900):
        now = time.time()
        self.x("DELETE FROM login_failures WHERE ts<?", (now - window,))
        return self.one("SELECT COUNT(*) AS n FROM login_failures WHERE ip=?", (ip,))["n"]

    def login_failed(self, ip):
        self.x("INSERT INTO login_failures VALUES (?,?)", (ip, time.time()))

    def try_login_attempt(self, ip, limit, window=900):
        """Atomically: refuse when `ip` already has `limit` attempts in the window, else count this one (review M3)."""
        c = self._conn()
        c.execute("BEGIN IMMEDIATE")
        try:
            now = time.time()
            c.execute("DELETE FROM login_failures WHERE ts<?", (now - window,))
            n = c.execute("SELECT COUNT(*) FROM login_failures WHERE ip=?", (ip,)).fetchone()[0]
            if n >= limit:
                c.execute("COMMIT")
                return False
            c.execute("INSERT INTO login_failures VALUES (?,?)", (ip, now))
            c.execute("COMMIT")
            return True
        except Exception:
            c.execute("ROLLBACK")
            raise

    def login_attempt_ok(self, ip):
        """Takes back one attempt counted up front (see login_api._local_login) when the login succeeded."""
        self.x("DELETE FROM login_failures WHERE rowid = (SELECT MAX(rowid) FROM login_failures WHERE ip=?)", (ip,))

    # --- audit -------------------------------------------------------------------------------------------
    def audit(self, user, action, module="", target="", result="", detail=""):
        self.x("INSERT INTO audit(ts, username, role, action, module, target, result, detail) VALUES (?,?,?,?,?,?,?,?)",
               (time.time(), (user or {}).get("username"), (user or {}).get("role"), action, module,
                target[:300], str(result)[:40], (detail or "")[:1000]))

    def audit_list(self, limit=200, before=None):
        if before:
            return self.q("SELECT * FROM audit WHERE id<? ORDER BY id DESC LIMIT ?", (before, limit))
        return self.q("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))

    def prune(self):
        now = time.time()
        self.x("DELETE FROM sessions WHERE expires<?", (now,))
        self.x("DELETE FROM audit WHERE ts<?", (now - AUDIT_KEEP_DAYS * 86400,))
        self.x("UPDATE approvals SET status='expired' WHERE status='pending' AND expires<?", (now,))
        old = now - APPROVAL_BODY_DAYS * 86400
        self.x("UPDATE approvals SET result_body=NULL, body=CASE WHEN body IS NULL THEN NULL ELSE '' END "
               "WHERE status NOT IN ('pending', 'running') AND COALESCE(decided_at, expires, created)<? "
               "AND (result_body IS NOT NULL OR COALESCE(body, '')<>'')", (old,))

    # --- approvals ---------------------------------------------------------------------------------------
    def add_approval(self, requester, module, method, path, query, body, label, reason, hours):
        now = time.time()
        cur = self.x("""INSERT INTO approvals(created, expires, requester, module, method, path, query, body, label, reason)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (now, now + hours * 3600, requester, module, method, path, query or "", body or "",
                      (label or "")[:120], (reason or "")[:500]))
        return self.approval(cur.lastrowid)

    def approval(self, aid):
        return self.one("SELECT * FROM approvals WHERE id=?", (aid,))

    def approvals(self, status=None, requester=None, limit=100):
        sql, args = "SELECT * FROM approvals WHERE 1=1", []
        if status:
            sql += " AND status=?"
            args.append(status)
        if requester:
            sql += " AND requester=?"
            args.append(requester)
        return self.q(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))

    def decide_approval(self, aid, status, by, code=None, body=None):
        """Moves a pending, unexpired approval to `status`; returns False if someone else got there first."""
        cur = self.x("""UPDATE approvals SET status=?, decided_by=?, decided_at=?, result_code=?, result_body=?
                        WHERE id=? AND status='pending' AND expires>?""",
                     (status, by, time.time(), code, (body or "")[:4000] if body is not None else None, aid, time.time()))
        return cur.rowcount == 1

    def set_approval_result(self, aid, status, code, body):
        self.x("UPDATE approvals SET status=?, result_code=?, result_body=? WHERE id=?",
               (status, code, (body or "")[:4000], aid))

    # --- module settings (owner) ---------------------------------------------------------------------------
    def module_settings(self):
        out = {}
        for r in self.q("SELECT module, key, value FROM module_settings"):
            out.setdefault(r["module"], {})[r["key"]] = json.loads(r["value"])
        return out

    def set_module_setting(self, module, key, value):
        if value is None:
            self.x("DELETE FROM module_settings WHERE module=? AND key=?", (module, key))
        else:
            self.x("INSERT INTO module_settings VALUES (?,?,?) ON CONFLICT(module, key) DO UPDATE SET value=excluded.value",
                   (module, key, json.dumps(value)))

    # --- module config (v2) ------------------------------------------------------------------------------
    def module_config(self, module=None):
        """{module: {key: (value, is_secret)}} — secrets stay sealed here; values are JSON."""
        out = {}
        rows = self.q("SELECT module, key, value, secret FROM module_config" + (" WHERE module=?" if module else ""),
                      (module,) if module else ())
        for r in rows:
            out.setdefault(r["module"], {})[r["key"]] = (r["value"] if r["secret"] else json.loads(r["value"]), bool(r["secret"]))
        return out.get(module, {}) if module else out

    def set_module_config(self, module, key, value, secret=False):
        """value None deletes; a secret value must already be sealed."""
        if value is None:
            self.x("DELETE FROM module_config WHERE module=? AND key=?", (module, key))
            return
        self.x("INSERT INTO module_config VALUES (?,?,?,?,?) ON CONFLICT(module, key) DO UPDATE SET value=excluded.value, "
               "secret=excluded.secret, updated=excluded.updated",
               (module, key, value if secret else json.dumps(value), int(bool(secret)), time.time()))

    def drop_module(self, module):
        """A module removed together with its config (Settings → ~/catalogs → remove): its config (sealed secrets
        included) and its settings go. Returns how many rows."""
        n = self.x("DELETE FROM module_config WHERE module=?", (module,)).rowcount
        return n + self.x("DELETE FROM module_settings WHERE module=?", (module,)).rowcount

    # --- prefs -------------------------------------------------------------------------------------------
    def prefs(self, username):
        return {r["key"]: json.loads(r["value"]) for r in self.q("SELECT key, value FROM prefs WHERE username=?", (username,))}

    def set_pref(self, username, key, value):
        self.x("INSERT INTO prefs VALUES (?,?,?) ON CONFLICT(username, key) DO UPDATE SET value=excluded.value",
               (username, key, json.dumps(value)))
