package com.atakmap.android.crowdcad;

import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.preference.PreferenceManager;
import android.util.Log;

import com.atakmap.android.cot.CotMapComponent;
import com.atakmap.android.crowdcad.cot.RosterMessage;
import com.atakmap.android.crowdcad.model.Roster;
import com.atakmap.android.ipc.AtakBroadcast;
import com.atakmap.android.maps.MapView;
import com.atakmap.comms.CommsMapComponent;
import com.atakmap.comms.CotServiceRemote;
import com.atakmap.comms.ReportingRate;
import com.atakmap.coremap.cot.event.CotDetail;
import com.atakmap.coremap.cot.event.CotEvent;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.BooleanSupplier;

/**
 * This phone's unit icon. The medic picks a designation (ALS / BLS / SUP) in the panel's Settings;
 * the colour is dispatch's status for this phone from the bridge's roster. Both ride on the
 * phone's own position report:
 *
 *   {@code <usericon iconsetpath="<uid>/CrowdCAD/EMS ALS AVL.png"/>}   CloudTAK and other clients draw it
 *   {@code <__crowdcad_unit designation="ALS"/>}                      plugin devices restyle from it
 *
 * A change forces a report at once. Off (no designation) = the normal ATAK marker.
 */
final class UnitIdentity implements Roster.Listener {

    static final String ELEMENT = "__crowdcad_unit";
    private static final String USERICON = "usericon";
    private static final String PREF = "crowdcad.designation";

    private final SharedPreferences prefs;
    private final Roster roster;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private String sent;    // iconsetpath on the last report, or null. UI thread only.
    // True while this phone is assigned an open call: light red even if no roster has arrived.
    private BooleanSupplier assigned = () -> false;

    // Comms thread: the bridge's roster tells this phone (and others) their dispatch status.
    private final CotServiceRemote.CotEventListener listener = this::onCot;

    UnitIdentity(MapView mapView, Roster roster) {
        this.prefs = PreferenceManager.getDefaultSharedPreferences(mapView.getContext());
        this.roster = roster;
    }

    private void onCot(CotEvent event, Bundle extra) {
        if (event == null || !RosterMessage.TYPE.equals(event.getType()))
            return;
        // ATAK's detail API first (no dependence on how CotEvent prints), the raw XML second.
        Map<String, String> statuses = new LinkedHashMap<>(), names = new LinkedHashMap<>();
        Map<String, Long> requests = new LinkedHashMap<>();   // open supervisor requests (cleared = absent)
        CotDetail detail = event.getDetail();
        CotDetail r = detail == null ? null : detail.getFirstChildByName(0, RosterMessage.ELEMENT);
        if (r != null) {
            roster.setAlert(r.getAttribute("alert"));
            for (int i = 0; i < r.childCount(); i++) {
                CotDetail u = r.getChild(i);
                String uid = u == null ? null : u.getAttribute("uid");
                if (uid == null || uid.isEmpty())
                    continue;
                statuses.put(uid, u.getAttribute("status") == null ? "" : u.getAttribute("status"));
                names.put(uid, u.getAttribute("name") == null ? "" : u.getAttribute("name"));
                long at = RosterMessage.toMs(u.getAttribute("supreq"));
                if (at > 0)
                    requests.put(uid, at);
            }
        } else {
            String xml = event.toString();
            roster.setAlert(RosterMessage.alert(xml));
            Map<String, String> parsed = RosterMessage.parse(xml);
            if (parsed != null) {
                statuses = parsed;
                names = RosterMessage.names(xml);
                requests = RosterMessage.supervisorRequests(xml);
            }
        }
        Log.d(CrowdCadMapComponent.TAG, "roster received: " + statuses.size() + " unit(s), this phone: "
                + statuses.get(MapView.getDeviceUid()));
        if (!statuses.isEmpty())
            roster.put(statuses, names, requests, System.currentTimeMillis());
    }

    /** Where this phone learns it's on an open call (the Board), for the busy colour. */
    void setAssignedCheck(BooleanSupplier check) {
        assigned = check;
    }

    /** The colour this phone shows: the bridge's roster, else light red while it has a call. */
    String colour() {
        String uid = MapView.getDeviceUid();
        if (roster.status(uid) == null && assigned.getAsBoolean())
            return Roster.BUSY;
        return roster.colour(uid);
    }

    /** UI thread: the Board changed (assignments): the colour may have too. */
    void refresh() {
        apply();
    }

    void start() {
        CommsMapComponent comms = CommsMapComponent.getInstance();
        if (comms != null)
            comms.addOnCotEventListener(listener);
        roster.addListener(this);
        apply();
    }

    void stop() {
        CommsMapComponent comms = CommsMapComponent.getInstance();
        if (comms != null)
            comms.removeOnCotEventListener(listener);
        CotMapComponent cmc = CotMapComponent.getInstance();
        if (cmc != null) {
            cmc.removeAdditionalDetail(USERICON);
            cmc.removeAdditionalDetail(ELEMENT);
        }
    }

    Roster roster() {
        return roster;
    }

    /** "ALS", "BLS", "SUP", or "" (off). */
    String designation() {
        String d = prefs.getString(PREF, "");
        return UnitIcons.valid(d) ? d : "";
    }

    /** UI thread. */
    void setDesignation(String designation) {
        prefs.edit().putString(PREF, UnitIcons.valid(designation) ? designation : "").apply();
        apply();
    }

    @Override
    public void onRosterChanged() {
        ui.post(this::apply);
    }

    /** UI thread: put this phone's icon on its position report (or take it off). */
    private void apply() {
        CotMapComponent cmc = CotMapComponent.getInstance();
        if (cmc == null)
            return;
        String d = designation();
        String path = d.isEmpty() ? null : UnitIcons.path(d, colour());
        if (path == null) {
            cmc.removeAdditionalDetail(USERICON);
            cmc.removeAdditionalDetail(ELEMENT);
        } else {
            CotDetail icon = new CotDetail(USERICON);
            icon.setAttribute("iconsetpath", path);
            cmc.addAdditionalDetail(USERICON, icon);
            CotDetail unit = new CotDetail(ELEMENT);
            unit.setAttribute("designation", d);
            cmc.addAdditionalDetail(ELEMENT, unit);
        }
        if (path == null ? sent == null : path.equals(sent))
            return;
        sent = path;
        Intent i = new Intent(ReportingRate.REPORT_LOCATION);
        i.putExtra("reason", "CrowdCAD unit icon");
        AtakBroadcast.getInstance().sendBroadcast(i);
    }
}
