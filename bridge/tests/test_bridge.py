"""Publisher send rules and the PocketBase client, with fakes (no network)."""

import io
import json
import unittest
import urllib.error
import xml.etree.ElementTree as ET

from crowdcad_tak import config
from crowdcad_tak.bridge import Publisher
from crowdcad_tak.pocketbase import PocketBase, PocketBaseError, iter_sse

from test_mapping import EID, demo

C1 = f"crowdcad-{EID}-call-c1"


class Clock:
    def __init__(self, ms=1794701000000):
        self.ms = ms

    def __call__(self):
        return self.ms


def publisher(**overrides):
    sent, clock = [], Clock()
    pub = Publisher({**config.DEFAULTS, **overrides}, sent.append, clock)
    return pub, sent, clock


def by_uid(messages):
    return {ET.fromstring(m).get("uid"): ET.fromstring(m) for m in messages}


class PublisherTest(unittest.TestCase):
    def test_first_apply_sends_live_items_only(self):
        pub, sent, _ = publisher()
        pub.apply(demo())
        uids = set(by_uid(sent))
        self.assertIn(C1, uids)
        self.assertNotIn(f"crowdcad-{EID}-call-c3", uids)   # already Delivered when first seen
        self.assertEqual(len(sent), len(uids))
        status = pub.status()["events"][0]
        self.assertEqual(status["counts"], {"incident": 2, "unit": 3, "zone": 1, "post": 0})
        self.assertEqual(len(status["unplaced"]), 2)

    def test_unchanged_record_sends_nothing(self):
        pub, sent, clock = publisher()
        pub.apply(demo())
        before = len(sent)
        clock.ms += 5000
        self.assertEqual(pub.apply(demo()), 0)
        self.assertEqual(len(sent), before)

    def test_change_bumps_updated_heartbeat_keeps_it(self):
        pub, sent, clock = publisher()
        pub.apply(demo())
        clock.ms += 1000
        event = demo()
        event["staff"][0]["status"] = "Transporting"
        sent.clear()
        pub.apply(event)
        changed = by_uid(sent)
        self.assertEqual(changed[C1].find("detail/__iucad_incident").get("status"), "TRAN")
        self.assertEqual(changed[C1].find("detail/__iucad_incident").get("updated"), str(clock.ms))
        self.assertEqual(changed[C1].find("detail/__iucad_incident").get("created"), "1794700800000")
        self.assertEqual(set(changed), {C1, f"crowdcad-{EID}-team-team-1"})
        sent.clear()
        clock.ms += 120000
        pub.heartbeat()
        again = by_uid(sent)[C1]
        self.assertEqual(again.find("detail/__iucad_incident").get("updated"), str(clock.ms - 120000))
        self.assertNotEqual(again.get("time"), changed[C1].get("time"))

    def test_updated_strictly_increases_within_one_ms(self):
        pub, sent, _ = publisher()
        pub.apply(demo())
        first = by_uid(sent)[C1].find("detail/__iucad_incident").get("updated")
        event = demo()
        event["calls"][0]["chiefComplaint"] = "Chest pain, diaphoretic"
        sent.clear()
        pub.apply(event)                                   # same clock ms
        self.assertEqual(int(by_uid(sent)[C1].find("detail/__iucad_incident").get("updated")), int(first) + 1)

    def test_resolving_a_call_closes_it_once(self):
        pub, sent, clock = publisher()
        pub.apply(demo())
        event = demo()
        event["calls"][0]["status"] = "Treat and Release"
        sent.clear()
        clock.ms += 1000
        pub.apply(event)
        closed = by_uid(sent)[C1]
        self.assertEqual(closed.find("detail/__iucad_incident").get("status"), "CLOSED")
        sent.clear()
        pub.heartbeat()
        self.assertNotIn(C1, by_uid(sent))                 # done: no longer refreshed
        pub.apply(event)
        self.assertNotIn(C1, by_uid(sent))

    def test_reopened_call_comes_back(self):
        pub, sent, _ = publisher()
        event = demo()
        event["calls"][0]["status"] = "Resolved"
        pub.apply(event)
        self.assertNotIn(C1, by_uid(sent))
        pub.apply(demo())
        self.assertEqual(by_uid(sent)[C1].find("detail/__iucad_incident").get("status"), "ONSC")

    def test_deleted_call_and_team_are_closed(self):
        pub, sent, _ = publisher()
        pub.apply(demo())
        event = demo()
        del event["calls"][0]
        del event["staff"][1]
        sent.clear()
        pub.apply(event)
        out = by_uid(sent)
        self.assertEqual(out[C1].find("detail/__iucad_incident").get("status"), "CLOSED")
        self.assertIn(f"crowdcad-{EID}-team-team-2", out)

    def test_event_ended_or_deleted_clears_the_map(self):
        for action in ("ended", "delete", "unselected"):
            pub, sent, _ = publisher()
            pub.on_change("update", demo())
            live = {u for u, e in pub.sent.items() if not e["done"]}
            sent.clear()
            event = demo()
            if action == "ended":
                event["ended"] = True
            elif action == "unselected":
                event["status"] = "draft"
            pub.on_change("delete" if action == "delete" else "update", event)
            out = by_uid(sent)
            # every live marker: its CLOSED message, then TAK's delete for it (t-x-d-d + __forcedelete)
            self.assertEqual({u for u in out if not u.endswith(".delete")}, live, action)
            self.assertEqual({u for u in out if u.endswith(".delete")}, {u + ".delete" for u in live}, action)
            for uid in live:
                delete = out[uid + ".delete"]
                self.assertEqual((delete.get("type"), delete.find("detail/link").get("uid")), ("t-x-d-d", uid), action)
                self.assertIsNotNone(delete.find("detail/__forcedelete"), action)
            self.assertTrue(all(e["done"] for e in pub.sent.values()), action)
            self.assertEqual(pub.status()["events"], [], action)

    def test_closed_call_is_deleted_from_every_map_right_after_closing(self):
        pub, sent, clock = publisher()
        pub.apply(demo())
        sent.clear()
        event = demo()
        event["calls"][0]["status"] = "Resolved"              # c1 closed in CrowdCAD
        clock.ms += 1000
        pub.apply(event)
        uids = [ET.fromstring(m).get("uid") for m in sent]
        self.assertEqual(uids[uids.index(C1) + 1], C1 + ".delete")   # CLOSED first, then the delete
        self.assertEqual(by_uid(sent)[C1].find("detail/__iucad_incident").get("status"), "CLOSED")
        pub.heartbeat()
        self.assertNotIn(C1, [ET.fromstring(m).get("uid") for m in sent[len(uids):]])   # never re-sent

    def test_roster_tells_phones_their_status(self):
        pub, sent, clock = publisher(team_uids={"Team 3": "ANDROID-t3"})
        pub.apply(demo())
        roster = [ET.fromstring(m) for m in sent if ET.fromstring(m).get("type") == "t-x-crowdcad-roster"]
        self.assertEqual(len(roster), 1)
        units = {u.get("uid"): (u.get("status"), u.get("name")) for u in roster[0].iter("unit")}
        self.assertEqual(units, {"ANDROID-t3": ("RESP", "Team 3")})
        self.assertEqual(roster[0].find("detail/__crowdcad_roster").get("alert"), "soft")   # default sound
        sent.clear()
        pub.apply(demo())                                          # unchanged: not re-sent
        self.assertFalse(any("roster" in m for m in sent))
        pub.heartbeat()                                            # but refreshed with the heartbeat
        self.assertTrue(any("t-x-crowdcad-roster" in m for m in sent))

    def test_roster_carries_open_supervisor_request_until_cleared(self):
        from crowdcad_tak.calldetails import CallDetails
        details, sent, clock = CallDetails(), [], Clock()
        pub = Publisher({**config.DEFAULTS, "team_uids": {"Team 3": "ANDROID-t3"}}, sent.append, clock,
                        details=details)
        pub.apply(demo())

        def last_unit():
            rosters = [ET.fromstring(m) for m in sent if "t-x-crowdcad-roster" in m]
            return next(rosters[-1].iter("unit"))

        self.assertIsNone(last_unit().get("supreq"))
        sent.clear()
        at = clock.ms - 5000
        details.add_supreq({"id": f"ANDROID-t3-{at}", "event": EID, "unit": "Team 3", "callsign": "Medic1",
                            "uid": "ANDROID-t3", "at": at, "lat": 0.0, "lon": 0.0, "cleared": False})
        self.assertEqual(last_unit().get("supreq"), str(at))        # re-sent at once, not on the heartbeat
        sent.clear()
        details.clear_supreq(f"ANDROID-t3-{at}")
        self.assertIsNone(last_unit().get("supreq"))                # cleared: the phone shows it was seen
        details.add_supreq({"id": "old", "uid": "ANDROID-t3", "at": clock.ms - 2 * 3600_000, "cleared": False})
        self.assertIsNone(last_unit().get("supreq"))                # over an hour old: no longer open

    def test_delete_can_be_switched_off(self):
        pub, sent, clock = publisher(delete_closed=False)
        pub.apply(demo())
        event = demo()
        event["calls"][0]["status"] = "Resolved"
        pub.apply(event)
        self.assertFalse(any(ET.fromstring(m).get("type") == "t-x-d-d" for m in sent))

    def test_resync_retires_events_missing_from_listing(self):
        pub, sent, _ = publisher()
        pub.resync([demo()])
        sent.clear()
        pub.resync([])
        self.assertIn(C1, by_uid(sent))
        self.assertEqual(pub.status()["events"], [])

    def test_crowdcad_clock_ahead_never_gives_updated_before_created(self):
        pub, sent, clock = publisher()
        clock.ms = 1794700000000                           # bridge clock behind the call's log
        pub.apply(demo())
        inc = by_uid(sent)[C1].find("detail/__iucad_incident")
        self.assertGreaterEqual(int(inc.get("updated")), int(inc.get("created")))

    def test_explicit_event_selection(self):
        pub, sent, _ = publisher(events=["zzzzzzzzzzzzzzz"])
        pub.on_change("update", demo())
        self.assertEqual(sent, [])


