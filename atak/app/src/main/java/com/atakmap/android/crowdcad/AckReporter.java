package com.atakmap.android.crowdcad;

import android.content.Intent;
import android.content.SharedPreferences;
import android.preference.PreferenceManager;
import android.util.Log;

import com.atakmap.android.cot.CotMapComponent;
import com.atakmap.android.crowdcad.cot.IucadUnit;
import com.atakmap.android.ipc.AtakBroadcast;
import com.atakmap.android.maps.MapView;
import com.atakmap.comms.ReportingRate;
import com.atakmap.coremap.cot.event.CotDetail;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashMap;
import java.util.Map;

/**
 * The medic's one field action: Acknowledge an assigned call. Field users can't set status
 * (Jon, 2026-11-25). Status is dispatch's, set in CrowdCAD or the CloudTAK console.
 *
 * The latest ack rides on the phone's own position report as
 * {@code <__crowdcad_ack incident="CC-007" at="<ms>"/>}. The bridge turns a new `at` into one
 * line in that call's CrowdCAD log (bridge fieldstatus.py), and changes no status. A change
 * forces a report at once instead of waiting for the PLI timer.
 *
 * Acked incident ids are kept in prefs so a restart doesn't offer Acknowledge again.
 * Replaces 0.1.5's StatusReporter; its {@code <__iucad_unit>} detail is removed on start.
 */
final class AckReporter {

    static final String ELEMENT = "__crowdcad_ack";
    private static final String PREF_ACKED = "crowdcad.acked";        // "id=ms|id=ms|..."
    private static final String[] LEGACY_PREFS = {"crowdcad.status", "crowdcad.incident", "crowdcad.since"};
    private static final int KEEP = 50;   // one event's worth of calls; oldest dropped first

    private final SharedPreferences prefs;
    // incident id → ms acknowledged, oldest first. UI thread only.
    private final Map<String, Long> acked = new HashMap<>();
    private final Deque<String> order = new ArrayDeque<>();

    AckReporter(MapView mapView) {
        prefs = PreferenceManager.getDefaultSharedPreferences(mapView.getContext());
        for (String pair : prefs.getString(PREF_ACKED, "").split("\\|")) {
            int eq = pair.lastIndexOf('=');
            if (eq <= 0)
                continue;
            try {
                remember(pair.substring(0, eq), Long.parseLong(pair.substring(eq + 1)));
            } catch (NumberFormatException e) {
                // a corrupt entry: drop it; worst case Acknowledge is offered again
            }
        }
    }

    void start() {
        CotMapComponent cmc = CotMapComponent.getInstance();
        if (cmc != null)
            cmc.removeAdditionalDetail(IucadUnit.ELEMENT);   // 0.1.5's self-set status: never again
        SharedPreferences.Editor e = prefs.edit();
        for (String key : LEGACY_PREFS)
            e.remove(key);
        e.apply();
    }

    void stop() {
        CotMapComponent cmc = CotMapComponent.getInstance();
        if (cmc != null)
            cmc.removeAdditionalDetail(ELEMENT);
    }

    /** UI thread. Ms this incident was acknowledged, or null. */
    Long ackedAt(String incidentId) {
        return acked.get(incidentId);
    }

    /** UI thread. */
    void acknowledge(String incidentId) {
        long at = System.currentTimeMillis();
        remember(incidentId, at);
        StringBuilder saved = new StringBuilder();
        for (String id : order)
            saved.append(saved.length() == 0 ? "" : "|").append(id).append('=').append(acked.get(id));
        prefs.edit().putString(PREF_ACKED, saved.toString()).apply();

        CotDetail d = new CotDetail(ELEMENT);
        d.setAttribute("incident", incidentId);
        d.setAttribute("at", Long.toString(at));
        CotMapComponent cmc = CotMapComponent.getInstance();
        if (cmc == null) {
            Log.w(CrowdCadMapComponent.TAG, "CotMapComponent not ready; acknowledgement not sent");
            return;
        }
        cmc.addAdditionalDetail(ELEMENT, d);
        Intent i = new Intent(ReportingRate.REPORT_LOCATION);
        i.putExtra("reason", "CrowdCAD acknowledge " + incidentId);
        AtakBroadcast.getInstance().sendBroadcast(i);
    }

    private void remember(String id, long at) {
        if (acked.put(id, at) == null)
            order.addLast(id);
        while (order.size() > KEEP)
            acked.remove(order.removeFirst());
    }
}
