"""Tracker R43: the infra-TAK console's root helper (infratak/crowdcad_admin.py) and the page's
TAK certificate upload, run in-process against temp dirs (no root, systemd or real bridge).

Certificates are made with the openssl CLI (skipped without it), including a TAK-style .p12
with a password and a truststore .p12, which is what TAK Portal's integration download holds.
"""

import base64
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRATAK = ROOT / "infratak"
OPENSSL = shutil.which("openssl")

try:
    import flask
except ImportError:
    flask = None


def load():
    sys.path.insert(0, str(INFRATAK))
    try:
        hook = importlib.reload(importlib.import_module("crowdcad_infratak"))
        admin = importlib.reload(importlib.import_module("crowdcad_admin"))
        return hook, admin
    finally:
        sys.path.remove(str(INFRATAK))


def openssl(*args, cwd):
    subprocess.run([OPENSSL, *args], cwd=cwd, check=True, capture_output=True)


class _Base(unittest.TestCase):
    def setUp(self):
        self.hook, self.admin = load()
        self.addCleanup(load)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name in ("data", "console", "certs"):
            (self.tmp / name).mkdir()
        self.hook.HOME = str(self.tmp)
        self.hook.DATA_DIR = str(self.tmp / "data")
        self.hook.CONSOLE_DIR = str(self.tmp / "console")
        self.hook._ADMIN_INLINE = self.admin.run
        self.restarts = []
        self.admin._restart_and_check = lambda: self.restarts.append(1) or True
        real_run = subprocess.run

        def run(args, **kwargs):             # systemctl never runs for real; openssl does
            if args and args[0] == "systemctl":
                self.restarts.append(args)
                return subprocess.CompletedProcess(args, 0, "", "")
            return real_run(args, **kwargs)
        self.admin.subprocess = type("S", (), {"run": staticmethod(run), "CompletedProcess": subprocess.CompletedProcess})
        (self.tmp / "data" / "config.json").write_text(json.dumps({"public_url": "https://cc.example.org"}))
        (self.tmp / "data" / "secrets.json").write_text(json.dumps(
            {"board_token": "b0ard", "crowdcad_password": "s3cret", "tak_key_password": "atakatak"}))

    def config(self):
        return json.loads((self.tmp / "data" / "config.json").read_text())

    def secrets(self):
        return json.loads((self.tmp / "data" / "secrets.json").read_text())


class HelperTest(_Base):
    def test_settings_saved_through_the_helper_and_restart(self):
        answer = self.hook._admin("settings", {"form": {"crowdcad_url": "http://127.0.0.1:8090",
                                                         "crowdcad_identity": "bridge@x", "crowdcad_password": "new"}})
        self.assertTrue(answer["ok"], answer)
        self.assertEqual(self.config()["crowdcad_url"], "http://127.0.0.1:8090")
        self.assertEqual(self.secrets()["crowdcad_password"], "new")
        self.assertTrue(self.restarts)

    def test_bad_settings_are_refused_and_nothing_written(self):
        answer = self.hook._admin("settings", {"form": {"crowdcad_url": "ftp://nope"}})
        self.assertFalse(answer["ok"])
        self.assertIn("http", answer["message"])
        self.assertNotIn("crowdcad_url", self.config())

    def test_view_has_flags_not_passwords(self):
        self.hook._admin("view")
        view = json.loads((self.tmp / "console" / "view.json").read_text())
        self.assertEqual(view["config"]["public_url"], "https://cc.example.org")
        self.assertIs(view["secrets"]["crowdcad_password"], True)
        self.assertNotIn("s3cret", json.dumps(view))
        self.assertNotIn("atakatak", json.dumps(view))

    def test_requests_and_answers_are_cleaned_up(self):
        self.hook._admin("view")
        self.assertEqual(sorted(p.name for p in (self.tmp / "console").iterdir()), ["view.json"])

    def test_unknown_request_is_refused(self):
        self.assertFalse(self.hook._admin("rm -rf")["ok"])

    def test_no_helper_answers_with_a_fix(self):
        self.hook._ADMIN_INLINE = None
        answer = self.hook._admin("view", timeout=0.5)
        self.assertFalse(answer["ok"])
        self.assertIn("crowdcad-tak-admin.path", answer["message"])


