"""fieldstatus.py: a medic's taps in the ATAK plugin become CrowdCAD changes, once per tap."""

import threading
import unittest

from crowdcad_tak import config, dispatch, fieldstatus, mapping
from crowdcad_tak.takclient import TakClient

from test_dispatch import CLOCK, apply, event, unit

NOW = 1795100000000
DEVICE = "ANDROID-medic1"


def pli(status, since, incident="", uid=DEVICE, callsign="MEDIC1"):
    inc = f' incident="{incident}"' if incident else ""
    return (f'<event version="2.0" uid="{uid}" type="a-f-G-U-C" how="m-g" time="t" start="t" stale="t">'
            f'<point lat="1" lon="1" hae="0" ce="1" le="1"/><detail><contact callsign="{callsign}"/>'
            f'<__iucad_unit v="1" status="{status}"{inc} since="{since}"/></detail></event>').encode()


class ParseTest(unittest.TestCase):
    def test_plugin_report(self):
        self.assertEqual(fieldstatus.parse(pli("ONSC", NOW, "CC-001")),
                         {"uid": DEVICE, "callsign": "MEDIC1", "status": "ONSC", "incident": "CC-001", "since": NOW})

    def test_ignores_everything_else(self):
        self.assertIsNone(fieldstatus.parse(b'<event uid="x"><detail><contact callsign="A"/></detail></event>'))
        self.assertIsNone(fieldstatus.parse(b"<event uid='x'><detail><__iucad_unit status='AVL'"))     # truncated
        self.assertIsNone(fieldstatus.parse(b'<!DOCTYPE x [<!ENTITY a "aaa">]><event uid="x"><detail>'
                                            b'<__iucad_unit status="AVL" since="1"/></detail></event>'))


class PlanTest(unittest.TestCase):
    """Each tap → CrowdCAD's own action (dispatch.py), as agreed with Jon 2026-11-19."""

    def setUp(self):
        self.prefix = "CC"
        self.ev = event()
        self.cfg = dict(config.DEFAULTS)

    def plan(self, ev, status, incident=""):
        report = {"status": status, "incident": incident, "since": NOW, "uid": DEVICE, "callsign": "MEDIC1"}
        return fieldstatus.plan(ev, self.cfg, "Team 1", report, "ATAK: MEDIC1", CLOCK)

    def test_on_scene_on_the_assigned_call(self):
        ev = apply(self.ev, dispatch.assign(self.ev, "c1", "Team 1", None, CLOCK))
        ev = apply(ev, self.plan(ev, "ONSC", mapping.incident_id(ev["calls"][0], self.prefix)))
        self.assertEqual((ev["calls"][0]["status"], unit(ev, "Team 1")["status"]), ("On Scene", "On Scene"))
        self.assertIn("(via ATAK: MEDIC1)", ev["calls"][0]["log"][-1]["message"])
        self.assertEqual(self.plan(ev, "ONSC", "CC-001"), {})                  # already so: nothing to write

    def test_respond_self_dispatches(self):
        ev = apply(self.ev, self.plan(self.ev, "RESP", "CC-001"))
        self.assertEqual((ev["calls"][0]["assignedTeam"], unit(ev, "Team 1")["status"]), (["Team 1"], "En Route"))

    def test_transporting_without_incident_uses_their_call(self):
        ev = apply(self.ev, dispatch.assign(self.ev, "c1", "Team 1", None, CLOCK))
        ev = apply(ev, self.plan(ev, "TRAN"))
        self.assertEqual(ev["calls"][0]["status"], "Transporting")

    def test_available_on_a_call_clears_them(self):
        ev = apply(self.ev, dispatch.assign(self.ev, "c1", "Team 1", None, CLOCK))
        ev = apply(ev, self.plan(ev, "AVL"))
        self.assertEqual(ev["calls"][0]["assignedTeam"], [])
        self.assertEqual(ev["calls"][0]["status"], "Resolved")                 # last unit: CrowdCAD closes it
        self.assertEqual((unit(ev, "Team 1")["status"], unit(ev, "Team 1")["location"]), ("Available", "Gate A"))

    def test_available_and_out_of_service_off_a_call(self):
        ev = apply(self.ev, self.plan(self.ev, "OOS"))
        self.assertEqual(unit(ev, "Team 1")["status"], "On Break")
        ev = apply(ev, self.plan(ev, "AVL"))
        self.assertEqual(unit(ev, "Team 1")["status"], "Available")
        self.assertEqual(self.plan(ev, "AVL"), {})

    def test_out_of_service_on_a_call_is_left_to_dispatch(self):
        ev = apply(self.ev, dispatch.assign(self.ev, "c1", "Team 1", None, CLOCK))
        self.assertEqual(self.plan(ev, "OOS"), {})

    def test_unknown_or_closed_incident(self):
        with self.assertRaises(dispatch.DispatchError):
            self.plan(self.ev, "ONSC", "CC-999")
        with self.assertRaises(dispatch.DispatchError):
            self.plan(self.ev, "ONSC")                                          # not on any call


