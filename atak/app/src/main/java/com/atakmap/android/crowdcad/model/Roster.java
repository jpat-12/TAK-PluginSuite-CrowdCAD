package com.atakmap.android.crowdcad.model;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Each phone-carried unit's dispatch status, as the bridge last said (its
 * {@code <__crowdcad_roster>} message, bridge cot.render_roster). Medics can't set status, so this
 * is the only place a phone learns its own: it picks the colour of the unit icons (green
 * available, grey out of service, light red anything else). Thread-safe.
 */
public final class Roster {

    public interface Listener {
        void onRosterChanged();
    }

    /** The iconset's status suffixes (iconset/build_iconset.py UNIT_STATUS_TINTS). */
    public static final String AVL = "AVL", OOS = "OOS", BUSY = "BUSY";

    private final Map<String, String> status = new HashMap<>();
    private final Map<String, String> names = new HashMap<>();   // device uid → CrowdCAD unit name
    private final CopyOnWriteArrayList<Listener> listeners = new CopyOnWriteArrayList<>();

    public void addListener(Listener l) {
        listeners.add(l);
    }

    /** Replace one event's roster. statuses: device uid → IU status code ("" unknown). */
    public void put(Map<String, String> statuses) {
        put(statuses, null);
    }

    /** As {@link #put(Map)}, with each device's CrowdCAD unit name (may be null). */
    public void put(Map<String, String> statuses, Map<String, String> unitNames) {
        boolean changed;
        synchronized (status) {
            changed = false;
            for (Map.Entry<String, String> e : statuses.entrySet())
                changed |= !e.getValue().equals(status.put(e.getKey(), e.getValue()));
            if (unitNames != null)
                for (Map.Entry<String, String> e : unitNames.entrySet())
                    changed |= !e.getValue().equals(names.put(e.getKey(), e.getValue()));
        }
        if (changed)
            for (Listener l : listeners)
                l.onRosterChanged();
    }

    /** The CrowdCAD unit this device carries ("Medic 1"), or "" if the bridge hasn't named one. */
    public String unitName(String uid) {
        synchronized (status) {
            String n = names.get(uid);
            return n == null ? "" : n;
        }
    }

    /** The IU status code the bridge last sent for this device ("" unknown, null not on the roster). */
    public String status(String uid) {
        synchronized (status) {
            return status.get(uid);
        }
    }

    /**
     * The icon colour for a device: AVL green, OOS grey, BUSY light red for responding / on
     * scene / transporting. A device the bridge hasn't named (not linked to a unit, or its status
     * unknown) is grey: never shown available on a guess (IU's rule for unknown status).
     */
    public String colour(String uid) {
        String s;
        synchronized (status) {
            s = status.get(uid);
        }
        return colourOf(s);
    }

    public static String colourOf(String iuStatus) {
        if (iuStatus == null || iuStatus.isEmpty() || "OOS".equals(iuStatus))
            return OOS;
        return "AVL".equals(iuStatus) ? AVL : BUSY;
    }
}
