"""The bridge's HTTP server (contract: docs/API.md).

    /healthz         anyone
    /status          the infra-TAK console only: loopback, and refused if it came through a
                     proxy (Caddy adds X-Forwarded-For), so it never leaks via the public site
    /api/v1/info     anyone: lets a client check it has the right URL before asking for a token
    /api/v1/board    Bearer board token: the web clients' call/team board (board.py)

Caddy only forwards /api/v1/* and /healthz (infratak/crowdcad_caddy.py); the /status
refusal is a second fence, not the only one.
"""

import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSION, board


def make_server(listen, status, board_source, token, cors_origins=()):
    """status(): dict for /status. board_source(): dict for /api/v1/board, or None if the
    bridge isn't configured. token: the board bearer token ('' = board disabled)."""
    host, _, port = listen.rpartition(":")
    origins = {o.rstrip("/") for o in cors_origins or () if o}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, payload, extra=None):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self._cors()
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _cors(self):
            origin = (self.headers.get("Origin") or "").rstrip("/")
            if origin and ("*" in origins or origin in origins):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _authorized(self):
            sent = self.headers.get("Authorization") or ""
            return bool(token) and sent.startswith("Bearer ") and hmac.compare_digest(sent[7:].strip(), token)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization")
            self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                return self._send(200, {"ok": True})
            if path == "/status":
                if self.headers.get("X-Forwarded-For") or self.client_address[0] not in ("127.0.0.1", "::1"):
                    return self._send(404, {"error": "not found"})
                return self._send(200, status())
            if path == "/api/v1/info":
                return self._send(200, {"api": board.API_VERSION, "version": VERSION, "name": "CrowdCAD for TAK"})
            if path == "/api/v1/board":
                if not self._authorized():
                    return self._send(401, {"error": "board token required"},
                                      {"WWW-Authenticate": 'Bearer realm="crowdcad-tak"'})
                data = board_source()
                if data is None:
                    return self._send(503, {"error": "bridge not configured yet"})
                return self._send(200, data)
            return self._send(404, {"error": "not found"})

        do_HEAD = do_GET

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((host or "127.0.0.1", int(port)), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()
    return server


def runner_board(runner):
    def source():
        status = runner.status()
        return board.build(runner.publisher, int(time.time() * 1000), {
            "crowdcad": status["crowdcad"]["mode"], "tak": status["tak"]["connected"],
            "version": status["version"]})
    return source
