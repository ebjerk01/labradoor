"""Core updates from the UI (mixed into server.Handler; owner only). Settings → ~/updates.

The gateway runs as the unprivileged user lab and never installs anything itself: it asks the root helper
deploy/lab-update-helper (socket /run/lab-update-helper.sock, group lab only), which accepts fixed commands — check an
index, stage a version, apply a staged version, roll back, status — and refuses anything unsigned or mismatching.

  GET  /api/update                      version, commit, index URL (+ where it comes from), helper status
  POST /api/update/settings {index}     owner: the release index URL (overrides LAB_RELEASE_INDEX, the installer's
                                        default in lab.env; empty = back to that default)
  POST /api/update/check                fetch + verify the signed index → releases, the newest allowed, notes
  POST /api/update/stage {version}      download + verify (sha256, signature, MANIFEST)
  POST /api/update/apply {version}      install the staged version (a job: poll /api/update/status)
  POST /api/update/rollback {release}   back to an earlier release (code only). Restoring the database as well is
                                        root's: `lab-admin rollback --with-db` on the host — the helper refuses it from
                                        the gateway, so the gateway refuses it first (security review 2026-11-15, H2)
  GET  /api/update/status               the helper's status (job progress); records a finished job in the audit log

Every step is audited (update-check, update-stage, update-apply, update-rollback, update-result)."""
import json
import os
import re
import socket
import urllib.parse

from . import config
from .errors import HTTPError
from .login_api import NOT_MINE

HELPER_SOCKET = os.environ.get("LAB_UPDATE_HELPER", "/run/lab-update-helper.sock")
INDEX_KEY = "update_index"       # gateway_config: the index URL set in Settings
AUDITED_KEY = "update_audited"   # gateway_config: the last job id written to the audit log
VERSION_RE = re.compile(r"^[0-9A-Za-z.+-]{1,64}$")
RELEASE_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9A-Za-z._-]{1,40}$")


class UpdateHelperError(Exception):
    pass


