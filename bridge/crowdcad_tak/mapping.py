"""CrowdCAD event record → the set of things TAK should show. Pure: no IO, no clock.

One CrowdCAD `events` record holds everything (calls, staff, supervisors and the venue are
JSON fields inside it), so the whole TAK picture for an event is a function of that one
record. The bridge diffs successive outputs to decide what to send.

PHI rule (load-bearing): only the fields in `Incident fields` below ever leave CrowdCAD.
Call.age, .gender, .notes, .log and member names are never copied into an Item, so no
config or code path downstream can leak them. tests/test_mapping.py asserts this over the
rendered XML.
"""

import re
from dataclasses import dataclass, field

from . import calldetails, geo

# CrowdCAD's own list of call statuses that end a call (src/lib/clinics.ts
# RESOLVED_CALL_STATUSES). Kept verbatim; a new CrowdCAD outcome missing here would keep a
# finished call on the map, which is the safe direction to be wrong in.
RESOLVED_CALL_STATUSES = frozenset({
    "Delivered", "Refusal", "NMM", "Treat and Release", "Rolled", "Resolved", "Unable to Locate",
    "Rolled from Scene",
})

# CrowdCAD team status → IU Event CAD unit status (COT_FORMAT.md §1). Statuses missing here
# (Assigned, Pending, Delivered, Refusal, ...) are deliberately unmapped: the unit detail is
# left off rather than defaulted, because IU's rule is that showing a busy unit as Available
# gets it sent to a second patient. "Assigned" in particular is shown by IU from the
# incident's `assigned` list, not from the unit's own status.
UNIT_STATUS = {
    "Available": "AVL",
    "En Route": "RESP",
    "En Route Eq": "RESP",
    "Assisting": "RESP",
    "On Scene": "ONSC",
    "Transporting": "TRAN",
    "On Break": "OOS",
    "In Clinic": "OOS",
    "Detached": "OOS",
}


@dataclass
class Item:
    uid: str
    kind: str                     # incident | unit | zone | post
    lat: float
    lon: float
    fields: dict                  # everything that goes on the wire (and is diffed)
    closed: bool = False          # incident finished / event ended → send once, short stale, forget
    created_ms: int | None = None  # earliest known time (call log); bridge fills first-seen otherwise
    shape: list = field(default_factory=list)  # zone polygon vertices
    # Board-only context, never rendered to CoT and not diffed (e.g. assigned team names).
    # Same PHI rule as `fields`: nothing from a Call/Staff that isn't already on the wire.
    meta: dict = field(default_factory=dict)


@dataclass
class Unplaced:
    """Something that should be on the map but can't be: shown on the console status page so
    the dispatcher learns *before* the event that 'Sec 104' isn't a georeferenced post."""
    kind: str
    label: str
    location: str
    # What the web boards list for it (same fields as a placed call/unit, never more): unplaced
    # calls and teams still belong on the board, just not on the map.
    details: dict = field(default_factory=dict)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "x"


def event_prefix(event_id):
    return f"crowdcad-{event_id}"


def incident_id(call, id_prefix):
    order = call.get("order")
    number = f"{int(order):03d}" if isinstance(order, (int, float)) else slug(call.get("id"))
    return f"{id_prefix}-{number}"


def call_status(call, staff_by_team):
    """IU incident status for a call. CrowdCAD's Call.status is partly a label: whether a
    call is on scene or transporting is read from its assigned teams' statuses, exactly as
    the dispatch board does (dispatch/page.tsx getCallPrimaryStatus)."""
    if call.get("duplicate"):
        return "CXL"
    status = call.get("status") or ""
    if status in RESOLVED_CALL_STATUSES:
        return "CLOSED"
    teams = [t for t in call.get("assignedTeam") or [] if t]
    if not teams:
        return "NEW"
    team_statuses = {staff_by_team.get(t, {}).get("status") for t in teams}
    if "Transporting" in team_statuses or status in ("Transporting", "Pending Transport"):
        return "TRAN"
    if "On Scene" in team_statuses or status == "On Scene":
        return "ONSC"
    return "DISP"


def _log_times(entries):
    return [e["timestamp"] for e in entries or []
            if isinstance(e, dict) and isinstance(e.get("timestamp"), (int, float))]


def _skipped(call, publish):
    # A walk-up seen in the clinic tent has no field response to show.
    return call.get("clinic") and not call.get("assignedTeam") and not publish.get("clinic_walkups", False)


def _id_prefix(event, config):
    return (config.get("id_prefixes") or {}).get(event.get("id")) or config.get("id_prefix") or "CC"


