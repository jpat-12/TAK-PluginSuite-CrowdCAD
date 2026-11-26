package com.atakmap.android.crowdcad;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import com.atakmap.android.cot.detail.CotDetailHandler;
import com.atakmap.android.crowdcad.model.Roster;
import com.atakmap.android.maps.MapItem;
import com.atakmap.android.maps.MapView;
import com.atakmap.android.maps.Marker;
import com.atakmap.comms.CommsMapComponent;
import com.atakmap.coremap.cot.event.CotDetail;
import com.atakmap.coremap.cot.event.CotEvent;
import com.atakmap.coremap.maps.assets.Icon;

import java.util.HashMap;
import java.util.Map;

/**
 * Other units' markers, on plugin devices: a PLI carrying {@code <__crowdcad_unit designation=..>}
 * gets that unit's EMS icon in its roster colour instead of the team skittle. Restyled after every
 * import (ATAK re-applies the contact icon on each PLI, the same lesson as {@link IncidentStyler})
 * and whenever the roster changes. The original icon is put back when the plugin unloads.
 */
final class UnitStyler extends CotDetailHandler implements Roster.Listener {

    private static final int ICON_PX = 40;

    private final Context plugin;
    private final MapView mapView;
    private final Roster roster;
    private final Handler ui = new Handler(Looper.getMainLooper());
    // Marker uid → designation / ATAK's icon before restyling. UI thread only.
    private final Map<String, String> designations = new HashMap<>();
    private final Map<String, Icon> originals = new HashMap<>();

    UnitStyler(Context plugin, MapView mapView, Roster roster) {
        super(UnitIdentity.ELEMENT);
        this.plugin = plugin;
        this.mapView = mapView;
        this.roster = roster;
        roster.addListener(this);
    }

    @Override
    public CommsMapComponent.ImportResult toItemMetadata(MapItem item, CotEvent event, CotDetail detail) {
        String d = detail.getAttribute("designation");
        if (!(item instanceof Marker) || !UnitIcons.valid(d) || event.getUID().equals(MapView.getDeviceUid()))
            return CommsMapComponent.ImportResult.IGNORE;
        Marker m = (Marker) item;
        ui.post(() -> {
            designations.put(m.getUID(), d);
            style(m, d);
        });
        return CommsMapComponent.ImportResult.SUCCESS;
    }

    // The designation is the other phone's to report; never re-serialised onto its marker.
    @Override
    public boolean toCotDetail(MapItem item, CotEvent event, CotDetail root) {
        return false;
    }

    @Override
    public void onRosterChanged() {
        ui.post(() -> {
            for (Map.Entry<String, String> e : designations.entrySet()) {
                MapItem item = mapView.getRootGroup().deepFindUID(e.getKey());
                if (item instanceof Marker)
                    style((Marker) item, e.getValue());
            }
        });
    }

    /** UI thread. */
    void stop() {
        for (Map.Entry<String, Icon> e : originals.entrySet()) {
            MapItem item = mapView.getRootGroup().deepFindUID(e.getKey());
            if (item instanceof Marker)
                ((Marker) item).setIcon(e.getValue());
        }
        originals.clear();
        designations.clear();
    }

    private void style(Marker m, String designation) {
        String uri = UnitIcons.uri(plugin, designation, roster.colour(m.getUID()));
        if (uri == null)
            return;   // icon missing: keep ATAK's own marker rather than a blank one
        Icon current = m.getIcon();
        if (current != null && uri.equals(current.getImageUri(Icon.STATE_DEFAULT)))
            return;
        if (current != null && !originals.containsKey(m.getUID()))
            originals.put(m.getUID(), current);
        m.setIcon(new Icon.Builder().setImageUri(Icon.STATE_DEFAULT, uri)
                .setSize(ICON_PX, ICON_PX).setAnchor(ICON_PX / 2, ICON_PX / 2).build());
    }
}