@unittest.skipUnless(OPENSSL, "openssl not installed")
class CertTest(_Base):
    @classmethod
    def setUpClass(cls):
        cls.certdir = Path(tempfile.mkdtemp())
        d = str(cls.certdir)
        # A CA, a client cert it signs, a password .p12 (TAK Portal style), a truststore .p12,
        # an encrypted key, and an unrelated key for the mismatch case.
        openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem",
                "-days", "2", "-subj", "/CN=Test CA", cwd=d)
        openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "client.key", "-out", "client.csr",
                "-subj", "/CN=global-crowdcad", cwd=d)
        openssl("x509", "-req", "-in", "client.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial",
                "-out", "client.pem", "-days", "2", cwd=d)
        openssl("pkcs12", "-export", "-in", "client.pem", "-inkey", "client.key", "-out", "client.p12",
                "-passout", "pass:atakatak", cwd=d)
        openssl("pkcs12", "-export", "-nokeys", "-in", "ca.pem", "-out", "truststore.p12",
                "-passout", "pass:trustpw", cwd=d)
        openssl("pkey", "-in", "client.key", "-aes256", "-passout", "pass:keypw", "-out", "client-enc.key", cwd=d)
        openssl("genpkey", "-algorithm", "RSA", "-out", "other.key", cwd=d)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.certdir, True)

    def b64(self, name):
        return base64.b64encode((self.certdir / name).read_bytes()).decode()

    def test_p12_and_truststore_install(self):
        answer = self.hook._admin("cert", {"client_p12": self.b64("client.p12"), "client_password": "atakatak",
                                           "truststore_p12": self.b64("truststore.p12"),
                                           "truststore_password": "trustpw"})
        self.assertTrue(answer["ok"], answer)
        self.assertIn("global-crowdcad", answer["message"])
        cfg = self.config()
        self.assertTrue(cfg["tak_cert"].endswith("tak-client.pem"))
        self.assertTrue(cfg["tak_ca"].endswith("tak-ca.pem"))
        self.assertIn("PRIVATE KEY", Path(cfg["tak_key"]).read_text())
        self.assertEqual(self.secrets()["tak_key_password"], "")      # the .p12's key is stored unencrypted
        self.assertIn("Test CA", subprocess.run([OPENSSL, "x509", "-in", cfg["tak_ca"], "-noout", "-subject"],
                                                capture_output=True, text=True).stdout)
        view = json.loads((self.tmp / "console" / "view.json").read_text())
        self.assertIn("global-crowdcad", view["cert"]["subject"])
        self.assertTrue(self.restarts)

    def test_legacy_encrypted_p12(self):
        # TAK's makeCert.sh / TAK Portal p12s use RC2/3DES, which OpenSSL 3 reads only with -legacy.
        try:
            openssl("pkcs12", "-export", "-legacy", "-in", "client.pem", "-inkey", "client.key",
                    "-out", "legacy.p12", "-passout", "pass:atakatak", cwd=str(self.certdir))
        except subprocess.CalledProcessError:
            self.skipTest("this openssl can't write legacy p12s")
        answer = self.hook._admin("cert", {"client_p12": self.b64("legacy.p12"), "client_password": "atakatak"})
        self.assertTrue(answer["ok"], answer)

    def test_wrong_p12_password_changes_nothing(self):
        answer = self.hook._admin("cert", {"client_p12": self.b64("client.p12"), "client_password": "nope"})
        self.assertFalse(answer["ok"])
        self.assertIn("password", answer["message"])
        self.assertNotIn("tak_cert", self.config())
        self.assertEqual(self.secrets()["tak_key_password"], "atakatak")
        self.assertFalse(self.restarts)

    def test_pem_and_encrypted_key_with_password(self):
        answer = self.hook._admin("cert", {"client_pem": self.b64("client.pem"),
                                           "client_key": self.b64("client-enc.key"), "client_password": "keypw"})
        self.assertTrue(answer["ok"], answer)
        self.assertEqual(self.secrets()["tak_key_password"], "keypw")
        self.assertNotIn("tak_ca", self.config())                      # no truststore: the CA is kept

    def test_encrypted_key_without_password_is_refused(self):
        answer = self.hook._admin("cert", {"client_pem": self.b64("client.pem"),
                                           "client_key": self.b64("client-enc.key")})
        self.assertFalse(answer["ok"])
        self.assertIn("password", answer["message"])

    def test_key_that_doesnt_match_is_refused(self):
        answer = self.hook._admin("cert", {"client_pem": self.b64("client.pem"), "client_key": self.b64("other.key")})
        self.assertFalse(answer["ok"])
        self.assertIn("don't work together", answer["message"])

    def test_nothing_uploaded_is_refused(self):
        self.assertIn(".p12", self.hook._admin("cert", {})["message"])


@unittest.skipUnless(flask and OPENSSL, "Flask or openssl not installed")
class PageTest(_Base):
    def setUp(self):
        super().setUp()
        self.hook._service_status = lambda fresh=False: (True, True, {"crowdcad": {"mode": "live"}, "tak": {}})
        app = flask.Flask("console")
        app.secret_key = "x"
        self.hook.attach({"app": app, "login_required": lambda f: f, "VERSION": "test"})
        self.client = app.test_client()

    def test_page_shows_the_card_and_settings_from_the_view(self):
        page = self.client.get("/crowdcad").get_data(as_text=True)
        self.assertIn("TAK certificate", page)
        self.assertIn('enctype="multipart/form-data"', page)
        self.assertIn("(set — leave blank to keep)", page)               # from the view's flag
        self.assertNotIn("s3cret", page)

    def test_upload_from_the_form(self):
        CertTest.setUpClass()
        self.addCleanup(CertTest.tearDownClass)
        import io
        d = CertTest.certdir
        response = self.client.post("/crowdcad/cert", content_type="multipart/form-data", data={
            "client_p12": (io.BytesIO((d / "client.p12").read_bytes()), "global-crowdcad.p12"),
            "client_password": "atakatak"})
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200, body)
        self.assertIn("global-crowdcad", body)
        self.assertTrue(self.config()["tak_cert"].endswith("tak-client.pem"))

    def test_cross_origin_upload_refused(self):
        response = self.client.post("/crowdcad/cert", data={}, headers={"Origin": "https://evil.example.com"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