def call_helper(req, timeout=60, path=None):
    """One request to the update helper: one JSON line in, one JSON line out ({"ok": bool, ...})."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path or HELPER_SOCKET)
            s.sendall(json.dumps(req).encode() + b"\n")
            s.shutdown(socket.SHUT_WR)
            buf = b""
            while len(buf) < 1 << 20:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
    except OSError as e:
        raise UpdateHelperError(f"update helper unavailable ({e.__class__.__name__}): is lab-update-helper.socket "
                                "running?") from None
    try:
        out = json.loads(buf.decode() or "{}")
    except ValueError:
        raise UpdateHelperError("update helper gave no answer") from None
    if not out.get("ok"):
        raise UpdateHelperError(str(out.get("error") or "update helper refused"))
    return out


def index_setting(store):
    """(url, source): the URL set in Settings, else LAB_RELEASE_INDEX from lab.env (the installer writes the index it
    installed from there), else ('', '') = updates off. Unlike login settings the environment is only the default: the
    owner may point an installation at another (signed) index without a shell."""
    v = store.gateway_config().get(INDEX_KEY, (None, False))[0]
    if isinstance(v, str) and v:
        return v, "settings"
    env = os.environ.get("LAB_RELEASE_INDEX", "").strip()
    return (env, "env") if env else ("", "")


def check_index_url(v):
    if not isinstance(v, str) or len(v) > 2048 or any(c in v for c in "\r\n\t "):
        raise HTTPError(400, "index: one URL")
    p = urllib.parse.urlsplit(v)
    if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password or p.fragment:
        raise HTTPError(400, "index: an https:// URL (http:// only for a LAN test server, if the host allows it)")
    return v


def startup_audit(app, call=None):
    """At gateway start: a job that finished while the gateway was restarting (its own update) gets its audit line."""
    try:
        out = (call or call_helper)({"op": "status"}, timeout=30)
    except UpdateHelperError:
        return
    record_job(app.store, out.get("job"))


def record_job(store, job):
    """A finished job goes into the audit log once (the gateway may have restarted in between: the job outlives it)."""
    if not job or job.get("state") not in ("ok", "failed", "interrupted") or not job.get("id"):
        return False
    st = store
    if st.gateway_config().get(AUDITED_KEY, (None, False))[0] == job["id"]:
        return False
    st.set_gateway_config(AUDITED_KEY, job["id"])
    st.audit({"username": job.get("by") or "lab-admin", "role": "owner"}, f"{job.get('op', 'update')}-result",
             "_core", str(job.get("target") or "")[:100], job.get("state"), str(job.get("message") or "")[:900])
    return True


class UpdateRoutes:
    _UPDATE_TIMEOUTS = {"check": 90, "stage": 600, "apply": 60, "rollback": 60, "status": 30}

    def _update_call(self, req):
        call = getattr(self.app, "update_helper", None) or call_helper
        try:
            return call(req, timeout=self._UPDATE_TIMEOUTS.get(req.get("op"), 60))
        except UpdateHelperError as e:
            raise HTTPError(502 if "unavailable" in str(e) or "no answer" in str(e) else 409, str(e)) from None

    def _update_get(self, path):
        if path not in ("/api/update", "/api/update/status"):
            return NOT_MINE
        u = self._need("owner")
        a = self.app
        try:
            status = self._update_call({"op": "status", "by": u["username"]})
            status.pop("ok", None)
            helper_error = ""
        except HTTPError as e:
            status, helper_error = None, e.msg
        if status:
            record_job(a.store, status.get("job"))
        if path == "/api/update/status":
            if not status:
                raise HTTPError(502, helper_error)
            return self._json(200, status)
        from .server import BUILD, BUILD_COMMIT
        url, source = index_setting(a.store)
        return self._json(200, {"build": {"version": BUILD, "commit": BUILD_COMMIT},
                                "index": {"url": url, "source": source, "env": "LAB_RELEASE_INDEX"},
                                "helper": status, "helperError": helper_error})

    def _update_post(self, path):
        if not path.startswith("/api/update/"):
            return NOT_MINE
        u = self._need("owner")
        a = self.app
        verb = path[len("/api/update/"):]
        data = self._body()
        if verb == "settings":
            v = data.get("index")
            v = None if v in (None, "") else check_index_url(v)
            a.store.set_gateway_config(INDEX_KEY, v)
            url, source = index_setting(a.store)
            a.store.audit(u, "update-settings", "_core", "index", "ok", url or "(off)")
            return self._json(200, {"index": {"url": url, "source": source, "env": "LAB_RELEASE_INDEX"}})
        if verb == "check":
            url, _ = index_setting(a.store)
            if not url:
                raise HTTPError(409, "no release index set: updates are off (Settings → ~/updates, or LAB_RELEASE_INDEX)")
            return self._update_step(u, "check", {"index": url}, url)
        if verb == "stage":
            url, _ = index_setting(a.store)
            if not url:
                raise HTTPError(409, "no release index set")
            v = data.get("version")
            if not isinstance(v, str) or not VERSION_RE.match(v):
                raise HTTPError(400, "version")
            return self._update_step(u, "stage", {"index": url, "version": v}, v)
        if verb == "apply":
            v = data.get("version")
            if not isinstance(v, str) or not VERSION_RE.match(v):
                raise HTTPError(400, "version")
            return self._update_step(u, "apply", {"version": v}, v)
        if verb == "rollback":
            rel, wdb = data.get("release") or None, data.get("with_db", False)
            if rel is not None and not (isinstance(rel, str) and RELEASE_RE.match(rel)):
                raise HTTPError(400, "release")
            if not isinstance(wdb, bool):
                raise HTTPError(400, "with_db: true or false")
            if wdb:
                self.app.store.audit(u, "update-rollback", "_core", (rel or "previous") + " +db", "refused", "root only")
                raise HTTPError(403, "restoring the database is only possible as root on the host: "
                                     "lab-admin rollback --with-db")
            req = {"with_db": False}
            if rel:
                req["release"] = rel
            return self._update_step(u, "rollback", req, rel or "previous")
        raise HTTPError(404, "not found")

    def _update_step(self, u, op, req, target):
        try:
            out = self._update_call({"op": op, **req, "by": u["username"]})
        except HTTPError as e:
            self.app.store.audit(u, f"update-{op}", "_core", target[:200], "refused", e.msg)
            raise
        out.pop("ok", None)
        detail = {"check": lambda: f"current {out.get('current')} latest {out.get('latest')} update {out.get('update')}",
                  "stage": lambda: f"sha256 {str(out.get('sha256', ''))[:16]} · {out.get('files')} files verified",
                  }.get(op, lambda: f"job {out.get('job', '')}")()
        self.app.store.audit(u, f"update-{op}", "_core", target[:200], "ok", detail)
        return self._json(200, out)