def team_incidents(event, config):
    """Team name → IU id of the open, published call it's assigned to."""
    publish = config.get("publish") or {}
    if not publish.get("calls", True) or event.get("ended"):
        return {}
    teams = list(event.get("staff") or []) + list(event.get("supervisor") or [])
    staff_by_team = {t.get("team"): t for t in teams if t.get("team")}
    out = {}
    for call in event.get("calls") or []:
        if _skipped(call, publish) or call_status(call, staff_by_team) in ("CLOSED", "CXL"):
            continue
        for team in call.get("assignedTeam") or []:
            if team:
                out[team] = incident_id(call, _id_prefix(event, config))
    return out


TAK_UID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


def unit_uids(event, config):
    """Team/supervisor name → the TAK device carrying it. Per event from the unit's own `takUid`
    (written by the manage API when the event was created from TAK, manage.py), else the
    console's config team_uids. Same validation as manage.UNIT_UID: it goes into CoT."""
    out = dict(config.get("team_uids") or {})
    for team in list(event.get("staff") or []) + list(event.get("supervisor") or []):
        uid = team.get("takUid")
        if team.get("team") and isinstance(uid, str) and TAK_UID.match(uid):
            out[team["team"]] = uid
    return out


def device_teams(event, config):
    """Teams carried by their own ATAK device (takUid / config team_uids) — no bridge marker,
    but the web board still lists them with dispatch's status for them."""
    team_uids = unit_uids(event, config)
    incidents = team_incidents(event, config)
    out = []
    for team in list(event.get("staff") or []) + list(event.get("supervisor") or []):
        name = team.get("team")
        if name in team_uids:
            out.append({"name": name, "uid": team_uids[name], "status": UNIT_STATUS.get(team.get("status") or ""),
                        "crowdcadStatus": team.get("status") or "",
                        "incident": incidents.get(name), "location": team.get("location") or "",
                        "supervisor": "member" in team,
                        "since": team.get("statusSince") if isinstance(team.get("statusSince"), (int, float)) else None})
    return out


