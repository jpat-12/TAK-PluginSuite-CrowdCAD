"""Create (and end) CrowdCAD events from TAK: the manage API behind CloudTAK's New Event form.

The one place the bridge WRITES to CrowdCAD, and deliberately narrow:

- `create`: a brand-new `events` record, the same shape CrowdCAD's own Create Event page writes
  (src/app/(main)/events/[eventId]/create/page.tsx, v1.6.0): the chosen venue copied in, its
  clinic posts and dispatch zones derived the way syncClinicsFromVenue/syncDispatchZonesFromVenue
  do, status 'active'. Each TAK contact picked becomes one team (`staff`) or supervisor, in
  CrowdCAD's own entry shapes, plus `takUid`: the contact's device. The bridge then treats that
  unit as carried by that device (its PLI is the unit's position, assignment alerts go to that
  phone), per event — config team_uids is the fallback for events made in CrowdCAD.
  A new record can't race a dispatcher, which is why creating is safe where native dispatch
  isn't (docs/PLAN.md Phase 3).
- `end`: `{ended: true, endedAt}`, exactly CrowdCAD's handleEndEvent, and only for events this
  bridge account created (owner), since that's all PocketBase's rules let it end anyway.

Created events are org events (`isOrgEvent`): owned by the bridge account (a TAK user isn't a
CrowdCAD account), dispatchable by every signed-in CrowdCAD user.
"""

import datetime
import json
import re
import urllib.parse
import urllib.request

from . import calldetails, dispatch, geo
from .dispatch import Clock, DispatchError
from .store import EventStore

# ATAK/WinTAK/iTAK device uids: ANDROID-…, UUIDs, S-1-5-… etc. Nothing that could break out of
# a CoT attribute or a JSON string; the bridge writes these into CoT `assigned` lists.
UNIT_UID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_UNITS = 200
MAX_NAME = 80


class ManageError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def venue_posts(venue):
    """CrowdCAD getVenuePosts: the flattened `posts` cache, else every layer's posts."""
    posts = venue.get("posts") or []
    if posts:
        return posts
    return [p for layer in venue.get("layers") or [] for p in (layer.get("posts") or [])]


def _with_layers(venue):
    """CrowdCAD's create page migrates a pre-layers venue to one 'Main Floor' layer."""
    if venue.get("layers"):
        return venue
    return {**venue, "layers": [{"id": f"legacy-{venue.get('id') or 'venue'}", "name": "Main Floor",
                                 "posts": venue.get("posts") or [], "mapUrl": venue.get("mapUrl")}]}


def venue_summary(venue):
    """What the New Event form shows per venue. `mapped`: some layer was georeferenced
    (GeoJSON import), so calls at its posts land on the TAK map."""
    posts = venue_posts(venue)
    return {
        "id": venue.get("id"),
        "name": venue.get("name") or "(unnamed venue)",
        "posts": len(posts),
        "clinics": sum(1 for p in posts if isinstance(p, dict) and p.get("isClinic") is True),
        "mapped": any(isinstance(layer.get("geoBounds"), dict) for layer in venue.get("layers") or []),
    }


def sync_clinics(venue):
    """CrowdCAD syncClinicsFromVenue(venue, undefined): clinic-flagged posts with a clinicId."""
    out = {}
    for post in venue_posts(venue):
        if isinstance(post, dict) and post.get("isClinic") is True and post.get("clinicId"):
            out[post["clinicId"]] = {"id": post["clinicId"], "name": post.get("name")}
    return list(out.values())


def sync_dispatch_zones(venue):
    """CrowdCAD syncDispatchZonesFromVenue(venue, undefined): zones flagged isDispatchZone."""
    out = {}
    for layer in venue.get("layers") or []:
        for zone in layer.get("zones") or []:
            if isinstance(zone, dict) and zone.get("isDispatchZone") is True and zone.get("id"):
                out[zone["id"]] = {"id": zone["id"], "name": zone.get("name")}
    return list(out.values())


def _text(value, field, limit=MAX_NAME, required=True):
    value = value.strip() if isinstance(value, str) else ""
    value = " ".join(value.split())        # no newlines/tabs in names that end up in CoT callsigns
    if required and not value:
        raise ManageError(f"{field} is required")
    if len(value) > limit:
        raise ManageError(f"{field} is longer than {limit} characters")
    return value


