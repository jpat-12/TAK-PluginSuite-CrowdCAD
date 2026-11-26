"""TAK call details: what a TAK dispatcher adds to a CrowdCAD call beyond CrowdCAD's own fields.

CrowdCAD stays unmodified. A dispatcher in CloudTAK can give a call a map position (clicked on
the map, what3words, typed coordinates or the map centre), a spoken description ("Sec 104 Row
22"), a floor and its what3words. Each of those lands in CrowdCAD itself:

    coordinates → the call's own `location` field, "39.18200, -86.52550"
                  (mapping.py places any call whose location is a coordinate pair, so the
                  position survives with CrowdCAD's data and a CrowdCAD user can read it)
    everything  → one tagged line in the call's `notes`:
                  "[TAK] Sec 104 Row 22 · Floor 3 · ///filled.count.soap · picked on map"
                  replaced in place on every edit; the rest of the notes is never touched

and in the bridge's own store (CallDetails, data_dir/call_details.json), which is where the
TAK side reads them back from.

PHI rule (load-bearing): `notes` is WRITE-ONLY from the bridge. Notes can hold patient details,
so nothing here or in mapping.py ever reads notes to send it anywhere; the structured copy in
CallDetails is the only source for the board and the CoT. tests/test_calldetails.py checks both.
"""

import json
import os
import re
import threading

from .dispatch import DispatchError, _find_call, _is_resolved, _replace, _text, _via

TAG = "[TAK]"
NOTE_TAG = "[TAK note]"   # dispatcher notes: sent to TAK (IU `notes`), so no names, DOB or MRN
MAX_NOTES = 240
SOURCES = ("map", "w3w", "coords", "centre", "post")
SOURCE_LABEL = {"map": "picked on map", "w3w": "from what3words", "coords": "typed coordinates",
                "centre": "map centre (estimate)", "post": "at post"}
FLOOR_BASEMENT, FLOOR_MAX = -1, 8          # IU Event CAD's floor rule (its COT_FORMAT.md): 1–8, -1
W3W = re.compile(r"^/{0,3}([a-z]+\.[a-z]+\.[a-z]+)$")
COORDS = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def parse_coords(text):
    """"39.18200, -86.52550" → (39.182, -86.5255), else None. CrowdCAD's `location` holds this
    form when a TAK dispatcher placed the call; a CrowdCAD user typing it works the same."""
    found = COORDS.match(text) if isinstance(text, str) else None
    if not found:
        return None
    lat, lon = float(found.group(1)), float(found.group(2))
    if abs(lat) > 90 or abs(lon) > 180 or (lat == 0 and lon == 0):
        return None
    return lat, lon


def format_coords(lat, lon):
    return f"{lat:.5f}, {lon:.5f}"


def _floor(value):
    if value in (None, "", 0):
        return None
    try:
        floor = int(value)
    except (TypeError, ValueError):
        raise DispatchError("floor must be 1–8, or -1 for the basement") from None
    if floor != FLOOR_BASEMENT and not 1 <= floor <= FLOOR_MAX:
        raise DispatchError("floor must be 1–8, or -1 for the basement")
    return floor


def _number(value, field, limit):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise DispatchError(f"{field} must be a number") from None
    if not -limit <= number <= limit:
        raise DispatchError(f"{field} is out of range")
    return round(number, 6)


def clean(form):
    """The dispatcher's form → validated details {description, floor, lat, lon, source, w3w}.
    Every key is optional; absent/empty ones are None."""
    if not isinstance(form, dict):
        raise DispatchError("details must be a JSON object")
    lat, lon = form.get("lat"), form.get("lon")
    if (lat is None) != (lon is None):
        raise DispatchError("give both lat and lon, or neither")
    if lat is not None:
        lat, lon = _number(lat, "lat", 90), _number(lon, "lon", 180)
        if lat == 0 and lon == 0:
            raise DispatchError("0, 0 is not a position (no GPS fix?)")
    source = form.get("source") or None
    if source is not None and source not in SOURCES:
        raise DispatchError(f"source must be one of: {', '.join(SOURCES)}")
    words = form.get("w3w") or ""
    if words:
        found = W3W.match(words.strip().lower()) if isinstance(words, str) else None
        if not found:
            raise DispatchError("what3words must look like ///word.word.word")
        words = found.group(1)
    post = _text(form.get("post"), "post") or None
    if post and lat is not None:
        raise DispatchError("give a post or a point, not both")
    return {
        "post": post,                       # a CrowdCAD post name: becomes the call's location as-is
        "description": _text(form.get("description"), "description") or None,
        "notes": _text(form.get("notes"), "notes", limit=MAX_NOTES) or None,
        "floor": _floor(form.get("floor")),
        "lat": lat, "lon": lon,
        "source": source if lat is not None else ("post" if post else None),
        "w3w": words or None,
    }


