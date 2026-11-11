"""Streaming CoT to TAK Server over mutual TLS (the 8089 input), reconnecting forever.

Messages queued while disconnected are dropped on purpose: on every (re)connect the bridge
re-sends the whole current picture (on_connect), which is both smaller and more correct than
replaying a backlog of superseded versions.
"""

import queue
import select
import socket
import ssl
import sys
import threading
import time

from . import LOG_PREFIX

BACKOFF_S = (1, 2, 5, 10, 30)


class TakClient:
    def __init__(self, host, port, cert, key, ca, key_password=None, on_connect=None):
        self.host, self.port = host, int(port)
        self.cert, self.key, self.ca, self.key_password = cert, key, ca, key_password
        self.on_connect = on_connect
        self.connected = False
        self.last_error = None
        self.sent = 0
        self._queue = queue.Queue(maxsize=5000)
        self._stop = threading.Event()
        self._thread = None

    def context(self):
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=self.ca)
        # The bridge dials TAK Server on loopback, but TAK's server cert names the public FQDN.
        # The chain is still verified against TAK's own CA; only the name check is skipped.
        ctx.check_hostname = False
        ctx.load_cert_chain(self.cert, self.key, password=self.key_password or None)
        return ctx

    def start(self):
        self._thread = threading.Thread(target=self._run, name="tak-writer", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def send(self, xml):
        if not self.connected:
            return
        try:
            self._queue.put_nowait(xml.encode("utf-8"))
        except queue.Full:
            self.last_error = "send queue full; dropping until the next full resend"

    def _run(self):
        attempt = 0
        while not self._stop.is_set():
            try:
                with socket.create_connection((self.host, self.port), timeout=10) as raw, \
                        self.context().wrap_socket(raw) as tls:
                    tls.settimeout(10.0)  # bounds sendall on a wedged connection
                    attempt = 0
                    self._drain_queue()
                    self.connected, self.last_error = True, None
                    print(f"{LOG_PREFIX} TAK connected {self.host}:{self.port}", file=sys.stderr, flush=True)
                    if self.on_connect:
                        self.on_connect()
                    self._pump(tls)
            except (OSError, ssl.SSLError) as error:
                self.last_error = f"{type(error).__name__}: {error}"
            if self.connected and not self._stop.is_set():
                print(f"{LOG_PREFIX} TAK disconnected: {self.last_error}", file=sys.stderr, flush=True)
            self.connected = False
            self._stop.wait(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
            attempt += 1

    def _pump(self, tls):
        while not self._stop.is_set():
            try:
                message = self._queue.get(timeout=0.2)
            except queue.Empty:
                message = None
            while message:  # flush a whole burst before looking at the read side
                tls.sendall(message)
                self.sent += 1
                try:
                    message = self._queue.get_nowait()
                except queue.Empty:
                    message = None
            # TAK Server streams everyone's traffic to us; read and discard so its send buffer
            # never stalls our connection. (TAK → CrowdCAD will parse this — docs/PLAN.md.)
            # Non-blocking: a blocking recv here would add its timeout to every send.
            if tls.pending() or select.select([tls], [], [], 0)[0]:
                try:
                    if not tls.recv(65536):
                        raise ConnectionError("closed by TAK Server")
                except (socket.timeout, ssl.SSLWantReadError):
                    pass

    def _drain_queue(self):
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def wait_connected(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self.connected:
            time.sleep(0.1)
        return self.connected
