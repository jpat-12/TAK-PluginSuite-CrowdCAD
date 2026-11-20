"""Field status: a medic's taps in the ATAK CrowdCAD plugin → CrowdCAD (docs/PLAN.md Phase 4).

The ATAK plugin puts the device's own unit status on its position report as
<__iucad_unit status=… incident=… since=…> (StatusReporter.java; IU Event CAD's format). The
bridge already receives every report in its TAK group; for a device that carries a CrowdCAD unit
(its `takUid`, or the console's team_uids) a NEW tap — `since` changed — becomes the matching
CrowdCAD dispatch action, through dispatch.py and store.py like any CloudTAK dispatch:

    Responding / On scene / Transporting  →  En Route / On Scene / Transporting on that incident
                                             (assigned to it first if dispatch hadn't: self-dispatch)
    Available        on a call            →  Detached from the call (CrowdCAD closes it "Resolved"
                                             if it was the last unit), back Available at its post
                     not on a call        →  Available
    Out of service   not on a call        →  On Break   (on a call: ignored; dispatch decides)

A phone no unit is linked to yet (not picked as a contact when the event was made, e.g. an event
made in CrowdCAD) links itself on its first tap: if its ATAK callsign matches exactly one free unit
name across the live events ("Team 1" ↔ TEAM1), that unit's `takUid` is set to the phone in the
same write as the tap (claim_by_callsign; anyone in the bridge's TAK group can dispatch anyway).
From then on it is an ordinary device unit: no bridge marker, "last heard" on the boards.

Only taps count: the position report repeats its status every few seconds, so a dispatcher's
later change in CrowdCAD is never undone by a stale report. A tap older than FRESH_MS when the
bridge first sees that device (e.g. after a bridge restart) is not replayed. Logs say
"via ATAK: <callsign>".
"""

import queue
import re
import threading
import time
import xml.etree.ElementTree as ET

from . import dispatch, mapping
from .dispatch import Clock, DispatchError

ON_CALL = {"RESP": "En Route", "ONSC": "On Scene", "TRAN": "Transporting"}
FRESH_MS = 120_000
EVENT_UID = re.compile(rb'<event\b[^>]*?\buid="([^"]{1,200})"')
WATCH_REFRESH_S = 10


def parse(message):
    """bytes of one CoT <event> → {uid, callsign, status, incident, since} or None."""
    if b"__iucad_unit" not in message or b"<!DOCTYPE" in message or b"<!ENTITY" in message:
        return None
    try:
        root = ET.fromstring(message)
    except ET.ParseError:
        return None
    unit = root.find("detail/__iucad_unit")
    if unit is None or not root.get("uid"):
        return None
    try:
        since = int(float(unit.get("since") or 0))
    except ValueError:
        return None
    contact = root.find("detail/contact")
    return {"uid": root.get("uid"), "callsign": (contact.get("callsign") if contact is not None else None) or root.get("uid"),
            "status": unit.get("status"), "incident": unit.get("incident") or "", "since": since}


def _merge(event, patch, more):
    patch = {**patch, **more}
    return {**event, **patch}, patch


def plan(event, config, unit_name, report, actor, clock):
    """→ the PATCH for this tap (possibly {} when CrowdCAD already says so). Raises DispatchError
    when the tap can't be applied (unknown incident, closed call)."""
    status = report.get("status")
    calls = event.get("calls") or []
    open_calls = [c for c in calls if c.get("status") not in dispatch.RESOLVED_CALL_STATUSES]
    mine = [c for c in open_calls if unit_name in (c.get("assignedTeam") or [])]
    prefix = mapping._id_prefix(event, config)

    def unit_status(ev):
        return next((u.get("status") for u in (ev.get("staff") or []) + (ev.get("supervisor") or [])
                     if u.get("team") == unit_name), None)

    patch, ev = {}, event
    if status in ON_CALL:
        incident = report.get("incident")
        if incident:
            target = next((c for c in calls if mapping.incident_id(c, prefix) == incident), None)
            if target is None:
                raise DispatchError(f"{incident} isn't a call in this event")
        else:
            target = mine[0] if mine else None
            if target is None:
                raise DispatchError(f"{unit_name} tapped {status} but isn't on a call")
        if unit_name not in (target.get("assignedTeam") or []):
            ev, patch = _merge(ev, patch, dispatch.assign(ev, target["id"], unit_name, actor, clock))
        wanted = ON_CALL[status]
        if unit_status(ev) != wanted:
            ev, patch = _merge(ev, patch, dispatch.status_on_call(ev, target["id"], unit_name, wanted, actor, clock))
        return patch
    if status == "AVL":
        if mine:
            for call in mine:
                ev, patch = _merge(ev, patch, dispatch.status_on_call(ev, call["id"], unit_name, "Detached", actor, clock))
            return patch
        return dispatch.unit_status(ev, unit_name, "Available", actor, clock) if unit_status(ev) != "Available" else {}
    if status == "OOS":
        if mine or unit_status(ev) == "On Break":
            return {}
        return dispatch.unit_status(ev, unit_name, "On Break", actor, clock)
    return {}


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
    """Consumes inbound CoT (TakClient.on_message) on its own thread and applies taps."""

    def __init__(self, publisher, store, config, log=print, now_ms=None):
        self.publisher, self.store, self.config, self.log = publisher, store, config, log
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.seen = {}                      # device uid → last `since` acted on (or skipped)
        self.heard = {}                     # device uid → ms of its last message of any kind (board "last heard")
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
        if b"__iucad_unit" in message:
            try:
                self._queue.put_nowait(message)
            except queue.Full:
                pass

    def start(self):
        self._thread = threading.Thread(target=self._run, name="field-status", daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            self.handle(self._queue.get())

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
        if not report or report["status"] not in (*ON_CALL, "AVL", "OOS"):
            return None
        bound = self.binding(report["uid"])
        claim = False
        if not bound:
            bound = self.claimable(report["uid"], report["callsign"])
            if not bound:
                return None
            claim = True
        last = self.seen.get(report["uid"])
        self.seen[report["uid"]] = report["since"]
        if last == report["since"]:
            return None                                       # the same tap, repeated on every PLI
        if last is None and self.now_ms() - report["since"] > FRESH_MS:
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
            if claim:
                self.heard[report["uid"]] = self.now_ms()
                self._watch_at = 0.0                        # watch it for "last heard" right away
            self.log(f"field status: {unit} ({report['callsign']}) tapped {report['status']}"
                     f"{' on ' + report['incident'] if report['incident'] else ''} → CrowdCAD"
                     f"{' (linked ' + report['uid'] + ' to ' + unit + ' by callsign)' if claim else ''}")
            return True
        except DispatchError as error:
            self.last_error = str(error)
            self.log(f"field status: {unit} tapped {report['status']}: not applied ({error})")
        except Exception as error:   # PocketBase down etc.: logged, next tap tries again
            self.last_error = repr(error)
            self.log(f"field status: {unit} tapped {report['status']}: CrowdCAD write failed ({error})")
        return False
