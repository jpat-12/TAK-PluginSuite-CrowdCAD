# CrowdCAD × TAK × infra-TAK — integration plan

Origin: a proposal (Nov 2026) that CrowdCAD + TAK + what3words together would serve
collegiate EMS and county EM: CrowdCAD runs patients, calls and equipment; TAK runs the map,
team tracking and the common operating picture. This plan turns that into phases, cheapest
and safest first. Status of each phase is in the README.

## What CrowdCAD gives us to integrate with (checked against v1.6.0, Oct 2026)

- Open source (AGPL-3.0), Next.js front end, **two backends**: Firebase or self-hosted
  **PocketBase**. Only the PocketBase backend is integrable from infra-TAK; its interface is
  documented in CrowdCAD's own `docs/ICD.md`, which explicitly anticipates "a TAK
  integration".
- **One record per event.** Calls, teams, supervisors, equipment and the venue are JSON
  fields inside one `events` record. No calls collection, no per-call ids in the database.
  Reading is easy (one record = the whole picture; PocketBase streams changes over SSE).
  **Writing is the hard part** (Phase 3).
- **No coordinates.** Posts are percent-of-map-image; only GeoJSON-imported venue layers
  carry `geoBounds`. Georeferenced venue maps are a prerequisite, not a nice-to-have.
- Any signed-in user can *read* every event; *writing* needs to be the owner, an admin, a
  `sharedWith` member, or the event must be an org event.

## Phase 1: CrowdCAD → TAK (built)

The bridge follows CrowdCAD live and publishes calls, teams and dispatch zones as CoT in
IU Event CAD's format (docs/COT_FORMAT.md). One-way, read-only, so it can't damage CrowdCAD
data. This is the proposal's model 1 ("medic creates an encounter → it appears on
ATAK/WinTAK for command staff, the medical branch, the EOC").

Every client gets the same picture: the ATAK plugin builds its board from that CoT (plus the
medic's own status on their PLI, and an alert on assignment); the CloudTAK and WebTAK plugins
read the same content from the bridge's board API (docs/API.md). Any TAK client without a
plugin still sees the markers and zone shapes.

## Phase 2: CrowdCAD deployed by infra-TAK (built: `install.sh --with-crowdcad`, `infratak/crowdcad_app.py`)

As built (2026-11-19), differing from the sketch below: CrowdCAD's web app runs on **3100**
(TAK Portal holds 3000), both containers publish on loopback only, the compose file is our own
(`<home>/crowdcad/docker-compose.yml`, project `crowdcad`), `setup-pocketbase.js` runs in a
throwaway `node:22-alpine` container, and **public sign-up is closed** by default (any signed-in
CrowdCAD user can list every event, so open sign-up on a public host exposes call data); accounts
come from `crowdcad_app.py add-user`. v1.6.0's Dockerfile COPYs a `next-env.d.ts` the tag lacks;
`crowdcad_app.py` writes Next's stock one before building.

The original sketch:

Make "CrowdCAD" an infra-TAK module, not just a bridge to one that exists elsewhere:
`install.sh --with-crowdcad` builds CrowdCAD's own `docker-compose.yml` with
`NEXT_PUBLIC_BACKEND=pocketbase`, pinned to a release tag, and adds one Caddy site,
`crowdcad.<fqdn>`, below infra-TAK's user-blocks marker (Aleph's `aleph_caddy.py` pattern):

```
crowdcad.<fqdn> {
    handle /api/contact* { reverse_proxy 127.0.0.1:3000 }   # Next.js's only API route
    handle /api/*        { reverse_proxy 127.0.0.1:8090 }   # PocketBase REST + realtime
    handle /_/*          { reverse_proxy 127.0.0.1:8090 }   # PocketBase admin UI
    handle               { reverse_proxy 127.0.0.1:3000 }
}
```

One host means one DNS record and `NEXT_PUBLIC_POCKETBASE_URL=https://crowdcad.<fqdn>`
(baked in at build time). Then the bridge points at `http://127.0.0.1:8090` and the installer
creates its account. To check first: free ports on the host (3000 / 8090), whether CrowdCAD
sits behind Authentik forward_auth (probably not: it has its own login, and forward_auth
would break PocketBase's API for the bridge), and running `scripts/setup-pocketbase.js`
(needs Node) inside the build.

The same install on a field laptop/NUC is the **offline** answer: CrowdCAD (PocketBase on
the LAN), TAK Server and the bridge on one box, no internet.

## Built 2026-11-19: dispatch and events from the web clients

- **Dispatch from CloudTAK/WebTAK** embeds CrowdCAD's own dispatch screen (`dispatchUrl`), so
  every dispatch write is CrowdCAD's own code, signed in as the dispatcher. Chosen over native
  buttons: CrowdCAD's assign/status cascade is ~1,000 lines of client logic (detach, supervisor
  and equipment release, clinic outcomes) that the bridge would have to track release by release.
