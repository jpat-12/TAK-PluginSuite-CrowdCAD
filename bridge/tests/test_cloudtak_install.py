"""Tracker R41: the one-command install (repo-root install.sh) and the console's
"Install CloudTAK plugin" button (infratak/crowdcad_infratak.py + crowdcad_cloudtak_job.sh).

ProgressTest: the log → progress-bar state machine (pure, always runs).
BootstrapTest: install.sh's argument handling via its dry run (needs bash).
JobScriptTest: the job script end to end against a fake cloudtak/install.sh (needs bash + python3).
ConsoleJobTest: the start/status endpoints on a bare Flask app, subprocess mocked (needs Flask).
Nothing here runs docker, systemctl or a real installer.
"""

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRATAK = ROOT / "infratak"
BASH = shutil.which("bash")

try:
    import flask
except ImportError:
    flask = None


def load_hook():
    sys.path.insert(0, str(INFRATAK))
    try:
        return importlib.reload(importlib.import_module("crowdcad_infratak"))
    finally:
        sys.path.remove(str(INFRATAK))


LOG = """==> Queued from the infra-TAK console
==> Job started 2026-11-27T16:00:00Z (CrowdCAD for TAK 1.0.0)
==> CloudTAK 13.102.0 at /root/CloudTAK (split layout)
==> Backed up the installed plugin → /opt/crowdcad-tak/backups/cloudtak-crowdcad-1.tgz
==> Installed web half → /root/CloudTAK/app/plugins/crowdcad, server half → x, settings → y
==> Rebuilding the CloudTAK API image (5–15 min; the build also lint/type-checks the plugin)
#7 [api 3/12] COPY package.json .
\x1b[32m#9 [api 6/12] RUN npm ci\x1b[0m
"""


class ProgressTest(unittest.TestCase):
    def setUp(self):
        self.hook = load_hook()

    def test_no_log_is_idle(self):
        self.assertEqual(self.hook._parse_progress(None, False)["state"], "idle")

    def test_build_substeps_move_the_bar(self):
        s = self.hook._parse_progress(LOG, True)
        self.assertEqual((s["state"], s["step"]), ("running", "build"))
        self.assertEqual(s["label"], "Rebuilding CloudTAK — build step 6 of 12")
        self.assertEqual(s["percent"], 58)                     # 30 + 56 × 6/12
        self.assertNotIn("\x1b", "".join(s["tail"]))           # colour codes stripped

    def test_success(self):
        s = self.hook._parse_progress(LOG + "==> Restarting the CloudTAK API container\n==> Done.\n"
                                      "==> Healthy: CloudTAK API answered 401\n==> EXIT 0\n", False)
        self.assertEqual((s["state"], s["percent"], s["error"]), ("done", 100, ""))

    def test_failure_reports_the_error_line(self):
        s = self.hook._parse_progress(LOG + "ERROR: build failed\n==> ERROR cloudtak/install.sh failed (exit 1)"
                                      " — see the lines above\n==> EXIT 1\n", False)
        self.assertEqual(s["state"], "failed")
        self.assertEqual(s["error"], "cloudtak/install.sh failed (exit 1) — see the lines above")
        self.assertLess(s["percent"], 100)

    def test_job_that_died_without_exit_is_failed(self):
        s = self.hook._parse_progress(LOG, active=False)
        self.assertEqual(s["state"], "failed")
        self.assertIn("stopped without finishing", s["error"])

    def test_percent_never_goes_backwards(self):
        s = self.hook._parse_progress(LOG + "#2 [api 1/12] FROM node\n", True)
        self.assertEqual(s["percent"], 58)


