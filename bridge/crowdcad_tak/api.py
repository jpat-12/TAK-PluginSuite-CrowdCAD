"""The bridge's HTTP server (contract: docs/API.md).

    /healthz         anyone
    /status          the infra-TAK console only: loopback, and refused if it came through a
                     proxy (Caddy adds X-Forwarded-For), so it never leaks via the public site
    /api/v1/info     anyone: lets a client check it has the right URL before asking for a token
    /api/v1/board    Bearer board token: the web clients' call/team board (board.py)
    /api/v1/manage/* Bearer manage token (CloudTAK's server half only): list venues, create an
                     event from TAK contacts, end an event created that way (manage.py). No CORS:
                     a browser never calls these directly.

Caddy only forwards /api/v1/* and /healthz (infratak/crowdcad_caddy.py); the /status
refusal is a second fence, not the only one.
"""

import hmac
import json
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSION, board
from .dispatcher import Dispatcher
from .manage import ManageError

MAX_BODY = 256 * 1024
END_PATH = re.compile(r"^/api/v1/manage/events/([a-z0-9]{15})/end$")
EVENT_PATH = re.compile(r"^/api/v1/manage/events/([a-z0-9]{15})(/.*)?$")
CALL_ID = r"([A-Za-z0-9_-]{1,40})"


def make_server(listen, status, board_source, token, cors_origins=(), manager=None, manage_token=""):
    """status(): dict for /status. board_source(): dict for /api/v1/board, or None if the
    bridge isn't configured. token: the board bearer token ('' = board disabled).
    manager: manage.Manager, or None (manage API off); manage_token: its bearer token."""
    host, _, port = listen.rpartition(":")
    # CloudTAK's dispatcher (the IU EMS Dispatch copy): IU's board + actions over CrowdCAD, manage token.
    dispatcher = Dispatcher(manager, board_source) if manager is not None else None
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
            if not self.path.startswith("/api/v1/manage/"):
                self._cors()
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _cors(self):
            origin = (self.headers.get("Origin") or "").rstrip("/")
            if origin and ("*" in origins or origin in origins):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _authorized(self, expected=None):
            expected = token if expected is None else expected
            sent = self.headers.get("Authorization") or ""
            return bool(expected) and sent.startswith("Bearer ") and hmac.compare_digest(sent[7:].strip(), expected)

        def _manage(self, action):
            if manager is None or not manage_token:
                return self._send(404, {"error": "manage API disabled on this bridge"})
            if not self._authorized(manage_token):
                return self._send(401, {"error": "manage token required"},
                                  {"WWW-Authenticate": 'Bearer realm="crowdcad-tak-manage"'})
            actor = " ".join((self.headers.get("X-TAK-User") or "unknown").split())[:120]
            try:
                return self._send(200, action(actor))
            except ManageError as error:
                return self._send(error.status, {"error": str(error)})
            except Exception as error:   # PocketBase down/refused: say so, never a stack trace
                return self._send(502, {"error": f"CrowdCAD refused or unreachable: {error}"})

        def _json_body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ManageError("request too large", 413)
            try:
                return json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                raise ManageError("body is not JSON") from None

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
            if path == "/api/v1/manage/venues":
                return self._manage(lambda actor: manager.venues())
            if path == "/api/v1/manage/dispatcher/board":
                return self._manage(lambda actor: dispatcher.board(int(time.time() * 1000)))
            if path == "/api/v1/manage/w3w":
                query = urllib.parse.parse_qs(self.path.partition("?")[2])
                return self._manage(lambda actor: manager.w3w(query))
            match = EVENT_PATH.match(path)
            if match and match.group(2) == "/dispatch":
                return self._manage(lambda actor: manager.view(match.group(1)))
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

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/v1/manage/events":
                return self._manage(lambda actor: manager.create(self._json_body(), actor))
            if path == "/api/v1/manage/dispatcher/action":
                return self._manage(lambda actor: dispatcher.act(self._json_body(), actor))
            match = END_PATH.match(path)
            if match:
                return self._manage(lambda actor: manager.end(match.group(1), actor))
            match = EVENT_PATH.match(path)
            if match:
                eid, rest = match.group(1), match.group(2) or ""
                routes = [
                    (r"^/calls$", lambda m, actor: manager.new_call(eid, self._json_body(), actor)),
                    (rf"^/calls/{CALL_ID}/assign$", lambda m, actor: manager.assign(eid, m.group(1), self._json_body(), actor)),
                    (rf"^/calls/{CALL_ID}/status$", lambda m, actor: manager.status_on_call(eid, m.group(1), self._json_body(), actor)),
                    (rf"^/calls/{CALL_ID}/details$", lambda m, actor: manager.call_details(eid, m.group(1), self._json_body(), actor)),
                    (r"^/teams$", lambda m, actor: manager.add_team(eid, self._json_body(), actor)),
                    (r"^/supervisors$", lambda m, actor: manager.add_supervisor(eid, self._json_body(), actor)),
                    (r"^/units/status$", lambda m, actor: manager.unit_status(eid, self._json_body(), actor)),
                    (r"^/units/post$", lambda m, actor: manager.unit_post(eid, self._json_body(), actor)),
                ]
                for pattern, handler in routes:
                    found = re.match(pattern, rest)
                    if found:
                        return self._manage(lambda actor, h=handler, f=found: h(f, actor))
            return self._send(404, {"error": "not found"})

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((host or "127.0.0.1", int(port)), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()
    return server


def runner_board(runner, manager=None, field=None):
    def source():
        status = runner.status()
        return board.build(runner.publisher, int(time.time() * 1000), {
            "crowdcad": status["crowdcad"]["mode"], "tak": status["tak"]["connected"],
            "version": status["version"]}, own_user=manager.pb.user_id if manager else None,
            heard=field.heard if field else None, positions=field.positions if field else None,
            designations=field.designations if field else None)
    return source