def block(details):
    """The one notes line the bridge owns for this call (no newlines, so it replaces cleanly)."""
    parts = []
    if details.get("description"):
        parts.append(details["description"])
    floor = details.get("floor")
    if floor:
        parts.append("Basement" if floor == FLOOR_BASEMENT else f"Floor {floor}")
    if details.get("w3w"):
        parts.append(f"///{details['w3w']}")
    if details.get("source"):
        parts.append(SOURCE_LABEL[details["source"]])
    return f"{TAG} {' · '.join(parts)}" if parts else ""


def notes_with(notes, line, note_line=""):
    """`notes` with the bridge's lines ([TAK] details, [TAK note]) replaced (dropped when empty).
    Other lines untouched. Only ever used to build the write: the result goes back into CrowdCAD,
    nowhere else."""
    ours = (TAG + " ", NOTE_TAG + " ")
    kept = [n for n in (notes or "").split("\n") if not n.startswith(ours) and n not in (TAG, NOTE_TAG)]
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept + [x for x in (line, note_line) if x])


def apply(event, call_id, details, actor=None, clock=None):
    """→ the PATCH that writes `details` into call `call_id`: coordinates (if any) into its
    `location`, the [TAK] line into its `notes`, one log entry. {} when nothing changes."""
    call = _find_call(event, call_id)
    if _is_resolved(call):
        raise DispatchError(f"call is already closed ({call.get('status')})", 409)
    updated = dict(call)
    changes = []
    where = format_coords(details["lat"], details["lon"]) if details.get("lat") is not None else details.get("post")
    if where:
        if call.get("location") != where:
            updated["location"] = where
            changes.append(f"location {where}")
    elif details.get("description") and (call.get("location") or "Unknown") == "Unknown":
        updated["location"] = details["description"]   # no position: the spoken spot is all there is
        changes.append(f"location {details['description']}")
    line = block(details)
    note_line = f"{NOTE_TAG} {details['notes']}" if details.get("notes") else ""
    notes = notes_with(call.get("notes"), line, note_line)
    if notes != (call.get("notes") or ""):
        updated["notes"] = notes
        if line:
            changes.append(line[len(TAG) + 1:])
        if note_line:
            changes.append("note: " + details["notes"])
        if not line and not note_line:
            changes.append("TAK details cleared")       # a removal is a change too
    if not changes:
        return {}
    hhmm = clock.hhmm if clock else "0000"
    ms = clock.ms if clock else 0
    updated["log"] = (call.get("log") or []) + [
        {"timestamp": ms, "message": f"{hhmm} - TAK details: {'; '.join(changes)}{_via(actor)}"}]
    return {"calls": _replace(event.get("calls"), lambda c: c.get("id") == call_id, updated)}