@unittest.skipUnless(BASH, "bash not found")
class BootstrapTest(unittest.TestCase):
    def dry(self, *args):
        env = {**os.environ, "CROWDCAD_BOOTSTRAP_DRY_RUN": "1"}
        out = subprocess.run([BASH, str(ROOT / "install.sh"), *args], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def test_default_builds_crowdcad_and_passes_flags_through(self):
        self.assertEqual(self.dry(), "infratak/install.sh --with-crowdcad")
        self.assertEqual(self.dry("--tak-group", "ALL", "--cloudtak"),
                         "infratak/install.sh --with-crowdcad --tak-group ALL --cloudtak")

    def test_existing_crowdcad_is_not_rebuilt(self):
        self.assertEqual(self.dry("--crowdcad-url", "https://cc.example.org", "--tak-group", "Team A"),
                         "infratak/install.sh --crowdcad-url https://cc.example.org --tak-group Team\\ A")
        self.assertEqual(self.dry("--no-crowdcad", "--no-pull", "--ref", "dev"), "infratak/install.sh")

    def test_help(self):
        out = subprocess.run([BASH, str(ROOT / "install.sh"), "--help"], capture_output=True, text=True)
        self.assertIn("--no-crowdcad", out.stdout)


def _bash_has_python3():
    if not BASH:
        return False
    return subprocess.run([BASH, "-c", "python3 -c 'import json'"], capture_output=True).returncode == 0


@unittest.skipUnless(_bash_has_python3(), "bash with python3 needed")
class JobScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "data").mkdir()
        fake = self.tmp / "src" / "cloudtak"
        fake.mkdir(parents=True)
        (self.tmp / "src" / "VERSION").write_text("1.0.0\n")
        # A stand-in for cloudtak/install.sh: prints the markers, records its args and the
        # token env it got, then exits with $FAKE_RC.
        (fake / "install.sh").write_text(
            '#!/bin/bash\necho "$@" > "$CROWDCAD_HOME/args"\n'
            'echo "$CROWDCAD_TAK_URL|$CROWDCAD_TAK_TOKEN|$CROWDCAD_TAK_MANAGE_TOKEN" > "$CROWDCAD_HOME/env"\n'
            'echo "==> CloudTAK 13.102.0 at /x (split layout)"\necho "==> Nothing to back up"\n'
            'echo "==> Installed web half"\necho "==> Rebuilding"\necho "==> Restarting"\necho "==> Done."\n'
            'exit "${FAKE_RC:-0}"\n', newline="\n")

    def run_job(self, rc=0, *args):
        env = {**os.environ, "CROWDCAD_HOME": str(self.tmp).replace("\\", "/"),
               "CLOUDTAK_HEALTH_URL": "http://127.0.0.1:9/", "CLOUDTAK_HEALTH_WAIT": "3", "FAKE_RC": str(rc)}
        out = subprocess.run([BASH, str(INFRATAK / "crowdcad_cloudtak_job.sh"), *args],
                             capture_output=True, text=True, env=env, timeout=60)
        return out.stdout

    def publish(self):
        (self.tmp / "data" / "config.json").write_text(json.dumps({"public_url": "https://cc-tak.example.org"}))
        (self.tmp / "data" / "secrets.json").write_text(json.dumps({"board_token": "b0ard", "manage_token": "m4n"}))

    def test_refuses_before_the_board_is_published(self):
        log = self.run_job()
        self.assertIn("==> ERROR the board isn't published yet", log)
        self.assertTrue(log.rstrip().endswith("==> EXIT 1"))

    def test_tokens_go_by_environment_and_failures_end_with_exit(self):
        self.publish()
        log = self.run_job(3, "/root/CloudTAK")
        self.assertTrue(log.rstrip().endswith("==> EXIT 3"))
        self.assertIn("==> ERROR cloudtak/install.sh failed (exit 3)", log)
        args = (self.tmp / "args").read_text().split()
        self.assertEqual(args[0], "--backup")                  # always backs up first
        self.assertEqual(args[-1], "/root/CloudTAK")
        self.assertNotIn("b0ard", " ".join(args))              # never a token on a command line
        self.assertEqual((self.tmp / "env").read_text().strip(), "https://cc-tak.example.org|b0ard|m4n")

    def test_unhealthy_cloudtak_is_a_failure(self):
        self.publish()
        log = self.run_job(0)
        self.assertIn("==> ERROR CloudTAK didn't answer", log)
        self.assertTrue(log.rstrip().endswith("==> EXIT 1"))


