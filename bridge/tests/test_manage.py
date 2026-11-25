"""manage.py + the /api/v1/manage/* endpoints: events created from TAK contacts (CloudTAK's New
Event form) have exactly CrowdCAD's own shape, each unit is bound to its device, and the write
API is locked to the manage token."""

import datetime
import json
import unittest
import urllib.error
import urllib.request

from crowdcad_tak import api, board, config, manage, mapping
from crowdcad_tak.bridge import Publisher

from test_mapping import EID, demo

NOW = datetime.datetime(2026, 11, 19, 15, 30, 0, 123000, tzinfo=datetime.timezone.utc)
UNITS = [
    {"name": "Medic 1", "kind": "team", "uid": "ANDROID-aaa111", "callsign": "MEDIC1"},
    {"name": "Sup Ops", "kind": "supervisor", "uid": "S-1-5-21-42", "callsign": "OPS"},
]


def venue():
    return demo()["venue"]


class BuildEventTest(unittest.TestCase):
    def build(self, **form):
        return manage.build_event({"name": "Homecoming", "date": "2026-11-21", "units": UNITS, **form},
                                  venue(), "bridgeuser00001", NOW)

    def test_same_shape_as_crowdcads_create_page(self):
        record = self.build()
        self.assertEqual((record["status"], record["isOrgEvent"], record["userId"]), ("active", True, "bridgeuser00001"))
        self.assertEqual(record["date"], "2026-11-21T00:00:00.000Z")       # new Date('YYYY-MM-DD').toISOString()
        self.assertEqual(record["createdAt"], "2026-11-19T15:30:00.123Z")
        self.assertEqual(record["venue"]["id"], venue()["id"])
        for key in ("calls", "postingTimes", "eventPosts", "eventEquipment"):
            self.assertEqual(record[key], [], key)
        self.assertEqual(record["staff"], [{"team": "Medic 1", "location": "No Post", "status": "On Break",
                                            "members": ["MEDIC1"], "takUid": "ANDROID-aaa111"}])
        self.assertEqual(record["supervisor"], [{"team": "Sup Ops", "location": "Roaming", "status": "On Break",
                                                 "member": "OPS", "takUid": "S-1-5-21-42"}])

    def test_clinics_and_dispatch_zones_come_from_the_venue(self):
        v = venue()
        v["layers"][0]["posts"].append({"name": "Aid Tent", "x": 10, "y": 10, "isClinic": True, "clinicId": "c-1"})
        v["layers"][0].setdefault("zones", []).append({"id": "z-9", "name": "North", "isDispatchZone": True,
                                                       "points": []})
        record = manage.build_event({"name": "E", "units": UNITS}, v, "u", NOW)
        self.assertIn({"id": "c-1", "name": "Aid Tent"}, record["clinics"])
        self.assertIn({"id": "z-9", "name": "North"}, record["dispatchZones"])

    def test_legacy_venue_gets_one_layer(self):
        record = manage.build_event({"name": "E", "units": UNITS}, {"id": "v1", "name": "Old", "posts": ["Gate A"]},
                                    "u", NOW)
        self.assertEqual(record["venue"]["layers"][0]["posts"], ["Gate A"])
        self.assertEqual(record["venue"]["layers"][0]["name"], "Main Floor")

    def test_bad_input_is_refused_before_anything_is_written(self):
        bad = [
            {"units": []},                                                               # nobody picked
            {"units": [dict(UNITS[0], uid='x"/><event')]},                               # CoT injection
            {"units": [dict(UNITS[0], kind="admin")]},
            {"units": [UNITS[0], dict(UNITS[1], name="medic 1")]},                       # CrowdCAD names unique
            {"units": [UNITS[0], dict(UNITS[1], uid=UNITS[0]["uid"])]},                  # same device twice
            {"units": [dict(UNITS[0], name="   ")]},
            {"name": ""},
            {"date": "2026-02-30"},
            {"date": "tomorrow"},
            {"units": "Medic 1"},
        ]
        for patch in bad:
            with self.assertRaises(manage.ManageError, msg=patch):
                self.build(**patch)

    def test_names_are_single_line(self):
        record = self.build(units=[dict(UNITS[0], name="Medic\n1\t ", callsign=" MEDIC1 ")])
        self.assertEqual((record["staff"][0]["team"], record["staff"][0]["members"]), ("Medic 1", ["MEDIC1"]))

    def test_venue_summary(self):
        summary = manage.venue_summary(venue())
        self.assertTrue(summary["mapped"])                     # Field Level has geoBounds
        self.assertGreater(summary["posts"], 0)
        self.assertFalse(manage.venue_summary({"id": "v", "name": "Plain", "layers": [{"posts": []}]})["mapped"])


