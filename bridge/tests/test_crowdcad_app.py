"""infratak/crowdcad_app.py + the CrowdCAD app block in crowdcad_caddy.py (install.sh
--with-crowdcad): what gets deployed, the accounts it makes, and that it never takes over a
bridge someone pointed elsewhere."""

import importlib
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

INFRATAK = Path(__file__).resolve().parents[2] / "infratak"
sys.path.insert(0, str(INFRATAK))
app = importlib.import_module("crowdcad_app")
caddy = importlib.import_module("crowdcad_caddy")
sys.path.remove(str(INFRATAK))

SUPERUSER = {"email": "admin@crowdcad.example.org", "password": "su-pass-123"}
OPEN_RULE = "(@request.body.isAdmin:isset = false || @request.body.isAdmin = false)"


class FakePocketBase:
    """Just enough of PocketBase 0.37's REST API for crowdcad_app.PocketBaseAdmin."""

    def __init__(self):
        self.users = {}
        self.create_rule = OPEN_RULE
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, body=None):
                raw = json.dumps(body or {}).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def body(self):
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length) or b"{}")

            def authed(self):
                if self.headers.get("Authorization") != "su-token":
                    self.reply(403, {"message": "superuser only"})
                    return False
                return True

            def do_GET(self):
                url = urllib.parse.urlparse(self.path)
                if url.path == "/api/health":
                    return self.reply(200, {"code": 200})
                if url.path == "/api/collections/users/records" and self.authed():
                    flt = urllib.parse.parse_qs(url.query).get("filter", [""])[0]
                    email = flt.split('"')[1] if '"' in flt else ""
                    items = [u for u in fake.users.values() if u["email"] == email]
                    return self.reply(200, {"items": items})
                self.reply(404)

            def do_POST(self):
                if self.path == "/api/collections/_superusers/auth-with-password":
                    body = self.body()
                    if body == {"identity": SUPERUSER["email"], "password": SUPERUSER["password"]}:
                        return self.reply(200, {"token": "su-token"})
                    return self.reply(400, {"message": "Failed to authenticate."})
                if self.path == "/api/collections/users/records" and self.authed():
                    body = self.body()
                    if body.get("password") != body.get("passwordConfirm"):
                        return self.reply(400)
                    uid = f"u{len(fake.users) + 1}"
                    fake.users[uid] = {"id": uid, **body}
                    return self.reply(200, fake.users[uid])
                self.reply(404)

            def do_PATCH(self):
                if self.path == "/api/collections/users" and self.authed():
                    fake.create_rule = self.body().get("createRule")
                    return self.reply(200)
                prefix = "/api/collections/users/records/"
                if self.path.startswith(prefix) and self.authed():
                    fake.users[self.path[len(prefix):]].update(self.body())
                    return self.reply(200)
                self.reply(404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class PocketBaseAdminTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakePocketBase()
        self.addCleanup(self.fake.close)
        self.pb = app.PocketBaseAdmin(self.fake.url, SUPERUSER["email"], SUPERUSER["password"])

    def test_wrong_superuser_password_is_an_error(self):
        with self.assertRaises(app.AppError):
            app.PocketBaseAdmin(self.fake.url, SUPERUSER["email"], "nope")

    def test_user_created_verified_then_left_alone(self):
        self.assertEqual(self.pb.ensure_user("medic@x.org", "pw-123456"), "created")
        user = next(iter(self.fake.users.values()))
        self.assertTrue(user["verified"])          # can sign in without an email round trip
        self.assertFalse(user["isAdmin"])
        self.assertEqual(self.pb.ensure_user("medic@x.org", "other-pw"), "unchanged")
        self.assertEqual(user["password"], "pw-123456")   # someone's own password is never reset

    def test_admin_is_promoted(self):
        self.pb.ensure_user("boss@x.org", "pw-123456")
        self.assertEqual(self.pb.ensure_user("boss@x.org", "pw-123456", admin=True), "updated")
        self.assertTrue(next(iter(self.fake.users.values()))["isAdmin"])

    def test_bridge_password_follows_the_stored_secret(self):
        self.pb.ensure_user("bridge@x.org", "old-pw-123")
        self.pb.ensure_user("bridge@x.org", "new-pw-123", reset_password=True)
        self.assertEqual(next(iter(self.fake.users.values()))["password"], "new-pw-123")

    def test_signup_closed_and_reopened(self):
        self.pb.set_signup(False)
        self.assertIsNone(self.fake.create_rule)     # superuser-only
        self.pb.set_signup(True)
        self.assertEqual(self.fake.create_rule, OPEN_RULE)   # CrowdCAD's own rule, isAdmin still blocked

    def test_wait_healthy(self):
        self.assertTrue(app.wait_healthy(self.fake.url, seconds=5))


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def test_compose_is_loopback_only_and_bakes_in_the_public_pocketbase_url(self):
        spec = app.compose_spec("crowdcad.example.org", "v1.6.0", 3100, 8090)
        web, pb = spec["services"]["web"], spec["services"]["pocketbase"]
        self.assertEqual(web["ports"], ["127.0.0.1:3100:3000"])
        self.assertEqual(pb["ports"], ["127.0.0.1:8090:8090"])
        self.assertEqual(web["build"]["args"], {"NEXT_PUBLIC_BACKEND": "pocketbase",
                                                "NEXT_PUBLIC_POCKETBASE_URL": "https://crowdcad.example.org"})
        self.assertEqual(pb["volumes"], ["./pb_data:/pb/pb_data", "./pb_hooks:/pb/pb_hooks:ro"])
        self.assertEqual(spec["name"], "crowdcad")

    def test_fingerprint_ignores_ports_and_volumes(self):
        spec = app.compose_spec("crowdcad.example.org", "v1.6.0", 3100, 8090)
        moved = app.compose_spec("crowdcad.example.org", "v1.6.0", 3999, 8091)
        moved["services"]["pocketbase"]["volumes"] = []
        self.assertEqual(app.build_fingerprint(spec, str(self.d)), app.build_fingerprint(moved, str(self.d)))
        rehosted = app.compose_spec("cad.example.org", "v1.6.0", 3100, 8090)       # baked into the web image
        self.assertNotEqual(app.build_fingerprint(spec, str(self.d)), app.build_fingerprint(rehosted, str(self.d)))

    def test_hook_installed_once(self):
        target = self.d / "hooks"
        app.install_hooks(str(target))
        hook = target / "crowdcad_tak.pb.js"
        self.assertIn("/api/crowdcad-tak/events/{id}/apply", hook.read_text())
        mtime = hook.stat().st_mtime_ns
        app.install_hooks(str(target))
        self.assertEqual(hook.stat().st_mtime_ns, mtime)          # unchanged → untouched (no PocketBase reload)

    def test_credentials_made_once_and_kept(self):
        path = str(self.d / "credentials.json")
        first = app.credentials(path, "crowdcad.example.org")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(first["bridge"]["email"], "crowdcad-bridge@crowdcad.example.org")
        self.assertEqual(first["admin"]["email"], "admin@crowdcad.example.org")
        for role in ("superuser", "admin", "bridge"):
            self.assertGreaterEqual(len(first[role]["password"]), 20)
            self.assertFalse(set(first[role]["password"]) & set("$# '\""))
        self.assertEqual(app.credentials(path, "crowdcad.example.org", "someone@else.org"), first)

    def write_bridge(self, config, secrets):
        data = self.d / "data"
        data.mkdir()
        (data / "config.json").write_text(json.dumps(config))
        (data / "secrets.json").write_text(json.dumps(secrets))
        return data

    def test_bridge_pointed_at_local_crowdcad(self):
        data = self.write_bridge({"events": "active"}, {"board_token": "t"})
        self.assertTrue(app.seed_bridge(str(data), "http://127.0.0.1:8090", "b@x", "pw"))
        config = json.loads((data / "config.json").read_text())
        secrets = json.loads((data / "secrets.json").read_text())
        self.assertEqual((config["crowdcad_url"], config["crowdcad_identity"], config["events"]),
                         ("http://127.0.0.1:8090", "b@x", "active"))
        self.assertEqual((secrets["crowdcad_password"], secrets["board_token"]), ("pw", "t"))
        self.assertEqual(stat.S_IMODE(os.stat(data / "secrets.json").st_mode), 0o600)
        self.assertFalse(app.seed_bridge(str(data), "http://127.0.0.1:8090", "b@x", "pw"))   # no needless restart

    def test_dispatch_site_seeded_once_and_never_overwritten(self):
        data = self.write_bridge({"crowdcad_url": "http://127.0.0.1:8090", "crowdcad_identity": "b@x"},
                                 {"crowdcad_password": "pw"})
        # An earlier install already pointed the bridge here, without the app URL: add it.
        self.assertTrue(app.seed_bridge(str(data), "http://127.0.0.1:8090", "b@x", "pw", "https://crowdcad.example.org"))
        self.assertEqual(json.loads((data / "config.json").read_text())["crowdcad_app_url"], "https://crowdcad.example.org")
        config = json.loads((data / "config.json").read_text())
        config["crowdcad_app_url"] = "https://cad.custom.org"        # changed on the console page
        (data / "config.json").write_text(json.dumps(config))
        self.assertFalse(app.seed_bridge(str(data), "http://127.0.0.1:8090", "b@x", "pw", "https://crowdcad.example.org"))
        self.assertEqual(json.loads((data / "config.json").read_text())["crowdcad_app_url"], "https://cad.custom.org")

    def test_bridge_set_elsewhere_is_never_taken_over(self):
        data = self.write_bridge({"crowdcad_url": "https://cad.other.org", "crowdcad_identity": "me"},
                                 {"crowdcad_password": "mine"})
        self.assertFalse(app.seed_bridge(str(data), "http://127.0.0.1:8090", "b@x", "pw"))
        self.assertEqual(json.loads((data / "config.json").read_text())["crowdcad_url"], "https://cad.other.org")


CADDYFILE = """tak.example.org {
    reverse_proxy 127.0.0.1:8443
}

# --- User-added blocks (do not remove) ---
"""


class AppCaddyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        (self.d / "console" / ".config").mkdir(parents=True)
        (self.d / "console" / ".config" / "settings.json").write_text(json.dumps({"fqdn": "example.org"}))
        (self.d / "data").mkdir()
        (self.d / "data" / "config.json").write_text("{}")
        self.caddyfile = self.d / "Caddyfile"
        self.caddyfile.write_text(CADDYFILE)

    def caddy(self, *args):
        return caddy.main([args[0], "--caddyfile", str(self.caddyfile), "--console-dir", str(self.d / "console"),
                           "--data", str(self.d / "data"), *args[1:]])

    def ensure_with_app(self):
        return self.caddy("ensure", "--app-host", "crowdcad.example.org", "--app-web", "127.0.0.1:3100",
                          "--app-pocketbase", "127.0.0.1:8090")

    def test_app_block_routes_pocketbase_and_next(self):
        self.assertEqual(self.ensure_with_app(), 0)
        text = self.caddyfile.read_text()
        app_part = text[text.index(caddy.APP_BEGIN):text.index(caddy.APP_END)]
        self.assertLess(text.index(caddy.USER_BLOCKS_MARKER), text.index(caddy.APP_BEGIN))
        self.assertIn("crowdcad.example.org {", app_part)
        self.assertIn("@pocketbase path /api/* /_/*", app_part)
        self.assertIn("reverse_proxy 127.0.0.1:8090", app_part)
        # Next.js's own API route is matched before PocketBase's /api/*
        self.assertLess(app_part.index("handle /api/contact*"), app_part.index("handle @pocketbase"))
        pb_handle = app_part[app_part.index("handle @pocketbase"):app_part.index("    handle {")]
        self.assertNotIn("encode", pb_handle)     # realtime SSE must not be buffered by gzip
        self.assertIn("crowdcad-tak.example.org {", text)   # board block alongside

    def test_idempotent_and_removed_separately(self):
        self.ensure_with_app()
        once = self.caddyfile.read_text()
        self.ensure_with_app()
        self.assertEqual(self.caddyfile.read_text(), once)
        self.assertEqual(once.count(caddy.APP_BEGIN), 1)
        self.caddy("remove")                                   # bridge uninstall leaves CrowdCAD reachable
        text = self.caddyfile.read_text()
        self.assertNotIn(caddy.BEGIN, text)
        self.assertIn(caddy.APP_BEGIN, text)
        self.caddy("app-remove")
        self.assertEqual(self.caddyfile.read_text().strip(), CADDYFILE.strip())

    def test_no_ping_pong_with_another_plugins_heal(self):
        """Aleph's heal moves its block to the end of the file. Ours must then see its own blocks
        unchanged and write nothing; moving back to the end would re-trigger Aleph's heal, forever."""
        aleph = "# >>> aleph-tak (managed)\naleph.example.org {\n    reverse_proxy 127.0.0.1:8781\n}\n# <<< aleph-tak"
        self.caddyfile.write_text(CADDYFILE + "\n" + aleph + "\n")
        self.ensure_with_app()
        text = self.caddyfile.read_text()
        self.assertLess(text.index("aleph.example.org"), text.index(caddy.BEGIN))   # appended after Aleph
        # Aleph's heal: strip its block, append it at the end.
        start, stop = text.index("# >>> aleph-tak"), text.index("# <<< aleph-tak") + len("# <<< aleph-tak")
        moved = text[:start].rstrip("\n") + "\n" + text[stop:].lstrip("\n").rstrip("\n") + "\n\n" + aleph + "\n"
        self.caddyfile.write_text(moved)
        self.ensure_with_app()
        self.assertEqual(self.caddyfile.read_text(), moved)     # unchanged: nothing re-triggers Aleph

    def test_changed_block_is_replaced_in_place(self):
        self.ensure_with_app()
        self.caddy("ensure", "--app-host", "crowdcad.example.org", "--app-web", "127.0.0.1:3999",
                   "--app-pocketbase", "127.0.0.1:8090")
        text = self.caddyfile.read_text()
        self.assertEqual(text.count(caddy.APP_BEGIN), 1)
        self.assertIn("reverse_proxy 127.0.0.1:3999", text)
        self.assertNotIn("127.0.0.1:3100", text)
        self.assertLess(text.index(caddy.BEGIN), text.index(caddy.APP_BEGIN))

    def test_block_above_the_marker_is_moved_below_it(self):
        stray = caddy.block("crowdcad-tak.example.org", "127.0.0.1:8782")
        self.caddyfile.write_text(stray + "\n\n" + CADDYFILE)
        self.caddy("ensure")
        text = self.caddyfile.read_text()
        self.assertEqual(text.count(caddy.BEGIN), 1)
        self.assertLess(text.index(caddy.USER_BLOCKS_MARKER), text.index(caddy.BEGIN))

    def test_plain_ensure_leaves_an_existing_app_block_alone_only_when_asked(self):
        self.ensure_with_app()
        self.caddy("ensure")       # no --app-host: the app block isn't touched either way
        self.assertIn(caddy.APP_BEGIN, self.caddyfile.read_text())

    def test_app_host(self):
        self.assertEqual(caddy.app_site_host(str(self.d / "console")), "crowdcad.example.org")
        self.assertEqual(caddy.app_site_host(str(self.d / "console"), "cad"), "cad.example.org")
        self.assertEqual(caddy.app_site_host(str(self.d / "console"), "cad.other.org"), "cad.other.org")
        self.assertIsNone(caddy.app_site_host(None))


if __name__ == "__main__":
    unittest.main()
