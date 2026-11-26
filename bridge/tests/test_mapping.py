"""Geometry, CrowdCAD → item mapping, and the rendered CoT — over the demo fixture."""

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from crowdcad_tak import config, cot, geo, mapping

FIXTURE = Path(__file__).parent / "fixtures" / "event_demo_stadium.json"
EID = "e1f2g3h4i5j6k7l"


def demo():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def build(event=None, **overrides):
    return mapping.build(event or demo(), {**config.DEFAULTS, **overrides})


def latlng_to_percent(lat, lng, b):
    """CrowdCAD's src/lib/markerUtils.ts latLngToPercent, transcribed — geo must invert it."""
    return (lng - b["west"]) / (b["east"] - b["west"]) * 100, (b["north"] - lat) / (b["north"] - b["south"]) * 100


class GeoTest(unittest.TestCase):
    B = {"north": 39.183, "south": 39.179, "east": -86.523, "west": -86.528}

    def test_corners_and_centre(self):
        self.assertEqual(geo.percent_to_latlon(0, 0, self.B), (39.183, -86.528))
        self.assertEqual(geo.percent_to_latlon(100, 100, self.B), (39.179, -86.523))
        self.assertEqual(geo.percent_to_latlon(50, 50, self.B), (39.181, -86.5255))

    def test_inverts_crowdcads_projection(self):
        for lat, lng in [(39.1801234, -86.5271111), (39.1829, -86.5231)]:
            x, y = latlng_to_percent(lat, lng, self.B)
            back = geo.percent_to_latlon(x, y, self.B)
            self.assertAlmostEqual(back[0], lat, places=6)
            self.assertAlmostEqual(back[1], lng, places=6)

    def test_post_uses_live_xy_over_import_latlng(self):
        # Gate A carries stale import lat/lng (39.0, -86.0); x/y on a bounded layer wins.
        lat, lon, layer = geo.post_location("Gate A", demo())
        self.assertEqual((lat, lon, layer), (39.181, -86.5275, "Field Level"))

    def test_unbounded_layer_unplaced_until_overridden(self):
        self.assertIsNone(geo.post_location("Concourse 2", demo()))
        where = geo.post_location("Concourse 2", demo(), {"l2": self.B})
        self.assertEqual(where[:2], geo.percent_to_latlon(30, 30, self.B))

    def test_latlng_fallback_when_no_bounds(self):
        event = demo()
        del event["venue"]["layers"][0]["geoBounds"]
        self.assertEqual(geo.post_location("Gate A", event)[:2], (39.0, -86.0))

    def test_free_text_and_string_posts_unplaced(self):
        self.assertIsNone(geo.post_location("Row 22 by the hot dog stand", demo()))
        self.assertIsNone(geo.post_location("Legacy string post", demo()))
        self.assertIsNone(geo.post_location("", demo()))

    def test_legacy_venue_uses_event_posts(self):
        event = {"venue": {"name": "Old"}, "eventPosts": [{"name": "P", "x": 1, "y": 2}]}
        self.assertEqual(geo.event_layers(event)[0]["id"], "legacy-layer")
        self.assertIsNone(geo.post_location("P", event))           # no bounds, no lat/lng
        self.assertIsNotNone(geo.post_location("P", event, {"legacy-layer": self.B}))

    def test_degenerate_bounds_rejected(self):
        self.assertIsNone(geo.layer_bounds({"geoBounds": {"north": 1, "south": 1, "east": 2, "west": 1}}))


