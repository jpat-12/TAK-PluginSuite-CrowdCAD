"""The compare-and-swap hook (infratak/pb_hooks/crowdcad_tak.pb.js) + store.py against a REAL
PocketBase with CrowdCAD's own collections and rules. Opt-in, needs Docker:

    CROWDCAD_LIVE_PB_IMAGE=crowdcad-pocketbase:v1.6.0 CROWDCAD_SRC=/opt/crowdcad-tak/crowdcad/src \\
        python -m unittest discover -s tests -p test_pb_hook_live.py

Starts a throwaway container on a free loopback port (its own temp data dir), runs CrowdCAD's
scripts/setup-pocketbase.js in node:22-alpine, then checks the hook's guarantees.
"""

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from crowdcad_tak import dispatch
from crowdcad_tak.pocketbase import PocketBase
from crowdcad_tak.store import EventStore

IMAGE = os.environ.get("CROWDCAD_LIVE_PB_IMAGE")
SRC = os.environ.get("CROWDCAD_SRC")
HOOK = Path(__file__).resolve().parents[2] / "infratak" / "pb_hooks" / "crowdcad_tak.pb.js"
SU = ("su@hooktest.example.org", "su-pass-123456")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(base, method, path, body=None, token=None):
    request = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **({"Authorization": token} if token else {})})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


@unittest.skipUnless(IMAGE and SRC and shutil.which("docker"), "set CROWDCAD_LIVE_PB_IMAGE and CROWDCAD_SRC (needs Docker)")
class HookLiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cc-hooktest-")
        hooks = Path(cls.tmp) / "pb_hooks"
        hooks.mkdir()
        shutil.copy(HOOK, hooks / HOOK.name)
        cls.port = free_port()
        cls.name = f"cc-hooktest-{cls.port}"
        subprocess.run(["docker", "run", "-d", "--rm", "--name", cls.name, "-p", f"127.0.0.1:{cls.port}:8090",
                        "-v", f"{hooks}:/pb/pb_hooks:ro", IMAGE], check=True, capture_output=True)
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.addClassCleanup(lambda: (subprocess.run(["docker", "rm", "-f", cls.name], capture_output=True),
                                     shutil.rmtree(cls.tmp, ignore_errors=True)))
        for _ in range(60):
            try:
                if http(cls.base, "GET", "/api/health")[0] == 200:
                    break
            except OSError:      # not listening yet
                pass
            time.sleep(0.5)
        subprocess.run(["docker", "exec", cls.name, "/pb/pocketbase", "superuser", "upsert", *SU, "--dir=/pb/pb_data"],
                       check=True, capture_output=True)
        env = {**os.environ, "PB_URL": cls.base, "PB_ADMIN_EMAIL": SU[0], "PB_ADMIN_PASSWORD": SU[1]}
        subprocess.run(["docker", "run", "--rm", "--network", "host", "-e", "PB_URL", "-e", "PB_ADMIN_EMAIL",
                        "-e", "PB_ADMIN_PASSWORD", "-v", f"{SRC}/scripts:/scripts:ro", "node:22-alpine",
                        "node", "/scripts/setup-pocketbase.js"], check=True, capture_output=True, env=env)
        cls.su = http(cls.base, "POST", "/api/collections/_superusers/auth-with-password",
                      {"identity": SU[0], "password": SU[1]})[1]["token"]
        cls.users = {}
        for who in ("bridge", "owner"):
            email = f"{who}@hooktest.example.org"
            record = http(cls.base, "POST", "/api/collections/users/records",
                          {"email": email, "password": "pw-12345678", "passwordConfirm": "pw-12345678", "verified": True},
                          cls.su)[1]
            cls.users[who] = (email, record["id"])

    def make_event(self, org=True, ended=False):
        record = {"name": "Hook test", "userId": self.users["owner"][1], "isOrgEvent": org, "ended": ended,
                  "status": "active", "calls": [], "postingTimes": [], "eventPosts": [], "eventEquipment": [],
                  "staff": [{"team": "Team 1", "location": "Gate A", "status": "Available", "members": ["A"]},
                            {"team": "Team 2", "location": "Gate B", "status": "Available", "members": ["B"]}],
                  "supervisor": [{"team": "Sup 1", "location": "Roaming", "status": "Available", "member": "S"}]}
        return http(self.base, "POST", "/api/collections/events/records", record, self.su)[1]["id"]

    def bridge(self):
        return PocketBase(self.base, self.users["bridge"][0], "pw-12345678")

    def test_ping_and_auth(self):
        self.assertEqual(http(self.base, "GET", "/api/crowdcad-tak/ping")[0], 200)
        eid = self.make_event()
        self.assertEqual(http(self.base, "POST", f"/api/crowdcad-tak/events/{eid}/apply",
                              {"calls": [], "_expect": {"calls": []}})[0], 401)

    def test_compare_and_swap(self):
        pb, eid = self.bridge(), self.make_event()
        pb.apply_cas(eid, {"calls": [{"id": "1"}]}, {"calls": []})
        with self.assertRaises(Exception) as caught:
            pb.apply_cas(eid, {"calls": [{"id": "2"}]}, {"calls": []})          # stale: someone wrote calls
        self.assertEqual(getattr(caught.exception, "status", None), 409)
        self.assertEqual(pb.get_record("events", eid)["calls"], [{"id": "1"}])

    def test_rules_still_apply(self):
        pb = self.bridge()
        private = self.make_event(org=False)                    # not shared, not org: REST would refuse too
        with self.assertRaises(Exception) as caught:
            pb.apply_cas(private, {"calls": []}, {"calls": []})
        self.assertIn(getattr(caught.exception, "status", None), (403, 404))
        with self.assertRaises(Exception) as caught:
            pb.apply_cas(self.make_event(), {"userId": "x"}, {"calls": []})    # protected field
        self.assertEqual(getattr(caught.exception, "status", None), 400)
        with self.assertRaises(Exception) as caught:
            pb.apply_cas(self.make_event(ended=True), {"calls": []}, {"calls": []})
        self.assertEqual(getattr(caught.exception, "status", None), 409)

    def test_store_reapplies_on_top_of_a_concurrent_change(self):
        pb, eid = self.bridge(), self.make_event()
        clock = dispatch.Clock(1795100000000, "UTC")
        store = EventStore(pb, log=lambda line: None)
        _, call_id = store.apply(eid, lambda ev: dispatch.new_call(ev, {"location": "Gate A", "chiefComplaint": "Fall"},
                                                                  "jon", clock))
        sneaky = {"n": 0}

        def assign_after_a_crowdcad_write(event):
            if sneaky["n"] == 0:      # a CrowdCAD dispatcher saves between our read and our write
                sneaky["n"] += 1
                staff = [dict(s, status="On Break") if s["team"] == "Team 2" else s for s in event["staff"]]
                http(self.base, "PATCH", f"/api/collections/events/records/{eid}", {"staff": staff}, self.su)
            return dispatch.assign(event, call_id, "Team 1", "jon", clock)

        store.apply(eid, assign_after_a_crowdcad_write)
        event = pb.get_record("events", eid)
        staff = {s["team"]: s for s in event["staff"]}
        self.assertEqual(staff["Team 1"]["status"], "En Route")          # ours landed…
        self.assertEqual(staff["Team 2"]["status"], "On Break")          # …and theirs survived
        self.assertEqual(event["calls"][0]["assignedTeam"], ["Team 1"])
        self.assertEqual(sneaky["n"], 1)


if __name__ == "__main__":
    unittest.main()
