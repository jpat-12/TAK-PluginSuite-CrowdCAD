package com.atakmap.android.crowdcad.model;

/**
 * Incident priority → marker colour. 1 is the most urgent (IU format: 1..3, clamped on parse).
 * The CrowdCAD bridge only sends 1 (flagged priority) or 2, so its calls show red or orange.
 * Yellow is for P3 from other senders, e.g. IU Event CAD.
 */
public final class Priority {

    public static final int P1_RED = 0xFFE03131;
    public static final int P2_ORANGE = 0xFFF76707;
    public static final int P3_YELLOW = 0xFFFCC419;

    private Priority() {
    }

    public static int color(int priority) {
        if (priority <= 1)
            return P1_RED;
        return priority == 2 ? P2_ORANGE : P3_YELLOW;
    }
}
