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
| `location` | `call.location` | the post name, as dispatch typed it |
| `reportedBy` | `call.source`, else `CrowdCAD` | |
| `created` | earliest `call.log[].timestamp`, else first seen | |
| `updated` | bridge clock when the content changed, strictly increasing, never < `created` | |
| `assigned` | `call.assignedTeam` → team uids | omitted when empty |
| point | the post named by `call.location`, see Placement | |
| `floor`, `w3w`, `notes` | **not sent** | no CrowdCAD source for floor/w3w; notes may hold PHI |

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

Anything that can't be placed (free-text location, layer without bounds) is **not sent**,
and is listed on the console page under "Not on the map", so it's found before game day.

## Send rules

- Sent when its content changes. **Heartbeat** every `heartbeat_seconds` (120) re-sends
  everything live with the *same* `updated`, and `stale` is `stale_seconds` (300) ahead, so
  if the bridge dies its markers age off TAK instead of looking current.
- Closed things (resolved call, deleted team/zone, ended or deselected event) are sent **once**
  with status `CLOSED` (incidents) and a 90 s stale, then stop. No `t-x-d-d` deletes (IU rule:
  late joiners never see them).
- Something first seen already closed (e.g. last night's calls when the bridge restarts) is
  never sent.
- On every TAK reconnect, everything live is re-sent. On every CrowdCAD reconnect, a full
  listing is re-applied (subscribe first, then list, so no change falls in the gap).

## PHI rule (load-bearing)

Only the attributes in the tables above leave CrowdCAD. `age`, `gender`, `notes`, call and
team logs, and member names are never copied into the bridge's items, so no config can leak
them. `tests/test_mapping.py::test_no_patient_or_member_data_on_the_wire` renders every item
from a fixture seeded with fake patient details and asserts none appear.
