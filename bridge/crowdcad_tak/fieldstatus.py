"""Field acknowledgements: a medic's Acknowledge tap in the ATAK CrowdCAD plugin → CrowdCAD.

Field users can't change status (Jon, 2026-11-25). Status is dispatch's, set in CrowdCAD or the
CloudTAK dispatch console. A medic can only acknowledge a call they are assigned to:

    ATAK plugin  →  <__crowdcad_ack incident="CC-007" at="<ms>"/> on the phone's position report
    bridge       →  one line in that call's CrowdCAD log: "1402 - Team 1 acknowledged the call.
                    (via ATAK: MEDIC1)". Call and team status are left alone.

The bridge already receives every report in its TAK group. A device that carries a CrowdCAD unit
(its `takUid`, or the console's team_uids) is bound to it. A phone no unit is linked to yet links
itself on its first acknowledgement: if its ATAK callsign matches exactly one free unit name across
the live events ("Team 1" ↔ TEAM1), that unit's `takUid` is set to the phone in the same write
(claim_by_callsign). The plugin offers Acknowledge on a call whose bridge unit uid ends in that
callsign, so an unlinked phone can get there.

Only new taps count: the report repeats its last ack every few seconds, so `at` must change. An ack
older than FRESH_MS when the bridge first sees that device (e.g. after a bridge restart) is not
replayed. The <__iucad_unit> status taps from plugins before 0.1.6 are ignored.
"""

import queue
import re
import threading
import time
import xml.etree.ElementTree as ET

from . import dispatch, mapping
from .dispatch import Clock, DispatchError

ACK = "__crowdcad_ack"
SUPREQ = "__crowdcad_supreq"          # Request Supervisor (ATAK plugin, confirmed twice on the phone)
SUPREQ_AT = re.compile(rb'<__crowdcad_supreq\b[^>]*?\bat="(\d{1,15})"')
CALLSIGN = re.compile(rb'<contact\b[^>]*?\bcallsign="([^"]{1,80})"')
FRESH_MS = 120_000
EVENT_UID = re.compile(rb'<event\b[^>]*?\buid="([^"]{1,200})"')
DESIGNATION = re.compile(rb'<__crowdcad_unit\b[^>]*?\bdesignation="(ALS|BLS|SUP)"')
POINT = re.compile(rb'<point\b[^>]*?\blat="(-?[0-9.]{1,20})"[^>]*?\blon="(-?[0-9.]{1,20})"')
WATCH_REFRESH_S = 10


def parse(message):
    """bytes of one CoT <event> → {uid, callsign, incident, at} or None."""
    if ACK.encode() not in message or b"<!DOCTYPE" in message or b"<!ENTITY" in message:
        return None
    try:
        root = ET.fromstring(message)
    except ET.ParseError:
        return None
    ack = root.find(f"detail/{ACK}")
    if ack is None or not root.get("uid") or not (ack.get("incident") or "").strip():
        return None
    try:
        at = int(float(ack.get("at") or 0))
    except ValueError:
        return None
    if at <= 0:
        return None
    contact = root.find("detail/contact")
    return {"uid": root.get("uid"), "callsign": (contact.get("callsign") if contact is not None else None) or root.get("uid"),
            "incident": ack.get("incident").strip(), "at": at}


def plan(event, config, unit_name, report, actor, clock):
    """→ the PATCH for this acknowledgement. Raises DispatchError when it can't be applied
    (unknown incident, closed call, unit no longer on it)."""
    prefix = mapping._id_prefix(event, config)
    target = next((c for c in event.get("calls") or [] if mapping.incident_id(c, prefix) == report["incident"]), None)
    if target is None:
        raise DispatchError(f"{report['incident']} isn't a call in this event")
    return dispatch.acknowledge(event, target["id"], unit_name, actor, clock)


