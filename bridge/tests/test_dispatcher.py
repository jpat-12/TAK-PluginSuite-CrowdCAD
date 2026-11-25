"""dispatcher.py: the CloudTAK dispatcher (a copy of IU EMS Dispatch) gets IU's board and actions,
each applied to CrowdCAD with CrowdCAD's own handlers."""

import json
import unittest

from crowdcad_tak import board, calldetails, config, dispatcher, manage
from crowdcad_tak.bridge import Publisher
from crowdcad_tak.dispatch import Clock

from test_manage import FakePB
from test_mapping import EID

NOW = 1794701000000


class Setup(unittest.TestCase):
    def setUp(self):
        self.pb = FakePB()
        ev = self.pb.records["events"][EID]
        ev.update(isOrgEvent=True, status="active")
        self.cfg = {**config.DEFAULTS, "team_uids": {"Team 3": "ANDROID-t3"}}
        self.pub = Publisher(self.cfg, lambda xml: None, clock_ms=lambda: NOW, details=calldetails.CallDetails())
        self.manager = manage.Manager(self.pb, log=lambda line: None, timezone="UTC", details=self.pub.details)
        self.d = dispatcher.Dispatcher(self.manager, self.source)

    def source(self):
        self.pub.apply(self.pb.records["events"][EID])           # what the realtime echo would do
        return board.build(self.pub, NOW, positions={"ANDROID-t3": (39.1815, -86.5252)}, heard={"ANDROID-t3": NOW - 5000})

    def record(self):
        return self.pb.records["events"][EID]

    def call(self, cid):
        return next(c for c in self.record()["calls"] if c["id"] == cid)

    def unit(self, name):
        return next(u for u in self.record()["staff"] + self.record()["supervisor"] if u["team"] == name)


class BoardTest(Setup):
    def test_iu_board_shape(self):
        b = self.d.board(NOW)
        self.assertEqual(b["now"], NOW)
        cc7 = next(i for i in b["incidents"] if i["id"] == "CC-007")
        for key in ("id", "cadId", "status", "type", "typeAbbrv", "medical", "priority", "location", "floor",
                    "eventTitle", "notes", "w3w", "lat", "lon", "positionFrom", "created", "updated", "assigned"):
            self.assertIn(key, cc7)
        self.assertEqual((cc7["cadId"], cc7["status"], cc7["priority"], cc7["positionFrom"]), ("c1", "ONSC", 1, "table"))
        self.assertEqual(cc7["assigned"], [f"crowdcad-{EID}-team-team-1"])
        t3 = next(u for u in b["units"] if u["callsign"] == "Team 3")
        self.assertEqual((t3["uid"], t3["lat"], t3["seen"]), ("ANDROID-t3", 39.1815, NOW - 5000))
        for key in ("uid", "callsign", "status", "incident", "since", "lat", "lon", "seen"):
            self.assertIn(key, t3)
        self.assertNotIn("John", json.dumps(b))                   # no patient data, notes included
        self.assertTrue(all(u["status"] in ("AVL", "RESP", "ONSC", "TRAN", "OOS") for u in b["units"]))

    def test_unplaced_call_reads_as_venue_centre(self):
        c4 = next(i for i in self.d.board(NOW)["incidents"] if i["cadId"] == "c4")
        self.assertEqual((c4["lat"], c4["lon"], c4["positionFrom"]), (0.0, 0.0, "facility"))


