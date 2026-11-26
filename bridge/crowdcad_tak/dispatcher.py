"""The CloudTAK dispatcher's backend: IU EMS Dispatch's board and actions, served from CrowdCAD.

The CloudTAK plugin is a 1:1 copy of IU Event CAD's dispatcher (TAK-PluginSuite-IndianaUniversity/
CloudTAK-Eventcad), so this module speaks exactly what that plugin's bridge spoke
(NodeRED-CAD-Bridge dispatch-api.js) — `{now, incidents, units}` and the same five actions — and
turns each action into CrowdCAD's own handler (dispatch/page.tsx, v1.6.0), written
compare-and-swap through store.py like every other TAK dispatch:

    assign    {id, unitUid}   handleAddTeamToCall            (dispatch.assign)
    unassign  {id, unitUid}   handleRemoveTeamFromCall       (remove_team, below)
    status    DISP|ONSC|TRAN  each assigned unit's status on the call: En Route / On Scene /
                              Transporting (handleTeamStatusChange, dispatch.status_on_call)
              CLOSED          call Resolved, its units freed back to their post (close_call)
              CXL             call Resolved + duplicate (handleResolveDuplicate's shape; the
                              mapping shows duplicate calls as cancelled)
    unit_status {id, unitUid, status}   one unit on the call: RESP/ONSC/TRAN → En Route / On Scene /
                              Transporting on it; AVL → Detached (back Available at its post; the
                              call resolves if it was the last unit, as in CrowdCAD); OOS → Detached,
                              then On Break
    add_unit  {unit}          Add Team / Add Supervisor (handleSaveNewTeam / handleSaveNewSupervisor),
                              optionally carried by a TAK contact's device (takUid)
    remove_unit {unitUid}     handleDeleteTeam / handleDeleteSupervisor: gone from the event, off
                              any open call (Pending if it was the last unit)
    create    {incident}      Add Call (quickcallmodal) + TAK details: the point goes into CrowdCAD's
                              `location` as "lat, lon"; place, floor, what3words into the [TAK]
                              notes line (calldetails.py)

The board is built from the bridge's board (board.py), so it carries nothing the TAK side can't
already see: no age, sex, notes, logs or member names. IU's `notes` field (its complaint text)
is filled with the TAK description, never CrowdCAD's notes.
"""

import copy

from . import mapping
from .dispatch import Clock, DispatchError, _find_call, _find_unit, _replace, _via, add_supervisor, add_team
from .manage import ManageError

ON_CALL = {"DISP": "En Route", "ONSC": "On Scene", "TRAN": "Transporting"}
MAX_TEXT = 120

# The IU plugin's positionWarning() reads these exact strings.
POSITION_FROM = {"post": "table", "coords": "dispatch", "estimate": "table (estimated)", None: "facility"}


def _unit_uid(event_id, unit):
    """Every unit needs a uid in IU's model; a team without a device or marker gets the uid its
    marker would have (mapping.py)."""
    return unit.get("uid") or f"{mapping.event_prefix(event_id)}-team-{mapping.slug(unit.get('callsign'))}"


ACK_FEED_MS = 15 * 60_000      # the dispatcher's "acknowledged" banner looks back this far


def _designation(u):
    """ALS / BLS / SUP column: the phone's own setting, else SUP for a supervisor, else BLS."""
    return u.get("designation") or ("SUP" if u.get("supervisor") else "BLS")


MAX_POLYGONS, MAX_POINTS = 20, 500


def clean_boundaries(polygons):
    """A dispatcher's drawn venue boundaries → [[[lat, lon], ...], ...], validated."""
    if not isinstance(polygons, list) or len(polygons) > MAX_POLYGONS:
        raise ManageError(f"boundaries must be a list of at most {MAX_POLYGONS} polygons")
    out = []
    for poly in polygons:
        if not isinstance(poly, list) or not 3 <= len(poly) <= MAX_POINTS:
            raise ManageError(f"each boundary needs 3 to {MAX_POINTS} points")
        points = []
        for pt in poly:
            try:
                lat, lon = float(pt[0]), float(pt[1])
            except (TypeError, ValueError, IndexError):
                raise ManageError("boundary points are [lat, lon]") from None
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ManageError("boundary point out of range")
            points.append([round(lat, 7), round(lon, 7)])
        out.append(points)
    return out


