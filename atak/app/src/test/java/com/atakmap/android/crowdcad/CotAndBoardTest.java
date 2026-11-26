package com.atakmap.android.crowdcad;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.atakmap.android.crowdcad.cot.Attrs;
import com.atakmap.android.crowdcad.cot.IucadIncident;
import com.atakmap.android.crowdcad.cot.IucadUnit;
import com.atakmap.android.crowdcad.model.Assignment;
import com.atakmap.android.crowdcad.model.Board;
import com.atakmap.android.crowdcad.model.Incident;
import com.atakmap.android.crowdcad.model.IncidentStatus;
import com.atakmap.android.crowdcad.model.Priority;
import com.atakmap.android.crowdcad.model.Unit;
import com.atakmap.android.crowdcad.model.UnitStatus;

import org.junit.Test;
import org.w3c.dom.Element;

import java.io.BufferedReader;
import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.xml.parsers.DocumentBuilderFactory;

/**
 * Parsing and board rules. bridge-demo.cot is real bridge output (bridge/tests/make_atak_fixture.py)
 * — if the bridge's wire format drifts from what this plugin reads, these tests fail.
 */
public class CotAndBoardTest {

    private static final long NOW = 1794701000000L;
    private static final String C1 = "crowdcad-e1f2g3h4i5j6k7l-call-c1";

    private static Attrs attrs(String... kv) {
        Map<String, String> m = new HashMap<>();
        for (int i = 0; i < kv.length; i += 2)
            m.put(kv[i], kv[i + 1]);
        return m::get;
    }

    private static Attrs attrs(Element e) {
        return name -> e.hasAttribute(name) ? e.getAttribute(name) : null;
    }