class ActionTest(Setup):
    def test_assign_and_unassign(self):
        self.d.act({"action": "assign", "id": "CC-008", "unitUid": f"crowdcad-{EID}-team-team-2"}, "jon")
        self.assertEqual(self.call("c2")["assignedTeam"], ["Team 2"])
        self.assertEqual(self.unit("Team 2")["status"], "En Route")
        self.d.act({"action": "unassign", "id": "CC-008", "unitUid": f"crowdcad-{EID}-team-team-2"}, "jon")
        self.assertEqual((self.call("c2")["assignedTeam"], self.call("c2")["status"]), ([], "Pending"))
        self.assertEqual(self.unit("Team 2")["status"], "Available")
        self.assertIn("detached from call. (via CloudTAK: jon)", self.call("c2")["log"][-1]["message"])

    def test_status_moves_every_assigned_unit(self):
        self.d.act({"action": "status", "id": "CC-009", "status": "ONSC"}, "jon")      # c4: Team 3
        self.assertEqual(self.unit("Team 3")["status"], "On Scene")
        self.assertEqual(self.call("c4")["status"], "On Scene")

    def test_one_unit_status_on_the_call(self):
        uid = "ANDROID-t3"                                             # Team 3 on c4 (CC-009)
        self.d.act({"action": "unit_status", "id": "CC-009", "unitUid": uid, "status": "TRAN"}, "jon")
        self.assertEqual(self.unit("Team 3")["status"], "Transporting")
        self.d.act({"action": "unit_status", "id": "CC-009", "unitUid": uid, "status": "OOS"}, "jon")
        self.assertEqual(self.unit("Team 3")["status"], "On Break")
        self.assertNotIn("Team 3", self.call("c4")["assignedTeam"])

    def test_unit_available_frees_it(self):
        self.d.act({"action": "unit_status", "id": "CC-009", "unitUid": "ANDROID-t3", "status": "AVL"}, "jon")
        self.assertEqual(self.unit("Team 3")["status"], "Available")
        self.assertEqual(self.call("c4")["status"], "Resolved")        # it was the last unit: CrowdCAD's cascade

    def test_status_needs_a_unit(self):
        with self.assertRaises(manage.ManageError):
            self.d.act({"action": "status", "id": "CC-008", "status": "DISP"}, "jon")

    def test_close_frees_units(self):
        self.d.act({"action": "status", "id": "CC-009", "status": "CLOSED"}, "jon")
        self.assertEqual((self.call("c4")["status"], self.call("c4")["assignedTeam"]), ("Resolved", []))
        self.assertEqual(self.unit("Team 3")["status"], "Available")
        self.assertFalse(self.call("c4").get("duplicate"))

    def test_cancel_is_crowdcads_duplicate_shape(self):
        self.d.act({"action": "status", "id": "CC-008", "status": "CXL"}, "jon")
        self.assertEqual((self.call("c2")["status"], self.call("c2")["duplicate"]), ("Resolved", True))
        self.assertNotIn("CC-008", [i["id"] for i in self.d.board(NOW)["incidents"]])

    def test_create_puts_the_point_in_location_and_returns_the_radio_id(self):
        r = self.d.act({"action": "create", "incident": {
            "type": "Cardiac", "priority": 1, "location": "Sec 104 Row 22", "floor": 2, "notes": "chest pain",
            "reportedBy": "Event Services", "lat": 39.18205, "lon": -86.52541, "w3w": ""}}, "jon")
        new = self.record()["calls"][-1]
        self.assertEqual(r["id"], f"CC-{new['order']:03d}")
        self.assertEqual((new["location"], new["chiefComplaint"], new["priority"], new["source"]),
                         ("39.18205, -86.52541", "Cardiac: chest pain", True, "Event Services"))
        self.assertEqual(new["notes"], "[TAK] Sec 104 Row 22 · Floor 2 · picked on map")
        inc = next(i for i in self.d.board(NOW)["incidents"] if i["id"] == r["id"])
        self.assertEqual((inc["floor"], inc["notes"], inc["positionFrom"]), (2, "Sec 104 Row 22", "dispatch"))

    def test_add_and_remove_units(self):
        self.d.act({"action": "add_unit", "unit": {"name": "Medic 9", "kind": "team", "takUid": "ANDROID-m9"}}, "jon")
        self.assertEqual((self.unit("Medic 9")["status"], self.unit("Medic 9")["takUid"]), ("Available", "ANDROID-m9"))
        self.d.act({"action": "add_unit", "unit": {"name": "Sup 2", "kind": "supervisor", "cert": "Paramedic"}}, "jon")
        self.assertEqual(self.unit("Sup 2")["member"], "Supervisor [Paramedic]")
        with self.assertRaises(manage.ManageError):                  # names are unique
            self.d.act({"action": "add_unit", "unit": {"name": "medic 9", "kind": "team"}}, "jon")
        uid = next(u["uid"] for u in self.d.board(NOW)["units"] if u["callsign"] == "Team 3")
        self.d.act({"action": "remove_unit", "unitUid": uid}, "jon")    # Team 3 was on c4
        self.assertNotIn("Team 3", [u["team"] for u in self.record()["staff"]])
        self.assertEqual((self.call("c4")["assignedTeam"], self.call("c4")["status"]), ([], "Pending"))
        self.assertIn("Team 3 removed (team deleted).", self.call("c4")["log"][-1]["message"])

    def test_never_heard_device_says_so(self):
        b = self.d.board(NOW)
        self.assertTrue(all("device" in u for u in b["units"]))

    def test_bad_create_input_is_a_clear_400(self):
        for inc in ({"type": "Fall", "priority": "x", "lat": 39.1, "lon": -86.5},
                    {"type": "Fall", "priority": 1, "lat": "nan", "lon": -86.5},
                    {"type": "Fall", "priority": 1, "lat": 95, "lon": -86.5}):
            with self.assertRaises(manage.ManageError, msg=inc) as error:
                self.d.act({"action": "create", "incident": inc}, "jon")
            self.assertEqual(error.exception.status, 400, inc)

    def test_unknown_things_refused(self):
        for body in ({"action": "nope", "id": "CC-007"}, {"action": "assign", "id": "CC-999", "unitUid": "x"},
                     {"action": "assign", "id": "CC-008", "unitUid": "ghost"}):
            with self.assertRaises(manage.ManageError, msg=body):
                self.d.act(body, "jon")


class HandlerTest(unittest.TestCase):
    def test_close_refuses_closed_calls(self):
        from test_mapping import demo
        with self.assertRaises(Exception):
            dispatcher.close_call(demo(), "c3", None, Clock(NOW, "UTC"))


if __name__ == "__main__":
    unittest.main()
