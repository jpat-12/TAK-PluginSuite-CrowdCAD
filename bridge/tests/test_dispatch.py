"""dispatch.py: each native TAK dispatch action writes exactly what CrowdCAD v1.6.0's dispatch
screen writes for the same click (handler named in each test), and nothing patient-identifying."""

import json
import unittest

from crowdcad_tak import config, dispatch, mapping

T0 = 1795100000000                          # 2026-11-19 14:53:20 UTC = 08:53 in Chicago
CLOCK = dispatch.Clock(T0, "America/Chicago")
LATER = dispatch.Clock(T0 + 125_000, "America/Chicago")


def event(**extra):
    return {
        "id": "e1f2g3h4i5j6k7l", "name": "Test", "status": "active",
        "staff": [
            {"team": "Team 1", "location": "Gate A", "status": "Available", "members": ["A"]},
            {"team": "Team 2", "location": "Gate B", "status": "Available", "members": ["B"]},
        ],
        "supervisor": [{"team": "Sup 1", "location": "Roaming", "status": "Available", "member": "Sam"}],
        "calls": [{"id": "c1", "order": 1, "status": "Pending", "location": "Sec 104", "assignedTeam": [],
                   "chiefComplaint": "Fall", "priority": False,
                   "log": [{"timestamp": T0, "message": "0853 - Call created, location: Sec 104"}]}],
        "eventEquipment": [], "clinics": [],
        **extra,
    }


def apply(ev, patch):
    return {**ev, **patch}


def unit(ev, name):
    return next(u for u in ev["staff"] + ev["supervisor"] if u["team"] == name)


class ClockTest(unittest.TestCase):
    def test_hhmm_in_the_events_zone(self):
        self.assertEqual(dispatch.Clock(T0, "UTC").hhmm, "1453")
        self.assertEqual(CLOCK.hhmm, "0853")                     # CrowdCAD writes browser-local time
        self.assertEqual(dispatch.Clock(T0, "Not/AZone").hhmm, dispatch.Clock(T0, "").hhmm)


class NewCallTest(unittest.TestCase):
    """quickcallmodal handleSubmit."""

    def test_pending_call(self):
        patch, cid = dispatch.new_call(event(), {"location": " Sec  110 ", "chiefComplaint": "Chest pain",
                                                 "priority": True}, "CloudTAK: jon", CLOCK)
        call = patch["calls"][-1]
        self.assertEqual(cid, str(T0))
        self.assertEqual((call["order"], call["status"], call["location"], call["assignedTeam"]), (2, "Pending", "Sec 110", []))
        self.assertEqual((call["source"], call["priority"], call["chiefComplaint"]), ("TAK", True, "Chest pain"))
        self.assertEqual(call["log"][0]["message"],
                         "0853 - Call created from TAK, complaint: Chest pain, location: Sec 110 (via CloudTAK: jon)")
        self.assertEqual(set(patch), {"calls"})

    def test_never_patient_fields(self):
        patch, _ = dispatch.new_call(event(), {"location": "x", "chiefComplaint": "y", "age": "34", "gender": "F",
                                               "notes": "John Smith"}, "CloudTAK: jon", CLOCK)
        wire = json.dumps(patch["calls"][-1])
        for field in ('"age"', '"gender"', '"notes"', "John Smith"):
            self.assertNotIn(field, wire)

    def test_created_assigned(self):
        patch, _ = dispatch.new_call(event(), {"location": "Sec 110", "assign": "Team 2"}, None, CLOCK)
        call = patch["calls"][-1]
        self.assertEqual((call["status"], call["assignedTeam"]), ("Assigned", ["Team 2"]))
        self.assertIn(", assigned to Team 2 (via TAK)", call["log"][0]["message"])
        team = unit({"staff": patch["staff"], "supervisor": []}, "Team 2")
        self.assertEqual((team["status"], team["location"], team["originalPost"]), ("En Route", "Sec 110", "Gate B"))
        self.assertEqual(team["log"][-1]["message"], "0853 - responding to call #2")

    def test_unique_ids_and_defaults(self):
        ev = event()
        ev["calls"].append({"id": str(T0), "order": 7})
        patch, cid = dispatch.new_call(ev, {}, None, CLOCK)
        self.assertEqual(cid, str(T0 + 1))
        self.assertEqual((patch["calls"][-1]["location"], patch["calls"][-1]["order"]), ("Unknown", 8))