    /** {event element, detail child} per line of the fixture. */
    private static List<Element[]> fixture() throws Exception {
        List<Element[]> out = new ArrayList<>();
        InputStream in = CotAndBoardTest.class.getClassLoader().getResourceAsStream("bridge-demo.cot");
        assertNotNull("bridge-demo.cot missing — run bridge/tests/make_atak_fixture.py", in);
        try (BufferedReader r = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = r.readLine()) != null) {
                if (line.trim().isEmpty())
                    continue;
                Element event = DocumentBuilderFactory.newInstance().newDocumentBuilder()
                        .parse(new ByteArrayInputStream(line.getBytes(StandardCharsets.UTF_8))).getDocumentElement();
                out.add(new Element[] {event, null});
            }
        }
        return out;
    }

    private static Element child(Element event, String name) {
        org.w3c.dom.NodeList list = event.getElementsByTagName(name);
        return list.getLength() == 0 ? null : (Element) list.item(0);
    }

    private static Incident incident(String uid, IncidentStatus status, long updated, long staleAt, String... assigned) {
        return new Incident(uid, "CC-1", status, "Fall", 2, "Gate A", "CrowdCAD", 1000, updated,
                Arrays.asList(assigned), 39.18, -86.52, staleAt);
    }

    // --- the bridge's real output -------------------------------------------------------

    @Test
    public void bridgeOutputParses() throws Exception {
        Map<String, Incident> incidents = new HashMap<>();
        Map<String, IucadUnit> units = new HashMap<>();
        for (Element[] e : fixture()) {
            Element event = e[0];
            Element point = child(event, "point");
            Element inc = child(event, IucadIncident.ELEMENT);
            if (inc != null) {
                Incident i = IucadIncident.parse(attrs(inc), event.getAttribute("uid"),
                        Double.parseDouble(point.getAttribute("lat")), Double.parseDouble(point.getAttribute("lon")), NOW);
                assertNotNull("bridge incident must parse: " + event.getAttribute("uid"), i);
                incidents.put(i.uid + "/" + i.status.code, i);
            }
            Element unit = child(event, IucadUnit.ELEMENT);
            if (unit != null) {
                IucadUnit u = IucadUnit.parse(attrs(unit));
                assertNotNull("bridge unit must parse", u);
                units.put(event.getAttribute("uid"), u);
            }
        }
        Incident c1 = incidents.get(C1 + "/ONSC");
        assertNotNull(c1);
        assertEquals("CC-007", c1.id);
        assertEquals(1, c1.priority);
        assertEquals("Sec 104", c1.location);
        assertEquals(1794700800000L, c1.created);
        assertEquals(Collections.singletonList("crowdcad-e1f2g3h4i5j6k7l-team-team-1"), c1.assigned);
        assertNotNull("closed copy of CC-008", incidents.get("crowdcad-e1f2g3h4i5j6k7l-call-c2/CLOSED"));
        IucadUnit team1 = units.get("crowdcad-e1f2g3h4i5j6k7l-team-team-1");
        assertEquals(UnitStatus.ONSC, team1.status);
        assertEquals("CC-007", team1.incidentId);
        assertEquals(UnitStatus.AVL, units.get("crowdcad-e1f2g3h4i5j6k7l-team-supervisor-1").status);
    }

    @Test
    public void bridgeOutputCarriesNoPatientData() throws Exception {
        for (Element[] e : fixture()) {
            Element inc = child(e[0], IucadIncident.ELEMENT);
            if (inc == null)
                continue;
            for (String attribute : new String[] {"age", "gender", "notes"})
                assertFalse(attribute, inc.hasAttribute(attribute));
        }
    }

    // --- parsing rules ------------------------------------------------------------------

    @Test
    public void incidentRules() {
        Attrs ok = attrs("v", "1", "id", "CC-1", "status", "NEW", "type", "Fall", "priority", "7",
                "location", "Gate A", "reportedBy", "x", "created", "1", "updated", "2", "assigned", "a, ,b");
        Incident i = IucadIncident.parse(ok, "uid", 0, 0, NOW);
        assertEquals(3, i.priority);                                   // clamped
        assertEquals(Arrays.asList("a", "b"), i.assigned);
        assertNull(IucadIncident.parse(attrs("v", "2", "id", "x", "status", "NEW", "priority", "1",
                "created", "1", "updated", "1"), "u", 0, 0, NOW));       // newer format: ignored
        assertNull(IucadIncident.parse(attrs("v", "1", "id", "x", "status", "WAT", "priority", "1",
                "created", "1", "updated", "1"), "u", 0, 0, NOW));       // unknown status
        assertNull(IucadIncident.parse(attrs("v", "1", "status", "NEW", "priority", "1",
                "created", "1", "updated", "1"), "u", 0, 0, NOW));       // no id
    }

    @Test
    public void rosterColoursUnitIcons() {
        java.util.Map<String, String> r = com.atakmap.android.crowdcad.cot.RosterMessage.parse(
                "<event type=\"t-x-crowdcad-roster\"><detail><__crowdcad_roster v=\"1\">"
                        + "<unit uid=\"ANDROID-a\" status=\"AVL\" name=\"Medic 1\"/><unit uid=\"ANDROID-b\" status=\"TRAN\"/>"
                        + "<unit uid=\"ANDROID-c\" status=\"\"/></__crowdcad_roster></detail></event>");
        assertEquals(3, r.size());
        com.atakmap.android.crowdcad.model.Roster roster = new com.atakmap.android.crowdcad.model.Roster();
        roster.put(r, com.atakmap.android.crowdcad.cot.RosterMessage.names(
                "<__crowdcad_roster v=\"1\"><unit uid=\"ANDROID-a\" status=\"AVL\" name=\"Medic 1\"/></__crowdcad_roster>"));
        assertEquals("Medic 1", roster.unitName("ANDROID-a"));     // the banner's CrowdCAD callsign
        assertEquals("", roster.unitName("ANDROID-b"));
        assertEquals("AVL", roster.colour("ANDROID-a"));    // green
        assertEquals("BUSY", roster.colour("ANDROID-b"));   // light red
        assertEquals("OOS", roster.colour("ANDROID-c"));    // unknown: grey, never "available" on a guess
        assertEquals("OOS", roster.colour("ANDROID-zzz"));  // not linked to a unit
        assertNull(com.atakmap.android.crowdcad.cot.RosterMessage.parse("<__crowdcad_roster v=\"2\">"));
        assertEquals(UnitIcons.ICON_BASE + "EMS%20ALS%20AVL.png", UnitIcons.path("ALS", "AVL"));   // raw GitHub PNG
        assertTrue(UnitIcons.ICON_BASE.startsWith("https://raw.githubusercontent.com/"));
        assertTrue(UnitIcons.valid("SUP"));
        assertFalse(UnitIcons.valid("MD1"));
    }

    @Test
    public void notesComeThroughOnTheCall() {
        Incident i = IucadIncident.parse(attrs("v", "1", "id", "CC-9", "status", "NEW", "priority", "2",
                "created", "1", "updated", "1", "notes", " Pt by Gate 3 "), "u", 0, 0, NOW);
        assertEquals("Pt by Gate 3", i.notes);
        assertEquals("Pt by Gate 3", i.withStaleAt(NOW + 1).notes);
    }

    @Test
    public void floorWhat3wordsAndEstimate() {
        Incident i = IucadIncident.parse(attrs("v", "1", "id", "CC-9", "status", "NEW", "priority", "2",
                "created", "1", "updated", "1", "floor", "3", "w3w", "filled.count.soap"), "u", 0, 0, 75.0, NOW);
        assertEquals("Floor 3", i.floorLabel());
        assertEquals("filled.count.soap", i.w3w);
        assertTrue(i.positionIsEstimate());                            // the bridge's map-centre ce
        assertEquals(3, i.withStaleAt(NOW + 1).floor);                 // survives a heartbeat copy
        for (String bad : new String[] {"0", "9", "-2", "x"})
            assertEquals(bad, 0, IucadIncident.parse(attrs("v", "1", "id", "x", "status", "NEW", "priority", "1",
                    "created", "1", "updated", "1", "floor", bad), "u", 0, 0, NOW).floor);
        Incident basement = IucadIncident.parse(attrs("v", "1", "id", "x", "status", "NEW", "priority", "1",
                "created", "1", "updated", "1", "floor", "-1"), "u", 0, 0, 20.0, NOW);
        assertEquals("Basement", basement.floorLabel());
        assertFalse(basement.positionIsEstimate());                    // a post: a real place
        assertFalse(IucadIncident.parse(attrs("v", "1", "id", "x", "status", "NEW", "priority", "1",
                "created", "1", "updated", "1"), "u", 0, 0, 9999999.0, NOW).positionIsEstimate());   // unknown: no warning
    }

    @Test
    public void unitRules() {
        assertNull(IucadUnit.parse(attrs("v", "1", "status", "Assigned", "since", "1")));   // never defaulted
        IucadUnit avl = IucadUnit.parse(attrs("v", "1", "status", "AVL", "incident", "CC-1", "since", "5"));
        assertEquals("", avl.incidentId);                              // AVL clears the incident
        Map<String, String> wire = new IucadUnit(UnitStatus.RESP, "CC-9", 42).toAttributes();
        assertEquals(Arrays.asList("v", "status", "incident", "since"), new ArrayList<>(wire.keySet()));
        assertFalse(new IucadUnit(UnitStatus.OOS, "CC-9", 42).toAttributes().containsKey("incident"));
    }

    // --- board rules --------------------------------------------------------------------

    @Test
    public void newestCopyWinsAndHeartbeatOnlyRefreshesStale() {
        Board b = new Board();
        assertEquals(Board.Change.NEW, b.put(incident("u", IncidentStatus.NEW, 10, NOW + 1000)));
        assertEquals(Board.Change.UPDATED, b.put(incident("u", IncidentStatus.DISP, 20, NOW + 1000)));
        assertEquals(Board.Change.IGNORED, b.put(incident("u", IncidentStatus.NEW, 15, NOW + 9000)));
        assertEquals(IncidentStatus.DISP, b.openIncidents(NOW).get(0).status);
        assertEquals(Board.Change.IGNORED, b.put(incident("u", IncidentStatus.DISP, 20, NOW + 5000)));
        assertEquals(1, b.openIncidents(NOW + 4000).size());           // heartbeat extended stale
        assertEquals(0, b.openIncidents(NOW + 6000).size());           // then it expires
    }

    @Test
    public void closedIncidentLeavesAndCannotBeResurrected() {
        Board b = new Board();
        b.put(incident("u", IncidentStatus.ONSC, 10, NOW + 1000));
        assertEquals(Board.Change.CLOSED, b.put(incident("u", IncidentStatus.CLOSED, 20, NOW + 90)));
        assertTrue(b.openIncidents(NOW).isEmpty());
        assertEquals(Board.Change.IGNORED, b.put(incident("u", IncidentStatus.ONSC, 10, NOW + 1000)));
        assertTrue(b.openIncidents(NOW).isEmpty());
    }

    @Test
    public void openIncidentsSortByPriorityThenStatusThenAge() {
        Board b = new Board();
        b.put(new Incident("a", "A", IncidentStatus.ONSC, "", 2, "", "", 1, 1, Collections.emptyList(), 0, 0, NOW + 1));
        b.put(new Incident("b", "B", IncidentStatus.NEW, "", 2, "", "", 5, 1, Collections.emptyList(), 0, 0, NOW + 1));
        b.put(new Incident("c", "C", IncidentStatus.TRAN, "", 1, "", "", 9, 1, Collections.emptyList(), 0, 0, NOW + 1));
        b.put(new Incident("d", "D", IncidentStatus.NEW, "", 2, "", "", 2, 1, Collections.emptyList(), 0, 0, NOW + 1));
        List<String> order = new ArrayList<>();
        for (Incident i : b.openIncidents(NOW))
            order.add(i.id);
        assertEquals(Arrays.asList("C", "D", "B", "A"), order);
    }

    @Test
    public void unitsNewestSinceWinsAndExpire() {
        Board b = new Board();
        int[] fired = {0};
        b.addListener(() -> fired[0]++);
        assertTrue(b.put(new Unit("u", "Team 1", UnitStatus.ONSC, "CC-1", 20, NOW + 100)));
        assertFalse(b.put(new Unit("u", "Team 1", UnitStatus.AVL, "", 10, NOW + 100)));   // older
        assertEquals(UnitStatus.ONSC, b.unit("u").status);
        assertEquals("Team 1", b.callsign("u"));
        assertEquals("nobody", b.callsign("nobody"));
        assertEquals(0, b.units(NOW + 200).size());
        assertEquals(1, fired[0]);
    }

    @Test
    public void priorityColoursMarkers_p1RedP2OrangeP3Yellow() {
        assertEquals(Priority.P1_RED, Priority.color(1));
        assertEquals(Priority.P2_ORANGE, Priority.color(2));
        assertEquals(Priority.P3_YELLOW, Priority.color(3));
        // parse clamps to 1..3, but the colour map must not depend on that
        assertEquals(Priority.P1_RED, Priority.color(0));
        assertEquals(Priority.P3_YELLOW, Priority.color(9));
    }

    @Test
    public void iconsetHeader_readsUidAndVersion_rejectsIncomplete() throws Exception {
        // The real bundled zip, as build_iconset.py wrote it.
        java.util.zip.ZipFile zip = new java.util.zip.ZipFile(new java.io.File("src/main/assets/" + IconsetInstaller.ASSET));
        String xml;
        try (InputStream in = zip.getInputStream(zip.getEntry("iconset.xml"))) {
            xml = new String(in.readAllBytes(), StandardCharsets.UTF_8);
        } finally {
            zip.close();
        }
        IconsetInstaller.Header h = IconsetInstaller.parseHeader(xml);
        assertNotNull(h);
        assertEquals("abee9e5e3aec4b62a5bbb27c78fcb9b27e0140919c7ff132c8c6fa41ab2b0c78", h.uid);
        assertEquals(3, h.version);                                     // 3: + unit icons (build_iconset.py)
        assertNull(IconsetInstaller.parseHeader("<iconset name=\"x\" version=\"1\">"));    // no uid
        assertNull(IconsetInstaller.parseHeader("<iconset uid=\"u\" version=\"one\">"));   // bad version
        assertNull(IconsetInstaller.parseHeader("<other uid=\"u\" version=\"1\">"));
    }

    @Test
    public void assignedToMe_byDeviceUid_orUnlinkedTeamMatchingCallsign() {
        List<String> linked = Arrays.asList("ANDROID-medic1");
        assertTrue(Assignment.isMine(linked, "ANDROID-medic1", "whatever"));
        // Not linked yet: the bridge names the team; "Team 1" matches callsign TEAM1 the way the bridge does.
        List<String> unlinked = Arrays.asList("crowdcad-e1f2g3h4i5j6k7l-team-team-1");
        assertTrue(Assignment.isMine(unlinked, "ANDROID-medic1", "TEAM1"));
        assertTrue(Assignment.isMine(unlinked, "ANDROID-medic1", "Team 1"));
        assertFalse(Assignment.isMine(unlinked, "ANDROID-medic1", "Team 11"));
        assertFalse(Assignment.isMine(unlinked, "ANDROID-medic1", ""));
        assertFalse(Assignment.isMine(Arrays.asList("ANDROID-other-team-team1"), "ANDROID-medic1", "TEAM1"));  // not a bridge uid
    }

    @Test
    public void ago() {
        assertEquals("0m", CrowdCadDropDown.ago(NOW + 5000, NOW));     // skew never negative
        assertEquals("1h05", CrowdCadDropDown.ago(NOW - 65 * 60_000, NOW));
    }
}
