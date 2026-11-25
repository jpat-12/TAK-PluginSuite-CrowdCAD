"""TAK call details (calldetails.py): a dispatcher's point goes into CrowdCAD's own `location`,
the rest into one [TAK] line in `notes`; the TAK side reads them back from the bridge's store,
never from notes. Plus Add Team / Add Supervisor (CrowdCAD's own handlers) and the board fields
the CloudTAK dispatcher builds on."""

import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from crowdcad_tak import board, calldetails, config, cot, dispatch, fieldstatus, manage, mapping
from crowdcad_tak.bridge import Publisher
from crowdcad_tak.dispatch import Clock, DispatchError

from test_manage import FakePB
from test_mapping import EID, demo

NOW = 1794701000000


def render(item):
    return cot.render(item, NOW, item.created_ms or NOW, NOW, 300)


class CleanTest(unittest.TestCase):
    def test_parse_coords(self):
        self.assertEqual(calldetails.parse_coords("39.18200, -86.52550"), (39.182, -86.5255))
        self.assertEqual(calldetails.parse_coords(" 39.1,-86.5 "), (39.1, -86.5))
        for text in ("Sec 104", "0, 0", "91.0, 10", "39.1", None, "39.1, -86.5, 3"):
            self.assertIsNone(calldetails.parse_coords(text), text)

    def test_clean_validates_every_field(self):
        d = calldetails.clean({"lat": "39.1825", "lon": -86.5251, "floor": "3", "source": "map",
                               "w3w": "///Filled.Count.Soap", "description": "  Sec 104\nRow 22 "})
        self.assertEqual(d, {"lat": 39.1825, "lon": -86.5251, "floor": 3, "source": "map", "post": None,
                             "w3w": "filled.count.soap", "description": "Sec 104 Row 22"})
        self.assertEqual(calldetails.clean({"floor": -1})["floor"], -1)
        self.assertIsNone(calldetails.clean({"floor": 0})["floor"])
        for bad in ({"lat": 1}, {"lat": 0, "lon": 0}, {"lat": 95, "lon": 1}, {"floor": 9},
                    {"floor": "x"}, {"source": "gps"}, {"w3w": "two.words"}, {"lat": "a", "lon": "b"}):
            with self.assertRaises(DispatchError, msg=bad):
                calldetails.clean(bad)

    def test_source_is_dropped_without_a_point(self):
        self.assertIsNone(calldetails.clean({"source": "map"})["source"])
        self.assertEqual(calldetails.clean({"post": "Gate A"})["source"], "post")
        with self.assertRaises(DispatchError):
            calldetails.clean({"post": "Gate A", "lat": 39.1, "lon": -86.5})


class NotesTest(unittest.TestCase):
    def test_block_line(self):
        self.assertEqual(calldetails.block({"description": "Sec 104 Row 22", "floor": 3, "w3w": "a.b.c",
                                            "source": "map"}),
                         "[TAK] Sec 104 Row 22 · Floor 3 · ///a.b.c · picked on map")
        self.assertEqual(calldetails.block({"floor": -1}), "[TAK] Basement")
        self.assertEqual(calldetails.block({}), "")

    def test_only_the_tak_line_is_replaced(self):
        notes = "Pt alert and oriented\n[TAK] Floor 2"
        self.assertEqual(calldetails.notes_with(notes, "[TAK] Floor 3"), "Pt alert and oriented\n[TAK] Floor 3")
        self.assertEqual(calldetails.notes_with(notes, ""), "Pt alert and oriented")
        self.assertEqual(calldetails.notes_with(None, "[TAK] Floor 3"), "[TAK] Floor 3")
        self.assertEqual(calldetails.notes_with("[TAKE] not ours", "[TAK] F"), "[TAKE] not ours\n[TAK] F")


