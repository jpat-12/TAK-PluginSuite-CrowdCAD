package com.atakmap.android.crowdcad.model;

/** One unit's last reported status (a device's PLI, or a bridge team marker). Immutable. */
public final class Unit {
    public final String uid;
    public final String callsign;
    public final UnitStatus status;
    public final String incidentId;   // "" when not on an incident
    public final long since;
    public final long staleAt;

    public Unit(String uid, String callsign, UnitStatus status, String incidentId, long since, long staleAt) {
        this.uid = uid;
        this.callsign = callsign;
        this.status = status;
        this.incidentId = incidentId == null ? "" : incidentId;
        this.since = since;
        this.staleAt = staleAt;
    }
}