class FakePublisher:
    def __init__(self, bound=True, free=()):
        self.lock = threading.Lock()
        self.events = {"e1f2g3h4i5j6k7l": {"name": "T", "ended": False, "free_units": list(free),
                                           "device_teams": [{"name": "Team 1", "uid": DEVICE}] if bound else []}}


class FakeStore:
    def __init__(self):
        self.event = event()
        self.writes = 0

    def apply(self, eid, action):
        patch = action(self.event)
        if patch:
            self.event = apply(self.event, patch)
            self.writes += 1
        return patch, None


class WatcherTest(unittest.TestCase):
    def watcher(self, bound=True, now=NOW, free=(), **cfg):
        self.store = FakeStore()
        self.pub = FakePublisher(bound, free)
        return fieldstatus.FieldStatus(self.pub, self.store, {**config.DEFAULTS, **cfg}, log=lambda line: None,
                                       now_ms=lambda: now)

    def test_one_write_per_tap(self):
        w = self.watcher()
        self.assertTrue(w.handle(pli("RESP", NOW - 1000, "CC-001")))
        self.assertIsNone(w.handle(pli("RESP", NOW - 1000, "CC-001")))        # same tap, next PLI
        self.assertTrue(w.handle(pli("ONSC", NOW, "CC-001")))
        self.assertEqual(self.store.writes, 2)
        self.assertEqual(self.store.event["calls"][0]["status"], "On Scene")

    def test_old_tap_not_replayed_after_restart(self):
        w = self.watcher(now=NOW + fieldstatus.FRESH_MS + 1)
        self.assertIsNone(w.handle(pli("OOS", NOW)))
        self.assertEqual(self.store.writes, 0)

    def test_unbound_device_and_other_traffic_ignored(self):
        w = self.watcher(bound=False)
        self.assertIsNone(w.handle(pli("OOS", NOW)))
        self.assertIsNone(w.handle(b'<event uid="x"/>'))
        self.assertEqual(self.store.writes, 0)

    def test_last_heard_for_bound_devices_only(self):
        w = self.watcher()
        w.offer(b'<event version="2.0" uid="' + DEVICE.encode() + b'" type="a-f-G-U-C"><detail/></event>')
        w.offer(b'<event version="2.0" uid="SOMEONE-ELSE" type="a-f-G-U-C"><detail/></event>')
        self.assertEqual(w.heard, {DEVICE: NOW})

    def test_unlinked_phone_links_itself_by_callsign(self):
        w = self.watcher(bound=False, free=["Team 1", "Team 2"])
        self.assertTrue(w.handle(pli("RESP", NOW, "CC-001", callsign="TEAM1")))     # "Team 1" ↔ TEAM1
        self.assertEqual(unit(self.store.event, "Team 1")["takUid"], DEVICE)       # saved with the tap, one write
        self.assertEqual((self.store.writes, unit(self.store.event, "Team 1")["status"]), (1, "En Route"))
        self.assertEqual(w.heard, {DEVICE: NOW})

    def test_no_link_when_callsign_matches_nothing_or_is_off(self):
        w = self.watcher(bound=False, free=["Team 2"])
        self.assertIsNone(w.handle(pli("AVL", NOW, callsign="TEAM1")))
        w = self.watcher(bound=False, free=["Team 1"], claim_by_callsign=False)
        self.assertIsNone(w.handle(pli("AVL", NOW, callsign="Team 1")))
        self.assertEqual(self.store.writes, 0)

    def test_ambiguous_callsign_links_nothing(self):
        w = self.watcher(bound=False, free=["Team 1"])
        self.pub.events["other0000000000"] = {"name": "U", "ended": False, "free_units": ["TEAM 1"], "device_teams": []}
        self.assertIsNone(w.handle(pli("AVL", NOW, callsign="Team 1")))

    def test_unit_taken_meanwhile_is_refused(self):
        ev = event()
        ev["staff"][0]["takUid"] = "ANDROID-someone-else"
        with self.assertRaises(dispatch.DispatchError):
            fieldstatus.link_device(ev, ev["staff"][0]["team"], DEVICE)
        self.assertEqual(fieldstatus.link_device(ev, ev["staff"][0]["team"], "ANDROID-someone-else")[1], {})

    def test_errors_are_reported_not_raised(self):
        w = self.watcher()
        self.assertFalse(w.handle(pli("ONSC", NOW, "CC-999")))
        self.assertIn("CC-999", w.last_error)


class StreamTest(unittest.TestCase):
    def test_tak_stream_is_split_into_events(self):
        got = []
        client = TakClient("127.0.0.1", 1, "c", "k", "a", on_message=got.append)
        one, two = pli("AVL", 1), pli("ONSC", 2)
        stream = b'<?xml version="1.0"?>' + one + two
        client._feed(stream[:50])
        client._feed(stream[50:-10])
        client._feed(stream[-10:])
        self.assertEqual(got, [one, two])

    def test_handler_errors_never_break_the_link(self):
        client = TakClient("127.0.0.1", 1, "c", "k", "a", on_message=lambda m: 1 / 0)
        client._feed(pli("AVL", 1))
        self.assertIn("ZeroDivisionError", client.last_error)


if __name__ == "__main__":
    unittest.main()