SUPREQ_SHOW_MS = 60 * 60_000     # an uncleared supervisor request stays on the board this long


def board(board_data, now_ms, acks=None, boundaries=None, supreqs=None):
    """The bridge's board (board.build) → IU's dispatcher board. acks: event id → incident id →
    unit name → ms (calldetails.CallDetails.acks): a phone-carried unit on a call shows TASK
    (tasked, not acknowledged) until its medic acknowledges, then RESP."""
    acks = acks or {}
    incidents, units, history, acked = [], [], [], []
    for event in board_data.get("events") or []:
        eid = event["id"]
        uid_of = {u.get("callsign"): _unit_uid(eid, u) for u in event.get("units") or []}
        for c in event.get("calls") or []:
            if not c.get("callId"):
                continue
            incidents.append({
                "id": c["id"], "cadId": c["callId"], "eventId": eid,
                "status": c.get("status") or "NEW",
                "type": c.get("type") or "Call", "typeAbbrv": (c.get("type") or "")[:4], "medical": True,
                "priority": c.get("priority") or 2,
                "location": c.get("location") or "", "floor": c.get("floor") or 0,
                "eventTitle": event.get("name") or "",
                "notes": c.get("takNotes") or "",                # the dispatcher's TAK notes; never CrowdCAD notes
                "w3w": c.get("w3w") or "",
                "lat": c["lat"] if c.get("lat") is not None else 0.0,
                "lon": c["lon"] if c.get("lon") is not None else 0.0,
                "positionFrom": POSITION_FROM.get(c.get("positionFrom"), "facility"),
                "created": c.get("created") or now_ms, "updated": c.get("updated") or now_ms,
                "assigned": [a.get("uid") or uid_of.get(a.get("callsign")) or a.get("callsign")
                             for a in c.get("assigned") or []],
            })
        event_acks = acks.get(eid) or {}
        for incident_id, by_unit in event_acks.items():
            for name, at in by_unit.items():
                if now_ms - at <= ACK_FEED_MS:
                    acked.append({"unit": name, "incident": incident_id, "at": at})
        for c in event.get("history") or []:
            history.append({"id": c["id"], "status": c.get("status") or "CLOSED", "type": c.get("type") or "Call",
                            "priority": c.get("priority") or 2, "location": c.get("location") or "",
                            "lat": c.get("lat") or 0.0, "lon": c.get("lon") or 0.0,
                            "created": c.get("created") or 0, "updated": c.get("updated") or 0})
        for u in event.get("units") or []:
            status = u.get("status") or "OOS"
            # Assigned but not acknowledged by its phone yet: Tasked. (A unit without a phone can't
            # acknowledge, so it shows CrowdCAD's own status.)
            if u.get("device") and u.get("incident") and status == "RESP" \
                    and u.get("callsign") not in (event_acks.get(u["incident"]) or {}):
                status = "TASK"
            units.append({
                "uid": _unit_uid(eid, u), "callsign": u.get("callsign") or "", "eventId": eid,
                # IU's rule: never default a unit to Available. CrowdCAD statuses with no IU code
                # (Assigned, Delivered, ...) show as out of service until CrowdCAD says more.
                "status": status,
                "designation": _designation(u),
                "incident": u.get("incident") or "",
                "since": u.get("since") or now_ms,
                "lat": u["lat"] if u.get("lat") is not None else 0.0,
                "lon": u["lon"] if u.get("lon") is not None else 0.0,
                # A team at its post is as fresh as CrowdCAD; a phone is as fresh as its last report
                # (0 = never heard: the panel says "not heard yet").
                "seen": (u.get("lastHeard") or 0) if u.get("device") else now_ms,
                "device": bool(u.get("device")),
            })
    return {"now": now_ms, "incidents": incidents, "units": units, "history": history,
            "acks": sorted(acked, key=lambda a: a["at"]), "boundaries": boundaries or [],
            "supRequests": [r for r in (supreqs or []) if not r.get("cleared") and now_ms - r["at"] <= SUPREQ_SHOW_MS]}


# --- CrowdCAD handlers IU needs that dispatch.py doesn't port yet ------------------------------