class DeviceBindingTest(unittest.TestCase):
    """A unit created from a TAK contact is carried by that device, per event."""

    def event(self):
        event = demo()
        event["staff"][0]["takUid"] = "ANDROID-team1"           # Team 1, assigned to CC-007
        return event

    def test_unit_is_its_device(self):
        items, _ = mapping.build(self.event(), config.DEFAULTS)
        units = [i for i in items.values() if i.kind == "unit"]
        self.assertNotIn("Team 1", [u.fields["callsign"] for u in units])           # no bridge marker: the PLI is it
        incident = next(i for i in items.values() if i.kind == "incident" and i.fields["id"] == "CC-007")
        self.assertEqual(incident.fields["assigned"], "ANDROID-team1")              # alert goes to that phone
        teams = {t["name"]: t for t in mapping.device_teams(self.event(), config.DEFAULTS)}
        self.assertEqual(teams["Team 1"]["uid"], "ANDROID-team1")

    def test_event_binding_beats_console_mapping_and_bad_uids_are_ignored(self):
        cfg = {**config.DEFAULTS, "team_uids": {"Team 1": "ANDROID-console"}}
        self.assertEqual(mapping.unit_uids(self.event(), cfg)["Team 1"], "ANDROID-team1")
        event = self.event()
        event["staff"][0]["takUid"] = "bad uid\"/>"
        self.assertEqual(mapping.unit_uids(event, cfg)["Team 1"], "ANDROID-console")

    def test_board_lists_the_device_and_endable_only_for_own_events(self):
        pub = Publisher(dict(config.DEFAULTS), lambda xml: None, lambda: 0)
        event = self.event()
        event["userId"] = "bridgeuser00001"
        pub.apply(event)
        data = board.build(pub, 0, own_user="bridgeuser00001")
        units = {u["callsign"]: u for u in data["events"][0]["units"]}
        self.assertEqual((units["Team 1"]["uid"], units["Team 1"]["device"]), ("ANDROID-team1", True))
        self.assertTrue(data["events"][0]["endable"])
        self.assertFalse(board.build(pub, 0, own_user="someoneelse0001")["events"][0]["endable"])
        self.assertFalse(board.build(pub, 0)["events"][0]["endable"])


class FakePB:
    def __init__(self):
        self.user_id = "bridgeuser00001"
        self.created, self.updated = [], []
        self.records = {"venues": {"venue000000001": venue()},
                        "events": {EID: {**demo(), "userId": "otheruser000001"},
                                   "mine00000000001": {"name": "Mine", "userId": "bridgeuser00001"}}}

    def ensure_auth(self):
        return "token"

    def list_venues(self):
        return list(self.records["venues"].values())

    def get_record(self, collection, rid):
        if rid not in self.records[collection]:
            raise RuntimeError("404")
        return json.loads(json.dumps(self.records[collection][rid]))   # a copy, like a real GET

    def create_event(self, record):
        self.created.append(record)
        return {"id": "new000000000001", **record}

    def update_event(self, rid, patch):
        self.updated.append((rid, patch))
        return {}

    def hook_available(self):
        return True

    def apply_cas(self, rid, patch, expect):
        record = self.records["events"][rid]
        assert all(record.get(k) == v for k, v in expect.items()), "stale write"
        record.update(json.loads(json.dumps(patch)))
        self.updated.append((rid, patch))
        return {"ok": True}


