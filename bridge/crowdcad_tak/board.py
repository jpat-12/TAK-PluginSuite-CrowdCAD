"""The board: the same live picture the bridge sends as CoT, as JSON for the web clients
(CloudTAK, WebTAK). Contract: docs/API.md.

Built only from the Publisher's record of what TAK was told, never from CrowdCAD records
directly, so the board can't show anything a TAK device couldn't already see (PHI rule in
mapping.py holds here by construction). ATAK doesn't use this: it builds the same board
from the CoT it receives.
"""

import urllib.parse

API_VERSION = 1

STATUS_ORDER = {"NEW": 0, "DISP": 1, "ONSC": 2, "TRAN": 3}


def build(publisher, now_ms, bridge_status=None, own_user=None, heard=None):
    """own_user: the bridge account's CrowdCAD id; its events (created from TAK) are `endable`.
    heard: device uid → ms the bridge last received anything from it (fieldstatus.FieldStatus)."""
    heard = heard or {}
    with publisher.lock:
        live = [(uid, e) for uid, e in publisher.sent.items() if not e["done"]]
        callsigns = {uid: e["item"].fields.get("callsign") for uid, e in live if e["item"].kind == "unit"}
        team_uids = publisher.config.get("team_uids") or {}
        app_url = (publisher.config.get("crowdcad_app_url") or "").strip().rstrip("/") or None
        events = []
        for eid, info in publisher.events.items():
            calls, units = [], []
            for uid, entry in live:
                if entry["event"] != eid:
                    continue
                item, f = entry["item"], entry["item"].fields
                if item.kind == "incident":
                    uids = [u for u in (f.get("assigned") or "").split(",") if u]
                    names = item.meta.get("assigned_teams") or []
                    calls.append({
                        "uid": uid, "placed": True, "id": f["id"], "status": f["status"], "type": f["type"],
                        "priority": f["priority"], "location": f["location"], "reportedBy": f["reportedBy"],
                        "assigned": [{"uid": u, "callsign": callsigns.get(u) or (names[i] if i < len(names) else u)}
                                     for i, u in enumerate(uids)],
                        "lat": item.lat, "lon": item.lon,
                        "created": entry["created"], "updated": entry["updated"],
                    })
                elif item.kind == "unit":
                    units.append({
                        "uid": uid, "placed": True, "callsign": f["callsign"], "status": f.get("status"),
                        "incident": f.get("incident"), "location": f["location"],
                        "supervisor": bool(f.get("supervisor")), "device": False,
                        "lat": item.lat, "lon": item.lon, "since": f.get("since") or entry["updated"],
                    })
            # Teams carried by their own ATAK device: listed with dispatch's view of them, but
            # their position lives on the device's PLI, which the bridge doesn't track.
            for team in info.get("device_teams") or []:
                device_uid = team.get("uid") or team_uids.get(team["name"])
                units.append({"uid": device_uid, "placed": False, "lastHeard": heard.get(device_uid), "callsign": team["name"],
                              "status": team["status"], "incident": team["incident"], "location": team["location"],
                              "supervisor": team["supervisor"], "device": True, "lat": None, "lon": None,
                              "since": team["since"]})
            # Open calls and teams CrowdCAD can't place still belong on the board: listed with
            # placed=false and no position (the map can't show them; the board must).
            for u in info["unplaced"]:
                d = u.get("details") or {}
                if u["kind"] == "call":
                    calls.append({"uid": None, "placed": False, "id": d.get("id") or u["label"],
                                  "status": d.get("status"), "type": d.get("type") or u["label"],
                                  "priority": d.get("priority", 2), "location": u["location"],
                                  "reportedBy": d.get("reportedBy") or "CrowdCAD",
                                  "assigned": [{"uid": None, "callsign": name} for name in d.get("assigned") or []],
                                  "lat": None, "lon": None, "created": d.get("created"), "updated": None})
                elif u["kind"] == "team":
                    units.append({"uid": None, "placed": False, "callsign": u["label"], "status": d.get("status"),
                                  "incident": d.get("incident"), "location": u["location"],
                                  "supervisor": bool(d.get("supervisor")), "device": False,
                                  "lat": None, "lon": None, "since": d.get("since")})
            calls.sort(key=lambda c: (c["priority"], STATUS_ORDER.get(c["status"], 9), c["created"] or 0))
            units.sort(key=lambda u: (u["supervisor"], u["callsign"] or ""))
            events.append({"id": eid, "name": info["name"], "date": info.get("date"), "calls": calls, "units": units,
                           "unplaced": info["unplaced"],
                           "endable": bool(own_user) and info.get("owner") == own_user,
                           # CrowdCAD's own dispatch screen for this event (the clients embed it);
                           # writes happen there, as the signed-in dispatcher, never through the bridge.
                           "dispatchUrl": f"{app_url}/events/{urllib.parse.quote(eid, safe='')}/dispatch" if app_url else None})
    return {"api": API_VERSION, "generated": now_ms, "bridge": bridge_status or {}, "crowdcadUrl": app_url,
            "events": events}
