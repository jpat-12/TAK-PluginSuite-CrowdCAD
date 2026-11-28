"""The infra-TAK console hook (infratak/crowdcad_infratak*.py).

HookPageTest: the /crowdcad page and settings form on a bare Flask app (needs Flask).
ConsoleVersionsTest: the hook inside real infra-TAK app.py files, oldest release to current,
alongside Aleph for TAK's hook when that sibling repo is present (both must attach). Needs
Flask + psutil and INFRATAK_REPO=/path/to/infra-TAK checkout; refs via INFRATAK_VERSIONS.
"""

import importlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

INFRATAK = Path(__file__).resolve().parents[2] / "infratak"
ALEPH = Path(__file__).resolve().parents[3] / "InfraTAK-Plugin-Aleph" / "infratak"
REPO = os.environ.get("INFRATAK_REPO")
VERSIONS = os.environ.get("INFRATAK_VERSIONS", "v0.1.0-alpha v0.6.1-alpha v0.9.0-alpha HEAD").split()

try:
    import flask
except ImportError:
    flask = None


def load_hook():
    sys.path.insert(0, str(INFRATAK))
    try:
        return importlib.import_module("crowdcad_infratak")
    finally:
        sys.path.remove(str(INFRATAK))


@unittest.skipUnless(flask, "Flask not installed")
class HookPageTest(unittest.TestCase):
    def setUp(self):
        self.hook = load_hook()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hook.DATA_DIR = self.tmp.name
        self.restarts = []
        self.hook.subprocess = type("S", (), {"run": lambda _, args, **k: self.restarts.append(args)})()
        self.hook.time.sleep = lambda s: None
        # Tracker R43: saving goes through the root helper (crowdcad_admin.py); run it in-process.
        sys.path.insert(0, str(INFRATAK))
        try:
            admin = importlib.import_module("crowdcad_admin")
        finally:
            sys.path.remove(str(INFRATAK))
        admin.subprocess = self.hook.subprocess
        console = Path(self.tmp.name, "console")
        console.mkdir()
        self.hook.CONSOLE_DIR = str(console)
        self.hook._ADMIN_INLINE = admin.run
        self.hook._service_status = lambda fresh=False: (True, True, {
            "version": "0.1.0", "crowdcad": {"mode": "live", "url": "http://pb:8090"},
            "tak": {"connected": True, "host": "127.0.0.1:8089", "sent": 12},
            "events": [{"id": "e1", "name": "Demo <Game>", "counts": {"incident": 2},
                        "unplaced": [{"kind": "call", "label": "009 · Laceration", "location": "Row 22"}]}]})
        app = flask.Flask("console")
        app.secret_key = "x"
        g = {"app": app, "login_required": lambda f: f, "VERSION": "test",
             "detect_modules": lambda: {"takserver": {"installed": True, "priority": 1}},
             "render_sidebar": lambda modules, active: '<nav class="sidebar"></nav>'}
        self.assertEqual(self.hook.attach(g), ["routes", "module card", "sidebar"])
        self.g, self.client = g, app.test_client()

    def write(self, name, value):
        Path(self.tmp.name, name).write_text(json.dumps(value))

    def read(self, name):
        return json.loads(Path(self.tmp.name, name).read_text())

    def form(self, **overrides):
        return {"crowdcad_url": "https://crowdcad.example.org/", "crowdcad_identity": "bridge@x.org",
                "crowdcad_password": "", "events": "active", "publish_calls": "on", "publish_zones": "on",
                "team_uids": "Team 1 = ANDROID-abc\n\n", "layer_bounds": "",
                "cors_origins": "https://tak.example.org:8443/\n", **overrides}

    def test_card_sidebar_and_page(self):
        self.assertEqual(self.g["detect_modules"]()["crowdcad"]["route"], "/crowdcad")
        self.assertIn('href="/crowdcad"', self.g["render_sidebar"]({"crowdcad": {"installed": True}}, "crowdcad"))
        page = self.client.get("/crowdcad").get_data(as_text=True)
        self.assertIn("CrowdCAD live (realtime)", page)
        self.assertIn("Demo &lt;Game&gt;", page)               # CrowdCAD text is escaped
        self.assertIn("009 · Laceration", page)
        self.assertIn('name="crowdcad_url"', page)
        self.assertIn("Board URL (CloudTAK / WebTAK)", page)

    def test_save_writes_config_keeps_password_and_restarts(self):
        self.write("config.json", {"tak_port": 8089, "crowdcad_url": "http://old"})
        self.write("secrets.json", {"crowdcad_password": "keep-me", "tak_key_password": "atakatak"})
        response = self.client.post("/crowdcad/settings", data=self.form())
        self.assertEqual((response.status_code, response.headers["Location"]), (302, "/crowdcad?saved=1"))
        cfg = self.read("config.json")
        self.assertEqual(cfg["crowdcad_url"], "https://crowdcad.example.org")
        self.assertEqual(cfg["tak_port"], 8089)                # untouched keys survive
        self.assertEqual(cfg["team_uids"], {"Team 1": "ANDROID-abc"})
        self.assertEqual(cfg["cors_origins"], ["https://tak.example.org:8443"])
        self.assertEqual(cfg["publish"], {"calls": True, "teams": False, "zones": True, "posts": False,
                                          "clinic_walkups": False})
        self.assertEqual(self.read("secrets.json")["crowdcad_password"], "keep-me")
        self.assertEqual(self.restarts, [["systemctl", "restart", "crowdcad-tak"]])
        self.client.post("/crowdcad/settings", data=self.form(crowdcad_password="new", events="abc, def"))
        self.assertEqual(self.read("secrets.json")["crowdcad_password"], "new")
        self.assertEqual(self.read("config.json")["events"], ["abc", "def"])

    def test_invalid_input_writes_nothing(self):
        for bad in ({"crowdcad_url": "ftp://x"}, {"team_uids": "no equals sign"},
                    {"layer_bounds": '{"l1": {"north": 1}}'}, {"layer_bounds": "not json"},
                    {"cors_origins": "tak.example.org"}):
            response = self.client.post("/crowdcad/settings", data=self.form(**bad))
            self.assertEqual(response.status_code, 400, bad)
            self.assertFalse(Path(self.tmp.name, "config.json").exists(), bad)
        self.assertEqual(self.restarts, [])

    def test_cross_origin_post_refused(self):
        response = self.client.post("/crowdcad/settings", data=self.form(),
                                    headers={"Origin": "https://evil.example.com"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Path(self.tmp.name, "config.json").exists())

    def test_attach_twice_is_harmless(self):
        self.assertEqual(self.hook.attach(self.g), ["routes", "module card", "sidebar"])
        self.assertEqual(self.g["render_sidebar"]({"crowdcad": {"installed": True}}, "x").count('href="/crowdcad"'), 1)


PROBE = r"""
import json, os, subprocess, sys
for d in sys.argv[1:]:
    sys.path.insert(0, d)
if os.name == "nt":
    # Old consoles call systemctl/docker unguarded; answer as a Linux host with nothing installed.
    _run = subprocess.run
    def run(args, *a, **k):
        if isinstance(args, (list, tuple)) and args and args[0] in ("systemctl", "docker", "caddy", "ufw"):
            return subprocess.CompletedProcess(args, 3, "inactive\n", "")
        return _run(args, *a, **k)
    subprocess.run = run
    os.getuid = lambda: 0
# What the .pth files do at interpreter start, in .pth (alphabetical) order.
names = [n for n in ("aleph_infratak_boot", "crowdcad_infratak_boot") if any(
    os.path.exists(os.path.join(d, n + ".py")) for d in sys.argv[1:])]
for name in names:
    __import__(name)
import crowdcad_infratak
crowdcad_infratak._service_status = lambda fresh=False: (True, True, {"version": "t", "configured": False})
if "aleph_infratak_boot" in names:
    import aleph_infratak
    aleph_infratak._service_status = lambda: (True, True, {"version": "t", "jobs": {}})
    aleph_infratak._public_url = lambda: "https://aleph.example.org"
import app as console
client = console.app.test_client()
with client.session_transaction() as s:
    s["authenticated"] = True
modules = console.detect_modules()
rules = sorted(r.rule for r in console.app.url_map.iter_rules())
result = dict(version=getattr(console, "VERSION", "?"),
              routes=[r for r in rules if r.startswith("/crowdcad")],
              aleph=[r for r in rules if r.startswith("/aleph")],
              card=modules.get("crowdcad", {}).get("route"),
              page_status=client.get("/crowdcad").status_code,
              anonymous_status=console.app.test_client().get("/crowdcad").status_code)
if hasattr(console, "render_sidebar"):
    result["sidebar_link"] = 'href="/crowdcad"' in console.render_sidebar(modules, "crowdcad")
print("PROBE" + json.dumps(result), flush=True)
os._exit(0)   # some consoles start non-daemon threads at import
"""


@unittest.skipUnless(REPO and flask, "set INFRATAK_REPO (and install flask + psutil) to run")
class ConsoleVersionsTest(unittest.TestCase):
    def probe(self, ref):
        tree = subprocess.run(["git", "-C", REPO, "archive", "--format=tar", ref], capture_output=True, check=True).stdout
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            console = Path(tmp) / "infra-TAK"
            console.mkdir()
            with tarfile.open(fileobj=io.BytesIO(tree)) as archive:
                archive.extractall(console)
            (console / ".config").mkdir(exist_ok=True)
            if not (console / "start.sh").exists():
                (console / "start.sh").write_text("#!/bin/bash\n")
            paths = [str(INFRATAK)] + ([str(ALEPH)] if ALEPH.is_dir() else [])
            env = {**os.environ, "CONFIG_DIR": str(console / ".config"), "PYTHONPATH": str(console),
                   "PYTHONIOENCODING": "utf-8"}
            run = subprocess.run([sys.executable, "-c", PROBE, *paths], cwd=console, env=env,
                                 capture_output=True, text=True, timeout=180)
        line = next((l for l in run.stdout.splitlines() if l.startswith("PROBE")), None)
        self.assertIsNotNone(line, f"{ref} probe failed:\n{run.stdout[-1500:]}\n{run.stderr[-3000:]}")
        return json.loads(line[5:]), run.stderr

    def test_every_version_gets_the_integration(self):
        for ref in VERSIONS:
            with self.subTest(version=ref):
                result, log = self.probe(ref)
                self.assertIn("[crowdcad-tak] attached to infra-TAK", log)
                self.assertEqual(result["routes"], ["/crowdcad", "/crowdcad/settings"])
                self.assertEqual(result["card"], "/crowdcad")
                self.assertEqual(result["page_status"], 200)
                self.assertIn(result["anonymous_status"], (302, 401))
                if "sidebar_link" in result:
                    self.assertTrue(result["sidebar_link"])
                if ALEPH.is_dir():   # both plugins' finders must attach, not just the first
                    self.assertIn("/aleph", result["aleph"], log[-2000:])


if __name__ == "__main__":
    unittest.main()
