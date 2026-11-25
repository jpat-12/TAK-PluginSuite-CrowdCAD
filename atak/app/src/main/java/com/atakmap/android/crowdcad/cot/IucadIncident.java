package com.atakmap.android.crowdcad.cot;

import com.atakmap.android.crowdcad.model.Incident;
import com.atakmap.android.crowdcad.model.IncidentStatus;

import java.util.ArrayList;
import java.util.List;

/**
 * {@code <__iucad_incident>} — IU Event CAD's incident detail (its docs/COT_FORMAT.md §2, the
 * format the CrowdCAD bridge produces). Read-only here: this plugin never authors incidents.
 */
public final class IucadIncident {

    public static final String ELEMENT = "__iucad_incident";
    /** Newest format version understood; a higher one is ignored, not guessed at. */
    public static final int VERSION = 1;

    private IucadIncident() {
    }

    /** @return the incident, or null if the detail is malformed or from a newer format. */
    public static Incident parse(Attrs a, String uid, double lat, double lon, long staleAt) {
        return parse(a, uid, lat, lon, Double.NaN, staleAt);
    }

    /** @param ce the CoT point's ce in metres (how good the point is), NaN if unknown. */
    public static Incident parse(Attrs a, String uid, double lat, double lon, double ce, long staleAt) {
        Integer v = integer(a.get("v"));
        if (v == null || v > VERSION)
            return null;
        String id = a.get("id");
        IncidentStatus status = IncidentStatus.fromCode(a.get("status"));
        Integer priority = integer(a.get("priority"));
        Long created = number(a.get("created"));
        Long updated = number(a.get("updated"));
        if (empty(id) || status == null || priority == null || created == null || updated == null)
            return null;
        List<String> assigned = new ArrayList<>();
        String list = a.get("assigned");
        if (list != null)
            for (String unit : list.split(","))
                if (!unit.trim().isEmpty())
                    assigned.add(unit.trim());
        return new Incident(uid, id, status, orEmpty(a.get("type")),
                Math.max(1, Math.min(3, priority)),   // out of range is clamped (IU rule)
                orEmpty(a.get("location")), orEmpty(a.get("reportedBy")), created, updated,
                assigned, lat, lon, staleAt, floor(a.get("floor")), orEmpty(a.get("w3w")).trim(), ce);
    }

    /** IU format: 1..8, -1 basement; anything else (or absent) is "none given" (0). */
    static int floor(String s) {
        Integer f = integer(s);
        return f == null || (f != -1 && (f < 1 || f > 8)) ? 0 : f;
    }

    static Integer integer(String s) {
        Long n = number(s);
        return n == null || n > Integer.MAX_VALUE || n < Integer.MIN_VALUE ? null : (int) (long) n;
    }

    static Long number(String s) {
        if (s == null)
            return null;
        try {
            return Long.parseLong(s.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static boolean empty(String s) {
        return s == null || s.trim().isEmpty();
    }

    private static String orEmpty(String s) {
        return s == null ? "" : s;
    }
}
