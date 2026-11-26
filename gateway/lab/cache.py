"""A short-lived cache for proxied GETs, so N open tabs (or N users) polling the same module cost the backend one call.

  * Who shares an entry: a module whose backend uses ONE credential for everyone (backend.auth: Proxmox, PBS,
    Cloudflare …) answers every caller the same, so its entries are shared (the gateway still checks each caller's
    permission for the route BEFORE serving from the cache). Any other module (own backends that see the signed user)
    gets entries per user.
  * How long: route `"cache": <seconds>` (0 = never), else DEFAULT_SHARED seconds for shared-credential modules and no
    caching for the rest. Secret routes and non-200 answers are never cached; nor are answers above MAX_BODY.
  * Single flight: concurrent misses for the same key wait for the first request instead of all hitting the backend.
  * A write that goes through the gateway to a module drops that module's entries (the next read is fresh)."""
import threading
import time

DEFAULT_SHARED = 5
MAX_TTL = 300
MAX_BODY = 2 * 1024 * 1024
MAX_ENTRIES = 600


def ttl_for(module, route):
    if route.get("secret"):
        return 0
    c = route.get("cache")
    if isinstance(c, (int, float)) and not isinstance(c, bool):
        return max(0, min(MAX_TTL, c))
    return DEFAULT_SHARED if shared(module) else 0


def shared(module):
    return bool((module.get("backend") or {}).get("auth"))


class ProxyCache:
    def __init__(self):
        self.lock = threading.Lock()
        self.entries = {}   # key -> (expires, value)
        self.flight = {}    # key -> threading.Event
        self.hits = self.misses = 0

    @staticmethod
    def key(module, route, user, path, query):
        return (module["id"], path, query or "", "" if shared(module) else user["username"])

    def get(self, key, ttl, fetch):
        """(value, hit). fetch() → (code, headers, body); only 200s are stored."""
        while True:
            with self.lock:
                now = time.monotonic()
                hit = self.entries.get(key)
                if hit and hit[0] > now:
                    self.hits += 1
                    return hit[1], True
                ev = self.flight.get(key)
                if ev is None:
                    ev = self.flight[key] = threading.Event()
                    break
            ev.wait(30)  # someone else is fetching it: use their answer (or try ourselves if it failed)
        try:
            value = fetch()
            code, headers, body = value
            if code == 200 and len(body or b"") <= MAX_BODY:
                with self.lock:
                    if len(self.entries) >= MAX_ENTRIES:
                        now = time.monotonic()
                        self.entries = {k: v for k, v in self.entries.items() if v[0] > now}
                        if len(self.entries) >= MAX_ENTRIES:
                            self.entries.clear()
                    self.entries[key] = (time.monotonic() + ttl, value)
            with self.lock:
                self.misses += 1
            return value, False
        finally:
            with self.lock:
                self.flight.pop(key, None)
            ev.set()

    def invalidate(self, module_id):
        with self.lock:
            for k in [k for k in self.entries if k[0] == module_id]:
                del self.entries[k]
