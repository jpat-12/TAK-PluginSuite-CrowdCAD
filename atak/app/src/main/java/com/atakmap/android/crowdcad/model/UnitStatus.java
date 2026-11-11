package com.atakmap.android.crowdcad.model;

/** IU Event CAD unit status codes (docs/COT_FORMAT.md). Codes are wire format: never rename. */
public enum UnitStatus {
    AVL("AVL", "Available"),
    RESP("RESP", "Responding"),
    ONSC("ONSC", "On scene"),
    TRAN("TRAN", "Transporting"),
    OOS("OOS", "Out of service");

    public final String code;
    public final String label;

    UnitStatus(String code, String label) {
        this.code = code;
        this.label = label;
    }

    /** Available and Out of Service end a unit's involvement in its incident. */
    public boolean clearsIncident() {
        return this == AVL || this == OOS;
    }

    /**
     * null for an unknown code. Never default it: showing a busy unit as Available gets it
     * sent to a second patient (IU's rule, kept by every client in this suite).
     */
    public static UnitStatus fromCode(String code) {
        for (UnitStatus s : values())
            if (s.code.equals(code))
                return s;
        return null;
    }
}
