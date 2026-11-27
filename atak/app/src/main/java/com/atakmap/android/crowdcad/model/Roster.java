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
    private volatile String alert = ALERT_SOFT;
    // device uid -> `at` (ms) of its open supervisor request (bridge: supreq attribute); absent = none
    private final Map<String, Long> supreq = new HashMap<>();
    private final Map<String, Long> lastRequest = new HashMap<>();   // newest `at` ever seen per uid
    private final Map<String, Long> acknowledged = new HashMap<>();  // uid -> when its request disappeared

    /** The assignment alert sounds a dispatcher can choose (bridge cot.ALERT_SOUNDS). */
    public static final String ALERT_SOFT = "soft", ALERT_HILO = "hilo";

    public void addListener(Listener l) {
        listeners.add(l);
    }

    /** Replace one event's roster. statuses: device uid → IU status code ("" unknown). */
    public void put(Map<String, String> statuses) {
        put(statuses, null);
    }

    /** As {@link #put(Map)}, with each device's CrowdCAD unit name (may be null). */
    public void put(Map<String, String> statuses, Map<String, String> unitNames) {
        put(statuses, unitNames, null, System.currentTimeMillis());
    }

    /**
     * As {@link #put(Map, Map)}, with each listed device's open supervisor request (uid -> `at`;
     * a listed device missing from it has none). null leaves requests as they were (an older
     * bridge). A request that disappears was cleared by a dispatcher: {@link #acknowledgedAt}.
     */
    public void put(Map<String, String> statuses, Map<String, String> unitNames, Map<String, Long> requests,
            long nowMs) {
        boolean changed;
        synchronized (status) {
            changed = false;
            if (requests != null)
                for (String uid : statuses.keySet()) {
                    Long at = requests.get(uid);
                    if (at != null && at > 0) {
                        Long was = supreq.put(uid, at);
                        Long seen = lastRequest.get(uid);
                        if (seen == null || at > seen)
                            lastRequest.put(uid, at);
                        changed |= !at.equals(was);
                    } else if (supreq.remove(uid) != null) {
                        acknowledged.put(uid, nowMs);
                        changed = true;
                    }
                }
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

    /** `at` (ms) of this device's open supervisor request, or 0 (none, or cleared). */
    public long supervisorRequest(String uid) {
        synchronized (status) {
            Long at = supreq.get(uid);
            return at == null ? 0 : at;
        }
    }

    /** The newest supervisor request `at` the bridge has ever echoed for this device, or 0. */
    public long lastSupervisorRequestSeen(String uid) {
        synchronized (status) {
            Long at = lastRequest.get(uid);
            return at == null ? 0 : at;
        }
    }

    /** When this device's open request disappeared from the roster (a dispatcher cleared it), or 0. */
    public long acknowledgedAt(String uid) {
        synchronized (status) {
            Long at = acknowledged.get(uid);
            return at == null ? 0 : at;
        }
    }

    /** The dispatcher's alert sound from the roster's {@code alert} attribute; anything else is soft. */
    public void setAlert(String sound) {
        alert = ALERT_HILO.equals(sound) ? ALERT_HILO : ALERT_SOFT;
    }

    /** {@link #ALERT_SOFT} (default, also before any roster arrives) or {@link #ALERT_HILO}. */
    public String alert() {
        return alert;
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