def remove_team(event, call_id, unit_name, actor=None, clock=None):
    """handleRemoveTeamFromCall: off the call, Available again, the call Pending if it was the last."""
    clock = clock or Clock()
    event = copy.deepcopy(event)
    call = _find_call(event, call_id)
    if unit_name not in (call.get("assignedTeam") or []):
        raise DispatchError(f"{unit_name} isn't on this call", 409)
    kind, unit = _find_unit(event, unit_name)
    number = call.get("order") or "?"
    assigned = call.get("assignedTeam") or []
    new_call = {**call, "assignedTeam": [t for t in assigned if t != unit_name],
                "status": "Pending" if len(assigned) <= 1 else call.get("status"),
                "log": (call.get("log") or []) + [{"timestamp": clock.ms,
                                                   "message": f"{clock.hhmm} - {unit_name} detached from call.{_via(actor)}"}]}
    new_unit = {**unit, "status": "Available",
                "log": (unit.get("log") or []) + [{"timestamp": clock.ms, "message":
                        f"{clock.hhmm} - detached from call #{number} ({call_id}); back to post at {unit.get('location')}"}]}
    return {"calls": _replace(event["calls"], lambda c: c.get("id") == call_id, new_call),
            kind: _replace(event.get(kind), lambda u: u.get("team") == unit_name, new_unit)}


def close_call(event, call_id, actor=None, clock=None, cancel=False):
    """Close (Resolved) or cancel (Resolved + duplicate, handleResolveDuplicate's shape) a call;
    every unit on it is freed back to its post, as CrowdCAD does for a resolved duplicate."""
    clock = clock or Clock()
    event = copy.deepcopy(event)
    call = _find_call(event, call_id)
    if call.get("status") in ("Resolved", "Delivered", "Refusal", "NMM", "Rolled", "Unable to Locate", "Rolled from Scene"):
        raise DispatchError("this call is already closed", 409)
    what = "Resolved, cancelled" if cancel else "Resolved"
    new_call = {**call, "status": "Resolved", "assignedTeam": [],
                "log": (call.get("log") or []) + [{"timestamp": clock.ms, "message": f"{clock.hhmm} - {what}{_via(actor)}"}]}
    if cancel:
        new_call["duplicate"] = True
    patch = {"calls": _replace(event["calls"], lambda c: c.get("id") == call_id, new_call)}
    freed = set(call.get("assignedTeam") or [])
    for kind in ("staff", "supervisor"):
        if any(u.get("team") in freed for u in event.get(kind) or []):
            entry = {"timestamp": clock.ms, "message": f"{clock.hhmm} - freed from call #{call.get('order') or '?'}, back to post"}
            patch[kind] = [{**u, "status": "Available", "location": u.get("originalPost") or u.get("location") or "Unknown",
                            "log": (u.get("log") or []) + [entry]} if u.get("team") in freed else u
                           for u in event.get(kind) or []]
    return patch


def delete_unit(event, unit_name, actor=None, clock=None):
    """handleDeleteTeam (handleDeleteSupervisor for a supervisor): out of the event; every call it
    was on loses it, and a call left with no unit goes back to Pending."""
    clock = clock or Clock()
    event = copy.deepcopy(event)
    kind, _ = _find_unit(event, unit_name)
    calls = []
    for c in event.get("calls") or []:
        if unit_name not in (c.get("assignedTeam") or []):
            calls.append(c)
            continue
        left = [t for t in c.get("assignedTeam") or [] if t != unit_name]
        calls.append({**c, "assignedTeam": left, "status": "Pending" if not left else c.get("status"),
                      "log": (c.get("log") or []) + [{"timestamp": clock.ms, "message":
                              f"{clock.hhmm} - {unit_name} removed ({'team' if kind == 'staff' else 'supervisor'} deleted).{_via(actor)}"}]})
    return {kind: [u for u in event.get(kind) or [] if u.get("team") != unit_name], "calls": calls}


# --- actions -----------------------------------------------------------------------------------

def _text(value, limit=MAX_TEXT):
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