class AssignTest(unittest.TestCase):
    """dispatch/page.tsx handleAddTeamToCall; calltracking.tsx supervisor assign."""

    def test_team(self):
        patch = dispatch.assign(event(), "c1", "Team 1", "CloudTAK: jon", LATER)
        call, team = patch["calls"][0], unit({**event(), **patch}, "Team 1")
        self.assertEqual((call["status"], call["assignedTeam"]), ("Assigned", ["Team 1"]))
        self.assertEqual(call["log"][-1]["message"],
                         "0855 - Team 1 assigned and en route. (assigned after 2m 5s pending) (via CloudTAK: jon)")
        self.assertEqual((team["status"], team["location"], team["originalPost"]), ("En Route", "Sec 104", "Gate A"))
        self.assertEqual(team["log"][-1]["message"], "0855 - responding to call #1 (c1)")

    def test_second_team_has_no_pending_suffix_and_refusals(self):
        ev = apply(event(), dispatch.assign(event(), "c1", "Team 1", None, CLOCK))
        patch = dispatch.assign(ev, "c1", "Team 2", None, LATER)
        self.assertNotIn("pending", patch["calls"][0]["log"][-1]["message"])
        with self.assertRaises(dispatch.DispatchError):
            dispatch.assign(ev, "c1", "Team 1")                          # already on it
        with self.assertRaises(dispatch.DispatchError):
            dispatch.assign(ev, "c1", "Team 9")
        closed = event()
        closed["calls"][0]["status"] = "Delivered"
        with self.assertRaises(dispatch.DispatchError):
            dispatch.assign(closed, "c1", "Team 1")

    def test_supervisor(self):
        ev = apply(event(), dispatch.assign(event(), "c1", "Team 1", None, CLOCK))
        ev["calls"][0]["status"] = "On Scene"
        patch = dispatch.assign(ev, "c1", "Sup 1", None, CLOCK)
        call, sup = patch["calls"][0], patch["supervisor"][0]
        self.assertEqual(call["status"], "On Scene")                     # keeps the call's status once staffed
        self.assertIn("Supervisor Sam (Sup 1) assigned to call.", call["log"][-1]["message"])
        self.assertEqual((sup["status"], sup["location"], sup["originalPost"]), ("En Route", "Sec 104", "Roaming"))
        self.assertNotIn("staff", patch)

    def test_equipment_goes_in_use_with_the_team(self):
        ev = event(eventEquipment=[{"id": "q1", "name": "AED", "status": "Available", "assignedTeam": "Team 1"},
                                   {"id": "q2", "name": "Stretcher", "status": "Available"}])
        patch = dispatch.assign(ev, "c1", "Team 1", None, CLOCK)
        self.assertEqual(patch["eventEquipment"][0], {"id": "q1", "name": "AED", "status": "In Use",
                                                      "assignedTeam": "Team 1", "location": "Sec 104"})
        self.assertEqual(patch["eventEquipment"][1]["status"], "Available")


