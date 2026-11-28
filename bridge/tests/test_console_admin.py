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


class VersionsTest(_Base):
    """Tracker R47: CloudTAK found without asking; versions compared with GitHub main."""

    def fake_cloudtak(self, plugin_version=None):
        ct = self.tmp / "CloudTAK"
        (ct / "api" / "web" / "plugins" / "crowdcad").mkdir(parents=True)
        (ct / "api" / "web" / "plugin.ts").write_text("")
        (ct / "package.json").write_text(json.dumps({"version": "13.77.1"}))
        if plugin_version is not None:
            (ct / "api" / "web" / "plugins" / "crowdcad" / "index.ts").write_text("")
            (ct / "api" / "web" / "plugins" / "crowdcad" / "VERSION").write_text(plugin_version + "\n")
        self.admin.CLOUDTAK_GUESSES = [str(ct)]
        return ct

    def test_finds_cloudtak_and_reads_installed_versions(self):
        ct = self.fake_cloudtak("1.0.4")
        (self.tmp / "crowdcad").mkdir()
        (self.tmp / "crowdcad" / "app.json").write_text(json.dumps({"ref": "v1.6.0"}))
        self.assertEqual(self.admin.installed_versions({}), {
            "cloudtak_dir": str(ct), "cloudtak": "13.77.1", "cloudtak_plugin": "1.0.4", "crowdcad": "v1.6.0"})

    def test_nothing_installed(self):
        self.admin.CLOUDTAK_GUESSES = []
        got = self.admin.installed_versions({})
        self.assertEqual((got["cloudtak_plugin"], got["crowdcad"]), (None, None))

    def test_cloudtak_job_uses_the_found_folder(self):
        ct = self.fake_cloudtak()
        started = []
        self.hook._start_job = lambda d: started.append(d)
        self.assertTrue(self.hook._admin("cloudtak", {"dir": ""})["ok"])
        self.assertEqual(started, [str(ct)])

    def test_view_carries_versions(self):
        self.fake_cloudtak("1.0.3")
        self.hook._admin("view")
        self.assertEqual(self.hook._view_versions()["cloudtak_plugin"], "1.0.3")

    def source_checkout(self, version="1.0.4"):
        src = self.tmp / "src" / "cloudtak" / "plugin"
        (src / "lib").mkdir(parents=True)
        (self.tmp / "src" / "VERSION").write_text(version + "\n")
        for rel, text in (("index.ts", "entry"), ("lib/a.ts", "a"), ("package.json", "{}")):
            (src / rel).write_text(text)
        return src

    def test_unrecorded_plugin_matching_the_source_gets_its_version(self):
        # R48: installed before install.sh wrote VERSION; same files as the server's checkout.
        ct = self.fake_cloudtak()
        self.source_checkout("1.0.4")
        web = ct / "api" / "web" / "plugins" / "crowdcad"
        (web / "lib").mkdir()
        (web / "index.ts").write_text("entry")
        (web / "lib" / "a.ts").write_text("a")
        self.assertEqual(self.admin.installed_versions({})["cloudtak_plugin"], "1.0.4")
        (web / "lib" / "a.ts").write_text("older")
        self.assertEqual(self.admin.installed_versions({})["cloudtak_plugin"], self.admin.OUTDATED)
        self.hook._main_version = lambda component: "1.0.4"
        self.assertEqual(self.hook._update_check("cloudtak", self.admin.OUTDATED)["state"], "newer")

    def check(self, installed, main):
        self.hook._main_version = lambda component: main
        return self.hook._update_check("bridge", installed)

    def test_update_states(self):
        self.assertEqual(self.check("1.0.3", "1.0.4")["state"], "newer")
        self.assertIn("1.0.4 on main", self.check("1.0.3", "1.0.4")["message"])
        self.assertEqual(self.check("1.0.4", "1.0.4")["message"], "Up to date with main (1.0.4)")
        self.assertEqual(self.check("1.0.4", "0.1.0")["message"], "Newer than main (0.1.0)")
        self.assertIn("Not installed", self.check(None, "1.0.4")["message"])
        self.assertIn("unknown", self.check("", "1.0.4")["message"])
        self.assertEqual(self.hook._vtuple("v1.6.0"), (1, 6, 0))
        self.assertGreater(self.hook._vtuple("1.0.10"), self.hook._vtuple("1.0.9"))

    def test_github_unreachable(self):
        def boom(component):
            raise OSError("offline")
        self.hook._main_version = boom
        self.assertEqual(self.hook._update_check("crowdcad", "v1.6.0")["state"], "failed")


