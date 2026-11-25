package com.atakmap.android.crowdcad.model;

import java.util.List;
import java.util.Locale;

/**
 * "Is this incident assigned to me?" Pure, so it's unit-tested.
 *
 * A phone linked to its CrowdCAD unit appears in `assigned` by its own device uid. A phone not
 * linked yet appears as the bridge's team uid, {@code crowdcad-<event>-team-<slug(name)>}. It
 * counts as mine when that name matches this phone's ATAK callsign the way the bridge matches
 * them (mapping.callsign_key: lower-case, letters and digits only, so "Team 1" ↔ TEAM1). The
 * medic's first Acknowledge then links the phone (bridge fieldstatus.py, claim_by_callsign).
 */
public final class Assignment {

    private static final String TEAM_MARK = "-team-";

    private Assignment() {
    }

    public static boolean isMine(List<String> assigned, String deviceUid, String callsign) {
        if (deviceUid != null && assigned.contains(deviceUid))
            return true;
        String me = key(callsign);
        if (me.isEmpty())
            return false;
        for (String uid : assigned) {
            if (uid == null || !uid.startsWith("crowdcad-"))
                continue;
            // The FIRST "-team-": the event id before it is letters and digits only, and the team
            // name after it may itself start with "team-" ("…-team-team-1" is Team 1).
            int at = uid.indexOf(TEAM_MARK);
            if (at >= 0 && key(uid.substring(at + TEAM_MARK.length())).equals(me))
                return true;
        }
        return false;
    }

    /** bridge mapping.callsign_key. */
    static String key(String name) {
        return name == null ? "" : name.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]", "");
    }
}