class FakeTak:
    host, port, connected, last_error, on_connect = "127.0.0.1", 8089, True, None, None

    def __init__(self):
        self.messages, self.sent = [], 0

    def send(self, xml):
        self.messages.append(xml)

    def start(self):
        pass

    def stop(self):
        pass


class FakePocketBase:
    """First realtime session: subscribe, then one live change; then the stream fails, so the
    runner must fall back to a polling resync — which sees the event has ended."""
    base = "http://pb.test"

    def __init__(self, runner_ref):
        self.runner_ref, self.sessions, self.listings = runner_ref, 0, 0

    def list_events(self, selection):
        self.listings += 1
        return [demo()] if self.listings == 1 else []

    def realtime(self, topics, on_record, on_connect=None):
        self.sessions += 1
        if self.sessions == 1:
            on_connect()
            changed = demo()
            changed["calls"][1]["assignedTeam"] = ["Team 2"]
            on_record("update", changed)
            raise PocketBaseError("realtime stream: reset")
        self.runner_ref[0].stop()
        raise PocketBaseError("stopping")


class RunnerTest(unittest.TestCase):
    def test_live_then_polling_fallback(self):
        from crowdcad_tak.bridge import Runner
        ref = []
        tak = FakeTak()
        runner = Runner({**config.DEFAULTS, "heartbeat_seconds": 3600}, FakePocketBase(ref), tak)
        ref.append(runner)
        runner.run()
        statuses = [ET.fromstring(m).find("detail/__iucad_incident") for m in tak.messages]
        c2 = [s.get("status") for s in statuses if s is not None and s.get("id") == "CC-008"]
        self.assertEqual(c2, ["NEW", "DISP", "CLOSED"])    # snapshot, live change, event gone on resync
        self.assertEqual(runner.status()["crowdcad"]["mode"], "polling")
        self.assertIs(tak.on_connect.__self__, runner.publisher)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeServer:
    """Answers PocketBase REST calls from a route table; records every request."""

    def __init__(self, routes):
        self.routes, self.requests = routes, []

    def __call__(self, request, timeout=None):
        body = json.loads(request.data) if request.data else None
        self.requests.append((request.get_method(), request.full_url, dict(request.headers), body))
        for (method, prefix), answer in self.routes.items():
            if request.get_method() == method and request.full_url.startswith(prefix):
                answer = answer(request) if callable(answer) else answer
                if isinstance(answer, int):
                    raise urllib.error.HTTPError(request.full_url, answer, "err", {}, io.BytesIO(b'{"message":"nope"}'))
                return FakeResponse(answer if isinstance(answer, bytes) else json.dumps(answer).encode())
        raise AssertionError(f"unexpected {request.get_method()} {request.full_url}")


