"""TakClient against a real local mutual-TLS listener, with certs shaped like TAK Server's
makeCert.sh output (CA-signed client cert, key encrypted with a passphrase, server cert whose
name is NOT the loopback address the bridge dials). Skipped without the openssl CLI."""

import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from crowdcad_tak.takclient import TakClient

OPENSSL = shutil.which("openssl")


def _ssl(*args, cwd):
    subprocess.run([OPENSSL, *args], cwd=cwd, check=True, capture_output=True)


def make_pki(d):
    _ssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem",
         "-days", "2", "-subj", "/CN=Test TAK CA", cwd=d)
    # Server key plain; client key encrypted like makeCert.sh's (passphrase = CA PASS).
    for name, key_protection in (("server", ["-noenc"]), ("crowdcad", ["-passout", "pass:atakatak"])):
        _ssl("req", "-newkey", "rsa:2048", *key_protection,
             "-keyout", f"{name}.key", "-out", f"{name}.csr", "-subj", f"/CN={name}.tak.example.org", cwd=d)
        _ssl("x509", "-req", "-in", f"{name}.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial",
             "-out", f"{name}.pem", "-days", "2", cwd=d)


@unittest.skipUnless(OPENSSL, "openssl CLI not available")
class TakClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.d = Path(cls.dir.name)
        make_pki(cls.d)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def serve(self, ca="ca.pem"):
        """One-connection TLS server requiring a client cert; collects what it receives."""
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.d / "server.pem", self.d / "server.key")
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(self.d / ca)
        listener = socket.create_server(("127.0.0.1", 0))
        received = {"data": b"", "peer": None}
        done = threading.Event()

        def run():
            with listener:
                conn, _ = listener.accept()
                try:
                    with ctx.wrap_socket(conn, server_side=True) as tls:
                        received["peer"] = dict(x[0] for x in tls.getpeercert()["subject"])["commonName"]
                        tls.sendall(b"<event uid='someone-else'/>")   # TAK streams others' traffic
                        tls.settimeout(5)
                        while b"</event>" not in received["data"]:
                            chunk = tls.recv(65536)
                            if not chunk:
                                break
                            received["data"] += chunk
                except (OSError, ssl.SSLError):
                    pass
                done.set()

        threading.Thread(target=run, daemon=True).start()
        return listener.getsockname()[1], received, done

    def client(self, port, **kw):
        return TakClient("127.0.0.1", port, str(self.d / "crowdcad.pem"), str(self.d / "crowdcad.key"),
                         str(self.d / "ca.pem"), key_password=kw.get("password", "atakatak"),
                         on_connect=kw.get("on_connect"))

    def test_mutual_tls_with_encrypted_key_delivers_cot(self):
        port, received, done = self.serve()
        tak = self.client(port, on_connect=lambda: tak.send("<event uid='x'>hello</event>"))
        tak.start()
        try:
            self.assertTrue(done.wait(10), tak.last_error)
        finally:
            tak.stop()
        self.assertEqual(received["peer"], "crowdcad.tak.example.org")
        self.assertIn(b"<event uid='x'>hello</event>", received["data"])

    def test_send_while_disconnected_is_dropped_not_queued(self):
        tak = self.client(1)
        tak.send("<event/>")
        self.assertEqual(tak._queue.qsize(), 0)

    def test_wrong_key_password_reports_error(self):
        port, _, _ = self.serve()
        tak = self.client(port, password="wrong")
        tak.start()
        try:
            self.assertFalse(tak.wait_connected(2))
        finally:
            tak.stop()
        self.assertIn("SSLError", tak.last_error or "")


if __name__ == "__main__":
    unittest.main()