class Dispatcher:
    """IU's POST /iucad/action, against CrowdCAD (manage.Manager does the writes)."""

    def __init__(self, manager, board_source):
        self.manager = manager
        self.board_source = board_source      # () → the bridge's board (board.build), or None

    def _board(self):
        data = self.board_source()
        if data is None:
            raise ManageError("bridge not configured yet", 503)
        return data

    def _incident(self, data, iid):
        for event in data.get("events") or []:
            for c in event.get("calls") or []:
                if c.get("id") == iid and c.get("callId"):
                    return event, c
        raise ManageError(f"{iid} is closed or not on the board", 404)

    @staticmethod
    def _unit_name(event, uid):
        for u in event.get("units") or []:
            if _unit_uid(event["id"], u) == uid:
                return u["callsign"]
        raise ManageError(f"no unit {uid} in {event.get('name')}", 404)

    def board(self, now_ms):
        data = self._board()
        events = data.get("events") or []
        venue = self.manager.details.boundaries(events[0]["id"]) if events else []
        return board(data, now_ms, self.manager.details.acks(), venue, self.manager.details.supreqs())

    def act(self, body, actor):
        if not isinstance(body, dict):
            raise ManageError("body must be a JSON object")
        action = body.get("action")
        name = _text(body.get("dispatcher"), 40)
        if name:
            actor = f"{name} ({actor})"         # "via CloudTAK: Dispatcher1 (jon@…)"
        m, via = self.manager, f"CloudTAK: {actor}"
        if action == "create":
            return self._create(body.get("incident") or {}, actor)
        data = self._board()
        if action == "add_unit":
            return self._add_unit(data, body.get("unit") or {}, actor)
        if action == "clear_supreq":
            self.manager.details.clear_supreq(_text(body.get("id"), 200))
            return {"id": ""}
        if action == "boundaries":
            events = data.get("events") or []
            if not events:
                raise ManageError("no live CrowdCAD event", 409)
            self.manager.details.put_boundaries(events[0]["id"], clean_boundaries(body.get("boundaries") or []))
            return {"id": ""}
        if action == "unit_set":
            return self._unit_set(data, body, actor)
        if action == "remove_unit":
            for event in data.get("events") or []:
                for u in event.get("units") or []:
                    if _unit_uid(event["id"], u) == body.get("unitUid"):
                        name = u["callsign"]
                        m._dispatch(event["id"], f"{name} removed", actor,
                                    lambda ev: delete_unit(ev, name, via, m._clock()))
                        return {"id": ""}
            raise ManageError(f"no unit {body.get('unitUid')} on the board", 404)
        event, call = self._incident(data, body.get("id"))
        eid, cid = event["id"], call["callId"]
        if action == "assign":
            m.assign(eid, cid, {"unit": self._unit_name(event, body.get("unitUid"))}, actor)
        elif action == "unassign":
            name = self._unit_name(event, body.get("unitUid"))
            m._dispatch(eid, f"{name} removed from call {cid}", actor, lambda ev: remove_team(ev, cid, name, via, m._clock()))
        elif action == "unit_status":
            name = self._unit_name(event, body.get("unitUid"))
            status = body.get("status")
            if status == "RESP" and self._waiting_for_ack(data, event, call, body.get("unitUid")):
                raise ManageError(f"{name} hasn't acknowledged {call['id']} yet: Responding comes with the acknowledgement", 409)
            if status in ("RESP", "ONSC", "TRAN"):
                m.status_on_call(eid, cid, {"unit": name, "status": ON_CALL["DISP" if status == "RESP" else status]}, actor)
            elif status in ("AVL", "OOS"):
                m.status_on_call(eid, cid, {"unit": name, "status": "Detached"}, actor)
                if status == "OOS":
                    m.unit_status(eid, {"unit": name, "status": "On Break"}, actor)
            else:
                raise ManageError("status must be AVL, RESP, ONSC, TRAN or OOS")
        elif action == "notes":
            notes = body.get("notes")
            m.call_notes(eid, cid, notes if isinstance(notes, str) else "", actor)
        elif action == "status":
            status = body.get("status")
            if status in ON_CALL:
                names = [a["callsign"] for a in call.get("assigned") or []]
                if not names:
                    raise ManageError("assign a unit first: in CrowdCAD a call's status is its units' status")
                for name in names:
                    try:
                        m.status_on_call(eid, cid, {"unit": name, "status": ON_CALL[status]}, actor)
                    except ManageError as error:
                        if error.status != 409:        # already that status / not on it any more
                            raise
            elif status in ("CLOSED", "CXL"):
                m._dispatch(eid, f"call {cid} {'cancelled' if status == 'CXL' else 'closed'}", actor,
                            lambda ev: close_call(ev, cid, via, m._clock(), cancel=status == "CXL"))
            else:
                raise ManageError("status must be DISP, ONSC, TRAN, CLOSED or CXL")
        else:
            raise ManageError("action must be assign, unassign, unit_status, status, create, add_unit or remove_unit")
        return {"id": call["id"]}

    def _waiting_for_ack(self, data, event, call, uid):
        unit = next((u for u in event.get("units") or [] if _unit_uid(event["id"], u) == uid), None)
        if not unit or not unit.get("device"):
            return False
        return unit["callsign"] not in (self.manager.details.acks(event["id"]).get(call["id"]) or {})

    def _unit_set(self, data, body, actor):
        """A unit's status straight from the board: on a call, its status on that call (as
        unit_status); off a call, Available or On Break (CrowdCAD's handleStatusChange)."""
        uid, status, m = body.get("unitUid"), body.get("status"), self.manager
        for event in data.get("events") or []:
            unit = next((u for u in event.get("units") or [] if _unit_uid(event["id"], u) == uid), None)
            if not unit:
                continue
            name = unit["callsign"]
            call = next((c for c in event.get("calls") or []
                         if c.get("callId") and any(a.get("callsign") == name for a in c.get("assigned") or [])), None)
            if call:
                return self.act({"action": "unit_status", "id": call["id"], "unitUid": uid, "status": status,
                                 "dispatcher": body.get("dispatcher")}, actor)
            if status in ("AVL", "OOS"):
                m.unit_status(event["id"], {"unit": name, "status": "Available" if status == "AVL" else "On Break"}, actor)
                return {"id": ""}
            if status in ("RESP", "ONSC", "TRAN"):
                raise ManageError(f"{name} isn't on a call: assign it to one first")
            raise ManageError("status must be AVL, RESP, ONSC, TRAN or OOS")
        raise ManageError(f"no unit {uid} on the board", 404)

    def _add_unit(self, data, unit, actor):
        """Add Team / Add Supervisor to the event on the board (the first when several are live)."""
        events = data.get("events") or []
        if not events:
            raise ManageError("no live CrowdCAD event to add the unit to", 409)
        eid, m = events[0]["id"], self.manager
        via = f"CloudTAK: {actor}"
        name = _text(unit.get("name"), 80)
        device = {"takUid": unit["takUid"]} if unit.get("takUid") else {}
        if unit.get("kind") == "supervisor":
            form = {"callSign": name, "cert": _text(unit.get("cert"), 40) or "Supervisor", **device}
            m._dispatch(eid, f"supervisor {name!r} added", actor, lambda ev: add_supervisor(ev, form, via, m._clock()))
        else:
            form = {"name": name, "members": [], **device}
            m._dispatch(eid, f"team {name!r} added", actor, lambda ev: add_team(ev, form, via, m._clock()))
        return {"id": ""}

    def _create(self, inc, actor):
        """IU's New incident → CrowdCAD's Add Call, in the event on the board (the first one when
        several are live, the order the board lists them in)."""
        data = self._board()
        events = data.get("events") or []
        if not events:
            raise ManageError("no live CrowdCAD event to add the call to", 409)
        event = events[0]
        kind = _text(inc.get("type"), 60) or "Medical"
        complaint = _text(inc.get("notes"))
        place = _text(inc.get("location"))
        try:
            lat, lon = float(inc.get("lat")), float(inc.get("lon"))
        except (TypeError, ValueError):
            raise ManageError("give the incident's position (lat, lon)") from None
        try:
            priority = min(3, max(1, int(inc.get("priority") or 2)))
        except (TypeError, ValueError):
            raise ManageError("priority must be 1, 2 or 3") from None
        result = self.manager.new_call(event["id"], {
            "location": place,
            "chiefComplaint": f"{kind}: {complaint}"[:MAX_TEXT] if complaint else kind,
            "priority": priority == 1,
            "source": _text(inc.get("reportedBy"), 60) or "TAK",
            "details": {"lat": lat, "lon": lon, "source": "w3w" if inc.get("w3w") else "map",
                        "description": place or None, "floor": inc.get("floor") or None,
                        "w3w": inc.get("w3w") or None},
        }, actor)
        # The id dispatch says on the radio (CC-007): CrowdCAD's number for the new call.
        record = self.manager.pb.get_record("events", event["id"])
        call = next((c for c in record.get("calls") or [] if c.get("id") == result.get("callId")), None)
        prefix = event.get("idPrefix") or "CC"
        return {"id": mapping.incident_id(call, prefix) if call else ""}
