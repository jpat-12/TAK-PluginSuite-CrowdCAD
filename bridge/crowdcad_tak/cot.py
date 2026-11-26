"""mapping.Item → CoT XML. Wire format: docs/COT_FORMAT.md (incident/unit details are IU Event
CAD's `__iucad_*` format verbatim, so the IU ATAK plugin reads CrowdCAD calls unmodified)."""

import hashlib
import time
import xml.etree.ElementTree as ET

from . import IUCAD_FORMAT_VERSION

UNKNOWN = "9999999.0"   # CoT's "not known" for hae/ce/le
CLOSED_STALE_S = 90     # COT_FORMAT.md: closed incidents re-sent with a 90 s stale, then dropped

TYPES = {
    "incident": "b-m-p-s-p-i",   # IU's placeholder incident type — must match theirs
    "unit": "a-f-G-U-C",
    "zone": "u-d-f",
    "post": "b-m-p-s-m",
}


# The CrowdCAD iconset (iconset/build_iconset.py; installed on ATAK by the plugin, imported into
# CloudTAK/WinTAK by hand). Its uid and filenames are API: never change them once shipped.
ICONSET_UID = hashlib.sha256(b"crowdcad-tak/iconset").hexdigest()
PRIORITY_ICON = {1: "EMS P1.png", 2: "EMS P2.png", 3: "EMS P3.png"}
# Raw GitHub PNGs (iconset/png in this repo): every TAK client fetches the same picture by URL, no
# iconset import needed (the IU bridge's CAD_ICON_BASE approach). config `icon_base` overrides;
# "" falls back to the iconset path.
ICON_BASE = "https://raw.githubusercontent.com/jpat-12/TAK-PluginSuite-CrowdCAD/dev/iconset/png/"


def incident_icon(priority, base=ICON_BASE):
    """A call's marker: the EMS icon tinted by priority (same as ATAK's plugin), by URL."""
    name = PRIORITY_ICON.get(int(priority), PRIORITY_ICON[2])
    if base:
        return base.rstrip("/") + "/" + name.replace(" ", "%20")
    return f"{ICONSET_UID}/CrowdCAD/{name}"


def iso(ms):
    seconds, millis = divmod(int(ms), 1000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds)) + f".{millis:03d}Z"


def argb(hex_color, alpha=0xFF):
    """'#3b82f6' → ATAK's signed 32-bit ARGB int."""
    text = (hex_color or "").lstrip("#")
    try:
        rgb = int(text[:6], 16) if len(text) >= 6 else 0x3B82F6
    except ValueError:
        rgb = 0x3B82F6
    value = (alpha << 24) | rgb
    return value - (1 << 32) if value & 0x80000000 else value


def _event(item, now_ms, stale_s):
    stale_s = CLOSED_STALE_S if item.closed else stale_s
    root = ET.Element("event", {
        "version": "2.0", "uid": item.uid, "type": TYPES[item.kind], "how": "h-e",
        "time": iso(now_ms), "start": iso(now_ms), "stale": iso(now_ms + stale_s * 1000),
    })
    ce = item.fields.get("ce")     # incidents: how good the point is (mapping.POSITION_CE)
    ET.SubElement(root, "point", {"lat": f"{item.lat:.7f}", "lon": f"{item.lon:.7f}",
                                  "hae": UNKNOWN, "ce": f"{ce:.1f}" if ce else UNKNOWN, "le": UNKNOWN})
    detail = ET.SubElement(root, "detail")
    ET.SubElement(detail, "contact", {"callsign": str(item.fields.get("callsign") or "")})
    return root, detail


DELETE_STALE_S = 20
BRIDGE_UID = "crowdcad-bridge"
BRIDGE_CALLSIGN = "CrowdCAD"


def render_chat(to_uid, to_callsign, text, message_id, now_ms):
    """A GeoChat direct message from the bridge to one device (TAK Server routes it to that uid
    only, via <marti><dest>). ATAK, WinTAK, iTAK and CloudTAK show it with their own chat
    notification: no plugin needed. Used for Request Supervisor."""
    root = ET.Element("event", {
        "version": "2.0", "uid": f"GeoChat.{BRIDGE_UID}.{to_uid}.{message_id}", "type": "b-t-f",
        "how": "h-g-i-g-o", "time": iso(now_ms), "start": iso(now_ms), "stale": iso(now_ms + 3600 * 1000),
    })
    ET.SubElement(root, "point", {"lat": "0.0", "lon": "0.0", "hae": UNKNOWN, "ce": UNKNOWN, "le": UNKNOWN})
    detail = ET.SubElement(root, "detail")
    chat = ET.SubElement(detail, "__chat", {
        "parent": "RootContactGroup", "groupOwner": "false", "messageId": message_id,
        "chatroom": to_callsign, "id": to_uid, "senderCallsign": BRIDGE_CALLSIGN})
    ET.SubElement(chat, "chatgrp", {"uid0": BRIDGE_UID, "uid1": to_uid, "id": to_uid})
    ET.SubElement(detail, "link", {"uid": BRIDGE_UID, "type": "a-f-G-U-C", "relation": "p-p"})
    remarks = ET.SubElement(detail, "remarks", {"source": f"BAO.F.ATAK.{BRIDGE_UID}", "to": to_uid,
                                                "time": iso(now_ms)})
    remarks.text = text
    ET.SubElement(ET.SubElement(detail, "marti"), "dest", {"uid": to_uid})
    return ET.tostring(root, encoding="unicode")
