"""The web clients' board (board.py) and the bridge HTTP server (api.py) — the docs/API.md
contract the CloudTAK and WebTAK plugins build against."""

import json
import unittest
import urllib.error
import urllib.request

from crowdcad_tak import api, board, config
from crowdcad_tak.bridge import Publisher

from test_mapping import EID, demo

TOKEN = "t0ken-for-tests"


def published(**overrides):
    pub = Publisher({**config.DEFAULTS, **overrides}, lambda xml: None, lambda: 1794701000000)
    pub.apply(demo())
    return pub


class BoardTest(unittest.TestCase):
    def test_board_shape_and_order(self):
        data = board.build(published(), 1794701000000, {"crowdcad": "live", "tak": True})
        self.assertEqual((data["api"], data["bridge"]["crowdcad"]), (1, "live"))
        event = data["events"][0]
        self.assertEqual((event["id"], event["name"]), (EID, "Demo Football Game"))
        self.assertEqual([c["id"] for c in event["calls"]], ["CC-007", "CC-008", "CC-009"])   # priority 1 first
        unplaced = event["calls"][2]                                    # still listed, just not on the map
        self.assertEqual((unplaced["placed"], unplaced["lat"], unplaced["location"]),
                         (False, None, "Row 22 by the hot dog stand"))
        self.assertTrue(event["calls"][0]["placed"])
        self.assertIn("date", event)
        c1 = event["calls"][0]
        self.assertEqual(c1["assigned"], [{"uid": f"crowdcad-{EID}-team-team-1", "callsign": "Team 1"}])
        self.assertEqual((c1["status"], c1["location"], c1["created"]), ("ONSC", "Sec 104", 1794700800000))
        # Team 3 has no placeable post: listed (placed=false), not dropped
        self.assertEqual([u["callsign"] for u in event["units"]], ["Team 1", "Team 2", "Team 3", "Supervisor 1"])
        self.assertFalse(next(u for u in event["units"] if u["callsign"] == "Team 3")["placed"])
        self.assertEqual(event["units"][0]["incident"], "CC-007")
        self.assertEqual(len(event["unplaced"]), 2)

    def test_device_teams_listed_with_dispatch_status(self):
        data = board.build(published(team_uids={"Team 1": "ANDROID-abc", "Not In This Event": "ANDROID-zzz"}), 0)
        units = {u["callsign"]: u for u in data["events"][0]["units"]}
        self.assertNotIn("Not In This Event", units)
        self.assertEqual((units["Team 1"]["uid"], units["Team 1"]["device"], units["Team 1"]["status"],
                          units["Team 1"]["incident"]), ("ANDROID-abc", True, "ONSC", "CC-007"))
        self.assertEqual(data["events"][0]["calls"][0]["assigned"], [{"uid": "ANDROID-abc", "callsign": "Team 1"}])

    def test_dispatch_url_only_when_the_crowdcad_app_is_known(self):
        data = board.build(published(), 0)
        self.assertIsNone(data["crowdcadUrl"])
        self.assertIsNone(data["events"][0]["dispatchUrl"])            # clients hide the Dispatch button
        data = board.build(published(crowdcad_app_url="https://crowdcad.example.org/"), 0)
        self.assertEqual(data["crowdcadUrl"], "https://crowdcad.example.org")
        self.assertEqual(data["events"][0]["dispatchUrl"], f"https://crowdcad.example.org/events/{EID}/dispatch")

    def test_closed_calls_leave_the_board(self):
        pub = published()
        event = demo()
        event["calls"][0]["status"] = "Resolved"
        pub.apply(event)
        self.assertEqual([c["id"] for c in board.build(pub, 0)["events"][0]["calls"]], ["CC-008", "CC-009"])

    def test_no_patient_or_member_data(self):
        wire = json.dumps(board.build(published(), 0))
        for secret in ("John", "Smith", "DOB", "Alex Doe", "Jamie Poe", "Pat Quinn", '"age"', '"gender"', '"notes"'):
            self.assertNotIn(secret, wire)


class ApiTest(unittest.TestCase):
    def serve(self, source=lambda: {"api": 1, "events": []}, token=TOKEN, origins=("https://tak.example.org",)):
        server = api.make_server("127.0.0.1:0", lambda: {"version": "t", "secret": "status"}, source, token, origins)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def get(self, url, method="GET", **headers):
        request = urllib.request.Request(url, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body = response.read()
                return response.status, dict(response.headers), json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), json.loads(error.read() or b"null")

    def test_info_is_open(self):
        code, _, body = self.get(self.serve() + "/api/v1/info")
        self.assertEqual((code, body["api"], body["name"]), (200, 1, "CrowdCAD for TAK"))

    def test_board_needs_the_token(self):
        base = self.serve()
        self.assertEqual(self.get(base + "/api/v1/board")[0], 401)
        self.assertEqual(self.get(base + "/api/v1/board", Authorization="Bearer wrong")[0], 401)
        code, headers, body = self.get(base + "/api/v1/board", Authorization=f"Bearer {TOKEN}")
        self.assertEqual((code, body["api"], headers["Cache-Control"]), (200, 1, "no-store"))

    def test_empty_token_disables_board(self):
        self.assertEqual(self.get(self.serve(token="") + "/api/v1/board", Authorization="Bearer ")[0], 401)

    def test_unconfigured_bridge_is_503(self):
        base = self.serve(source=lambda: None)
        self.assertEqual(self.get(base + "/api/v1/board", Authorization=f"Bearer {TOKEN}")[0], 503)

    def test_status_never_through_a_proxy(self):
        base = self.serve()
        self.assertEqual(self.get(base + "/status")[2]["secret"], "status")
        self.assertEqual(self.get(base + "/status", **{"X-Forwarded-For": "203.0.113.9"})[0], 404)

    def test_cors_only_for_listed_origins(self):
        base = self.serve()
        _, headers, _ = self.get(base + "/api/v1/board", Origin="https://tak.example.org", Authorization=f"Bearer {TOKEN}")
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "https://tak.example.org")
        _, headers, _ = self.get(base + "/api/v1/board", Origin="https://evil.example.com", Authorization=f"Bearer {TOKEN}")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        code, headers, _ = self.get(base + "/api/v1/board", method="OPTIONS", Origin="https://tak.example.org",
                                    **{"Access-Control-Request-Headers": "authorization"})
        self.assertEqual((code, headers["Access-Control-Allow-Headers"]), (204, "Authorization"))


if __name__ == "__main__":
    unittest.main()