class ApplyTest(unittest.TestCase):
    CLOCK = Clock(NOW, "UTC")

    def call(self, patch, cid):
        return next(c for c in patch["calls"] if c["id"] == cid)

    def test_point_goes_into_location_and_the_rest_into_notes(self):
        details = calldetails.clean({"lat": 39.18205, "lon": -86.52541, "source": "map", "floor": 2,
                                     "description": "Sec 104 Row 22"})
        patch = calldetails.apply(demo(), "c1", details, "CloudTAK: jon", self.CLOCK)
        call = self.call(patch, "c1")
        self.assertEqual(call["location"], "39.18205, -86.52541")
        self.assertEqual(call["notes"], "Patient John Smith, DOB 1/2/1970\n[TAK] Sec 104 Row 22 · Floor 2 · picked on map")
        self.assertIn("TAK details: location 39.18205, -86.52541", call["log"][-1]["message"])
        self.assertIn("(via CloudTAK: jon)", call["log"][-1]["message"])
        self.assertEqual(set(patch), {"calls"})          # nothing else in the record is touched

    def test_post_replaces_a_point(self):
        ev = demo()
        ev["calls"][1]["location"] = "39.18000, -86.52500"
        patch = calldetails.apply(ev, "c2", calldetails.clean({"post": "Sec 104"}), None, self.CLOCK)
        self.assertEqual(self.call(patch, "c2")["location"], "Sec 104")
        self.assertEqual(self.call(patch, "c2")["notes"], "[TAK] at post")

    def test_no_point_keeps_the_location(self):
        patch = calldetails.apply(demo(), "c2", calldetails.clean({"floor": 4}), None, self.CLOCK)
        self.assertEqual(self.call(patch, "c2")["location"], "Gate A")
        self.assertEqual(self.call(patch, "c2")["notes"], "[TAK] Floor 4")

    def test_unchanged_is_no_write(self):
        ev = demo()
        details = calldetails.clean({"floor": 4})
        ev.update(calldetails.apply(ev, "c2", details, None, self.CLOCK))
        self.assertEqual(calldetails.apply(ev, "c2", details, None, self.CLOCK), {})

    def test_closed_call_refused(self):
        with self.assertRaises(DispatchError):
            calldetails.apply(demo(), "c3", calldetails.clean({"floor": 1}), None, self.CLOCK)


class MappingTest(unittest.TestCase):
    def build(self, event, details=None):
        return mapping.build(event, dict(config.DEFAULTS), details)

    def test_coordinate_location_is_placed(self):
        ev = demo()
        ev["calls"][3]["location"] = "39.18100, -86.52600"         # c4 was free text: unplaced
        items, unplaced = self.build(ev, {"c4": {"floor": 3, "w3w": "a.b.c", "description": "Row 22", "source": "map"}})
        item = items[f"crowdcad-{EID}-call-c4"]
        self.assertEqual((item.lat, item.lon), (39.181, -86.526))
        self.assertNotIn("009 · Laceration", [u.label for u in unplaced])
        root = ET.fromstring(render(item))
        inc = root.find("detail/__iucad_incident")
        self.assertEqual((inc.get("floor"), inc.get("w3w"), inc.get("location")), ("3", "a.b.c", "Row 22"))
        self.assertEqual(root.find("detail/contact").get("callsign"), "009 · Laceration · F3")
        self.assertEqual(root.find("point").get("ce"), "15.0")
        self.assertEqual(item.meta["positionFrom"], "coords")

    def test_map_centre_is_an_estimate(self):
        ev = demo()
        ev["calls"][3]["location"] = "39.18100, -86.52600"
        items, _ = self.build(ev, {"c4": {"source": "centre"}})
        item = items[f"crowdcad-{EID}-call-c4"]
        self.assertEqual(item.meta["positionFrom"], "estimate")
        self.assertEqual(ET.fromstring(render(item)).find("point").get("ce"), "75.0")

    def test_post_calls_say_how_good_their_point_is(self):
        items, _ = self.build(demo())
        root = ET.fromstring(render(items[f"crowdcad-{EID}-call-c1"]))
        self.assertEqual(root.find("point").get("ce"), "20.0")
        self.assertIsNone(root.find("detail/__iucad_incident").get("floor"))

    def test_notes_never_reach_the_wire_even_after_tak_details(self):
        ev = demo()
        patch = calldetails.apply(ev, "c1", calldetails.clean({"floor": 2, "description": "Sec 104"}), None,
                                  Clock(NOW, "UTC"))
        ev.update(patch)
        items, _ = self.build(ev, {"c1": {"floor": 2, "description": "Sec 104"}})
        wire = "\n".join(render(i) for i in items.values())
        for secret in ("John", "Smith", "DOB", "[TAK]", 'notes="'):
            self.assertNotIn(secret, wire)


