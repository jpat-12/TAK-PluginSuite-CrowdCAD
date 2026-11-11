package com.atakmap.android.crowdcad.cot;

import com.atakmap.android.crowdcad.model.UnitStatus;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * {@code <__iucad_unit>} — IU Event CAD's unit status detail (its docs/COT_FORMAT.md §1). Read
 * from other units' PLIs and the bridge's team markers; written onto this device's own PLI.
 */
public final class IucadUnit {

    public static final String ELEMENT = "__iucad_unit";
    public static final int VERSION = 1;

    public final UnitStatus status;
    public final String incidentId;   // "" when none
    public final long since;

    public IucadUnit(UnitStatus status, String incidentId, long since) {
        this.status = status;
        this.incidentId = status.clearsIncident() || incidentId == null ? "" : incidentId;
        this.since = since;
    }

    /** null if malformed, from a newer format, or an unknown status (never defaulted). */
    public static IucadUnit parse(Attrs a) {
        Integer v = IucadIncident.integer(a.get("v"));
        UnitStatus status = UnitStatus.fromCode(a.get("status"));
        Long since = IucadIncident.number(a.get("since"));
        if (v == null || v > VERSION || status == null || since == null)
            return null;
        return new IucadUnit(status, a.get("incident"), since);
    }

    /** Attributes in wire order; `incident` only when set. */
    public Map<String, String> toAttributes() {
        Map<String, String> out = new LinkedHashMap<>();
        out.put("v", String.valueOf(VERSION));
        out.put("status", status.code);
        if (!incidentId.isEmpty())
            out.put("incident", incidentId);
        out.put("since", String.valueOf(since));
        return out;
    }
}
