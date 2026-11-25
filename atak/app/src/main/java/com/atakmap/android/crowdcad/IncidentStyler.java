package com.atakmap.android.crowdcad;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffColorFilter;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;
import android.util.Log;

import com.atakmap.android.crowdcad.model.Incident;
import com.atakmap.android.crowdcad.model.Priority;
import com.atakmap.android.maps.MapItem;
import com.atakmap.android.maps.MapView;
import com.atakmap.android.maps.Marker;
import com.atakmap.coremap.maps.assets.Icon;

import java.io.ByteArrayOutputStream;
import java.util.HashMap;
import java.util.Map;

/**
 * Gives incident markers the EMS Star-of-Life icon, with the white disc tinted by priority
 * (P1 red, P2 orange, P3 yellow). The ring and the star stay dark because MULTIPLY leaves
 * black and near-black alone.
 *
 * Only plugin devices see this. The CoT still says b-m-p-s-p-i, so ATAK, WinTAK and iTAK
 * without the plugin keep their default incident icon.
 *
 * Restyled after every import, including the bridge's same-content heartbeats, which the Board
 * ignores. ATAK re-applies the type's default icon while it imports each CoT, so the styling
 * has to land after that import, every time (same lesson as IU Event CAD's MapStyler).
 */
final class IncidentStyler {

    private static final int ICON_PX = 48;

    private final Context plugin;
    private final MapView mapView;
    private final Handler ui = new Handler(Looper.getMainLooper());
    // Priority 1..3 → base64:// PNG, drawn once. UI thread only.
    private final Map<Integer, String> iconUris = new HashMap<>();
    // Incident CoT uid → ATAK's icon before we restyled it, put back when the plugin unloads. UI thread only.
    private final Map<String, Icon> originals = new HashMap<>();

    IncidentStyler(Context plugin, MapView mapView) {
        this.plugin = plugin;
        this.mapView = mapView;
    }

    /** Any thread. */
    void style(MapItem item, Incident incident) {
        if (!(item instanceof Marker))
            return;
        Marker m = (Marker) item;
        ui.post(() -> apply(m, incident));
    }

    /** UI thread. A closed incident's marker is removed, so its original icon is dropped too. */
    void forget(String uid) {
        ui.post(() -> originals.remove(uid));
    }

    /** UI thread. Puts ATAK's own icons back so an unloaded plugin leaves no custom icons on the map. */
    void stop() {
        for (Map.Entry<String, Icon> e : originals.entrySet()) {
            MapItem item = mapView.getRootGroup().deepFindUID(e.getKey());
            if (item instanceof Marker)
                ((Marker) item).setIcon(e.getValue());
        }
        originals.clear();
    }

    private void apply(Marker m, Incident incident) {
        String uri = iconUri(incident.priority);
        if (uri == null)
            return;   // the icon failed to load; leave ATAK's default rather than a blank marker
        Icon current = m.getIcon();
        if (current != null && uri.equals(current.getImageUri(Icon.STATE_DEFAULT)))
            return;
        if (current != null && !originals.containsKey(m.getUID()))
            originals.put(m.getUID(), current);
        m.setIcon(new Icon.Builder().setImageUri(Icon.STATE_DEFAULT, uri)
                .setSize(ICON_PX, ICON_PX)
                .setAnchor(ICON_PX / 2, ICON_PX / 2).build());
    }

    private String iconUri(int priority) {
        String uri = iconUris.get(priority);
        if (uri == null) {
            uri = draw(Priority.color(priority));
            if (uri != null)
                iconUris.put(priority, uri);
        }
        return uri;
    }

    private String draw(int color) {
        Bitmap src = BitmapFactory.decodeResource(plugin.getResources(),
                com.atakmap.android.crowdcad.plugin.R.drawable.cc_incident_ems);
        if (src == null) {
            Log.w(CrowdCadMapComponent.TAG, "incident icon resource failed to decode");
            return null;
        }
        Bitmap out = Bitmap.createBitmap(ICON_PX, ICON_PX, Bitmap.Config.ARGB_8888);
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
        // MULTIPLY: white disc → the priority colour, black ring and dark star stay dark,
        // and transparent corners stay transparent.
        p.setColorFilter(new PorterDuffColorFilter(color, PorterDuff.Mode.MULTIPLY));
        new Canvas(out).drawBitmap(Bitmap.createScaledBitmap(src, ICON_PX, ICON_PX, true), 0, 0, p);
        ByteArrayOutputStream png = new ByteArrayOutputStream();
        out.compress(Bitmap.CompressFormat.PNG, 100, png);
        return "base64://" + Base64.encodeToString(png.toByteArray(), Base64.NO_WRAP | Base64.URL_SAFE);
    }
}