class ManageApiTest(unittest.TestCase):
    TOKEN, MANAGE = "board-token", "manage-token"

    def setUp(self):
        self.pb = FakePB()
        self.lines = []
        manager = manage.Manager(self.pb, "https://crowdcad.example.org", log=self.lines.append)
        self.server = api.make_server("127.0.0.1:0", lambda: {}, lambda: {"api": 1, "events": []}, self.TOKEN,
                                      ("https://tak.example.org",), manager=manager, manage_token=self.MANAGE)
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def call(self, path, body=None, token=MANAGE, headers=None):
        request = urllib.request.Request(self.base + path, method="POST" if body is not None else "GET",
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Authorization": f"Bearer {token}", "Origin": "https://tak.example.org",
                                                  "X-TAK-User": "jon", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read()), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}"), dict(error.headers)

    def test_only_the_manage_token_works(self):
        self.assertEqual(self.call("/api/v1/manage/venues", token="")[0], 401)
        self.assertEqual(self.call("/api/v1/manage/venues", token=self.TOKEN)[0], 401)   # board token ≠ manage
        status, data, headers = self.call("/api/v1/manage/venues")
        self.assertEqual(status, 200)
        self.assertEqual(data["venues"][0]["name"], venue()["name"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)                         # never for browsers

    def test_create_event(self):
        status, data, _ = self.call("/api/v1/manage/events",
                                    {"name": "Homecoming", "venueId": "venue000000001", "units": UNITS})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["dispatchUrl"], "https://crowdcad.example.org/events/new000000000001/dispatch")
        record = self.pb.created[0]
        self.assertEqual((record["userId"], record["isOrgEvent"]), ("bridgeuser00001", True))
        self.assertTrue(any("created from TAK by jon" in line for line in self.lines))

    def test_create_errors_are_clean(self):
        self.assertEqual(self.call("/api/v1/manage/events", {"name": "X", "venueId": "nope00000000001",
                                                             "units": UNITS})[0], 404)
        status, data, _ = self.call("/api/v1/manage/events", {"name": "X", "venueId": "venue000000001", "units": []})
        self.assertEqual(status, 400)
        self.assertIn("pick at least one", data["error"])
        self.assertEqual(self.pb.created, [])

    def test_end_only_own_events(self):
        self.assertEqual(self.call(f"/api/v1/manage/events/{EID}/end", {})[0], 403)     # made in CrowdCAD
        status, data, _ = self.call("/api/v1/manage/events/mine00000000001/end", {})
        self.assertEqual((status, data["ended"]), (200, True))
        self.assertEqual(self.pb.updated[0][0], "mine00000000001")
        self.assertEqual(set(self.pb.updated[0][1]), {"ended", "endedAt"})              # CrowdCAD's handleEndEvent
        self.assertEqual(self.call("/api/v1/manage/events/BAD/end", {})[0], 404)

    def test_native_dispatch_over_http(self):
        base = f"/api/v1/manage/events/{EID}"
        self.pb.records["events"][EID]["isOrgEvent"] = True
        status, data, _ = self.call(base + "/calls", {"location": "Sec 104", "chiefComplaint": "Dizzy"})
        self.assertEqual(status, 200, data)
        call_id = data["callId"]
        self.assertEqual(self.call(f"{base}/calls/{call_id}/assign", {"unit": "Team 2"})[0], 200)
        self.assertEqual(self.call(f"{base}/calls/{call_id}/status", {"unit": "Team 2", "status": "On Scene"})[0], 200)
        record = self.pb.records["events"][EID]
        call = next(c for c in record["calls"] if c["id"] == call_id)
        self.assertEqual((call["status"], call["assignedTeam"]), ("On Scene", ["Team 2"]))
        self.assertTrue(all("(via CloudTAK: jon)" in entry["message"] for entry in call["log"]))
        self.assertEqual(self.call(f"{base}/calls/{call_id}/status", {"unit": "Team 2", "status": "Delivered"})[0], 200)
        self.assertEqual(self.call(base + "/units/status", {"unit": "Team 2", "status": "Available"})[0], 200)
        self.assertEqual(self.call(base + "/units/post", {"unit": "Team 2", "post": "Gate B"})[0], 200)
        self.assertTrue(any("Team 2 assigned to call" in line and "by jon" in line for line in self.lines))

    def test_dispatch_view_has_no_patient_data(self):
        record = self.pb.records["events"][EID]
        record["calls"][0].update({"age": "34", "gender": "F", "notes": "John Smith, DOB 1990"})
        status, view, _ = self.call(f"/api/v1/manage/events/{EID}/dispatch")
        self.assertEqual(status, 200)
        wire = json.dumps(view)
        for secret in ("John", "Smith", "DOB", '"age"', '"gender"', '"notes"', '"log"', '"members"'):
            self.assertNotIn(secret, wire)
        self.assertIn("Team 1", [u["name"] for u in view["units"]])
        self.assertIn("Delivered", view["statuses"]["onCall"])

    def test_view_says_when_the_bridge_cant_dispatch(self):
        status, view, _ = self.call(f"/api/v1/manage/events/{EID}/dispatch")      # made in CrowdCAD, not org
        self.assertEqual((status, view["canDispatch"]), (200, False))
        self.assertIn("org event", view["whyNot"])
        self.pb.records["events"][EID]["isOrgEvent"] = True
        self.assertTrue(self.call(f"/api/v1/manage/events/{EID}/dispatch")[1]["canDispatch"])
        self.assertTrue(manage.can_dispatch({"userId": "me"}, "me", None)[0])
        self.assertTrue(manage.can_dispatch({"sharedWith": ["b@x"]}, "me", "b@x")[0])

    def test_dispatch_errors(self):
        base = f"/api/v1/manage/events/{EID}"
        status, data, _ = self.call(base + "/calls/nope/assign", {"unit": "Team 1"})
        self.assertEqual((status, "no call" in data["error"]), (404, True))
        self.assertEqual(self.call(base + "/units/status", {"unit": "Team 1", "status": "Bogus"})[0], 400)
        self.assertEqual(self.call(base + "/calls", {"location": "x"}, token=self.TOKEN)[0], 401)
        self.pb.records["events"][EID]["ended"] = True
        self.assertEqual(self.call(base + "/calls", {"location": "x"})[0], 409)

    def test_disabled_without_a_manage_token(self):
        server = api.make_server("127.0.0.1:0", lambda: {}, lambda: None, self.TOKEN, (),
                                 manager=manage.Manager(self.pb), manage_token="")
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))
        self.base = f"http://127.0.0.1:{server.server_address[1]}"
        self.assertEqual(self.call("/api/v1/manage/venues", token="")[0], 404)


if __name__ == "__main__":
    unittest.main()
