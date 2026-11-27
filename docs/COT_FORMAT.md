# CrowdCAD for TAK — what the bridge sends

The bridge **produces IU Event CAD's CoT format; it doesn't define one.** Incidents and units
use `<__iucad_incident>` / `<__iucad_unit>` exactly as specified in
`TAK-PluginSuite-IndianaUniversity/ATAK5.6-Eventcad/docs/COT_FORMAT.md` (format `v="1"`).
That document is the authority. If it changes, this bridge follows it, never the reverse.
This is what the IU plan's Stage 3 ("real CAD: OpenAPI or CrowdCAD") needs: the IU plugin
shows CrowdCAD calls without knowing where they came from.

**Readers:** this suite's ATAK plugin (`atak/…/cot/IucadIncident.java`, `IucadUnit.java`) and
IU Event CAD. Both apply the same rules: newest `updated`/`since` wins, a higher `v` is ignored,
an unknown status drops the message, closed incidents leave the map at once.
`atak/app/src/test/resources/bridge-demo.cot` is this bridge's real output, parsed by the ATAK
tests. Regenerate it with `python bridge/tests/make_atak_fixture.py` after any change here.

> **Dependency:** IU's format is a DRAFT until it's locked (planned Tue Nov 10 2026). If the
> incident type, attribute names or status codes change at lock, `cot.py` / `mapping.py`
> change with them (tests pin every attribute).

## UIDs

| Thing | UID | Lives until |
|---|---|---|
| Call | `crowdcad-<eventId>-call-<call.id>` | call resolved / deleted / event ended |
| Team, supervisor | `crowdcad-<eventId>-team-<slug(team)>`, or the team's ATAK device uid if mapped (`team_uids`) | event ended / team removed |
| Dispatch zone | `crowdcad-<eventId>-zone-<zone.id>` | event ended / zone erased |
| Post (off by default) | `crowdcad-<eventId>-post-<layerId>-<slug(name)>` | event ended |

A team mapped to a device in `team_uids` gets **no** bridge marker: the device's own PLI is
the truth, and the incident's `assigned` names the device uid, which is what makes the IU
plugin alert that phone.

## Incident: CrowdCAD `Call` → `<__iucad_incident>`

```xml
<event version="2.0" uid="crowdcad-e1f2g3h4i5j6k7l-call-c1" type="b-m-p-s-p-i" how="h-e" ... stale="+300 s">
  <point lat="39.1820000" lon="-86.5255000" hae="9999999.0" ce="9999999.0" le="9999999.0"/>
  <detail>
    <contact callsign="007 · Chest pain"/>
    <__iucad_incident v="1" id="CC-007" status="ONSC" type="Chest pain" priority="1"
        location="Sec 104" reportedBy="Event Services" created="1794700800000"
        updated="1794701000000" assigned="crowdcad-e1f2g3h4i5j6k7l-team-team-1"/>
    <__crowdcad kind="incident"/>
  </detail>
</event>
```

| IU attribute | From CrowdCAD | Notes |
|---|---|---|
| `id` | `<id_prefix>-<call.order, 3 digits>` | `CC-007`. Set `id_prefixes` per event if two events run at once |
| `status` | derived, see below | |
| `type` | `call.chiefComplaint` | the one clinical field on the wire (see Decisions in README) |
| `priority` | `call.priority` → `1`, else `2` | CrowdCAD has a flag, not a 1–3 scale |
| `location` | the TAK description (`calldetails.py`) when a dispatcher gave one, else `call.location` | the post name, as dispatch typed it |
| `reportedBy` | `call.source`, else `CrowdCAD` | |
| `created` | earliest `call.log[].timestamp`, else first seen | |
| `updated` | bridge clock when the content changed, strictly increasing, never < `created` | |
| `assigned` | `call.assignedTeam` → team uids | omitted when empty |
| point | the post named by `call.location`, see Placement | |
| `floor` | TAK call details: 1–8, -1 basement; omitted when none | the callsign gains it: `009 · Laceration · F3` |
| `w3w` | TAK call details, without `///`; omitted when none | |
| point `ce` | `20` a georeferenced post · `15` a dispatcher's point · `75` the map centre (estimate) | IU reads `ce` as how good the point is |
| `notes` | **never sent** | notes may hold PHI; TAK details come from the bridge's own store, never from notes |

