package com.atakmap.android.crowdcad;

import android.content.Intent;
import android.util.Log;

import com.atakmap.android.cot.CotMapComponent;
import com.atakmap.android.ipc.AtakBroadcast;
import com.atakmap.comms.ReportingRate;
import com.atakmap.coremap.cot.event.CotDetail;

/**
 * Request Supervisor: the medic confirms twice in the panel, then
 * {@code <__crowdcad_supreq at="<ms>"/>} rides on the phone's position report (sent at once).
 * The bridge turns a new `at` into a GeoChat direct message to every supervisor's phone and a red
 * banner on the dispatcher's board (bridge fieldstatus.handle_supreq). The same `at` repeats on
 * later reports and is ignored there.
 */
final class SupervisorRequest {

    static final String ELEMENT = "__crowdcad_supreq";

    private long lastAt;    // UI thread only

    /** UI thread. */
    void send() {
        CotMapComponent cmc = CotMapComponent.getInstance();
        if (cmc == null) {
            Log.w(CrowdCadMapComponent.TAG, "CotMapComponent not ready; supervisor request not sent");
            return;
        }
        lastAt = System.currentTimeMillis();
        CotDetail d = new CotDetail(ELEMENT);
        d.setAttribute("at", Long.toString(lastAt));
        cmc.addAdditionalDetail(ELEMENT, d);
        Intent i = new Intent(ReportingRate.REPORT_LOCATION);
        i.putExtra("reason", "CrowdCAD supervisor request");
        AtakBroadcast.getInstance().sendBroadcast(i);
        Log.i(CrowdCadMapComponent.TAG, "supervisor requested at " + lastAt);
    }

    /** Ms of this phone's last request, or 0. */
    long lastAt() {
        return lastAt;
    }

    void stop() {
        CotMapComponent cmc = CotMapComponent.getInstance();
        if (cmc != null)
            cmc.removeAdditionalDetail(ELEMENT);
    }
}