class CallDetails:
    """The bridge's structured copy of TAK details, per event and call. A small JSON file in the
    data dir (atomic replace): it only holds what a dispatcher typed, so losing it loses the
    TAK-side extras (floor, description, what3words) but never a call or its position — those
    are in CrowdCAD's own record (location + notes)."""

    def __init__(self, path=None):
        self.path = path
        self.lock = threading.Lock()
        self.data = {}
        if path:
            try:
                with open(path, encoding="utf-8") as stream:
                    loaded = json.load(stream)
                    self.data = loaded if isinstance(loaded, dict) else {}
            except FileNotFoundError:
                pass
            except ValueError:   # a corrupt file must not stop the bridge: start empty, keep the bad copy
                os.replace(path, path + ".bad")

    def for_event(self, event_id):
        with self.lock:
            calls = self.data.get(event_id)
            return {cid: dict(d) for cid, d in calls.items()} if isinstance(calls, dict) else {}

    # Acknowledgements: "_acks" → event id → incident id (CC-007) → unit name → ms. Kept here so
    # a unit stays Responding (not Tasked) across a bridge restart. Never an event id: "_" prefix.
    def put_ack(self, event_id, incident_id, unit_name, at_ms):
        with self.lock:
            data = {eid: dict(v) if isinstance(v, dict) else list(v) for eid, v in self.data.items()}
            acks = {e: {i: dict(u) for i, u in calls.items()} for e, calls in (data.get("_acks") or {}).items()}
            acks.setdefault(event_id, {}).setdefault(incident_id, {})[unit_name] = int(at_ms)
            data["_acks"] = acks
            self._save(data)
            self.data = data

    # Venue boundaries a dispatcher drew (CloudTAK radar + map): "_venue" → event id → list of
    # polygons [[lat, lon], ...]. Shared by every dispatcher of the event.
    def boundaries(self, event_id):
        with self.lock:
            return [list(map(list, poly)) for poly in ((self.data.get("_venue") or {}).get(event_id) or [])]

    def put_boundaries(self, event_id, polygons):
        with self.lock:
            data = {eid: dict(v) if isinstance(v, dict) else list(v) for eid, v in self.data.items()}
            venue = dict(data.get("_venue") or {})
            if polygons:
                venue[event_id] = polygons
            else:
                venue.pop(event_id, None)
            data["_venue"] = venue
            self._save(data)
            self.data = data

    # Supervisor requests: "_supreq" → list of {id, event, unit, callsign, uid, at, lat, lon, cleared}
    # (newest last, the last 50 kept). Cleared by a dispatcher.
    def add_supreq(self, request):
        with self.lock:
            data = {eid: dict(v) if isinstance(v, dict) else v for eid, v in self.data.items()}
            reqs = [dict(r) for r in (data.get("_supreq") or [])] + [request]
            data["_supreq"] = reqs[-50:]
            self._save(data)
            self.data = data

    def supreqs(self):
        with self.lock:
            return [dict(r) for r in (self.data.get("_supreq") or [])]

    def clear_supreq(self, request_id):
        with self.lock:
            data = {eid: dict(v) if isinstance(v, dict) else v for eid, v in self.data.items()}
            reqs = [dict(r, cleared=True) if r.get("id") == request_id else dict(r) for r in (data.get("_supreq") or [])]
            data["_supreq"] = reqs
            self._save(data)
            self.data = data

    def acks(self, event_id=None):
        """event id → {incident id → {unit name → ms}}, or one event's {incident id → …}."""
        with self.lock:
            all_acks = self.data.get("_acks") or {}
            if event_id is not None:
                return {i: dict(u) for i, u in (all_acks.get(event_id) or {}).items()}
            return {e: {i: dict(u) for i, u in calls.items()} for e, calls in all_acks.items()}

    def get(self, event_id, call_id):
        with self.lock:
            found = (self.data.get(event_id) or {}).get(call_id)
            return dict(found) if found else None

    def put(self, event_id, call_id, details):
        """→ the previous value (for undo when CrowdCAD refuses the write). A post name isn't
        kept: it lives in CrowdCAD's own location field. Saved to disk first, so a failed save
        (OSError) leaves the store exactly as it was."""
        kept = {k: v for k, v in details.items() if v is not None and k != "post"}
        with self.lock:
            previous = (self.data.get(event_id) or {}).get(call_id)
            self._commit(event_id, call_id, kept or None)
            return previous

    def restore(self, event_id, call_id, previous):
        with self.lock:
            self._commit(event_id, call_id, previous or None)

    def _commit(self, event_id, call_id, value):
        data = {eid: dict(calls) if isinstance(calls, dict) else list(calls) for eid, calls in self.data.items()}
        calls = data.setdefault(event_id, {})
        if value:
            calls[call_id] = value
        else:
            calls.pop(call_id, None)
        self._save(data)
        self.data = data

    def _save(self, data):
        if not self.path:
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=1, sort_keys=True)
        os.replace(tmp, self.path)