def parse_units(units):
    """[{name, kind: team|supervisor, uid, callsign}] → (staff, supervisor) in CrowdCAD's shapes."""
    if not isinstance(units, list):
        raise ManageError("units must be a list")
    if len(units) > MAX_UNITS:
        raise ManageError(f"at most {MAX_UNITS} units")
    staff, supervisors, names, uids = [], [], set(), set()
    for unit in units:
        if not isinstance(unit, dict):
            raise ManageError("each unit must be an object")
        name = _text(unit.get("name"), "unit name")
        callsign = _text(unit.get("callsign") or name, "callsign")
        kind = unit.get("kind")
        uid = unit.get("uid")
        if kind not in ("team", "supervisor"):
            raise ManageError(f"{name}: kind must be team or supervisor")
        if not isinstance(uid, str) or not UNIT_UID.match(uid):
            raise ManageError(f"{name}: not a TAK device uid: {uid!r}")
        if name.lower() in names:
            raise ManageError(f"two units are named {name!r}; CrowdCAD needs unique names")
        if uid in uids:
            raise ManageError(f"{callsign} is picked twice")
        names.add(name.lower())
        uids.add(uid)
        if kind == "team":
            # CrowdCAD handleSaveTeam: members are display strings; status/location as it seeds them.
            staff.append({"team": name, "location": "No Post", "status": "On Break", "members": [callsign],
                          "takUid": uid})
        else:
            # CrowdCAD handleAddSamUnit (supervisor / roaming unit).
            supervisors.append({"team": name, "location": "Roaming", "status": "On Break", "member": callsign,
                                "takUid": uid})
    return staff, supervisors


def build_event(form, venue, owner_id, now=None):
    """The new `events` record. form: {name, date?: YYYY-MM-DD, units}. venue: the record."""
    if not isinstance(form, dict):
        raise ManageError("body must be a JSON object")
    now = now or datetime.datetime.now(datetime.timezone.utc)
    name = _text(form.get("name"), "event name", limit=120)
    date = form.get("date") or now.strftime("%Y-%m-%d")
    if not isinstance(date, str) or not DATE.match(date):
        raise ManageError("date must be YYYY-MM-DD")
    try:
        day = datetime.datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ManageError("date must be a real YYYY-MM-DD date") from None
    if not owner_id:
        raise ManageError("bridge isn't signed in to CrowdCAD yet", 503)
    staff, supervisors = parse_units(form.get("units") or [])
    if not staff and not supervisors:
        raise ManageError("pick at least one contact as a team or supervisor")
    venue = _with_layers(venue)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {
        # CrowdCAD's create page: new Date('YYYY-MM-DD').toISOString() → midnight UTC.
        "name": name,
        "date": day.strftime("%Y-%m-%dT00:00:00.000Z"),
        "venue": venue,
        "postingTimes": [],
        "staff": staff,
        "supervisor": supervisors,
        "userId": owner_id,
        "calls": [],
        "eventPosts": [],
        "eventEquipment": [],
        "clinics": sync_clinics(venue),
        "dispatchZones": sync_dispatch_zones(venue),
        "surgeLimitPercent": 70,
        "pendingTransportSurgeThreshold": 3,
        "unassignedCallSurgeSeconds": 120,
        "isOrgEvent": True,
        "status": "active",
        "createdAt": stamp,
    }


def _where(name, event, overrides):
    spot = geo.post_location(name, event, overrides)
    return {"lat": spot[0], "lon": spot[1]} if spot else {"lat": None, "lon": None}


def can_dispatch(event, user_id, email):
    """CrowdCAD's events updateRule, for the bridge account: owner, org event, or shared with it.
    (The hook enforces the real rule on every write; this only explains it before a click.)"""
    if event.get("userId") and event.get("userId") == user_id:
        return True, None
    if event.get("isOrgEvent") is True:
        return True, None
    shared = event.get("sharedWith") or []
    if email and isinstance(shared, list) and email in shared:
        return True, None
    return False, (f"This event was made in CrowdCAD and isn't open to TAK dispatch yet. A CrowdCAD admin can open "
                   f"the event's menu on CrowdCAD's venue page and choose “Designate as org event”, or share it "
                   f"with {email or 'the bridge account'}. Events created with New event here are always dispatchable.")