class UpdateTest(_Base):
    """Tracker R49: "Install update" — the helper rebuilds this server's install options and starts the job."""

    def setUp(self):
        super().setUp()
        self.started = []
        self.hook._start_update_job = lambda component, args: self.started.append((component, args))
        self.admin.CLOUDTAK_GUESSES = []
        self.admin.WEBTAK_PLUGIN = str(self.tmp / "no-webtak")

    def test_bridge_update_keeps_this_servers_options(self):
        (self.tmp / "crowdcad").mkdir()
        (self.tmp / "crowdcad" / "app.json").write_text("{}")
        (self.tmp / "webtak").mkdir()
        self.admin.WEBTAK_PLUGIN = str(self.tmp / "webtak")
        self.assertTrue(self.hook._admin("update", {"component": "bridge"})["ok"])
        self.assertEqual(self.started, [("bridge", ["--domain", "cc.example.org", "--webtak"])])

    def test_crowdcad_elsewhere_is_never_built_here(self):
        self.hook._admin("update", {"component": "bridge"})
        self.assertIn("--no-crowdcad", self.started[0][1])
        answer = self.hook._admin("update", {"component": "crowdcad"})
        self.assertFalse(answer["ok"])
        self.assertIn("isn't installed", answer["message"])

    def test_cloudtak_update_rebuilds_the_found_cloudtak(self):
        ct = self.tmp / "CloudTAK"
        (ct / "app").mkdir(parents=True)
        (ct / "app" / "plugin.ts").write_text("")
        self.admin.CLOUDTAK_GUESSES = [str(ct)]
        self.assertTrue(self.hook._admin("update", {"component": "cloudtak"})["ok"])
        self.assertEqual(self.started[0][1][-2:], ["--cloudtak", str(ct)])

    def test_refused_while_another_job_runs_and_for_unknown_components(self):
        self.hook._update_status = lambda: {"state": "running"}
        self.assertIn("already running", self.hook._admin("update", {"component": "bridge"})["message"])
        self.assertFalse(self.hook._admin("update", {"component": "rm -rf"})["ok"])
        self.assertEqual(self.started, [])

    def test_log_parsing(self):
        parse = self.hook._parse_update
        self.assertEqual(parse(None, False)["state"], "idle")
        running = parse("==> Update started 2026-11-28T03:00:00Z: cloudtak\n==> Getting main from GitHub\n", True)
        self.assertEqual((running["state"], running["component"], running["label"]),
                         ("running", "cloudtak", "Getting main from GitHub"))
        failed = parse("==> Update started x: bridge\n==> ERROR couldn't reach GitHub\n==> EXIT 1\n", False)
        self.assertEqual((failed["state"], failed["error"]), ("failed", "couldn't reach GitHub"))
        self.assertEqual(parse("==> Done: bridge 1.0.6 is running\n==> EXIT 0\n", False)["state"], "done")
        self.assertEqual(parse("==> Installing\n", False)["state"], "failed")     # job gone without EXIT

    def versions(self, **found):
        self.hook._main_version = lambda component: found[component.replace("-", "_")]

    def test_newer_is_installable_with_a_confirmation(self):
        self.versions(bridge="1.0.6")
        got = self.hook._update_check("bridge", "1.0.5")
        self.assertTrue(got["installable"])
        self.assertIn("1.0.6", got["confirm"])
        self.assertNotIn("installable", self.hook._update_check("bridge", "1.0.6"))

    def test_crowdcad_installs_only_what_the_bridge_supports(self):
        self.versions(crowdcad="1.7.0", crowdcad_supported="v1.6.0")
        held = self.hook._update_check("crowdcad", "v1.6.0")
        self.assertEqual(held["state"], "held")
        self.assertNotIn("installable", held)
        self.versions(crowdcad="1.7.0", crowdcad_supported="v1.7.0")
        got = self.hook._update_check("crowdcad", "v1.6.0")
        self.assertEqual((got["state"], got["latest"]), ("newer", "v1.7.0"))
        self.versions(crowdcad="1.6.0", crowdcad_supported="v1.6.0")
        self.assertEqual(self.hook._update_check("crowdcad", "v1.6.0")["state"], "current")


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
            "client_password": "atakatak"}, follow_redirects=True)
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200, body)
        self.assertIn("global-crowdcad", body)
        self.assertIn('<details class="card" id="cc-cert" open>', body)    # opened once for the result
        self.assertTrue(self.config()["tak_cert"].endswith("tak-client.pem"))
        again = self.client.get("/crowdcad").get_data(as_text=True)          # R48: closed again on reload
        self.assertIn('<details class="card" id="cc-cert">', again)
        self.assertNotIn("Certificate installed", again)

    def test_cards_fold_closed_and_status_row_has_update_buttons(self):
        page = self.client.get("/crowdcad").get_data(as_text=True)
        for card in ("cc-details", "cc-events", "cc-cert", "cc-settings", "cc-clients", "cc-cloudtak"):
            self.assertIn(f'<details class="card" id="{card}">', page)        # closed: no " open"
        self.assertEqual(page.count('class="ubtn"'), 3)
        self.assertIn('name="p12_password"', page)
        self.assertIn('name="key_password"', page)
        self.assertIn("document.querySelectorAll('.ubtn').forEach(ccCheck)", page)   # R48: checked on load

    def test_save_error_opens_settings(self):
        page = self.client.post("/crowdcad/settings", data={"crowdcad_url": "ftp://x"}).get_data(as_text=True)
        self.assertIn('<details class="card" id="cc-settings" open>', page)

    def test_install_route_starts_the_job_and_refuses_other_sites(self):
        started = []
        self.hook._start_update_job = lambda component, args: started.append(component)
        self.admin.CLOUDTAK_GUESSES = []
        response = self.client.post("/crowdcad/updates/bridge/install")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(started, ["bridge"])
        self.assertEqual(self.client.post("/crowdcad/updates/bridge/install",
                                          headers={"Origin": "https://evil.example.com"}).status_code, 403)
        self.assertEqual(self.client.get("/crowdcad/update-job").get_json()["state"], "idle")
        self.assertIn('id="cc-upd" hidden', self.client.get("/crowdcad").get_data(as_text=True))

    def test_update_route(self):
        self.hook._main_version = lambda component: "9.9.9"
        body = self.client.get("/crowdcad/updates/bridge").get_json()
        self.assertEqual(body["state"], "unknown")             # this fake bridge reports no version
        self.assertEqual(self.client.get("/crowdcad/updates/nope").status_code, 404)

    def p12_post(self, **extra):
        CertTest.setUpClass()
        self.addCleanup(CertTest.tearDownClass)
        import io
        d = CertTest.certdir
        data = {"client_p12": (io.BytesIO((d / "client.p12").read_bytes()), "global-crowdcad.p12"), **extra}
        if "client_pem" in extra:
            data["client_pem"] = (io.BytesIO((d / "client.pem").read_bytes()), "c.pem")
        return self.client.post("/crowdcad/cert", content_type="multipart/form-data", data=data,
                                follow_redirects=True)

    def test_p12_with_its_own_password_field(self):
        response = self.p12_post(p12_password="atakatak")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(self.config()["tak_cert"].endswith("tak-client.pem"))

    def test_p12_and_pem_together_refused(self):
        response = self.p12_post(p12_password="atakatak", client_pem="yes")
        self.assertEqual(response.status_code, 400)
        self.assertIn("not both", response.get_data(as_text=True))
        self.assertNotIn("tak_cert", self.config())

    def test_upload_behind_caddy_is_same_origin(self):
        # R45: Caddy forwards to 127.0.0.1:5001, so Host is the upstream; the browser's origin
        # matches X-Forwarded-Host. This must not be refused as cross-origin.
        for headers in ({"Origin": "https://infratak.example.org", "X-Forwarded-Host": "infratak.example.org"},
                        {"Origin": "https://infratak.example.org", "X-Forwarded-Host": "infratak.example.org",
                         "X-Forwarded-Port": "443"},
                        {"Origin": "https://infratak.example.org:443", "Host": "infratak.example.org"}):
            response = self.client.post("/crowdcad/cert", data={}, headers=headers,
                                        base_url="http://127.0.0.1:5001")
            self.assertNotEqual(response.status_code, 403, headers)
        response = self.client.post("/crowdcad/cert", data={}, base_url="http://127.0.0.1:5001",
                                    headers={"Origin": "https://evil.example.com",
                                             "X-Forwarded-Host": "infratak.example.org"})
        self.assertEqual(response.status_code, 403)

    def test_cross_origin_upload_refused(self):
        response = self.client.post("/crowdcad/cert", data={}, headers={"Origin": "https://evil.example.com"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
