package com.atakmap.android.crowdcad.model;

import java.util.Collections;
import java.util.List;

/** One incident as last received. Immutable; a newer copy replaces it on the {@link Board}. */
public final class Incident {
    public final String uid;          // CoT uid: the map item
    public final String id;           // dispatch's id, e.g. CC-007
    public final IncidentStatus status;
    public final String type;
    public final int priority;        // 1 most urgent .. 3
    public final String location;
    public final String reportedBy;
    public final long created;
    public final long updated;
    public final List<String> assigned;   // unit uids
    public final double lat;
    public final double lon;
    public final long staleAt;        // CoT stale: gone from the board after this unless re-sent
    public final int floor;           // IU format: 1..8, -1 basement, 0 none given
    public final String w3w;          // what3words of the point, "" when not sent
    public final double ce;           // CoT point ce (m): how good the point is; NaN unknown
    public final String notes;        // dispatch's notes for the field (IU `notes`; no names/DOB/MRN), "" none

    /** IU's floor rule: below this ce the point is a real place; above, an estimate. */
    public static final double ESTIMATE_CE_M = 50;

    public Incident(String uid, String id, IncidentStatus status, String type, int priority,
            String location, String reportedBy, long created, long updated, List<String> assigned,
            double lat, double lon, long staleAt) {
        this(uid, id, status, type, priority, location, reportedBy, created, updated, assigned, lat, lon,
                staleAt, 0, "", Double.NaN, "");
    }

    public Incident(String uid, String id, IncidentStatus status, String type, int priority,
            String location, String reportedBy, long created, long updated, List<String> assigned,
            double lat, double lon, long staleAt, int floor, String w3w, double ce, String notes) {
        this.uid = uid;
        this.id = id;
        this.status = status;
        this.type = type;
        this.priority = priority;
        this.location = location;
        this.reportedBy = reportedBy;
        this.created = created;
        this.updated = updated;
        this.assigned = Collections.unmodifiableList(assigned);
        this.lat = lat;
        this.lon = lon;
        this.staleAt = staleAt;
        this.floor = floor;
        this.w3w = w3w == null ? "" : w3w;
        this.ce = ce;
        this.notes = notes == null ? "" : notes;
    }

    public Incident withStaleAt(long staleAt) {
        return new Incident(uid, id, status, type, priority, location, reportedBy, created, updated,
                assigned, lat, lon, staleAt, floor, w3w, ce, notes);
    }

    /** "Floor 3", "Basement", or "" (IU format: floor is what dispatch said, never GPS altitude). */
    public String floorLabel() {
        return floor == 0 ? "" : floor == -1 ? "Basement" : "Floor " + floor;
    }

    /** The point is only an estimate (e.g. dispatch used the map centre): get the spot by radio.
     *  Unknown ce says nothing either way, so older senders never show a false warning. */
    public boolean positionIsEstimate() {
        return !Double.isNaN(ce) && ce >= ESTIMATE_CE_M && ce < 9_999_999;
    }
}