class StoreTest(unittest.TestCase):
    def test_persists_and_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "call_details.json")
            store = calldetails.CallDetails(path)
            previous = store.put(EID, "c1", {"floor": 2, "w3w": None, "post": "Gate A"})
            self.assertIsNone(previous)
            self.assertEqual(calldetails.CallDetails(path).get(EID, "c1"), {"floor": 2})
            store.restore(EID, "c1", previous)
            self.assertIsNone(calldetails.CallDetails(path).get(EID, "c1"))

    def test_failed_save_changes_nothing_and_says_so(self):
        store = calldetails.CallDetails()
        store.put(EID, "c2", {"floor": 2})

        def broken(data):
            raise OSError(30, "Read-only file system", "/opt/crowdcad-tak/data/call_details.json.tmp")
        store._save = broken
        with self.assertRaises(OSError):
            store.put(EID, "c2", {"floor": 5})
        self.assertEqual(store.get(EID, "c2"), {"floor": 2})
        pb = FakePB()
        pb.records["events"][EID]["isOrgEvent"] = True
        manager = manage.Manager(pb, log=lambda line: None, details=store)
        with self.assertRaises(manage.ManageError) as error:
            manager.call_details(EID, "c2", {"floor": 5}, "jon")
        self.assertIn("nothing was written to CrowdCAD", str(error.exception))
        self.assertEqual(pb.updated, [])

    def test_corrupt_file_starts_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "call_details.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(calldetails.CallDetails(str(path)).for_event(EID), {})
            self.assertTrue(Path(str(path) + ".bad").exists())


class ManagerTest(unittest.TestCase):
    def setUp(self):
        self.pb = FakePB()
        self.pb.records["events"][EID]["isOrgEvent"] = True
        self.store = calldetails.CallDetails()
        self.manager = manage.Manager(self.pb, log=lambda line: None, timezone="UTC", details=self.store)

    def record(self):
        return self.pb.records["events"][EID]

    def test_add_call_with_a_point_writes_location_notes_and_store_together(self):
        result = self.manager.new_call(EID, {"location": "", "chiefComplaint": "Fall", "priority": True,
                                             "details": {"lat": 39.18, "lon": -86.525, "source": "map",
                                                         "floor": 1, "description": "Gate 3 ramp"}}, "jon")
        call = next(c for c in self.record()["calls"] if c["id"] == result["callId"])
        self.assertEqual(call["location"], "39.18000, -86.52500")
        self.assertEqual(call["notes"], "[TAK] Gate 3 ramp · Floor 1 · picked on map")
        self.assertEqual(len(self.pb.updated), 1)                    # one write
        self.assertEqual(self.store.get(EID, result["callId"])["floor"], 1)

    def test_set_details_on_an_open_call(self):
        self.manager.call_details(EID, "c2", {"floor": 5}, "jon")
        self.assertTrue(self.record()["calls"][1]["notes"].endswith("[TAK] Floor 5"))
        self.assertEqual(self.store.get(EID, "c2"), {"floor": 5})

    def test_refused_write_leaves_the_store_as_it_was(self):
        self.store.put(EID, "c3", {"floor": 2})
        with self.assertRaises(manage.ManageError):
            self.manager.call_details(EID, "c3", {"floor": 7}, "jon")     # c3 is closed
        self.assertEqual(self.store.get(EID, "c3"), {"floor": 2})

    def test_view_carries_store_details_and_coordinate_positions(self):
        self.record()["calls"][1]["location"] = "39.18000, -86.52500"
        self.store.put(EID, "c2", {"floor": 3})
        view = self.manager.view(EID)
        c2 = next(c for c in view["calls"] if c["id"] == "c2")
        self.assertEqual((c2["lat"], c2["lon"], c2["details"]), (39.18, -86.525, {"floor": 3}))
        self.assertFalse(view["w3w"])
        self.assertNotIn("notes", json.dumps(view))

    def test_w3w_needs_a_key_and_never_leaks_it(self):
        with self.assertRaises(manage.ManageError) as no_key:
            self.manager.w3w({"words": ["a.b.c"]})
        self.assertEqual(no_key.exception.status, 404)
        seen = []

        def urlopen(url, timeout):
            seen.append(url)
            return io.BytesIO(json.dumps({"words": "filled.count.soap", "nearestPlace": "Bloomington",
                                          "coordinates": {"lat": 39.18, "lng": -86.52}}).encode())
        keyed = manage.Manager(self.pb, w3w_key="SECRETKEY", urlopen=urlopen)
        self.assertEqual(keyed.w3w({"lat": ["39.18"], "lon": ["-86.52"]}),
                         {"words": "filled.count.soap", "lat": 39.18, "lon": -86.52, "nearestPlace": "Bloomington"})
        self.assertIn("convert-to-3wa", seen[0])

        def broken(url, timeout):
            raise OSError(f"failed {url}")
        with self.assertRaises(manage.ManageError) as error:
            manage.Manager(self.pb, w3w_key="SECRETKEY", urlopen=broken).w3w({"words": ["a.b.c"]})
        self.assertNotIn("SECRETKEY", str(error.exception))


