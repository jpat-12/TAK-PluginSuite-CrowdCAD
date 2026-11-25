# Board API — what the web clients build against

The bridge's only HTTP interface for clients. **Read-only** (dispatching happens in CrowdCAD's own
screen, which the clients embed via `dispatchUrl`; see below), and it carries exactly what the
bridge already sends as CoT (built from the bridge's record of what TAK was told, never from
CrowdCAD records directly), so it can't show anything a TAK device couldn't see, and no
patient data. ATAK doesn't use it: the ATAK plugin builds the same board from CoT.

Published at `https://crowdcad-tak.<fqdn>` (infratak/crowdcad_caddy.py). Only `/api/v1/*` and
`/healthz` are proxied; everything else on that host is 404.

Clients: CloudTAK's server half relays it (token stays server-side, no CORS); the WebTAK bundle
calls it from the browser (its page origin must be in the bridge's `cors_origins`).
Contract tests: `bridge/tests/test_api.py`, plus `webtak/test/board.test.mjs`, which renders a
board the Python bridge just produced.

## `GET /api/v1/info` (no auth)

```json
{"api": 1, "version": "0.1.0", "name": "CrowdCAD for TAK"}
```

Clients refuse a different `api` major instead of rendering a wrong board.

## `GET /api/v1/board` (`Authorization: Bearer <board_token>`)

`401` without the right token, `503` while the bridge isn't configured. `Cache-Control: no-store`.

```json
{
  "api": 1,
  "generated": 1794701000000,
  "bridge": {"crowdcad": "live", "tak": true, "version": "0.1.0"},
  "crowdcadUrl": "https://crowdcad.tak.example.org",
  "events": [{
    "id": "e1f2g3h4i5j6k7l",
    "name": "Demo Football Game",
    "dispatchUrl": "https://crowdcad.tak.example.org/events/e1f2g3h4i5j6k7l/dispatch",
    "calls": [{
      "uid": "crowdcad-e1f2g3h4i5j6k7l-call-c1", "id": "CC-007", "status": "ONSC",
      "type": "Chest pain", "priority": 1, "location": "Sec 104", "reportedBy": "Event Services",
      "assigned": [{"uid": "crowdcad-e1f2g3h4i5j6k7l-team-team-1", "callsign": "Team 1"}],
      "lat": 39.182, "lon": -86.5255, "created": 1794700800000, "updated": 1794701000000
    }],
    "units": [{
      "uid": "crowdcad-e1f2g3h4i5j6k7l-team-team-1", "callsign": "Team 1", "status": "ONSC",
      "incident": "CC-007", "location": "Sec 104", "supervisor": false, "device": false,
      "lat": 39.182, "lon": -86.5255, "since": 1794700931000
    }],
    "unplaced": [{"kind": "call", "label": "009 · Laceration", "location": "Row 22 by the hot dog stand"}]
  }]
}
```

| Field | Meaning |
|---|---|
| `bridge.crowdcad` | `live` (realtime) · `polling` (realtime failed, ~30 s) · `down` · `starting`. Clients warn on anything but `live` |
| `bridge.tak` | the bridge's TAK link is up; if false, map markers may be stale |
| `calls` | open incidents only (closed ones leave), sorted priority → least-progressed status → oldest. Status codes and field meanings: COT_FORMAT.md |
| `units[].status` | IU unit code, or `null` when CrowdCAD's team status has no IU equivalent (never defaulted) |
| `units[].device` | team carried by its own ATAK device (`team_uids`): listed with dispatch's status for it; `lat/lon` null, since its position is the device's PLI |
| `unplaced` | calls/teams CrowdCAD can't place on the map (show them; nobody else will) |
| `calls[].callId` / `number` | CrowdCAD's own call id (for the manage API's call actions) and its `#number` |
| `calls[].crowdcadStatus`, `units[].crowdcadStatus` | CrowdCAD's own status text ("Pending", "En Route", "On Break"…): clients show it, so their words match CrowdCAD's screen |
| `calls[].positionFrom` | `post` (a georeferenced post) · `coords` (a point a dispatcher placed: the call's CrowdCAD location is "lat, lon") · `estimate` (map centre) · `null` unplaced |
| `calls[].floor` / `w3w` / `description` | TAK call details (bridge `calldetails.py`, the bridge's own store; never read from notes). `floor` 1–8, -1 basement |
| `calls[].callLocation` | the call's CrowdCAD `location` field as stored (`location` shows the description when there is one) |
| `units[].lat/lon` (device units) | the device's last position report with a fix, as the bridge heard it (radar, closest units); null until heard |
| `crowdcadUrl` | the CrowdCAD web app (`crowdcad_app_url`), or `null` when not configured |
| `endable` | the event was created from TAK (owned by the bridge account), so the manage API can end it |
| `dispatchUrl` | CrowdCAD's own dispatch screen for this event, or `null`. Clients show a **Dispatch** button that embeds it (CloudTAK floating pane, WebTAK floating window) with an "open in new window" link. The dispatcher signs in to CrowdCAD there as themselves, so every change follows CrowdCAD's own rules and is attributed in its call log. The bridge never writes to CrowdCAD |

## Manage API: create/end events from TAK (`Authorization: Bearer <manage_token>`)

The bridge's only writes to CrowdCAD (`bridge/crowdcad_tak/manage.py`). The manage token goes
to CloudTAK's server half only (its New event form), never the WebTAK bundle. These responses
carry no CORS headers. `404` when the bridge has no manage token; `401` with the wrong one (the
board token doesn't work here). `X-TAK-User` (the CloudTAK username) is logged with each write.

| Call | Does |
|---|---|
| `GET /api/v1/manage/venues` | `{"venues": [{"id", "name", "posts", "clinics", "mapped"}]}`. `mapped`: a layer is georeferenced, so its posts reach the TAK map |
| `POST /api/v1/manage/events` | body `{"name", "date": "YYYY-MM-DD", "venueId", "units": [{"name", "kind": "team"\|"supervisor", "uid", "callsign"}]}` → `{"id", "name", "dispatchUrl"}`. Writes a new `events` record in the shape CrowdCAD's own Create Event page writes, status `active`, `isOrgEvent: true`, owned by the bridge account. Each unit is a team (`staff`) or supervisor entry plus `takUid` (the contact's device), so that device carries the unit: its PLI is the unit's position and assignment alerts go to it. `400` with a readable `error` for bad input; nothing is written then |
| `POST /api/v1/manage/events/{id}/end` | `{ended: true, endedAt}` (CrowdCAD's handleEndEvent). `403` for events not created from TAK |
| `GET /api/v1/manage/events/{id}/dispatch` | Native dispatch view in CrowdCAD's own names: `units` (`name, kind, status, location, device, lat, lon`), open `calls` (`id, number, status, location, chiefComplaint, priority, assigned, lat, lon`), `posts` (`name, lat, lon`), `clinics`, and the allowed `statuses.onCall` / `statuses.availability`. Never age, sex, notes, logs or member names |
| `POST …/events/{id}/calls` | `{location, chiefComplaint, priority, assign?}` → `{callId}` (quickcallmodal) |
| `POST …/events/{id}/calls/{callId}/assign` | `{unit}` (handleAddTeamToCall / supervisor assign) |
| `POST …/events/{id}/calls/{callId}/status` | `{unit, status, clinicId?, transportUnit?}`: `En Route, On Scene, Transporting, Pending Transport, Detached`, or a closing status (`Delivered, Refusal, NMM, Unable to Locate, Rolled from Scene`) with CrowdCAD's full cascade (handleTeamStatusChange) |
| `POST …/events/{id}/units/status` | `{unit, status}`: `Available, On Break, In Clinic` (handleStatusChange) |
| `POST …/events/{id}/units/post` | `{unit, post}` (handleLocationChange) |
| `POST …/calls` with `details` | Add Call plus TAK details in one write: `details: {lat, lon, source: map\|w3w\|coords\|centre\|post, post?, description?, floor?, w3w?}`. A point becomes the call's CrowdCAD `location` ("39.18200, -86.52550"); description, floor, what3words and the source go into ONE `[TAK] …` line of its `notes` |
| `POST …/calls/{callId}/details` | the same details for an open call: a point or `post` replaces its `location`; the `[TAK]` line in `notes` is replaced in place (the rest of the notes is never touched); one log entry "TAK details: …" |
| `POST …/events/{id}/teams` | Add Team (handleSaveNewTeam): `{name, members?: [{name, cert, lead}], takUid?}` → staff entry `{team, members: ["Name [Cert] (Lead)"], status: Available, location: ""}`. Names unique across teams AND supervisors (409) |
| `POST …/events/{id}/supervisors` | Add Supervisor (handleSaveNewSupervisor): `{callSign, cert, name?, takUid?}` → `{team, member: "Name [Cert]", status: Available, location: Roaming}` |
| `GET /api/v1/manage/w3w?words=a.b.c` or `?lat=&lon=` | `{words, lat, lon, nearestPlace}` via what3words with the bridge's `w3w_api_key` (secrets.json). `404` when no key; the key never leaves the bridge |

**Notes are write-only from TAK.** Notes can hold patient details, so the bridge never reads them
to send anywhere: the `[TAK]` line is a copy for people working in CrowdCAD's own screen, and the
board and CoT read the bridge's store (`data_dir/call_details.json`). Tests: `bridge/tests/test_calldetails.py`.

Dispatch writes are CrowdCAD v1.6.0's own handlers ported to `bridge/crowdcad_tak/dispatch.py`,
applied by `store.py` compare-and-swap through the PocketBase hook `infratak/pb_hooks/crowdcad_tak.pb.js`
(installed with `--with-crowdcad`): the write lands only if what the bridge read is unchanged,
else it re-reads and re-applies, so it never overwrites a newer CrowdCAD change. The hook enforces
the events collection's own update rule. Errors: `404` unknown event/call/unit, `400` bad
status/input, `403` the bridge account can't update that event (make it an org event or share
it with the bridge account), `409` closed call / ended event / kept changing. Log lines say
"(via CloudTAK: <user>)" and use the bridge's `timezone` setting for their "hhmm" prefix.

Additive changes (new fields) keep `api: 1`; clients ignore fields they don't know. Removing or
renaming a field bumps `api` and every client together.
