package com.atakmap.android.crowdcad.model;

/** IU Event CAD incident status codes (docs/COT_FORMAT.md). Codes are wire format: never rename. */
public enum IncidentStatus {
    NEW("NEW", "New"),
    DISP("DISP", "Dispatched"),
    ONSC("ONSC", "On scene"),
    TRAN("TRAN", "Transporting"),
    CLOSED("CLOSED", "Closed"),
    CXL("CXL", "Cancelled");

    public final String code;
    public final String label;

    IncidentStatus(String code, String label) {
        this.code = code;
        this.label = label;
    }

    public boolean isOpen() {
        return this != CLOSED && this != CXL;
    }

    /** null for an unknown code — callers drop the message rather than guess. */
    public static IncidentStatus fromCode(String code) {
        for (IncidentStatus s : values())
            if (s.code.equals(code))
                return s;
        return null;
    }
}
