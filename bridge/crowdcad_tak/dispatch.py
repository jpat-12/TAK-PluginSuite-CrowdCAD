"""Native dispatch from TAK: CrowdCAD v1.6.0's own dispatch actions, ported to the bridge.

Each action takes the event record and returns a PATCH (only the fields it changes) that
reproduces exactly what CrowdCAD's dispatch screen writes for the same click, so a call
dispatched from CloudTAK is indistinguishable in CrowdCAD from one dispatched there (plus a
"via CloudTAK" note in the logs). Sources, all in CrowdCAD v1.6.0 (re-check on every upgrade):

  new_call        components/modals/event/quickcallmodal.tsx  handleSubmit
  assign          dispatch/page.tsx handleAddTeamToCall (teams);
                  components/dispatch/calltracking.tsx supervisor assign (supervisors)
  status_on_call  dispatch/page.tsx handleTeamStatusChange (teams; the resolving cascade);
                  handleSupervisorStatusChange for a supervisor's non-closing status
  unit_status     dispatch/page.tsx handleStatusChange / handleSupervisorStatusChange
  unit_post       dispatch/page.tsx handleLocationChange / handleSupervisorLocationChange

Deliberate differences, all because the bridge has no browser state:
- CrowdCAD keeps each team's status *per call* in React state (teamStatusMap); the record only
  has the team's own status. Here a team's status on its call is its `status` field.
- Equipment-only runs (En Route Eq / Assisting / Delivered Eq) aren't offered from TAK.
- Times in log lines ("1432 - …") use the bridge's `timezone` setting, not a browser clock.

PHI: TAK can set a chief complaint, location, priority and source. Never age, sex or notes.
Writes go through store.py (compare-and-swap), never a blind PATCH.
"""

import copy
import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None

# CrowdCAD v1.6.0 lists (dispatch/page.tsx, lib/clinics.ts, calltrackingcard.tsx, teamcard.tsx).
RESOLVING_STATUSES = ["Delivered", "Refusal", "NMM", "Unable to Locate", "Rolled from Scene"]
RESOLVED_CALL_STATUSES = ["Delivered", "Refusal", "NMM", "Rolled", "Resolved", "Unable to Locate"]
ON_CALL_STATUSES = ["En Route", "On Scene", "Unable to Locate", "Transporting", "Pending Transport",
                    "Rolled from Scene", "Delivered", "Refusal", "NMM", "Detached"]
AVAILABILITY_STATUSES = ["Available", "On Break", "In Clinic"]
DEFAULT_CLINICS = [{"id": "clinic", "name": "Clinic"}]
MAX_TEXT = 120


class DispatchError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# --- helpers ---------------------------------------------------------------------------------

class Clock:
    """now (ms since epoch) + the zone CrowdCAD's "hhmm - …" log prefixes are written in."""

    def __init__(self, now_ms=None, timezone=""):
        self.ms = int(now_ms if now_ms is not None else datetime.datetime.now().timestamp() * 1000)
        zone = None
        if timezone and ZoneInfo:
            try:
                zone = ZoneInfo(timezone)
            except Exception:   # unknown zone name: fall back to the host's
                zone = None
        stamp = datetime.datetime.fromtimestamp(self.ms / 1000, tz=datetime.timezone.utc)
        self.local = stamp.astimezone(zone) if zone else stamp.astimezone()

    @property
    def hhmm(self):
        return self.local.strftime("%H%M")


def _text(value, field, required=False, limit=MAX_TEXT):
    value = " ".join(value.split()) if isinstance(value, str) else ""
    if required and not value:
        raise DispatchError(f"{field} is required")
    if len(value) > limit:
        raise DispatchError(f"{field} is longer than {limit} characters")
    return value


def _via(actor):
    """actor: who and where, e.g. "CloudTAK: jon" or "ATAK: MEDIC1"."""
    return f" (via {actor})" if actor else " (via TAK)"


def _find_call(event, call_id):
    for call in event.get("calls") or []:
        if call.get("id") == call_id:
            return call
    raise DispatchError(f"no call {call_id!r} in this event", 404)


def _find_unit(event, name):
    """→ ('staff' | 'supervisor', entry). CrowdCAD names are unique across both lists."""
    for kind in ("staff", "supervisor"):
        for unit in event.get(kind) or []:
            if unit.get("team") == name:
                return kind, unit
    raise DispatchError(f"no team or supervisor named {name!r} in this event", 404)