class MappingTest(unittest.TestCase):
    def test_call_status_follows_team_status(self):
        staff = {"T": {"status": "On Scene"}, "U": {"status": "Transporting"}, "V": {"status": "En Route"}}
        s = mapping.call_status
        self.assertEqual(s({"status": "Pending", "assignedTeam": []}, staff), "NEW")
        self.assertEqual(s({"status": "Assigned", "assignedTeam": ["V"]}, staff), "DISP")
        self.assertEqual(s({"status": "Assigned", "assignedTeam": ["T"]}, staff), "ONSC")
        self.assertEqual(s({"status": "Assigned", "assignedTeam": ["T", "U"]}, staff), "TRAN")
        self.assertEqual(s({"status": "Pending Transport", "assignedTeam": ["V"]}, staff), "TRAN")
        self.assertEqual(s({"status": "Refusal", "assignedTeam": ["T"]}, staff), "CLOSED")
        self.assertEqual(s({"status": "Assigned", "assignedTeam": ["T"], "duplicate": True}, staff), "CXL")

    def test_demo_event_items(self):
        items, unplaced = build()
        prefix = f"crowdcad-{EID}"
        c1 = items[f"{prefix}-call-c1"].fields
        self.assertEqual((c1["id"], c1["status"], c1["priority"], c1["callsign"]), ("CC-007", "ONSC", 1, "007 · Chest pain"))
        self.assertEqual(c1["assigned"], f"{prefix}-team-team-1")
        self.assertEqual(items[f"{prefix}-call-c1"].created_ms, 1794700800000)
        self.assertEqual(items[f"{prefix}-call-c2"].fields["status"], "NEW")
        self.assertTrue(items[f"{prefix}-call-c3"].closed)
        self.assertNotIn(f"{prefix}-call-c5", items)               # clinic walk-up: no field response
        self.assertEqual(items[f"{prefix}-team-team-1"].fields["incident"], "CC-007")
        self.assertEqual(items[f"{prefix}-team-team-2"].fields["status"], "AVL")
        self.assertIn(f"{prefix}-zone-z1", items)
        self.assertNotIn("post", {i.kind for i in items.values()})  # posts off by default
        self.assertEqual(sorted((u.kind, u.label) for u in unplaced),
                         [("call", "009 · Laceration"), ("team", "Team 3")])

    def test_team_on_its_own_device(self):
        items, _ = build(team_uids={"Team 1": "ANDROID-abc123"})
        self.assertNotIn(f"crowdcad-{EID}-team-team-1", items)
        self.assertEqual(items[f"crowdcad-{EID}-call-c1"].fields["assigned"], "ANDROID-abc123")

    def test_unmapped_team_status_sends_no_unit_detail(self):
        event = demo()
        event["staff"][1]["status"] = "Assigned"
        items, _ = build(event)
        xml = render(items[f"crowdcad-{EID}-team-team-2"])
        self.assertIsNone(ET.fromstring(xml).find("detail/__iucad_unit"))

    def test_ended_event_closes_everything(self):
        event = demo()
        event["ended"] = True
        items, unplaced = build(event)
        self.assertTrue(all(i.closed for i in items.values()))
        self.assertEqual({i.fields["status"] for i in items.values() if i.kind == "incident"}, {"CLOSED"})
        self.assertEqual(unplaced, [])

    def test_publish_switches(self):
        items, _ = build(publish={"calls": False, "teams": False, "zones": False, "posts": True})
        self.assertEqual({i.kind for i in items.values()}, {"post"})
        names = {i.fields["callsign"] for i in items.values()}
        self.assertEqual(names, {"Gate A", "Sec 104", "First Aid"})

    def test_no_patient_or_member_data_on_the_wire(self):
        event = demo()
        items, _ = build(event, publish={**config.DEFAULTS["publish"], "posts": True, "clinic_walkups": True})
        wire = "\n".join(render(i) for i in items.values())
        for secret in ("John", "Smith", "DOB", "1970", "Alex Doe", "Sam Roe", "Jamie Poe", "Pat Quinn"):
            self.assertNotIn(secret, wire)
        for attribute in ('age="', 'gender="', 'notes="', 'members="'):
            self.assertNotIn(attribute, wire)


def render(item, now=1794701000000):
    return cot.render(item, now, item.created_ms or now, now, 300)