ROSTER_TYPE = "t-x-crowdcad-roster"   # a tasking type: TAK clients route it, maps don't draw it


def render_roster(event_id, units, now_ms, stale_s):
    """Each phone-carried unit's dispatch status, for the ATAK plugin's unit icons (green available,
    grey out of service, light red anything else), and its CrowdCAD unit name for the panel's
    banner. units: [(device uid, IU status code or "", unit name)]. Unit names already go out as
    marker callsigns; no member names, nothing from a call."""
    root = ET.Element("event", {
        "version": "2.0", "uid": f"crowdcad-{event_id}-roster", "type": ROSTER_TYPE, "how": "h-g-i-g-o",
        "time": iso(now_ms), "start": iso(now_ms), "stale": iso(now_ms + stale_s * 1000),
    })
    ET.SubElement(root, "point", {"lat": "0.0", "lon": "0.0", "hae": UNKNOWN, "ce": UNKNOWN, "le": UNKNOWN})
    roster = ET.SubElement(ET.SubElement(root, "detail"), "__crowdcad_roster", {"v": "1"})
    for uid, status, name in units:
        ET.SubElement(roster, "unit", {"uid": uid, "status": status or "", "name": name or ""})
    return ET.tostring(root, encoding="unicode")


def render_delete(target_uid, target_kind, now_ms):
    """TAK's standard delete for a marker: <event type="t-x-d-d"> linking the target, with
    <__forcedelete/>. ATAK, WinTAK, iTAK and CloudTAK drop the marker at once instead of waiting for
    its stale; sent right after the CLOSED message, so plugins still see the call close first."""
    root = ET.Element("event", {
        "version": "2.0", "uid": f"{target_uid}.delete", "type": "t-x-d-d", "how": "h-g-i-g-o",
        "time": iso(now_ms), "start": iso(now_ms), "stale": iso(now_ms + DELETE_STALE_S * 1000),
    })
    ET.SubElement(root, "point", {"lat": "0.0", "lon": "0.0", "hae": UNKNOWN, "ce": UNKNOWN, "le": UNKNOWN})
    detail = ET.SubElement(root, "detail")
    ET.SubElement(detail, "link", {"uid": target_uid, "relation": "p-p", "type": TYPES[target_kind]})
    ET.SubElement(detail, "__forcedelete")
    return ET.tostring(root, encoding="unicode")


def render(item, now_ms, created_ms, updated_ms, stale_s):
    root, detail = _event(item, now_ms, stale_s)
    f = item.fields
    if item.kind == "incident":
        attrs = {"v": str(IUCAD_FORMAT_VERSION), "id": f["id"], "status": f["status"], "type": f["type"],
                 "priority": str(f["priority"]), "location": f["location"], "reportedBy": f["reportedBy"],
                 "created": str(int(created_ms)), "updated": str(int(updated_ms))}
        if f.get("assigned"):
            attrs["assigned"] = f["assigned"]
        if f.get("floor"):
            attrs["floor"] = str(int(f["floor"]))     # IU: 1–8, -1 basement; omitted = none
        if f.get("w3w"):
            attrs["w3w"] = f["w3w"]
        if f.get("notes"):
            attrs["notes"] = f["notes"]     # IU format: complaint/notes, no names, DOB or MRN (TAK notes only)
        ET.SubElement(detail, "__iucad_incident", attrs)
        ET.SubElement(detail, "usericon", {"iconsetpath": incident_icon(f["priority"])})
    elif item.kind == "unit":
        # Unmapped status → no unit detail at all (COT_FORMAT.md §1: unknown is ignored, never defaulted).
        if f.get("status"):
            attrs = {"v": str(IUCAD_FORMAT_VERSION), "status": f["status"],
                     "since": str(int(f.get("since") or updated_ms))}
            if f.get("incident") and f["status"] not in ("AVL", "OOS"):
                attrs["incident"] = f["incident"]
            ET.SubElement(detail, "__iucad_unit", attrs)
    elif item.kind == "zone":
        for lat, lon in list(item.shape) + item.shape[:1]:   # closed ring: first vertex repeated
            ET.SubElement(detail, "link", {"point": f"{lat:.7f},{lon:.7f}"})
        ET.SubElement(detail, "strokeColor", {"value": str(argb(f["color"]))})
        ET.SubElement(detail, "strokeWeight", {"value": "3.0"})
        ET.SubElement(detail, "fillColor", {"value": str(argb(f["color"], 0x40))})
        ET.SubElement(detail, "labels_on", {"value": "true"})
    if item.kind != "incident" and f.get("layer"):
        ET.SubElement(detail, "remarks").text = f"CrowdCAD · {f['layer']}"
    ET.SubElement(detail, "__crowdcad", {"kind": item.kind})
    return ET.tostring(root, encoding="unicode")
