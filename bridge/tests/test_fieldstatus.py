"""fieldstatus.py: a medic's Acknowledge tap in the ATAK plugin → one CrowdCAD call-log line, once
per tap. Field users never change status (Jon, 2026-11-25)."""

import threading
import unittest

from crowdcad_tak import config, dispatch, fieldstatus, mapping
from crowdcad_tak.takclient import TakClient

from test_dispatch import CLOCK, apply, event, unit

NOW = 1795100000000
DEVICE = "ANDROID-medic1"


def pli(incident, at, uid=DEVICE, callsign="MEDIC1"):
    """A position report carrying the plugin's last Acknowledge."""
    return (f'<event version="2.0" uid="{uid}" type="a-f-G-U-C" how="m-g" time="t" start="t" stale="t">'
            f'<point lat="1" lon="1" hae="0" ce="1" le="1"/><detail><contact callsign="{callsign}"/>'
            f'<__crowdcad_ack incident="{incident}" at="{at}"/></detail></event>').encode()


def old_status_pli(status, since, uid=DEVICE):
    """A 0.1.5 plugin's status tap (<__iucad_unit>): must change nothing now."""
    return (f'<event version="2.0" uid="{uid}" type="a-f-G-U-C"><detail><contact callsign="MEDIC1"/>'
            f'<__iucad_unit v="1" status="{status}" incident="CC-001" since="{since}"/></detail></event>').encode()


