"""Server → browser push (Server-Sent Events) without holding a request thread per open tab.

GET /api/events answers the SSE headers in the request thread, then hands the socket to ONE broadcaster thread and
returns; the pool thread is free again (64 workers would otherwise cap the number of open tabs — the 2026-11-13 pool
starvation). The broadcaster writes events to every subscribed socket the event is meant for and a comment line every
HEARTBEAT seconds (keeps NPM / Cloudflare from timing the stream out, and finds dead sockets).

Events are small hints, never data: {"t": "invalidate", "m": "<module>"} (a write went through the gateway: refresh that
module now), {"t": "registry"} (settings/config changed), {"t": "approvals"}, {"t": "health", "m": …, "up": …}.
Each subscriber is checked with `may(user)` at send time, so a guest never learns that an admin module changed."""
import json
import logging
import queue
import threading
import time

log = logging.getLogger("lab.events")
HEARTBEAT = 20
PER_USER = 12
TOTAL = 400
HEADERS = (b"HTTP/1.0 200 OK\r\nContent-Type: text/event-stream; charset=utf-8\r\nCache-Control: no-store\r\n"
           b"X-Accel-Buffering: no\r\nX-Content-Type-Options: nosniff\r\nConnection: keep-alive\r\n\r\n"
           b"retry: 5000\n: lab events\n\n")


class Events:
    def __init__(self, session_alive=None, user_lookup=None):
        self.lock = threading.Lock()
        self.subs = {}  # socket -> {"user": user dict, "token": session token hash, "since": ts}
        self.session_alive = session_alive  # token hash -> bool: a logged-out session stops receiving
        self.user_lookup = user_lookup      # username -> current user dict (roles change: rolesync)
        self.sent = 0
        self.q = queue.Queue(maxsize=5000)  # publish() only enqueues: a slow tab never delays the request that caused it
        threading.Thread(target=self._loop, name="events", daemon=True).start()

    def count(self, username=None):
        with self.lock:
            return sum(1 for s in self.subs.values() if username is None or s["user"]["username"] == username)

    def subscribe(self, sock, user, token_hash):
        """Takes over `sock` (headers not yet sent). False when over the limits (the caller answers 429)."""
        with self.lock:
            if len(self.subs) >= TOTAL or sum(1 for s in self.subs.values() if s["user"]["username"] == user["username"]) >= PER_USER:
                return False
            try:
                sock.settimeout(5)
                sock.sendall(HEADERS)
            except OSError:
                return False
            self.subs[sock] = {"user": dict(user), "token": token_hash, "since": time.time()}
        return True

    def publish(self, event, may=None):
        """event: a small dict; may(user) → bool decides who gets it (default: everyone subscribed)."""
        line = b"data: " + json.dumps(event, separators=(",", ":")).encode() + b"\n\n"
        try:
            self.q.put_nowait((line, may))
        except queue.Full:  # nobody is reading: drop hints (browsers still poll)
            pass

    def _deliver(self, line, may):
        with self.lock:
            targets = list(self.subs.items())
        for s, sub in targets:
            try:
                if may and not may(sub["user"]):
                    continue
            except Exception:  # noqa: BLE001 — a broken audience check must not stop the others
                continue
            self._send(s, line)

    def _send(self, s, line):
        try:
            s.sendall(line)
            self.sent += 1
        except OSError:
            self._drop(s)

    def _drop(self, s):
        with self.lock:
            self.subs.pop(s, None)
        try:
            s.close()
        except OSError:
            pass

    def _loop(self):
        next_beat = time.monotonic() + HEARTBEAT
        while True:
            try:
                line, may = self.q.get(timeout=max(0.05, next_beat - time.monotonic()))
                self._deliver(line, may)
            except queue.Empty:
                pass
            except Exception:  # noqa: BLE001
                log.exception("event delivery failed")
            if time.monotonic() >= next_beat:  # also while events keep coming
                next_beat = time.monotonic() + HEARTBEAT
                try:
                    self._beat()
                except Exception:  # noqa: BLE001
                    log.exception("event heartbeat failed")

    def _beat(self):
        with self.lock:
            subs = list(self.subs.items())
        for s, sub in subs:
            if self.session_alive and not self.session_alive(sub["token"]):  # logged out / revoked
                self._drop(s)
                continue
            if self.user_lookup:
                fresh = self.user_lookup(sub["user"]["username"])
                if not fresh:
                    self._drop(s)
                    continue
                sub["user"] = dict(fresh)
            self._send(s, b": ping\n\n")

    def close_all(self):
        with self.lock:
            subs = list(self.subs)
        for s in subs:
            self._drop(s)