- **Native dispatch from CloudTAK** (same day, at Jon's request): new call, assign, status on call
  incl. the closing cascade, availability and post, ported from CrowdCAD v1.6.0's handlers into
  `dispatch.py` and written compare-and-swap through a PocketBase hook (`store.py`). This is the
  Phase 3/4 write problem solved for TAK-initiated dispatch: the hook makes the bridge's writes
  safe against CrowdCAD's; CrowdCAD's own read-then-PATCH window remains (it already exists
  between two CrowdCAD dispatchers). Embedding stays available as the *CrowdCAD* button.
- **New event from CloudTAK** (manage API, docs/API.md): the bridge creates the event record.
  Safe where native dispatch isn't, because a new record can't race a dispatcher. TAK contacts
  become units with `takUid`, so device binding is per event (config `team_uids` still works for
  events made in CrowdCAD).

## Phase 3: TAK → CrowdCAD (the proposal's model 2: "medic drops a marker → new call")

The bridge already holds a TAK connection; it reads and discards traffic today. Design:

1. A TAK user creates an incident in the IU plugin (or drops a marker of an agreed type) in
   the bridge's group. The bridge sees an `<__iucad_incident status="NEW">` it didn't send.
2. Location: nearest georeferenced post within N m (configurable), else the zone it falls in,
   else "TAK <lat,lon>" as free text.
3. It appends a `Pending` call to the event, source `TAK`, and from then on owns the CoT uid
   mapping (TAK uid ↔ CrowdCAD call id).

**The blocker is CrowdCAD's write model.** `calls` is one JSON array; a PATCH replaces the
whole array and PocketBase has no version/ETag check, so a bridge read-modify-write that
races a dispatcher's edit **silently drops one of them**. Options, best first:

- **A PocketBase JS hook** (`pb_hooks/crowdcad_tak.pb.js`) adding `POST /api/crowdcad-tak/calls`
  that appends inside a transaction. Atomic, and it only becomes possible once infra-TAK
  deploys PocketBase itself (Phase 2). Best fit.
- Ask CrowdCAD upstream for an append endpoint or a `calls` sub-collection. The ICD shows
  they think about integrations; this is worth raising either way.
- Read-modify-write with an immediate re-read check. Narrows the race but doesn't close it.
  Not acceptable for patient calls.

The bridge account also needs write access per event (shared with it, or org events).

## Phase 4: unit status from the field (bi-directional teams) — built 2026-11-19 (`fieldstatus.py`)

As built: taps (a changed `since`) from a device bound to a unit (`takUid` / team_uids) become
dispatch.py actions through store.py. Decisions (Jon): Available on a call = Detached (last unit →
CrowdCAD "Resolved"); Respond on an unassigned call = self-assign; Out of service on a call is
ignored. Phones nobody picked (events made in CrowdCAD) link themselves: a tap from an unlinked
phone whose ATAK callsign matches exactly one free unit name ("Team 1" ↔ TEAM1) writes that
unit's `takUid` with the tap (`claim_by_callsign`, default on). Conflict rule: only a new tap acts, so the newest human action wins either way. Spoofing:
any authenticated device in the TAK group could send a PLI with another unit's uid; acceptable
inside one group, revisit if groups get wide. The original sketch:

Medics set RESP / ONSC / TRAN on their own device (`<__iucad_unit>` on their PLI); the
bridge writes the matching CrowdCAD team status (reverse of the COT_FORMAT unit table) for
teams in `team_uids`. Same write constraint and same fix as Phase 3 (`staff` is also one
array). Conflict rule to decide: dispatcher's change vs medic's change, newest `since` wins?

## what3words (the IU flow)

Caller gives a w3w address → server converts it to lat/lon → nearest post → CrowdCAD call
location (via the Phase 3 write path) → TAK marker via Phase 1. The w3w key lives **on the
server only** (IU plan rule: no key in an APK). This lands naturally in the bridge as one
more "TAK → CrowdCAD" input; until then the IU Stage 2 Node-RED path covers it.

## The proposal's challenges, answered

| Challenge | Answer here |
|---|---|
| Implementing CoT support | In the bridge, not CrowdCAD: CrowdCAD stays unmodified upstream code |
| Authentication & permissions | CrowdCAD: a dedicated bridge account (read-only in Phase 1). TAK: its own client cert `crowdcad`, put in the medical group(s) with `--tak-group` |
| Offline synchronization | Bridge re-syncs on every reconnect (both sides) and degrades to polling if realtime fails; markers carry short stale times so outages show as gaps, not stale truth. Full offline = Phase 2 on a field node |
| Mapping standards between systems | Venue layers must be georeferenced (GeoJSON import or `layer_bounds`); unplaceable calls are listed, never guessed |
| HIPAA / privacy | No patient identifiers or notes leave CrowdCAD (tested). Chief complaint is sent as the IU `type`: a decision to confirm |