class _FakeProc:
    def __init__(self):
        self.done = False

    def poll(self):
        return 0 if self.done else None


@unittest.skipUnless(flask, "Flask not installed")
class ConsoleJobTest(unittest.TestCase):
    def setUp(self):
        self.hook = load_hook()
        self.addCleanup(load_hook)                              # give other tests an unpatched module
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hook.DATA_DIR = self.tmp.name
        self.hook.HOME = "/opt/crowdcad-tak"
        self.calls, self.procs = [], []
        test = self

        class FakeSubprocess:
            @staticmethod
            def run(args, **kwargs):
                test.calls.append(args)
                return subprocess.CompletedProcess(args, 0, "", "")

            @staticmethod
            def Popen(args, **kwargs):
                test.calls.append(args)
                proc = _FakeProc()
                test.procs.append(proc)
                return proc
        self.hook.subprocess = FakeSubprocess
        self.hook.shutil = type("Sh", (), {"which": staticmethod(lambda name: None)})   # no systemd: Popen path
        self.hook._job_proc["p"] = None
        self.hook._service_status = lambda fresh=False: (True, True, {"crowdcad": {"mode": "live"}, "tak": {}})
        app = flask.Flask("console")
        app.secret_key = "x"
        self.hook.attach({"app": app, "login_required": lambda f: f, "VERSION": "test"})
        self.client = app.test_client()

    def write(self, name, value):
        Path(self.tmp.name, name).write_text(json.dumps(value))

    def publish(self):
        self.write("config.json", {"public_url": "https://cc-tak.example.org"})
        self.write("secrets.json", {"board_token": "b0ard"})

    def test_page_shows_the_button(self):
        self.publish()
        page = self.client.get("/crowdcad").get_data(as_text=True)
        self.assertIn("Install CloudTAK plugin", page)
        self.assertIn('id="cc-ct-bar"', page)
        self.assertNotIn("b0ard</", page.split("CloudTAK plugin</h2>")[1])   # the card itself shows no token

    def test_unpublished_board_disables_and_refuses(self):
        page = self.client.get("/crowdcad").get_data(as_text=True)
        self.assertIn("isn't published yet", page)
        response = self.client.post("/crowdcad/cloudtak/install", data={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.calls, [])

    def test_start_then_one_job_at_a_time_then_status(self):
        self.publish()
        response = self.client.post("/crowdcad/cloudtak/install", data={"cloudtak_dir": "/root/CloudTAK/"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(len(self.calls), 1)
        command = self.calls[0][-1]
        self.assertIn("crowdcad_cloudtak_job.sh", command)
        self.assertIn("/root/CloudTAK", command)
        self.assertNotIn("b0ard", command)
        self.assertEqual(json.loads(Path(self.tmp.name, "config.json").read_text())["cloudtak_dir"], "/root/CloudTAK")
        self.assertEqual(response.get_json()["status"]["state"], "running")
        again = self.client.post("/crowdcad/cloudtak/install", data={"cloudtak_dir": "/root/CloudTAK"})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(len(self.calls), 1)                   # still only one job
        Path(self.tmp.name, "cloudtak-install.log").write_text(LOG + "==> Healthy: 401\n==> EXIT 0\n", encoding="utf-8")
        self.procs[0].done = True
        status = self.client.get("/crowdcad/cloudtak/status").get_json()
        self.assertEqual((status["state"], status["percent"]), ("done", 100))

    def test_bad_directory_and_cross_origin_are_refused(self):
        self.publish()
        for bad in ("relative/dir", "/root/../etc", "/root/Cloud TAK", "/x;rm -rf /"):
            response = self.client.post("/crowdcad/cloudtak/install", data={"cloudtak_dir": bad})
            self.assertEqual(response.status_code, 400, bad)
        response = self.client.post("/crowdcad/cloudtak/install", data={},
                                    headers={"Origin": "https://evil.example.com"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
