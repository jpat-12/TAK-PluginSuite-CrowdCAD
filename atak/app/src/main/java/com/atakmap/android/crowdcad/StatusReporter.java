package com.atakmap.android.crowdcad;

import android.content.Intent;
import android.content.SharedPreferences;
import android.preference.PreferenceManager;
import android.util.Log;

import com.atakmap.android.cot.CotMapComponent;
import com.atakmap.android.crowdcad.cot.IucadUnit;
import com.atakmap.android.crowdcad.model.Board;
import com.atakmap.android.crowdcad.model.Unit;
import com.atakmap.android.crowdcad.model.UnitStatus;
import com.atakmap.android.ipc.AtakBroadcast;
import com.atakmap.android.maps.MapView;
import com.atakmap.comms.ReportingRate;
import com.atakmap.coremap.cot.event.CotDetail;

import java.util.Map;

/**
 * This device's own unit status, riding on ATAK's normal position report as an additional
 * detail (IU Event CAD's mechanism, so no second message type and late joiners learn it from
 * the next PLI). A change forces a report at once instead of waiting for the PLI timer.
 *
 * Persisted in prefs so a crash or restart mid-call doesn't flip a busy medic to Available.
 * Don't run this plugin and IU Event CAD on one device: both own this same detail.
 */
final class StatusReporter {

    private static final String PREF_STATUS = "crowdcad.status";
    private static final String PREF_INCIDENT = "crowdcad.incident";
    private static final String PREF_SINCE = "crowdcad.since";

    private final MapView mapView;
    private final Board board;
    private final SharedPreferences prefs;
    private IucadUnit current;

    StatusReporter(MapView mapView, Board board) {
        this.mapView = mapView;
        this.board = board;
        prefs = PreferenceManager.getDefaultSharedPreferences(mapView.getContext());
        UnitStatus saved = UnitStatus.fromCode(prefs.getString(PREF_STATUS, null));
        current = new IucadUnit(saved != null ? saved : UnitStatus.AVL, prefs.getString(PREF_INCIDENT, ""),
                prefs.getLong(PREF_SINCE, System.currentTimeMillis()));
    }

    void start() {
        publish("plugin start");
    }

    /** Stop advertising a status: a device without the plugin running shouldn't look Available. */
    void stop() {
        CotMapComponent cmc = CotMapComponent.getInstance();
        if (cmc != null)
            cmc.removeAdditionalDetail(IucadUnit.ELEMENT);
        board.removeUnit(MapView.getDeviceUid());
    }

    IucadUnit current() {
        return current;
    }

    /** @param incidentId the incident being worked, or "" — cleared for Available / Out of Service. */
    void set(UnitStatus status, String incidentId) {
        current = new IucadUnit(status, incidentId, System.currentTimeMillis());
        prefs.edit()
                .putString(PREF_STATUS, status.code)
                .putString(PREF_INCIDENT, current.incidentId)
                .putLong(PREF_SINCE, current.since)
                .apply();
        publish("status " + status.code);
    }

    private void publish(String reason) {
        CotDetail d = new CotDetail(IucadUnit.ELEMENT);
        for (Map.Entry<String, String> a : current.toAttributes().entrySet())
            d.setAttribute(a.getKey(), a.getValue());
        CotMapComponent cmc = CotMapComponent.getInstance();
        if (cmc == null) {
            Log.w(CrowdCadMapComponent.TAG, "CotMapComponent not ready; status not attached to position report");
        } else {
            cmc.addAdditionalDetail(IucadUnit.ELEMENT, d);
            Intent i = new Intent(ReportingRate.REPORT_LOCATION);
            i.putExtra("reason", "CrowdCAD " + reason);
            AtakBroadcast.getInstance().sendBroadcast(i);
        }
        // Our own report never comes back through UnitHandler, so enter it directly.
        board.put(new Unit(MapView.getDeviceUid(), mapView.getDeviceCallsign(), current.status,
                current.incidentId, current.since, Long.MAX_VALUE));
    }
}
