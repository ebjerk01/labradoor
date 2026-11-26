"""Labradoor connector template: a tiny authenticated adapter for one third-party API. Copy to connectors/<id>/.

How it gets what it needs (connectors/README.md):
  * its HMAC key from systemd ($CREDENTIALS_DIRECTORY/key) — labconn.load_key()
  * its config (the module's `config` fields, secrets opened) from the gateway — labconn.Config, applied by configure()
  * a config test: the gateway POSTs the owner's CANDIDATE values to /api/_validate; try the upstream login with them.
State, if any: labconn.state_dir(ID). Never return a credential to the caller."""
import json
import logging
import os
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/opt/lab/sdk/python")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdk", "python"))
import labauth  # noqa: E402
import labconn  # noqa: E402

ID = os.environ.get("CONNECTOR_ID", "template")
PORT = int(os.environ.get("PORT", "8119"))  # = the port in the manifest's backend.url
KEY = labconn.load_key(ID)
UPSTREAM = {"url": "", "token": ""}
log = logging.getLogger(ID)


def configure(values, conf=None):
    """The module config from the gateway (once at start; the gateway restarts the connector after a change)."""
    UPSTREAM.update(url=labconn.url(values, "url"), token=labconn.text(values, "token"))


CONF = labconn.Config(ID, KEY, apply=configure)


def validate(values):
    """Config test with the CANDIDATE values: {"ok": true, "detail": ...} or {"ok": false, "error": ...}."""
    if not labconn.url(values, "url"):
        return {"ok": False, "error": "no URL"}
    return {"ok": True, "detail": "reachable"}  # replace with a real "who am I" call upstream


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _claims(self):
        # per request, never cached on the handler (keep-alive connections carry many users)
        if self.client_address[0] != "127.0.0.1":
            return None
        return labauth.verify(self.headers.get(labauth.HEADER), KEY, ID)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/healthz":
            return self._json(200, {"ok": True, "config": CONF.ready})
        claims = self._claims()
        if not claims:
            return self._json(401, {"error": "lab signature required"})
        if not CONF.ready:
            return self._json(503, {"error": CONF.why()})
        if path == "/api/status":
            return self._json(200, {"connector": ID, "you": claims["u"], "role": claims["r"]})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        claims = self._claims()
        if not claims:
            return self._json(401, {"error": "lab signature required"})
        if path == "/api/_validate":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                return self._json(200, validate(labconn.candidate(claims, json.loads(self.rfile.read(n) if 0 < n < 65536 else b"{}"))))
            except PermissionError as e:
                return self._json(403, {"error": str(e)})
            except ValueError as e:
                return self._json(400, {"error": str(e)})
        return self._json(404, {"error": "not found"})


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