def link_device(event, unit_name, uid):
    """→ (event with `unit_name` carried by phone `uid`, the patch saying so). Re-checked on the
    fresh record inside the write, so two phones can't both claim one unit."""
    for key in ("staff", "supervisor"):
        entries = event.get(key) or []
        for i, entry in enumerate(entries):
            if entry.get("team") != unit_name:
                continue
            current = entry.get("takUid")
            if current and current != uid:
                raise DispatchError(f"{unit_name} is already linked to another device")
            if current == uid:
                return event, {}
            entries = [*entries[:i], {**entry, "takUid": uid}, *entries[i + 1:]]
            return {**event, key: entries}, {key: entries}
    raise DispatchError(f"{unit_name} isn't a unit in this event")


class FieldStatus:
    """Consumes inbound CoT (TakClient.on_message) on its own thread and applies acknowledgements."""

    def __init__(self, publisher, store, config, log=print, now_ms=None):
        self.publisher, self.store, self.config, self.log = publisher, store, config, log
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.seen = {}                      # device uid → last ack `at` acted on (or skipped)
        self.heard = {}                     # device uid → ms of its last message of any kind (board "last heard")
        self.positions = {}                 # device uid → (lat, lon) of its last report with a fix (board radar)
        self.designations = {}              # device uid → ALS / BLS / SUP from its ATAK plugin Settings
        self.seen_supreq = {}               # device uid → last supervisor request `at` acted on
        self._watch, self._watch_at = set(), 0.0
        self.applied = 0
        self.last_error = None
        self._queue = queue.Queue(maxsize=2000)
        self._thread = None

    def _watched(self):
        if time.monotonic() - self._watch_at > WATCH_REFRESH_S:
            with self.publisher.lock:
                self._watch = {t.get("uid") for info in self.publisher.events.values()
                               for t in info.get("device_teams") or [] if t.get("uid")}
            self._watch_at = time.monotonic()
        return self._watch

    def offer(self, message):
        """TakClient's thread: cheap filter + enqueue, never block."""
        found = EVENT_UID.search(message[:1000])
        if found:
            uid = found.group(1).decode("utf-8", "replace")
            if uid in self._watched():
                self.heard[uid] = self.now_ms()
                designation = DESIGNATION.search(message)
                if designation:
                    self.designations[uid] = designation.group(1).decode()
                point = POINT.search(message[:2000])
                if point:
                    try:
                        lat, lon = float(point.group(1)), float(point.group(2))
                    except ValueError:
                        lat = lon = 0.0
                    if (lat, lon) != (0.0, 0.0) and abs(lat) <= 90 and abs(lon) <= 180:   # 0,0 = no GPS fix yet
                        self.positions[uid] = (lat, lon)
        if SUPREQ.encode() in message:
            try:
                self._queue.put_nowait(message)
            except queue.Full:
                pass
            return
        if ACK.encode() in message:
            try:
                self._queue.put_nowait(message)
            except queue.Full:
                pass

    def start(self):
        self._thread = threading.Thread(target=self._run, name="field-status", daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            message = self._queue.get()
            try:
                if SUPREQ.encode() in message:
                    self.handle_supreq(message)
                if ACK.encode() in message:
                    self.handle(message)
            except Exception as error:   # never let the field thread die: log and keep reading
                self.log(f"field message not handled: {error!r}")

    def handle_supreq(self, message):
        """Request Supervisor: a GeoChat DM to every supervisor phone of the event, and a request on
        the dispatcher's board until a dispatcher clears it. A repeated `at` (every PLI) is ignored."""
        uid_m, at_m = EVENT_UID.search(message[:1000]), SUPREQ_AT.search(message)
        if not uid_m or not at_m:
            return None
        uid, at = uid_m.group(1).decode("utf-8", "replace"), int(at_m.group(1))
        last = self.seen_supreq.get(uid)
        self.seen_supreq[uid] = at
        if last == at or (last is None and self.now_ms() - at > FRESH_MS):
            return None
        cs_m = CALLSIGN.search(message)
        callsign = cs_m.group(1).decode("utf-8", "replace") if cs_m else uid
        point = POINT.search(message[:2000])
        lat, lon = (float(point.group(1)), float(point.group(2))) if point else (0.0, 0.0)
        bound = self.binding(uid)
        with self.publisher.lock:
            events = {eid: info for eid, info in self.publisher.events.items() if not info.get("ended")}
        eid, unit = bound if bound else (next(iter(events), None), callsign)
        if eid is None:
            return None
        request = {"id": f"{uid}-{at}", "event": eid, "unit": unit, "callsign": callsign, "uid": uid, "at": at,
                   "lat": lat, "lon": lon, "cleared": False}
        details = getattr(self.publisher, "details", None)
        if details is not None:
            details.add_supreq(request)
        from . import cot   # local: cot imports nothing from here; keeps the module graph flat
        text = f"SUPERVISOR REQUESTED by {unit} ({callsign})" + (f" at {lat:.5f}, {lon:.5f}" if point else "")
        sent = 0
        for team in (events.get(eid) or {}).get("device_teams") or []:
            if team.get("supervisor") and team.get("uid") and team["uid"] != uid:
                self.publisher.send(cot.render_chat(team["uid"], team["name"], text, f"supreq-{uid}-{at}", self.now_ms()))
                sent += 1
        self.log(f"supervisor request: {unit} ({callsign}) → {sent} supervisor phone(s) + dispatch")
        return sent

    def binding(self, uid):
        """device uid → (event id, unit name) of a live event, or None."""
        with self.publisher.lock:
            for eid, info in self.publisher.events.items():
                if info.get("ended"):
                    continue
                for team in info.get("device_teams") or []:
                    if team.get("uid") == uid:
                        return eid, team["name"]
        return None

    def claimable(self, uid, callsign):
        """An unlinked phone → (event id, unit name) of the one free unit its callsign names, or None."""
        key = mapping.callsign_key(callsign)
        if not self.config.get("claim_by_callsign", True) or not key or not mapping.TAK_UID.match(uid or ""):
            return None
        with self.publisher.lock:
            hits = [(eid, name) for eid, info in self.publisher.events.items() if not info.get("ended")
                    for name in info.get("free_units") or [] if mapping.callsign_key(name) == key]
        return hits[0] if len(hits) == 1 else None

    def handle(self, message):
        report = parse(message)
        if not report:
            return None
        bound = self.binding(report["uid"])
        claim = False
        if not bound:
            bound = self.claimable(report["uid"], report["callsign"])
            if not bound:
                return None
            claim = True
        last = self.seen.get(report["uid"])
        self.seen[report["uid"]] = report["at"]
        if last == report["at"]:
            return None                                       # the same tap, repeated on every PLI
        if last is None and self.now_ms() - report["at"] > FRESH_MS:
            return None                                       # an old tap, first seen after a restart
        eid, unit = bound
        actor = f"ATAK: {report['callsign']}"
        clock = Clock(timezone=self.config.get("timezone") or "")
        def action(ev):
            if not claim:
                return plan(ev, self.config, unit, report, actor, clock)
            ev, link = link_device(ev, unit, report["uid"])
            return {**link, **plan(ev, self.config, unit, report, actor, clock)}

        try:
            self.store.apply(eid, action)
            self.applied += 1
            details = getattr(self.publisher, "details", None)
            if details is not None:
                # Tasked → Responding on every board, and the dispatcher's "acknowledged" banner.
                details.put_ack(eid, report["incident"], unit, report["at"])
            if claim:
                self.heard[report["uid"]] = self.now_ms()
                self._watch_at = 0.0                        # watch it for "last heard" right away
            self.log(f"field ack: {unit} ({report['callsign']}) acknowledged {report['incident']} → CrowdCAD log"
                     f"{' (linked ' + report['uid'] + ' to ' + unit + ' by callsign)' if claim else ''}")
            return True
        except DispatchError as error:
            self.last_error = str(error)
            self.log(f"field ack: {unit} on {report['incident']}: not applied ({error})")
        except Exception as error:   # PocketBase down etc.: logged, not raised; the CoT link must survive
            self.last_error = repr(error)
            self.log(f"field ack: {unit} on {report['incident']}: CrowdCAD write failed ({error})")
        return False