def dispatch_view(event, overrides=None, user_id=None, email=None, details=None, w3w=False):
    """What CloudTAK's native dispatch needs from one event, in CrowdCAD's own names: units,
    open calls, posts and clinics. Same PHI rule as the board: a call's chief complaint at most,
    never age, sex, notes, logs or member names."""
    units = []
    for kind, key in (("team", "staff"), ("supervisor", "supervisor")):
        for unit in event.get(key) or []:
            if unit.get("team"):
                units.append({"name": unit["team"], "kind": kind, "status": unit.get("status"),
                              "location": unit.get("location"), "device": unit.get("takUid"),
                              **_where(unit.get("location"), event, overrides)})
    calls = []
    details = details or {}
    for call in event.get("calls") or []:
        if call.get("status") in dispatch.RESOLVED_CALL_STATUSES:
            continue
        where = _where(call.get("location"), event, overrides)
        if where["lat"] is None:
            coords = calldetails.parse_coords(call.get("location"))
            if coords:
                where = {"lat": coords[0], "lon": coords[1]}
        calls.append({"id": call.get("id"), "number": call.get("order"), "status": call.get("status"),
                      "location": call.get("location"), "chiefComplaint": call.get("chiefComplaint") or "",
                      "priority": bool(call.get("priority")), "assigned": list(call.get("assignedTeam") or []),
                      # the TAK details from the bridge's store (never parsed back out of notes)
                      "details": details.get(call.get("id")) or {},
                      **where})
    posts, seen = [], set()
    for post in venue_posts(event.get("venue") or {}):
        name = post if isinstance(post, str) else (post or {}).get("name")
        if name and name not in seen:
            seen.add(name)
            posts.append({"name": name, **_where(name, event, overrides)})   # lat/lon: "nearest post" from the map
    allowed, why = can_dispatch(event, user_id, email)
    return {"id": event.get("id"), "name": event.get("name"), "ended": bool(event.get("ended")),
            "canDispatch": allowed, "whyNot": why, "w3w": bool(w3w),
            "units": units, "calls": calls, "posts": posts,
            "clinics": [{"id": c.get("id"), "name": c.get("name")} for c in (event.get("clinics") or dispatch.DEFAULT_CLINICS)],
            "statuses": {"onCall": dispatch.ON_CALL_STATUSES, "availability": dispatch.AVAILABILITY_STATUSES}}