class AddUnitsTest(unittest.TestCase):
    CLOCK = Clock(NOW, "UTC")

    def test_add_team_is_crowdcads_shape(self):
        patch = dispatch.add_team(demo(), {"name": "Team 4", "takUid": "ANDROID-abc",
                                           "members": [{"name": "Lee", "cert": "EMT", "lead": True},
                                                       {"name": "", "cert": "EMR"}]}, "CloudTAK: jon", self.CLOCK)
        team = patch["staff"][-1]
        self.assertEqual({k: team[k] for k in ("team", "members", "status", "location", "takUid")},
                         {"team": "Team 4", "members": ["Lee [EMT] (Lead)"], "status": "Available", "location": "",
                          "takUid": "ANDROID-abc"})
        self.assertEqual(team["log"][0]["message"], "Team created (via CloudTAK: jon)")

    def test_add_supervisor_is_crowdcads_shape(self):
        patch = dispatch.add_supervisor(demo(), {"callSign": "Sup 2", "cert": "Paramedic"}, None, self.CLOCK)
        sup = patch["supervisor"][-1]
        self.assertEqual((sup["team"], sup["member"], sup["status"], sup["location"], sup["originalPost"]),
                         ("Sup 2", "Supervisor [Paramedic]", "Available", "Roaming", "Roaming"))

    def test_duplicate_names_refused_across_teams_and_supervisors(self):
        for form, fn in (({"name": "team 1"}, dispatch.add_team), ({"name": "Supervisor 1"}, dispatch.add_team),
                         ({"callSign": "TEAM 2", "cert": "EMT"}, dispatch.add_supervisor)):
            with self.assertRaises(DispatchError):
                fn(demo(), form, None, self.CLOCK)
        with self.assertRaises(DispatchError):
            dispatch.add_supervisor(demo(), {"callSign": "Sup 9"}, None, self.CLOCK)   # certification required
        with self.assertRaises(DispatchError):
            dispatch.add_team(demo(), {"name": "T9", "takUid": "bad uid"}, None, self.CLOCK)


class BoardTest(unittest.TestCase):
    def test_board_has_dispatch_fields_and_device_positions(self):
        cfg = {**config.DEFAULTS, "team_uids": {"Team 3": "ANDROID-t3"}}
        ev = demo()
        ev["calls"][1]["location"] = "39.18000, -86.52500"
        store = calldetails.CallDetails()
        store.put(EID, "c2", {"floor": 2, "w3w": "a.b.c"})
        pub = Publisher(cfg, lambda xml: None, clock_ms=lambda: NOW, details=store)
        pub.apply(ev)
        data = board.build(pub, NOW, positions={"ANDROID-t3": (39.1801, -86.5251)})
        event = data["events"][0]
        c2 = next(c for c in event["calls"] if c["callId"] == "c2")
        self.assertEqual((c2["number"], c2["floor"], c2["w3w"], c2["positionFrom"], c2["crowdcadStatus"]),
                         (8, 2, "a.b.c", "coords", "Pending"))
        t3 = next(u for u in event["units"] if u["callsign"] == "Team 3")
        self.assertEqual((t3["lat"], t3["lon"], t3["placed"], t3["crowdcadStatus"]), (39.1801, -86.5251, True, "En Route"))
        self.assertNotIn("John", json.dumps(data))

    def test_field_status_remembers_device_positions(self):
        pub = Publisher({**config.DEFAULTS, "team_uids": {"Team 3": "ANDROID-t3"}}, lambda xml: None, clock_ms=lambda: NOW)
        pub.apply(demo())
        field = fieldstatus.FieldStatus(pub, store=None, config=pub.config, log=lambda line: None, now_ms=lambda: NOW)
        field.offer(b'<event version="2.0" uid="ANDROID-t3" type="a-f-G-U-C"><point lat="39.18" lon="-86.52" '
                    b'hae="0" ce="5" le="5"/><detail/></event>')
        field.offer(b'<event version="2.0" uid="ANDROID-t3" type="a-f-G-U-C"><point lat="0" lon="0" '
                    b'hae="0" ce="5" le="5"/><detail/></event>')                      # no fix: keep the last one
        field.offer(b'<event version="2.0" uid="ANDROID-zz" type="a-f-G-U-C"><point lat="1" lon="1"/></event>')
        self.assertEqual(field.positions, {"ANDROID-t3": (39.18, -86.52)})


if __name__ == "__main__":
    unittest.main()