def _replace(items, match, new):
    return [new if match(item) else item for item in items or []]


def _display_number(event, call):
    # CrowdCAD numbers calls by their position in its sorted list; `order` is that number for
    # every call created in v1.6.0 (quickcallmodal: order = max + 1).
    return call.get("order") or (event.get("calls") or []).index(call) + 1


def _pending_suffix(message, call, clock):
    """lib/callTiming.ts withPendingSuffix: first assignment notes how long it sat pending."""
    if call.get("assignedTeam"):
        return message
    log = call.get("log") or []
    created = log[0].get("timestamp") if log and isinstance(log[0], dict) else None
    if not isinstance(created, (int, float)):
        return message
    seconds = max(0, int((clock.ms - created) // 1000))
    return f"{message} (assigned after {seconds // 60}m {seconds % 60}s pending)"


def _clinics(event):
    return event.get("clinics") or DEFAULT_CLINICS


def _clinic_name(clinics, clinic_id):
    """lib/clinics.ts getClinicName: only named when there's more than one clinic."""
    if len(clinics) <= 1:
        return None
    return next((c.get("name") for c in clinics if c.get("id") == clinic_id), None)


def _is_resolved(call):
    return call.get("status") in RESOLVED_CALL_STATUSES


# --- actions ---------------------------------------------------------------------------------

def new_call(event, form, actor=None, clock=None):
    """quickcallmodal handleSubmit. form: {location, chiefComplaint, priority?, source?, assign?}"""
    clock = clock or Clock()
    event = copy.deepcopy(event)
    if not isinstance(form, dict):
        raise DispatchError("body must be a JSON object")
    location = _text(form.get("location"), "location") or "Unknown"
    complaint = _text(form.get("chiefComplaint"), "chief complaint")
    source = _text(form.get("source"), "source", limit=60) or "TAK"
    assign = form.get("assign") or None
    calls = event.get("calls") or []
    orders = [c.get("order") for c in calls if isinstance(c.get("order"), (int, float))]
    order = int(max(orders)) + 1 if calls else 1
    call_id = str(clock.ms)
    while any(c.get("id") == call_id for c in calls):
        call_id = str(int(call_id) + 1)
    message = (f"{clock.hhmm} - Call created from {source}"
               f"{f', complaint: {complaint}' if complaint else ''}, location: {location}"
               f"{f', assigned to {assign}' if assign else ''}{_via(actor)}")
    call = {
        "id": call_id,
        "order": order,
        "status": "Assigned" if assign else "Pending",
        "location": location,
        "assignedTeam": [assign] if assign else [],
        "chiefComplaint": complaint,
        "source": source,
        "priority": bool(form.get("priority")),
        "log": [{"timestamp": clock.ms, "message": message}],
    }
    patch = {"calls": calls + [call]}
    if assign:
        kind, unit = _find_unit(event, assign)
        entry = {"timestamp": clock.ms, "message": f"{clock.hhmm} - responding to call #{order}"}
        updated = {**unit, "status": "En Route", "location": location,
                   "originalPost": unit.get("location") or "Unknown", "log": (unit.get("log") or []) + [entry]}
        patch[kind] = _replace(event.get(kind), lambda u: u.get("team") == assign, updated)
    return patch, call_id


def assign(event, call_id, unit_name, actor=None, clock=None):
    """handleAddTeamToCall (team) / calltracking supervisor assign."""
    clock = clock or Clock()
    event = copy.deepcopy(event)
    call = _find_call(event, call_id)
    if _is_resolved(call):
        raise DispatchError(f"call #{_display_number(event, call)} is already closed ({call.get('status')})", 409)
    if unit_name in (call.get("assignedTeam") or []):
        raise DispatchError(f"{unit_name} is already on this call", 409)
    kind, unit = _find_unit(event, unit_name)
    number = _display_number(event, call)
    is_unit = lambda u: u.get("team") == unit_name   # noqa: E731
    if kind == "supervisor":
        member = unit.get("member") or unit_name
        call_entry = _pending_suffix(f"{clock.hhmm} - Supervisor {member} ({unit_name}) assigned to call.", call, clock)
        new_call_ = {**call, "assignedTeam": (call.get("assignedTeam") or []) + [unit_name],
                     "status": call.get("status") if call.get("assignedTeam") else "Assigned",
                     "log": (call.get("log") or []) + [{"timestamp": clock.ms, "message": call_entry + _via(actor)}]}
        team_entry = {"timestamp": clock.ms, "message": f"{clock.hhmm} - responding to call #{number} (supervisor support)"}
        new_unit = {**unit, "status": "En Route", "location": call.get("location"),
                    "originalPost": unit.get("location") or "Unknown", "log": (unit.get("log") or []) + [team_entry]}
        return {"calls": _replace(event["calls"], lambda c: c.get("id") == call_id, new_call_),
                "supervisor": _replace(event.get("supervisor"), is_unit, new_unit)}

    call_entry = _pending_suffix(f"{clock.hhmm} - {unit_name} assigned and en route.", call, clock)
    team_entry = {"timestamp": clock.ms, "message": f"{clock.hhmm} - responding to call #{number} ({call_id})"}
    new_call_ = {**call, "assignedTeam": (call.get("assignedTeam") or []) + [unit_name], "status": "Assigned",
                 "log": (call.get("log") or []) + [{"timestamp": clock.ms, "message": call_entry + _via(actor)}]}
    new_unit = {**unit, "status": "En Route", "location": call.get("location"),
                "originalPost": unit.get("location") or "Unknown", "log": (unit.get("log") or []) + [team_entry]}
    patch = {"calls": _replace(event["calls"], lambda c: c.get("id") == call_id, new_call_),
             "staff": _replace(event.get("staff"), is_unit, new_unit)}
    # Equipment listed on the call or already with this team goes In Use with it.
    equipment = event.get("eventEquipment") or []
    if equipment:
        listed = {e if isinstance(e, str) else (e or {}).get("name", "") for e in call.get("equipment") or []}
        patch["eventEquipment"] = [
            {**eq, "assignedTeam": unit_name, "status": "In Use",
             "location": call.get("location") or eq.get("location") or unit_name}
            if (eq.get("name") in listed or eq.get("assignedTeam") == unit_name) else eq
            for eq in equipment]
    return patch


def status_on_call(event, call_id, unit_name, new_status, actor=None, clock=None, clinic_id=None, transport_unit=None):
    """handleTeamStatusChange: a unit's status on its call, incl. the resolving cascade."""
    clock = clock or Clock()
    event = copy.deepcopy(event)
    if new_status not in ON_CALL_STATUSES:
        raise DispatchError(f"status must be one of: {', '.join(ON_CALL_STATUSES)}")
    call = _find_call(event, call_id)
    if unit_name not in (call.get("assignedTeam") or []):
        raise DispatchError(f"{unit_name} isn't on this call", 409)
    if _is_resolved(call):
        raise DispatchError(f"call #{_display_number(event, call)} is already closed ({call.get('status')})", 409)
    kind, unit = _find_unit(event, unit_name)
    transport_unit = _text(transport_unit, "transport unit", limit=40) or None
    resolving = new_status in RESOLVING_STATUSES
    detaching = resolving or new_status == "Detached"

    # A supervisor's ordinary status isn't a call transition in CrowdCAD (its supervisor card
    # uses handleSupervisorStatusChange); only detaching/closing goes through the cascade.
    if kind == "supervisor" and not detaching:
        return _supervisor_status(event, unit, new_status, actor, clock)

    hhmm = clock.hhmm
    clinics = _clinics(event)
    resolved_clinic = clinic_id or call.get("clinicId") or clinics[0].get("id") or "clinic"
    destination = _clinic_name(clinics, resolved_clinic) if new_status in ("Transporting", "Delivered") else None
    if new_status == "Transporting":
        message = f"{hhmm} - {unit_name} transporting to {destination or 'clinic'}"
    elif new_status == "Rolled from Scene":
        message = f"{hhmm} - {unit_name} Transferred to ambulance{f', unit #: {transport_unit}' if transport_unit else ''}"
    else:
        message = (f"{hhmm} - {unit_name} set to {new_status} at {call.get('location')}"
                   f"{f' ({destination})' if destination else ''}")

    assigned = list(call.get("assignedTeam") or [])
    others = [t for t in assigned if t != unit_name] if resolving else []
    supervisors = event.get("supervisor") or []
    staff = event.get("staff") or []
    status_of = {u.get("team"): u.get("status") for u in staff + supervisors}
    prior_status = unit.get("status")
    prior_location = unit.get("location")

    new_assigned = assigned
    new_equipment_teams = list(call.get("equipmentTeams") or [])
    detached = list(call.get("detachedTeams") or [])
    call_status = call.get("status")
    if detaching:
        new_assigned = [] if resolving else [t for t in assigned if t != unit_name]
        new_equipment_teams = [] if resolving else [t for t in new_equipment_teams if t != unit_name]
        if not any(d.get("team") == unit_name for d in detached):
            detached.append({"team": unit_name, "reason": new_status, "kind": "team",
                             "previousStatus": prior_status or "En Route", "previousLocation": prior_location})
        if resolving:
            for other in others:
                if any(d.get("team") == other for d in detached):
                    continue
                other_unit = next((u for u in staff + supervisors if u.get("team") == other), {})
                detached.append({"team": other, "reason": "Auto-detached",
                                 "kind": "equipment" if other in (call.get("equipmentTeams") or []) else "team",
                                 "previousStatus": other_unit.get("status"),
                                 "previousLocation": other_unit.get("location")})
            for sup in supervisors:
                if sup.get("team") in assigned and not any(d.get("team") == sup.get("team") for d in detached):
                    detached.append({"team": sup["team"], "reason": "Auto-detached", "kind": "supervisor",
                                     "previousStatus": sup.get("status"), "previousLocation": sup.get("location")})
            names = {s.get("team") for s in supervisors}
            new_assigned = [t for t in new_assigned if t not in names]
        if not new_assigned:
            call_status = new_status if new_status in ("Delivered", "NMM", "Unable to Locate", "Refusal") else "Resolved"
        else:
            remaining = [status_of.get(t) for t in new_assigned]
            if "Transporting" in remaining:
                call_status = "Transporting"
            elif "On Scene" in remaining:
                call_status = "On Scene"
            elif "En Route" in remaining:
                call_status = "En Route"
    elif new_status in ("On Scene", "Transporting", "Pending Transport"):
        call_status = new_status

    new_call_ = {
        **call,
        "status": call_status,
        "clinic": True if (new_status == "Delivered" or call_status == "Delivered") else call.get("clinic", False),
        "clinicId": resolved_clinic,
        "log": (call.get("log") or []) + [{"timestamp": clock.ms, "message": message + _via(actor)}],
        "assignedTeam": new_assigned,
        "equipmentTeams": new_equipment_teams,
        "detachedTeams": detached,
        "pin": False if call_status in RESOLVED_CALL_STATUSES else call.get("pin"),
    }
    if new_status == "Rolled from Scene" and transport_unit:
        new_call_["transportUnit"] = transport_unit
    patch = {"calls": _replace(event["calls"], lambda c: c.get("id") == call_id, new_call_)}

    def acting(u):
        location, status = u.get("location"), new_status
        if new_status == "Detached" or new_status in ("Refusal", "NMM", "Unable to Locate", "Rolled from Scene"):
            location, status = u.get("originalPost") or "Unknown", "Available"
        elif new_status == "Delivered":
            location, status = "Clinic", "In Clinic"
        elif new_status in ("En Route", "On Scene", "Transporting", "Pending Transport"):
            location = call.get("location")
        return {**u, "status": status, "location": location}

    def auto_returned(u):
        entry = {"timestamp": clock.ms, "message": f"{hhmm} - auto-detached from completed call, status set to "
                                                   f"Available at {u.get('originalPost') or 'Unknown'}"}
        return {**u, "status": "Available", "location": u.get("originalPost") or "Unknown",
                "log": (u.get("log") or []) + [entry]}

    if kind == "staff" or others:
        patch["staff"] = [acting(u) if u.get("team") == unit_name and kind == "staff"
                          else auto_returned(u) if u.get("team") in others else u for u in staff]
    if resolving and any(s.get("team") in assigned for s in supervisors):
        entry = {"timestamp": clock.ms, "message": f"{hhmm} - auto-detached from completed call, status set to Available at Roaming"}
        patch["supervisor"] = [{**s, "status": "Available", "location": "Roaming", "log": (s.get("log") or []) + [entry]}
                               if s.get("team") in assigned else s for s in supervisors]

    equipment = event.get("eventEquipment") or []
    if equipment:
        patch_equipment = _equipment_after(equipment, new_call_, call_status, unit_name, [unit_name] + others)
        if patch_equipment is not None:
            patch["eventEquipment"] = patch_equipment
    return patch


def _equipment_after(equipment, call, call_status, unit_name, resolving_teams):
    """handleTeamStatusChange's equipment block (non-equipment statuses)."""
    listed = {e if isinstance(e, str) else (e or {}).get("name", "") for e in call.get("equipment") or []}
    if not any(eq.get("assignedTeam") in resolving_teams or eq.get("name") in listed for eq in equipment):
        return None
    no_teams = not call.get("assignedTeam")
    resolved_like = call_status in ("Resolved", "Delivered", "Refusal", "NMM", "Unable to Locate", "Rolled")
    if no_teams and resolved_like:
        if call_status == "Delivered":
            return [{**eq, "status": "In Clinic", "location": "Clinic"} if eq.get("assignedTeam") in resolving_teams else eq
                    for eq in equipment]
        return [{**eq, "assignedTeam": None, "status": "Available", "location": "Clinic"}
                if eq.get("assignedTeam") in resolving_teams else eq for eq in equipment]
    remaining = call.get("assignedTeam") or []
    holder = (unit_name if unit_name in remaining else remaining[0]) if remaining else unit_name
    return [{**eq, "assignedTeam": holder, "status": "In Use",
             "location": call.get("location") or eq.get("location") or holder or "Roaming"}
            if eq.get("assignedTeam") == unit_name else eq for eq in equipment]


def _supervisor_status(event, unit, new_status, actor, clock):
    """handleSupervisorStatusChange."""
    name = unit.get("team")
    active = next((c for c in event.get("calls") or []
                   if name in (c.get("assignedTeam") or []) and c.get("status") not in ("Resolved", "Available")), None)
    where = f" at {active.get('location')}" if active else ""
    message = f"{clock.hhmm} - status changed to {new_status}{where}"
    entry = {"timestamp": clock.ms, "message": message + _via(actor)}
    updated = {**unit, "status": new_status, "log": (unit.get("log") or []) + [entry]}
    return {"supervisor": _replace(event.get("supervisor"), lambda s: s.get("team") == name, updated)}


def unit_status(event, unit_name, new_status, actor=None, clock=None, clinic_id=None):
    """handleStatusChange (team) / handleSupervisorStatusChange: availability off a call."""
    clock = clock or Clock()
    event = copy.deepcopy(event)
    if new_status not in AVAILABILITY_STATUSES:
        raise DispatchError(f"status must be one of: {', '.join(AVAILABILITY_STATUSES)} "
                            f"(a unit on a call changes status on the call)")
    kind, unit = _find_unit(event, unit_name)
    if kind == "supervisor":
        return _supervisor_status(event, unit, new_status, actor, clock)
    active = next((c for c in event.get("calls") or []
                   if unit_name in (c.get("assignedTeam") or []) and c.get("status") not in ("Resolved", "Available")), None)
    where = f" at {active.get('location')}" if active else ""
    message = f"{clock.hhmm} - {unit_name} set to {new_status}{where}"
    entry = {"timestamp": clock.ms, "message": message + _via(actor)}
    staff = [{**u, "status": new_status, "log": (u.get("log") or []) + [entry]} if u.get("team") == unit_name else u
             for u in event.get("staff") or []]
    patch = {"staff": staff}
    if active:
        statuses = {u.get("team"): u.get("status") for u in staff}
        team_statuses = [new_status if t == unit_name else statuses.get(t, "Available") for t in active.get("assignedTeam") or []]
        status = active.get("status")
        for candidate in ("Transporting", "Pending Transport", "On Scene", "En Route"):
            if candidate in team_statuses:
                status = candidate
                break
        updated = {**active, "status": status, "log": (active.get("log") or []) + [{"timestamp": clock.ms, "message": message + _via(actor)}]}
        patch["calls"] = _replace(event.get("calls"), lambda c: c.get("id") == active.get("id"), updated)
    return patch


def unit_post(event, unit_name, location, actor=None, clock=None):
    """handleLocationChange / handleSupervisorLocationChange: move an idle unit to a post."""
    clock = clock or Clock()
    event = copy.deepcopy(event)
    location = _text(location, "post", required=True)
    kind, unit = _find_unit(event, unit_name)
    entry = {"timestamp": clock.ms, "message": f"{clock.hhmm} - Post changed to {location}{_via(actor)}"}
    status = "In Clinic" if location == "Clinic" and unit.get("status") == "Available" else unit.get("status")
    updated = {**unit, "location": location, "status": status, "log": (unit.get("log") or []) + [entry]}
    return {kind: _replace(event.get(kind), lambda u: u.get("team") == unit_name, updated)}