def callsign_key(name):
    """"Team 1", "team1", "TEAM-1" → "team1": how an ATAK callsign is matched to a unit name."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def free_units(event, config):
    """Teams/supervisors no device carries yet → [name]. A phone whose ATAK callsign matches one
    links itself to it on its first Acknowledge tap (fieldstatus.py)."""
    bound = unit_uids(event, config)
    return [t["team"] for t in list(event.get("staff") or []) + list(event.get("supervisor") or [])
            if t.get("team") and t["team"] not in bound]


# How good an incident's point is, as CoT `ce` metres (IU Event CAD's COT_FORMAT.md reads `ce`
# this way): a georeferenced post, a point a dispatcher picked/typed, the map centre (estimate).
POSITION_CE = {"post": 20.0, "coords": 15.0, "estimate": 75.0}


def _floor_short(floor):
    return "B" if floor == calldetails.FLOOR_BASEMENT else f"F{floor}"


def build(event, config, details=None):
    """→ (items: {uid: Item}, unplaced: [Unplaced]) for one event record.
    details: call id → TAK call details (calldetails.CallDetails.for_event), or None."""
    details = details or {}
    eid = event.get("id") or "event"
    prefix = event_prefix(eid)
    publish = config.get("publish") or {}
    overrides = config.get("layer_bounds") or {}
    team_uids = unit_uids(event, config)
    id_prefix = _id_prefix(event, config)
    ended = bool(event.get("ended"))

    items, unplaced = {}, []
    teams = list(event.get("staff") or []) + list(event.get("supervisor") or [])
    staff_by_team = {t.get("team"): t for t in teams if t.get("team")}

    def team_uid(name):
        # A team carried by its own ATAK device is that device's uid: the IU plugin then
        # alerts the right phone on assignment and the bridge sends no marker for the team.
        return team_uids.get(name) or f"{prefix}-team-{slug(name)}"

    team_incident = team_incidents(event, config)  # for each unit's `incident` attribute

    if publish.get("calls", True):
        for call in event.get("calls") or []:
            if _skipped(call, publish):
                continue
            status = call_status(call, staff_by_team)
            if ended and status not in ("CLOSED", "CXL"):
                status = "CLOSED"  # an ended event rejects further dispatch writes; nothing is open
            closed = status in ("CLOSED", "CXL")
            iid = incident_id(call, id_prefix)
            assigned = [t for t in call.get("assignedTeam") or [] if t]
            # TAK details (calldetails.py) come from the bridge's own store, never from notes.
            extra = details.get(call.get("id")) or {}
            floor = extra.get("floor") or None
            where = geo.post_location(call.get("location"), event, overrides)
            position_from = "post"
            if not where:
                # A TAK dispatcher's point is the call's own CrowdCAD location, "lat, lon".
                coords = calldetails.parse_coords(call.get("location"))
                if coords:
                    where = (coords[0], coords[1], "")
                    position_from = "estimate" if extra.get("source") == "centre" else "coords"
            label = f"{iid[len(id_prefix) + 1:]} · {call.get('chiefComplaint') or 'Call'}"
            if floor:
                label += f" · {_floor_short(floor)}"     # IU's rule: the callsign carries the floor
            location = extra.get("description") or call.get("location") or ""
            times = _log_times(call.get("log"))
            board = {"callId": call.get("id"), "number": call.get("order"), "floor": floor,
                     "crowdcadStatus": call.get("status") or "",
                     "w3w": extra.get("w3w"), "description": extra.get("description"), "takNotes": extra.get("notes"),
                     "callLocation": call.get("location") or ""}
            if not where:
                if not closed:
                    unplaced.append(Unplaced("call", label, location, {
                        "id": iid, "status": status, "type": call.get("chiefComplaint") or "Unknown",
                        "priority": 1 if call.get("priority") else 2, "reportedBy": call.get("source") or "CrowdCAD",
                        "assigned": assigned, "created": min(times) if times else None, **board}))
                continue
            # Incident fields — the complete list of what leaves CrowdCAD for a call.
            fields = {
                "callsign": label,
                "id": iid,
                "status": status,
                "type": call.get("chiefComplaint") or "Unknown",
                "priority": 1 if call.get("priority") else 2,
                "location": location,
                "reportedBy": call.get("source") or "CrowdCAD",
                "assigned": ",".join(team_uid(t) for t in assigned),
                "layer": where[2],
                "ce": POSITION_CE[position_from],
            }
            if floor:
                fields["floor"] = floor
            if extra.get("w3w"):
                fields["w3w"] = extra["w3w"]
            if extra.get("notes"):
                fields["notes"] = extra["notes"]   # dispatcher's TAK notes, never CrowdCAD's notes
            uid = f"{prefix}-call-{slug(call.get('id') or iid)}"
            items[uid] = Item(uid, "incident", where[0], where[1], fields, closed=closed,
                              created_ms=min(times) if times else None,
                              meta={"assigned_teams": assigned, "event": eid, "positionFrom": position_from, **board})

    if publish.get("teams", True):
        for team in teams:
            name = team.get("team")
            if not name or name in team_uids:
                continue
            where = geo.post_location(team.get("location"), event, overrides)
            if not where:
                if not ended:
                    unplaced.append(Unplaced("team", name, team.get("location") or "", {
                        "status": UNIT_STATUS.get(team.get("status") or ""), "incident": team_incident.get(name),
                        "crowdcadStatus": team.get("status") or "",
                        "supervisor": "member" in team,
                        "since": team.get("statusSince") if isinstance(team.get("statusSince"), (int, float)) else None}))
                continue
            fields = {"callsign": name, "location": team.get("location") or "",
                      "status": UNIT_STATUS.get(team.get("status") or ""),
                      "incident": team_incident.get(name),
                      "since": team.get("statusSince") if isinstance(team.get("statusSince"), (int, float)) else None,
                      "supervisor": "member" in team}
            uid = team_uid(name)
            items[uid] = Item(uid, "unit", where[0], where[1], fields, closed=ended,
                              meta={"crowdcadStatus": team.get("status") or ""})

    if publish.get("zones", True):
        for layer, zone, shape in geo.zone_shapes(event, overrides):
            lat = sum(p[0] for p in shape) / len(shape)
            lon = sum(p[1] for p in shape) / len(shape)
            uid = f"{prefix}-zone-{slug(zone.get('id') or zone.get('name'))}"
            fields = {"callsign": zone.get("name") or "Zone", "color": zone.get("color") or "#3b82f6",
                      "layer": layer.get("name") or "", "points": [list(p) for p in shape]}
            items[uid] = Item(uid, "zone", round(lat, 7), round(lon, 7), fields, closed=ended, shape=shape)

    if publish.get("posts", False):
        for layer, post, lat, lon in geo.placed_posts(event, overrides):
            uid = f"{prefix}-post-{slug(layer.get('id'))}-{slug(post.get('name'))}"
            fields = {"callsign": post.get("name"), "layer": layer.get("name") or "",
                      "clinic": bool(post.get("isClinic"))}
            items[uid] = Item(uid, "post", lat, lon, fields, closed=ended)

    return items, unplaced
