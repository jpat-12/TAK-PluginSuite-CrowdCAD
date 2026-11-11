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

    public Incident(String uid, String id, IncidentStatus status, String type, int priority,
            String location, String reportedBy, long created, long updated, List<String> assigned,
            double lat, double lon, long staleAt) {
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
    }

    public Incident withStaleAt(long staleAt) {
        return new Incident(uid, id, status, type, priority, location, reportedBy, created, updated,
                assigned, lat, lon, staleAt);
    }
}