class StatusOnCallTest(unittest.TestCase):
    """dispatch/page.tsx handleTeamStatusChange."""

    def two_teams_and_sup(self):
        ev = event()
        for name in ("Team 1", "Team 2", "Sup 1"):
            ev = apply(ev, dispatch.assign(ev, "c1", name, None, CLOCK))
        return ev

    def test_on_scene_and_transporting(self):
        ev = self.two_teams_and_sup()
        ev = apply(ev, dispatch.status_on_call(ev, "c1", "Team 1", "On Scene", "CloudTAK: jon", CLOCK))
        self.assertEqual(ev["calls"][0]["status"], "On Scene")
        self.assertEqual(ev["calls"][0]["log"][-1]["message"], "0853 - Team 1 set to On Scene at Sec 104 (via CloudTAK: jon)")
        self.assertEqual(unit(ev, "Team 1")["status"], "On Scene")
        ev = apply(ev, dispatch.status_on_call(ev, "c1", "Team 1", "Transporting", None, CLOCK))
        self.assertEqual(ev["calls"][0]["status"], "Transporting")
        self.assertIn("Team 1 transporting to clinic", ev["calls"][0]["log"][-1]["message"])

    def test_transporting_names_the_clinic_when_there_are_several(self):
        ev = self.two_teams_and_sup()
        ev["clinics"] = [{"id": "a", "name": "Main Aid"}, {"id": "b", "name": "North Aid"}]
        patch = dispatch.status_on_call(ev, "c1", "Team 1", "Transporting", None, CLOCK, clinic_id="b")
        self.assertIn("transporting to North Aid", patch["calls"][0]["log"][-1]["message"])
        self.assertEqual(patch["calls"][0]["clinicId"], "b")

    def test_delivered_closes_the_call_for_everyone(self):
        ev = self.two_teams_and_sup()
        ev["calls"][0]["pin"] = True
        ev = apply(ev, dispatch.status_on_call(ev, "c1", "Team 1", "Delivered", None, CLOCK))
        call = ev["calls"][0]
        self.assertEqual((call["status"], call["clinic"], call["assignedTeam"], call["pin"]), ("Delivered", True, [], False))
        self.assertEqual([(d["team"], d["reason"], d["kind"]) for d in call["detachedTeams"]],
                         # CrowdCAD's own quirk, kept: its "other teams on the call" loop reaches the
                         # supervisor first (kind team); the supervisor loop then skips it.
                         [("Team 1", "Delivered", "team"), ("Team 2", "Auto-detached", "team"),
                          ("Sup 1", "Auto-detached", "team")])
        self.assertEqual((unit(ev, "Team 1")["status"], unit(ev, "Team 1")["location"]), ("In Clinic", "Clinic"))
        t2 = unit(ev, "Team 2")
        self.assertEqual((t2["status"], t2["location"]), ("Available", "Gate B"))
        self.assertIn("auto-detached from completed call, status set to Available at Gate B", t2["log"][-1]["message"])
        self.assertEqual((unit(ev, "Sup 1")["status"], unit(ev, "Sup 1")["location"]), ("Available", "Roaming"))
        with self.assertRaises(dispatch.DispatchError):
            dispatch.status_on_call(ev, "c1", "Team 2", "On Scene")      # closed, and nobody's on it

    def test_refusal_and_rolled(self):
        ev = apply(event(), dispatch.assign(event(), "c1", "Team 1", None, CLOCK))
        refused = apply(ev, dispatch.status_on_call(ev, "c1", "Team 1", "Refusal", None, CLOCK))
        self.assertEqual(refused["calls"][0]["status"], "Refusal")
        self.assertEqual((unit(refused, "Team 1")["status"], unit(refused, "Team 1")["location"]), ("Available", "Gate A"))
        rolled = apply(ev, dispatch.status_on_call(ev, "c1", "Team 1", "Rolled from Scene", None, CLOCK, transport_unit="M12"))
        self.assertEqual((rolled["calls"][0]["status"], rolled["calls"][0]["transportUnit"]), ("Resolved", "M12"))
        self.assertIn("Team 1 Transferred to ambulance, unit #: M12", rolled["calls"][0]["log"][-1]["message"])

    def test_detached_leaves_the_others_on_the_call(self):
        ev = self.two_teams_and_sup()
        ev = apply(ev, dispatch.status_on_call(ev, "c1", "Team 2", "On Scene", None, CLOCK))
        ev = apply(ev, dispatch.status_on_call(ev, "c1", "Team 1", "Detached", None, CLOCK))
        call = ev["calls"][0]
        self.assertEqual((call["assignedTeam"], call["status"]), (["Team 2", "Sup 1"], "On Scene"))
        self.assertEqual((unit(ev, "Team 1")["status"], unit(ev, "Team 1")["location"]), ("Available", "Gate A"))

    def test_supervisor_status_is_its_own(self):
        ev = self.two_teams_and_sup()
        patch = dispatch.status_on_call(ev, "c1", "Sup 1", "On Scene", None, CLOCK)
        self.assertEqual(set(patch), {"supervisor"})                      # handleSupervisorStatusChange
        self.assertEqual(patch["supervisor"][0]["log"][-1]["message"], "0853 - status changed to On Scene at Sec 104 (via TAK)")

    def test_refuses_what_crowdcad_wouldnt_offer(self):
        ev = self.two_teams_and_sup()
        for bad in ("Available", "Delivered Eq", "Resolved", ""):
            with self.assertRaises(dispatch.DispatchError):
                dispatch.status_on_call(ev, "c1", "Team 1", bad)
        with self.assertRaises(dispatch.DispatchError):
            dispatch.status_on_call(event(), "c1", "Team 1", "On Scene")    # not on this call

    def test_tak_sees_it(self):
        """The bridge publishes the result like any CrowdCAD change: IU status codes on the incident."""
        ev = self.two_teams_and_sup()
        ev = apply(ev, dispatch.status_on_call(ev, "c1", "Team 1", "On Scene", None, CLOCK))
        ev["venue"] = {"layers": [{"id": "L", "geoBounds": {"north": 1, "south": 0, "east": 1, "west": 0},
                                   "posts": [{"name": "Sec 104", "x": 50, "y": 50}]}]}
        items, _ = mapping.build(ev, config.DEFAULTS)
        incident = next(i for i in items.values() if i.kind == "incident")
        self.assertEqual(incident.fields["status"], "ONSC")


class AvailabilityTest(unittest.TestCase):
    """handleStatusChange / handleSupervisorStatusChange / handleLocationChange."""

    def test_team_availability(self):
        patch = dispatch.unit_status(event(), "Team 1", "On Break", "CloudTAK: jon", CLOCK)
        self.assertEqual(set(patch), {"staff"})
        self.assertEqual(patch["staff"][0]["status"], "On Break")
        self.assertEqual(patch["staff"][0]["log"][-1]["message"], "0853 - Team 1 set to On Break (via CloudTAK: jon)")
        with self.assertRaises(dispatch.DispatchError):
            dispatch.unit_status(event(), "Team 1", "On Scene")              # on-call statuses go through the call

    def test_supervisor_availability(self):
        patch = dispatch.unit_status(event(), "Sup 1", "In Clinic", None, CLOCK)
        self.assertEqual(patch["supervisor"][0]["status"], "In Clinic")

    def test_post_change(self):
        patch = dispatch.unit_post(event(), "Team 1", "Clinic", None, CLOCK)
        self.assertEqual((patch["staff"][0]["location"], patch["staff"][0]["status"]), ("Clinic", "In Clinic"))
        self.assertEqual(patch["staff"][0]["log"][-1]["message"], "0853 - Post changed to Clinic (via TAK)")
        patch = dispatch.unit_post(event(), "Sup 1", "Gate C", None, CLOCK)
        self.assertEqual(patch["supervisor"][0]["location"], "Gate C")
        with self.assertRaises(dispatch.DispatchError):
            dispatch.unit_post(event(), "Team 1", "  ")


if __name__ == "__main__":
    unittest.main()