class ParseTest(unittest.TestCase):
    def test_plugin_report(self):
        self.assertEqual(fieldstatus.parse(pli("CC-001", NOW)),
                         {"uid": DEVICE, "callsign": "MEDIC1", "incident": "CC-001", "at": NOW})

    def test_ignores_everything_else(self):
        self.assertIsNone(fieldstatus.parse(b'<event uid="x"><detail><contact callsign="A"/></detail></event>'))
        self.assertIsNone(fieldstatus.parse(old_status_pli("ONSC", NOW)))                 # status taps: gone
        self.assertIsNone(fieldstatus.parse(b"<event uid='x'><detail><__crowdcad_ack incident='CC-1'"))  # truncated
        self.assertIsNone(fieldstatus.parse(pli("", NOW)))                                # no incident
        self.assertIsNone(fieldstatus.parse(pli("CC-001", 0)))                            # no time
        self.assertIsNone(fieldstatus.parse(b'<!DOCTYPE x [<!ENTITY a "aaa">]><event uid="x"><detail>'
                                            b'<__crowdcad_ack incident="CC-1" at="1"/></detail></event>'))


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.ev = apply(event(), dispatch.assign(event(), "c1", "Team 1", None, CLOCK))
        self.cfg = dict(config.DEFAULTS)
        self.incident = mapping.incident_id(self.ev["calls"][0], "CC")

    def plan(self, ev, incident):
        report = {"incident": incident, "at": NOW, "uid": DEVICE, "callsign": "MEDIC1"}
        return fieldstatus.plan(ev, self.cfg, "Team 1", report, "ATAK: MEDIC1", CLOCK)

    def test_ack_logs_one_line_and_changes_no_status(self):
        before = (self.ev["calls"][0]["status"], unit(self.ev, "Team 1")["status"], len(self.ev["calls"][0]["log"]))
        ev = apply(self.ev, self.plan(self.ev, self.incident))
        self.assertEqual((ev["calls"][0]["status"], unit(ev, "Team 1")["status"]), before[:2])
        self.assertEqual(len(ev["calls"][0]["log"]), before[2] + 1)
        self.assertIn("Team 1 acknowledged the call. (via ATAK: MEDIC1)", ev["calls"][0]["log"][-1]["message"])
        self.assertEqual(set(self.plan(self.ev, self.incident)), {"calls"})               # only the call is written

    def test_unknown_call_or_unit_not_on_it(self):
        with self.assertRaises(dispatch.DispatchError):
            self.plan(self.ev, "CC-999")
        with self.assertRaises(dispatch.DispatchError):
            self.plan(event(), self.incident)                                          # Team 1 not assigned


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
    def watcher(self, bound=True, now=NOW, free=(), assigned=True, **cfg):
        self.store = FakeStore()
        if assigned:
            self.store.event = apply(self.store.event, dispatch.assign(self.store.event, "c1", "Team 1", None, CLOCK))
        self.pub = FakePublisher(bound, free)
        return fieldstatus.FieldStatus(self.pub, self.store, {**config.DEFAULTS, **cfg}, log=lambda line: None,
                                       now_ms=lambda: now)

    def test_one_write_per_tap(self):
        w = self.watcher()
        self.assertTrue(w.handle(pli("CC-001", NOW - 1000)))
        self.assertIsNone(w.handle(pli("CC-001", NOW - 1000)))               # same tap, next PLI
        self.assertEqual(self.store.writes, 1)
        self.assertIn("acknowledged", self.store.event["calls"][0]["log"][-1]["message"])

    def test_supervisor_ack_clears_supervisor_requests_from_units_on_that_call(self):
        # Tracker R29: Team 1 (on CC-001) and Team 2 (not on it) both asked for a supervisor; Sup 1,
        # assigned to CC-001, acknowledges it: only Team 1's request is answered, and through the
        # dispatcher's Clear path (on_change fires, so phones get the roster at once).
        from crowdcad_tak import calldetails
        sup_device = "ANDROID-sup1"
        w = self.watcher()
        self.store.event = apply(self.store.event, dispatch.assign(self.store.event, "c1", "Sup 1", None, CLOCK))
        self.pub.events["e1f2g3h4i5j6k7l"]["device_teams"].append({"name": "Sup 1", "uid": sup_device, "supervisor": True})
        details = self.pub.details = calldetails.CallDetails()
        changes = []
        for team, uid in (("Team 1", DEVICE), ("Team 2", "ANDROID-medic2")):
            details.add_supreq({"id": uid + "-1", "event": "e1f2g3h4i5j6k7l", "unit": team, "uid": uid,
                                "at": NOW - 9000, "cleared": False})
        details.on_change = lambda: changes.append(1)
        self.assertTrue(w.handle(pli("CC-001", NOW - 1000)))                  # Team 1's own ack: not a supervisor
        self.assertEqual([r["cleared"] for r in details.supreqs()], [False, False])
        self.assertTrue(w.handle(pli("CC-001", NOW - 500, uid=sup_device, callsign="SUP1")))
        self.assertEqual({r["unit"]: r["cleared"] for r in details.supreqs()}, {"Team 1": True, "Team 2": False})
        self.assertEqual(changes, [1])                                        # roster re-sent once
        self.assertEqual(set(details.open_supreqs(NOW)), {"ANDROID-medic2"})

    def test_old_status_taps_change_nothing(self):
        w = self.watcher()
        w.offer(old_status_pli("AVL", NOW))
        self.assertIsNone(w.handle(old_status_pli("AVL", NOW)))
        self.assertEqual(self.store.writes, 0)
        self.assertEqual(w._queue.qsize(), 0)                                  # not even queued

    def test_old_tap_not_replayed_after_restart(self):
        w = self.watcher(now=NOW + fieldstatus.FRESH_MS + 1)
        self.assertIsNone(w.handle(pli("CC-001", NOW)))
        self.assertEqual(self.store.writes, 0)

    def test_unbound_device_and_other_traffic_ignored(self):
        w = self.watcher(bound=False)
        self.assertIsNone(w.handle(pli("CC-001", NOW)))
        self.assertIsNone(w.handle(b'<event uid="x"/>'))
        self.assertEqual(self.store.writes, 0)

    def test_last_heard_for_bound_devices_only(self):
        w = self.watcher()
        w.offer(b'<event version="2.0" uid="' + DEVICE.encode() + b'" type="a-f-G-U-C"><detail/></event>')
        w.offer(b'<event version="2.0" uid="SOMEONE-ELSE" type="a-f-G-U-C"><detail/></event>')
        self.assertEqual(w.heard, {DEVICE: NOW})

    def test_unlinked_phone_links_itself_by_callsign(self):
        w = self.watcher(bound=False, free=["Team 1", "Team 2"])
        self.assertTrue(w.handle(pli("CC-001", NOW, callsign="TEAM1")))       # "Team 1" ↔ TEAM1
        self.assertEqual(unit(self.store.event, "Team 1")["takUid"], DEVICE)   # saved with the ack, one write
        self.assertEqual(self.store.writes, 1)
        self.assertEqual(w.heard, {DEVICE: NOW})

    def test_no_link_when_callsign_matches_nothing_or_is_off(self):
        w = self.watcher(bound=False, free=["Team 2"])
        self.assertIsNone(w.handle(pli("CC-001", NOW, callsign="TEAM1")))
        w = self.watcher(bound=False, free=["Team 1"], claim_by_callsign=False)
        self.assertIsNone(w.handle(pli("CC-001", NOW, callsign="Team 1")))
        self.assertEqual(self.store.writes, 0)

    def test_ambiguous_callsign_links_nothing(self):
        w = self.watcher(bound=False, free=["Team 1"])
        self.pub.events["other0000000000"] = {"name": "U", "ended": False, "free_units": ["TEAM 1"], "device_teams": []}
        self.assertIsNone(w.handle(pli("CC-001", NOW, callsign="Team 1")))

    def test_unit_taken_meanwhile_is_refused(self):
        ev = event()
        ev["staff"][0]["takUid"] = "ANDROID-someone-else"
        with self.assertRaises(dispatch.DispatchError):
            fieldstatus.link_device(ev, ev["staff"][0]["team"], DEVICE)
        self.assertEqual(fieldstatus.link_device(ev, ev["staff"][0]["team"], "ANDROID-someone-else")[1], {})

    def test_errors_are_reported_not_raised(self):
        w = self.watcher()
        self.assertFalse(w.handle(pli("CC-999", NOW)))
        self.assertIn("CC-999", w.last_error)
        w = self.watcher(assigned=False)
        self.assertFalse(w.handle(pli("CC-001", NOW)))                          # not on the call: no log line
        self.assertEqual(self.store.writes, 0)


class StreamTest(unittest.TestCase):
    def test_tak_stream_is_split_into_events(self):
        got = []
        client = TakClient("127.0.0.1", 1, "c", "k", "a", on_message=got.append)
        one, two = pli("CC-001", 1), pli("CC-002", 2)
        stream = b'<?xml version="1.0"?>' + one + two
        client._feed(stream[:50])
        client._feed(stream[50:-10])
        client._feed(stream[-10:])
        self.assertEqual(got, [one, two])

    def test_handler_errors_never_break_the_link(self):
        client = TakClient("127.0.0.1", 1, "c", "k", "a", on_message=lambda m: 1 / 0)
        client._feed(pli("CC-001", 1))
        self.assertIn("ZeroDivisionError", client.last_error)


if __name__ == "__main__":
    unittest.main()