**Status**, in this order (CrowdCAD shows on-scene/transporting from the teams' statuses,
not the call's, the same way `dispatch/page.tsx getCallPrimaryStatus` does):

| Condition | IU status |
|---|---|
| `call.duplicate` | `CXL` |
| `call.status` ∈ Delivered, Refusal, NMM, Treat and Release, Rolled, Rolled from Scene, Resolved, Unable to Locate | `CLOSED` |
| no assigned team | `NEW` |
| an assigned team is `Transporting`, or call is `Transporting` / `Pending Transport` | `TRAN` |
| an assigned team is `On Scene` (or call is) | `ONSC` |
| otherwise | `DISP` |
| event `ended` | `CLOSED` (everything) |

Clinic walk-ups (`clinic: true` with no team) are skipped by default: there's no field
response to show (`publish.clinic_walkups` turns them on).

## Unit: CrowdCAD `Staff` / `Supervisor` → marker + `<__iucad_unit>`

Type `a-f-G-U-C`, `how="h-e"`, callsign = team name, point = the team's `location` post.

| CrowdCAD `status` | IU `status` |
|---|---|
| Available | `AVL` |
| En Route, En Route Eq, Assisting | `RESP` |
| On Scene | `ONSC` |
| Transporting | `TRAN` |
| On Break, In Clinic, Detached | `OOS` |
| anything else (Assigned, Pending, Delivered, …) | **no `__iucad_unit` at all**: IU's rule is that unknown is ignored, never defaulted |

`incident` = the IU id of the open call the team is assigned to (omitted for AVL/OOS).
`since` = `statusSince`, else the bridge's `updated`. Member names are never sent.

## Zone: dispatch-zone polygon → `u-d-f` shape

Closed polygon (`<link point>` per vertex, first repeated last), `strokeColor` /
`fillColor` (25% alpha) from `zone.color` as ATAK signed ARGB, `labels_on`, callsign = zone
name, point = vertex centroid, `remarks` = `CrowdCAD · <layer>`.

## Placement: how a CrowdCAD location becomes lat/lon

CrowdCAD has no coordinates of its own. A post is `(x, y)` as a **percentage of its layer's
map image**, and a call or team location is just a post name. So:

1. Find the post by exact name in the event's layers (the same rule CrowdCAD uses).
2. The layer needs bounds: `geoBounds` (stored when the venue map was built by **GeoJSON
   import**), or the operator's `layer_bounds` override for that layer id.
3. `lat = north − y% × (north − south)`, `lon = west + x% × (east − west)`: the exact inverse
   of CrowdCAD's `latLngToPercent` (linear, not Web Mercator; tested).
4. Fallback: the post's import-time `lat/lng` (stale if the post was dragged later).
5. Not a post but a coordinate pair (`"39.18200, -86.52550"`): placed there. A TAK dispatcher's
   map point, what3words, coordinates or map centre writes exactly this into CrowdCAD's own
   `location` field (`calldetails.py`); a CrowdCAD user typing it works the same.

Anything that can't be placed (free-text location, layer without bounds) is **not sent**,
and is listed on the console page under "Not on the map", so it's found before game day.

## Send rules

- Sent when its content changes. **Heartbeat** every `heartbeat_seconds` (120) re-sends
  everything live with the *same* `updated`, and `stale` is `stale_seconds` (300) ahead, so
  if the bridge dies its markers age off TAK instead of looking current.
- Closed things (resolved, cancelled or deleted call, removed team, erased zone, ended or deselected
  event) are sent **once** with status `CLOSED` (incidents) and a 90 s stale, then **immediately
  followed by TAK's delete** (`t-x-d-d` linking the marker's uid, with `<__forcedelete/>`, uid
  `<marker uid>.delete`), so CloudTAK and plugin-less ATAK/WinTAK drop the marker at once instead of
  showing it until the stale runs out. Plugins still read the CLOSED status first. Never re-sent.
  `delete_closed: false` in config.json turns the delete off (CLOSED + 90 s stale only).
- Something first seen already closed (e.g. last night's calls when the bridge restarts) is
  never sent.
- On every TAK reconnect, everything live is re-sent. On every CrowdCAD reconnect, a full
  listing is re-applied (subscribe first, then list, so no change falls in the gap).

## PHI rule (load-bearing)

Only the attributes in the tables above leave CrowdCAD. `age`, `gender`, `notes`, call and
team logs, and member names are never copied into the bridge's items, so no config can leak
them. `tests/test_mapping.py::test_no_patient_or_member_data_on_the_wire` renders every item
from a fixture seeded with fake patient details and asserts none appear.

## To ATAK: the roster (`t-x-crowdcad-roster`, CrowdCAD-only)

One message per live event, sent when any phone-carried unit's status or name changes, at once
when a supervisor request is made or cleared or a setting changes, and on every heartbeat (uid
`crowdcad-<event id>-roster`, point 0,0). The plugin colours its unit icons from it, plays the
dispatcher's chosen alert sound, and shows whether its supervisor request is still open:

```xml
<__crowdcad_roster v="1" alert="soft">
  <unit uid="ANDROID-1a2b" status="RESP" name="Medic 1" supreq="1794701000000"/>
</__crowdcad_roster>
```

| Attribute | Meaning |
|---|---|
| `v` | `1`. A plugin ignores a newer version |
| `alert` | the assignment alert sound a dispatcher picked in CloudTAK Settings: `soft` (soft pulses, the default) or `hilo`. Missing or unknown = `soft` (older bridges) |
| `unit/@uid` | the phone's device uid |
| `unit/@status` | IU status code (`AVL`, `RESP`, `ONSC`, `TRAN`, `OOS`, or empty if unknown) |
| `unit/@name` | the CrowdCAD unit the phone carries (its banner callsign) |
| `unit/@supreq` | `at` (ms) of the phone's open supervisor request (its `<__crowdcad_supreq at>`). Absent when there is none: once a dispatcher clears the request (or after an hour) it disappears, and the plugin shows *Supervisor request acknowledged* for a minute (since 1.0.0) |

## From ATAK: `<__crowdcad_ack>` on the medic's own PLI (CrowdCAD-only, since 0.1.6)

Medics can't set status (decided 2026-11-25). The plugin's one field action is Acknowledge on a
call assigned to that phone. The phone's position report then carries its latest one:

```xml
<__crowdcad_ack incident="CC-007" at="1794701000000"/>
```

| Attribute | Meaning |
|---|---|
| `incident` | the IU incident `id` (`CC-007`), not the CoT uid |
| `at` | ms since epoch of the tap. The bridge acts once per new `at`; the same value repeats on every PLI |

The bridge (`fieldstatus.py`) turns a new `at` into one line in that call's CrowdCAD log,
"1402 - Team 1 acknowledged the call. (via ATAK: MEDIC1)", and changes no status. It applies
only to a unit on that call. From an unlinked phone it also links the phone to the free unit
named like its callsign. IU Event CAD doesn't read this element. Plugins up to 0.1.5 put a
self-set `<__iucad_unit>` on the PLI instead; the bridge now ignores it.
