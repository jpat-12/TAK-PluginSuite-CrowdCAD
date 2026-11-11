# Board API — what the web clients build against

The bridge's only HTTP interface for clients. **Read-only**, and it carries exactly what the
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
  "events": [{
    "id": "e1f2g3h4i5j6k7l",
    "name": "Demo Football Game",
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

Additive changes (new fields) keep `api: 1`; clients ignore fields they don't know. Removing or
renaming a field bumps `api` and every client together.
