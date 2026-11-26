"""Background poller: is each module's backend up? Feeds /api/health, the shell's status dots and /metrics."""
import ssl
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import urllib.error
import urllib.request

_INSECURE = ssl._create_unverified_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the request may carry the module's credential (security review 2026-11-15, M4)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def friendly_error(e):
    """A short, actionable text for a failed backend call (shown in Settings and the status dots), not a raw repr."""
    reason = getattr(e, "reason", e)
    text = str(reason)
    if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in text:
        return "certificate not trusted: turn off Verify TLS for a self-signed certificate (or install a trusted one)"
    if isinstance(reason, ssl.SSLError):
        return f"TLS error: {getattr(reason, 'reason', None) or text}"[:200] + " (http:// vs https:// in the URL?)"
    if isinstance(reason, ConnectionRefusedError) or "Connection refused" in text:
        return "connection refused: nothing listens at that address and port"
    if isinstance(reason, TimeoutError) or "timed out" in text:
        return "no answer (timed out): wrong address, or a firewall in between"
    if "Name or service not known" in text or "nodename nor servname" in text or "No address associated" in text:
        return "unknown host name: check the URL"
    if "No route to host" in text or "Network is unreachable" in text:
        return "no route to that address: check the URL and the network"
    return text[:200]


def _open(req, timeout, ctx):
    return urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=ctx)).open(req, timeout=timeout)


def probe(be, method, path, headers=None, expect=(200,), timeout=8, want_json=None):
    """One request to a backend: {"ok", "status", "ms", "error"}. Used by the config test (candidate credentials).
    want_json: top-level fields the JSON answer must carry (for APIs that say 200 to a bad token)."""
    url = be["url"].rstrip("/") + path
    ctx = _INSECURE if url.startswith("https") and be.get("tls_verify") is False else None
    hdrs = {"User-Agent": "lab-gateway/1 config-test", **(headers or {})}
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, headers=hdrs, method=method, data=b"" if method != "GET" else None)
        with _open(req, timeout, ctx) as r:
            code = r.status
            body = r.read(256 * 1024) if want_json else b""
        err = ""
        if want_json and code in tuple(expect):
            import json
            try:
                data = json.loads(body)
            except ValueError:
                data = None
            bad = [k for k, v in want_json.items() if not (isinstance(data, dict) and data.get(k) == v)]
            if bad:
                detail = (data or {}).get("errorMessage") or (data or {}).get("error") or (data or {}).get("message") if isinstance(data, dict) else ""
                return {"ok": False, "status": code, "ms": round((time.monotonic() - t0) * 1000, 1),
                        "error": f"unexpected answer ({', '.join(bad)}){': ' + str(detail)[:160] if detail else ''}"}
    except urllib.error.HTTPError as e:
        code, err = e.code, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        code, err = None, friendly_error(e)
    ok = code in tuple(expect)
    if code in (401, 403) and not ok:
        err = f"HTTP {code}: the credentials were refused"
    return {"ok": ok, "status": code, "ms": round((time.monotonic() - t0) * 1000, 1), "error": "" if ok else err}


class Health:
    def __init__(self, registry, interval=30, keys=None, on_change=None):
        self.registry, self.interval, self.keys = registry, interval, keys
        self.on_change = on_change  # (module id, up) when a backend goes up or down (pushed to the browsers)
        self.state = {}  # id -> {"up": bool, "ms": float, "checked": ts, "error": str}
        self._stop = threading.Event()

    def check_all(self):
        # in parallel: one at a time with a 5 s timeout, ~40 backends with a few down took minutes per round
        mods = [m for m in list(self.registry.modules.values()) if m.get("backend")]
        with ThreadPoolExecutor(max_workers=12, thread_name_prefix="health") as ex:
            list(ex.map(self.check_one, mods))

    def check_one(self, m):
        be = m.get("backend")
        url = be["url"].rstrip("/") + be.get("health", "/healthz")
        hdrs = {"User-Agent": "lab-gateway/1 health"}
        hdrs.update(be.get("headers") or {})
        if be.get("auth") and self.keys:  # third-party APIs with no anonymous health endpoint (Proxmox /version)
            hdrs.update(self.keys.credentials(m)[1] or {})
        ctx = _INSECURE if url.startswith("https") and be.get("tls_verify") is False else None
        t0 = time.monotonic()
        try:
            with _open(urllib.request.Request(url, headers=hdrs), 5, ctx) as r:
                up, err = 200 <= r.status < 400, ""
        except urllib.error.HTTPError as e:  # it answered: 401/403 = alive but picky about the probe, 3xx = alive (not followed)
            up, err = e.code in (401, 403) or 300 <= e.code < 400, f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001 — anything else means down
            up, err = False, friendly_error(e)
        before = self.state.get(m["id"], {}).get("up")
        if self.on_change and before is not None and before != up:
            try:
                self.on_change(m["id"], up)
            except Exception:  # noqa: BLE001
                pass
        self.state[m["id"]] = {"up": up, "ms": round((time.monotonic() - t0) * 1000, 1),
                               "checked": time.time(), "error": err}

    def start(self):
        def loop():
            while not self._stop.is_set():
                try:
                    self.check_all()
                except Exception:  # noqa: BLE001
                    pass
                self._stop.wait(self.interval)
        threading.Thread(target=loop, name="health", daemon=True).start()
