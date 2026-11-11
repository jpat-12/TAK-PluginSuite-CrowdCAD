"""Minimal PocketBase client for CrowdCAD's `events` collection: password auth, list/view, and
the realtime (SSE) stream. Stdlib only. Interface reference: CrowdCAD docs/ICD.md (v1.6.0)."""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

# PocketBase record ids (ICD §5). Anything else is refused before it reaches a filter
# expression, so a config value can't inject filter syntax.
RECORD_ID = re.compile(r"^[a-z0-9]{15}$")
REAUTH_AFTER_S = 24 * 3600      # PocketBase auth tokens default to 7 days; renew well inside it
SSE_READ_TIMEOUT_S = 330        # PocketBase drops idle realtime clients after 5 min


class PocketBaseError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def iter_sse(lines):
    """Server-Sent Events framing: yields (event_name, data_str) per blank-line-terminated
    block. `lines` is any iterable of str/bytes lines (a urllib response works)."""
    name, data = "message", []
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        line = line.rstrip("\r\n")
        if not line:
            if data:
                yield name, "\n".join(data)
            name, data = "message", []
            continue
        if line.startswith(":"):
            continue  # comment / keep-alive
        key, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if key == "event":
            name = value
        elif key == "data":
            data.append(value)
    if data:
        yield name, "\n".join(data)


class PocketBase:
    def __init__(self, base_url, identity, password, timeout=15, urlopen=urllib.request.urlopen):
        self.base = (base_url or "").rstrip("/")
        self.identity, self.password = identity, password
        self.timeout = timeout
        self._urlopen = urlopen
        self.token, self.token_at = None, 0.0
        if not self.base.startswith(("http://", "https://")):
            raise PocketBaseError(f"crowdcad_url must be http(s)://…, got {base_url!r}")

    # --- REST -----------------------------------------------------------------------------

    def _call(self, method, path, body=None, query=None, auth=True, timeout=None):
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = f"Bearer {self.ensure_auth()}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            detail = ""
            try:
                detail = json.loads(error.read() or b"{}").get("message", "")
            except ValueError:
                pass
            raise PocketBaseError(f"{method} {path} → {error.code} {detail}".strip(), error.code) from None
        except (urllib.error.URLError, OSError) as error:
            raise PocketBaseError(f"{method} {path}: {getattr(error, 'reason', error)}") from None

    def _authed(self, method, path, **kwargs):
        try:
            return self._call(method, path, **kwargs)
        except PocketBaseError as error:
            if error.status != 401:
                raise
            self.token = None  # expired or revoked: one fresh sign-in, then give up
            return self._call(method, path, **kwargs)

    def ensure_auth(self):
        if self.token and time.time() - self.token_at < REAUTH_AFTER_S:
            return self.token
        result = self._call("POST", "/api/collections/users/auth-with-password",
                            body={"identity": self.identity, "password": self.password}, auth=False)
        self.token, self.token_at = result.get("token"), time.time()
        if not self.token:
            raise PocketBaseError("auth-with-password returned no token")
        return self.token

    def list_events(self, selection="active"):
        """Events the bridge should publish. selection: "active" or a list of record ids."""
        if selection == "active":
            expression = "status='active' && ended!=true"
        else:
            ids = [i for i in selection or [] if isinstance(i, str) and RECORD_ID.match(i)]
            if not ids:
                return []
            expression = " || ".join(f"id='{i}'" for i in ids)
        records, page = [], 1
        while True:
            result = self._authed("GET", "/api/collections/events/records",
                                  query={"filter": f"({expression})", "page": page, "perPage": 50})
            records.extend(result.get("items") or [])
            if page >= int(result.get("totalPages") or 1):
                return records
            page += 1

    # --- realtime -------------------------------------------------------------------------

    def realtime(self, topics, on_record, on_connect=None):
        """Blocks while the SSE stream is open, calling on_record(action, record) per change.
        Returns when the server closes it (PocketBase does after 5 idle minutes); raises
        PocketBaseError on failure. The caller resyncs and reconnects — changes made while
        disconnected are only caught by that resync."""
        request = urllib.request.Request(self.base + "/api/realtime", headers={"Accept": "text/event-stream"})
        try:
            stream = self._urlopen(request, timeout=SSE_READ_TIMEOUT_S)
        except (urllib.error.URLError, OSError) as error:
            raise PocketBaseError(f"realtime connect: {getattr(error, 'reason', error)}") from None
        with stream:
            try:
                for name, data in iter_sse(stream):
                    try:
                        payload = json.loads(data)
                    except ValueError:
                        continue
                    if name == "PB_CONNECT":
                        # Subscriptions are bound to the client id and authorised by this POST's token.
                        self._authed("POST", "/api/realtime",
                                     body={"clientId": payload.get("clientId"), "subscriptions": list(topics)})
                        if on_connect:
                            on_connect()
                    elif isinstance(payload, dict) and isinstance(payload.get("record"), dict):
                        on_record(payload.get("action"), payload["record"])
            except (OSError, ValueError) as error:  # read timeout / reset mid-stream
                raise PocketBaseError(f"realtime stream: {error}") from None