class Manager:
    """The manage API's actions against a PocketBase client (pocketbase.PocketBase)."""

    def __init__(self, pb, app_url=None, log=print, timezone="", layer_bounds=None, details=None, w3w_key="",
                 urlopen=urllib.request.urlopen):
        self.pb = pb
        self.details = details or calldetails.CallDetails()   # shared with the Publisher (__main__)
        self.w3w_key = w3w_key or ""
        self.urlopen = urlopen
        self.layer_bounds = layer_bounds or {}
        self.app_url = (app_url or "").rstrip("/") or None
        self.log = log
        self.timezone = timezone or ""
        self.store = EventStore(pb, log=log)

    # --- native dispatch (dispatch.py through store.py) ----------------------------------

    def _clock(self):
        return Clock(timezone=self.timezone)

    def view(self, event_id):
        self.pb.ensure_auth()
        try:
            return dispatch_view(self.pb.get_record("events", event_id), self.layer_bounds,
                                 self.pb.user_id, getattr(self.pb, "identity", None),
                                 self.details.for_event(event_id), bool(self.w3w_key))
        except Exception as error:
            raise ManageError(f"event not found: {event_id}", 404) from error

    def _dispatch(self, event_id, what, actor, action):
        """actor: the CloudTAK username (X-TAK-User); logs say "via CloudTAK: <user>"."""
        try:
            patch, extra = self.store.apply(event_id, action)
        except DispatchError as error:
            raise ManageError(str(error), error.status) from error
        self.log(f"event {event_id}: {what} by {actor}")
        return {"ok": True, **({"callId": extra} if extra else {})}

    def new_call(self, event_id, form, actor):
        """CrowdCAD's Add Call. form: {location, chiefComplaint, priority, source?, assign?, details?}.
        With details carrying a point, the call's CrowdCAD location IS that point ("lat, lon"); the
        rest goes to notes (calldetails.py). One write: call, details and assignment land together."""
        if not isinstance(form, dict):
            raise ManageError("body must be a JSON object")
        details = self._clean(form.get("details")) if form.get("details") else None
        if details and details["lat"] is not None:
            form = {**form, "location": calldetails.format_coords(details["lat"], details["lon"])}
        elif details and not (form.get("location") or "").strip() and details.get("description"):
            form = {**form, "location": details["description"]}
        clock = self._clock()
        via = f"CloudTAK: {actor}"
        expected = str(clock.ms)        # dispatch.new_call's id, unless that ms is already taken
        previous = self._store_put(event_id, expected, details) if details else None

        def action(ev):
            patch, call_id = dispatch.new_call(ev, form, via, clock)
            if details:
                patch = {**patch, **calldetails.apply({**ev, **patch}, call_id, details, via, clock)}
            return patch, call_id

        try:
            result = self._dispatch(event_id, f"new call at {form.get('location')}", actor, action)
        except ManageError:
            if details:
                self.details.restore(event_id, expected, previous)
            raise
        if details and result.get("callId") != expected:
            self.details.restore(event_id, expected, previous)
            self._store_put(event_id, result["callId"], details)
        return result

    def call_details(self, event_id, call_id, form, actor):
        """Set a call's TAK details: its point into CrowdCAD's location, the rest into notes."""
        details = self._clean(form)
        previous = self._store_put(event_id, call_id, details)
        try:
            return self._dispatch(event_id, f"details for call {call_id}", actor,
                                  lambda ev: calldetails.apply(ev, call_id, details, f"CloudTAK: {actor}", self._clock()))
        except ManageError:
            self.details.restore(event_id, call_id, previous)
            raise

    def call_notes(self, event_id, call_id, text, actor):
        """Replace a call's TAK notes, keeping its other TAK details."""
        current = {k: v for k, v in (self.details.get(event_id, call_id) or {}).items() if k != "notes"}
        return self.call_details(event_id, call_id, {**current, "notes": text}, actor)

    def add_team(self, event_id, form, actor):
        """CrowdCAD's Add Team (handleSaveNewTeam)."""
        name = (form or {}).get("name") if isinstance(form, dict) else None
        return self._dispatch(event_id, f"team {name!r} added", actor,
                              lambda ev: dispatch.add_team(ev, form, f"CloudTAK: {actor}", self._clock()))

    def add_supervisor(self, event_id, form, actor):
        """CrowdCAD's Add Supervisor (handleSaveNewSupervisor)."""
        name = (form or {}).get("callSign") if isinstance(form, dict) else None
        return self._dispatch(event_id, f"supervisor {name!r} added", actor,
                              lambda ev: dispatch.add_supervisor(ev, form, f"CloudTAK: {actor}", self._clock()))

    def _store_put(self, event_id, call_id, details):
        """The bridge's own copy of TAK details; saved before CrowdCAD is written, so a failure
        here means nothing reached CrowdCAD."""
        try:
            return self.details.put(event_id, call_id, details)
        except OSError as error:
            raise ManageError(f"the bridge couldn't save the call details on its host ({error.strerror}: "
                              f"{error.filename}); nothing was written to CrowdCAD", 500) from error

    @staticmethod
    def _clean(form):
        try:
            return calldetails.clean(form)
        except DispatchError as error:
            raise ManageError(str(error), error.status) from error

    def w3w(self, query):
        """what3words <-> coordinates for the dispatcher's form. The API key stays on the bridge
        (secrets.json w3w_api_key); without one this is 404 and the form hides what3words."""
        if not self.w3w_key:
            raise ManageError("what3words isn't set up on this bridge (no API key)", 404)
        words = (query.get("words") or [""])[0].strip().lower().lstrip("/")
        if words:
            if not calldetails.W3W.match(words):
                raise ManageError("what3words must look like ///word.word.word")
            path = "convert-to-coordinates?" + urllib.parse.urlencode({"words": words, "key": self.w3w_key})
        else:
            try:
                lat, lon = float((query.get("lat") or [""])[0]), float((query.get("lon") or [""])[0])
            except ValueError:
                raise ManageError("give words, or lat and lon") from None
            path = "convert-to-3wa?" + urllib.parse.urlencode({"coordinates": f"{lat},{lon}", "key": self.w3w_key})
        try:
            with self.urlopen("https://api.what3words.com/v3/" + path, timeout=8) as response:
                data = json.loads(response.read() or b"{}")
        except Exception as error:   # never echo the URL or the error text: both can carry the key
            raise ManageError(f"what3words lookup failed ({type(error).__name__})", 502) from None
        if data.get("error") or not data.get("words"):
            raise ManageError((data.get("error") or {}).get("message") or "what3words found nothing", 404)
        point = data.get("coordinates") or {}
        return {"words": data["words"], "lat": point.get("lat"), "lon": point.get("lng"),
                "nearestPlace": data.get("nearestPlace") or ""}

    def assign(self, event_id, call_id, form, actor):
        unit = (form or {}).get("unit")
        return self._dispatch(event_id, f"{unit} assigned to call {call_id}", actor,
                              lambda ev: dispatch.assign(ev, call_id, unit, f"CloudTAK: {actor}", self._clock()))

    def status_on_call(self, event_id, call_id, form, actor):
        form = form or {}
        return self._dispatch(event_id, f"{form.get('unit')} → {form.get('status')} on call {call_id}", actor,
                              lambda ev: dispatch.status_on_call(ev, call_id, form.get("unit"), form.get("status"),
                                                                 f"CloudTAK: {actor}", self._clock(), clinic_id=form.get("clinicId"),
                                                                 transport_unit=form.get("transportUnit")))

    def unit_status(self, event_id, form, actor):
        form = form or {}
        return self._dispatch(event_id, f"{form.get('unit')} → {form.get('status')}", actor,
                              lambda ev: dispatch.unit_status(ev, form.get("unit"), form.get("status"), f"CloudTAK: {actor}", self._clock()))

    def unit_post(self, event_id, form, actor):
        form = form or {}
        return self._dispatch(event_id, f"{form.get('unit')} → post {form.get('post')}", actor,
                              lambda ev: dispatch.unit_post(ev, form.get("unit"), form.get("post"), f"CloudTAK: {actor}", self._clock()))

    def venues(self):
        self.pb.ensure_auth()
        return {"venues": [venue_summary(v) for v in self.pb.list_venues()]}

    def create(self, form, actor="?"):
        venue_id = form.get("venueId") if isinstance(form, dict) else None
        if not isinstance(venue_id, str) or not venue_id:
            raise ManageError("pick a venue")
        self.pb.ensure_auth()
        try:
            venue = self.pb.get_record("venues", venue_id)
        except Exception as error:   # PocketBaseError: 404, or not visible to the bridge
            raise ManageError(f"venue not found: {venue_id}", 404) from error
        record = build_event(form, venue, self.pb.user_id)
        created = self.pb.create_event(record)
        eid = created.get("id")
        self.log(f"event {eid} '{record['name']}' created from TAK by {actor}: "
                 f"{len(record['staff'])} teams, {len(record['supervisor'])} supervisors, venue {venue.get('name')!r}")
        return {"id": eid, "name": record["name"],
                "dispatchUrl": f"{self.app_url}/events/{eid}/dispatch" if self.app_url and eid else None}

    def end(self, event_id, actor="?"):
        self.pb.ensure_auth()
        try:
            event = self.pb.get_record("events", event_id)
        except Exception as error:
            raise ManageError(f"event not found: {event_id}", 404) from error
        if event.get("userId") != self.pb.user_id:
            raise ManageError("only events created from TAK can be ended here; end this one in CrowdCAD", 403)
        if event.get("ended"):
            return {"id": event_id, "ended": True}
        self.pb.update_event(event_id, {"ended": True, "endedAt": int(datetime.datetime.now().timestamp() * 1000)})
        self.log(f"event {event_id} '{event.get('name')}' ended from TAK by {actor}")
        return {"id": event_id, "ended": True}