class CotTest(unittest.TestCase):
    def test_incident_matches_iucad_format(self):
        items, _ = build()
        root = ET.fromstring(render(items[f"crowdcad-{EID}-call-c1"]))
        self.assertEqual((root.get("type"), root.get("how")), ("b-m-p-s-p-i", "h-e"))
        self.assertEqual(root.get("stale"), "2026-11-15T00:08:20.000Z")    # now + 300 s
        self.assertEqual(root.find("point").get("hae"), "9999999.0")
        inc = root.find("detail/__iucad_incident")
        self.assertEqual(inc.attrib, {
            "v": "1", "id": "CC-007", "status": "ONSC", "type": "Chest pain", "priority": "1",
            "location": "Sec 104", "reportedBy": "Event Services", "created": "1794700800000",
            "updated": "1794701000000", "assigned": f"crowdcad-{EID}-team-team-1"})
        self.assertEqual(root.find("detail/contact").get("callsign"), "007 · Chest pain")
        self.assertEqual(root.find("detail/usericon").get("iconsetpath"),
                         "https://raw.githubusercontent.com/jpat-12/TAK-PluginSuite-CrowdCAD/dev/iconset/png/EMS%20P1.png")

    def test_closed_incident_short_stale(self):
        items, _ = build()
        root = ET.fromstring(render(items[f"crowdcad-{EID}-call-c3"]))
        self.assertEqual(root.get("stale"), "2026-11-15T00:04:50.000Z")    # now + 90 s
        self.assertEqual(root.find("detail/__iucad_incident").get("status"), "CLOSED")

    def test_unit_detail(self):
        items, _ = build()
        unit = ET.fromstring(render(items[f"crowdcad-{EID}-team-team-1"])).find("detail/__iucad_unit")
        self.assertEqual(unit.attrib, {"v": "1", "status": "ONSC", "since": "1794700931000", "incident": "CC-007"})
        avl = ET.fromstring(render(items[f"crowdcad-{EID}-team-team-2"])).find("detail/__iucad_unit")
        self.assertNotIn("incident", avl.attrib)

    def test_zone_is_closed_polygon(self):
        items, _ = build()
        root = ET.fromstring(render(items[f"crowdcad-{EID}-zone-z1"]))
        links = [l.get("point") for l in root.findall("detail/link")]
        self.assertEqual(len(links), 5)
        self.assertEqual(links[0], links[-1])
        self.assertEqual(root.find("detail/strokeColor").get("value"), str(cot.argb("#ef4444")))

    def test_argb(self):
        self.assertEqual(cot.argb("#ffffff"), -1)
        self.assertEqual(cot.argb("#000000", 0x40), 0x40000000)
        self.assertEqual(cot.argb("not a colour"), cot.argb("#3b82f6"))

    def test_xml_escapes_crowdcad_text(self):
        event = demo()
        event["calls"][1]["chiefComplaint"] = 'Fall <"bleachers"> & stairs'
        items, _ = build(event)
        root = ET.fromstring(render(items[f"crowdcad-{EID}-call-c2"]))
        self.assertEqual(root.find("detail/__iucad_incident").get("type"), 'Fall <"bleachers"> & stairs')


class ConfigTest(unittest.TestCase):
    def test_old_config_gains_new_keys(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            Path(d, "config.json").write_text(json.dumps({"crowdcad_url": "http://x", "publish": {"posts": True}}))
            cfg, secrets = config.load(d)
            self.assertEqual(cfg["tak_port"], 8089)
            self.assertEqual(cfg["publish"], {**config.DEFAULTS["publish"], "posts": True})
            self.assertEqual(secrets["tak_key_password"], "atakatak")
            config.save(d, cfg, {"crowdcad_password": "pw"})
            self.assertEqual(config.load(d)[1]["crowdcad_password"], "pw")


class FreeUnitsTest(unittest.TestCase):
    def test_free_units_and_callsign_key(self):
        names = mapping.free_units(demo(), {**config.DEFAULTS, "team_uids": {"Team 1": "ANDROID-abc"}})
        self.assertNotIn("Team 1", names)
        self.assertIn("Team 2", names)
        self.assertEqual({mapping.callsign_key(n) for n in ("Team 1", "TEAM-1", "team1")}, {"team1"})


if __name__ == "__main__":
    unittest.main()