BASE = "http://pb.test:8090"
AUTH = {("POST", f"{BASE}/api/collections/users/auth-with-password"): {"token": "T1", "record": {}}}


class PocketBaseTest(unittest.TestCase):
    def test_iter_sse(self):
        lines = [b"id: 1\n", b"event: PB_CONNECT\n", b'data: {"clientId":"abc"}\n', b"\n",
                 b": keep-alive\n", b"event: events/*\n", b"data: {\"a\":\n", b"data: 1}\n", b"\n"]
        self.assertEqual(list(iter_sse(lines)), [("PB_CONNECT", '{"clientId":"abc"}'), ("events/*", '{"a":\n1}')])

    def test_list_active_events_pages_and_auths(self):
        pages = iter([{"items": [{"id": "a"}], "totalPages": 2}, {"items": [{"id": "b"}], "totalPages": 2}])
        server = FakeServer({**AUTH, ("GET", f"{BASE}/api/collections/events/records"): lambda r: next(pages)})
        pb = PocketBase(BASE + "/", "bridge@x.org", "pw", urlopen=server)
        self.assertEqual([e["id"] for e in pb.list_events("active")], ["a", "b"])
        method, url, headers, body = server.requests[1]
        self.assertIn("filter=%28status%3D%27active%27+%26%26+ended%21%3Dtrue%29", url)
        self.assertEqual(headers["Authorization"], "Bearer T1")
        self.assertEqual(server.requests[0][3], {"identity": "bridge@x.org", "password": "pw"})
        self.assertEqual(sum(1 for r in server.requests if "auth-with-password" in r[1]), 1)

    def test_event_id_list_refuses_filter_injection(self):
        server = FakeServer({**AUTH, ("GET", f"{BASE}/api/collections/events/records"): {"items": [], "totalPages": 1}})
        pb = PocketBase(BASE, "u", "p", urlopen=server)
        self.assertEqual(pb.list_events(["x' || id!='"]), [])
        pb.list_events(["e1f2g3h4i5j6k7l", "bad id"])
        self.assertIn("id%3D%27e1f2g3h4i5j6k7l%27%29", server.requests[-1][1])
        self.assertNotIn("bad", server.requests[-1][1])

    def test_expired_token_reauths_once(self):
        calls = iter([401, {"items": [], "totalPages": 1}])
        server = FakeServer({**AUTH, ("GET", f"{BASE}/api/collections/events/records"): lambda r: next(calls)})
        pb = PocketBase(BASE, "u", "p", urlopen=server)
        self.assertEqual(pb.list_events(), [])
        self.assertEqual(sum(1 for r in server.requests if "auth-with-password" in r[1]), 2)

    def test_bad_password_is_a_clear_error(self):
        server = FakeServer({("POST", f"{BASE}/api/collections/users/auth-with-password"): 400})
        with self.assertRaisesRegex(PocketBaseError, "400 nope"):
            PocketBase(BASE, "u", "bad", urlopen=server).list_events()

    def test_realtime_subscribes_then_delivers_records(self):
        stream = (b'event: PB_CONNECT\ndata: {"clientId":"cid"}\n\n'
                  b'event: events/*\ndata: {"action":"update","record":{"id":"e1"}}\n\n'
                  b'event: events/*\ndata: not json\n\n')
        server = FakeServer({**AUTH, ("GET", f"{BASE}/api/realtime"): stream, ("POST", f"{BASE}/api/realtime"): b""})
        got, connected = [], []
        PocketBase(BASE, "u", "p", urlopen=server).realtime(
            ["events/*"], lambda a, r: got.append((a, r["id"])), on_connect=lambda: connected.append(True))
        subscribe = [r for r in server.requests if r[0] == "POST" and r[1].endswith("/api/realtime")][0]
        self.assertEqual(subscribe[3], {"clientId": "cid", "subscriptions": ["events/*"]})
        self.assertEqual(subscribe[2]["Authorization"], "Bearer T1")
        self.assertEqual((got, connected), ([("update", "e1")], [True]))

    def test_rejects_non_http_url(self):
        with self.assertRaises(PocketBaseError):
            PocketBase("file:///etc/passwd", "u", "p")


if __name__ == "__main__":
    unittest.main()
