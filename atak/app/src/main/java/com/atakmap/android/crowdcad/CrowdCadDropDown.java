package com.atakmap.android.crowdcad;

import android.content.Context;
import android.content.Intent;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.atakmap.android.crowdcad.cot.IucadUnit;
import com.atakmap.android.crowdcad.model.Board;
import com.atakmap.android.crowdcad.model.Incident;
import com.atakmap.android.crowdcad.model.IncidentStatus;
import com.atakmap.android.crowdcad.model.Unit;
import com.atakmap.android.crowdcad.model.UnitStatus;
import com.atakmap.android.crowdcad.plugin.R;
import com.atakmap.android.dropdown.DropDown;
import com.atakmap.android.dropdown.DropDownReceiver;
import com.atakmap.android.maps.MapItem;
import com.atakmap.android.maps.MapView;
import com.atakmap.android.maps.PointMapItem;
import com.atakmap.coremap.maps.coords.GeoPoint;

import java.util.ArrayList;
import java.util.List;

/**
 * The CrowdCAD panel: this device's status bar, then open incidents (priority first, tap to
 * show on the map, "Respond" to take one), then units. UI only: data comes from the
 * {@link Board}, status changes go to the {@link StatusReporter}. The medic's status rides on
 * their PLI; the bridge writes each tap into CrowdCAD (bridge fieldstatus.py), linking this
 * phone to the unit named like its callsign if no one picked it as a contact.
 */
public class CrowdCadDropDown extends DropDownReceiver implements DropDown.OnStateListener, Board.Listener {

    public static final String SHOW_PLUGIN = "com.atakmap.android.crowdcad.SHOW_PLUGIN";
    private static final long TICK_MS = 30_000;               // ages + stale expiry
    private static final double VENUE_SCALE = 1d / 2500;      // the whole venue beside the pane

    private final Context plugin;
    private final Board board;
    private final StatusReporter reporter;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Runnable render = this::render;
    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            render();
            ui.postDelayed(this, TICK_MS);
        }
    };

    private View root;
    private LinearLayout statusRow;
    private TextView statusLabel;
    private LinearLayout incidentsBox;
    private LinearLayout unitsBox;
    private boolean visible;

    public CrowdCadDropDown(MapView mapView, Context plugin, Board board, StatusReporter reporter) {
        super(mapView);
        this.plugin = plugin;
        this.board = board;
        this.reporter = reporter;
        board.addListener(this);
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        if (!SHOW_PLUGIN.equals(intent.getAction()))
            return;
        if (root == null)
            root = build();
        showDropDown(root, HALF_WIDTH, FULL_HEIGHT, FULL_WIDTH, HALF_HEIGHT, this);
        render();
    }

    /** UI thread: called by the assignment alert to bring the incident up. */
    void showIncident(Incident incident) {
        onReceive(getMapView().getContext(), new Intent(SHOW_PLUGIN));
        centreOn(incident);
    }

    @Override
    public void onBoardChanged() {
        if (!visible)
            return;
        ui.removeCallbacks(render);       // coalesce a burst of CoT into one redraw
        ui.postDelayed(render, 250);
    }

    // --- UI construction ------------------------------------------------------------------

    private View build() {
        ScrollView scroll = new ScrollView(plugin);
        LinearLayout col = new LinearLayout(plugin);
        col.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(10);
        col.setPadding(pad, pad, pad, pad);
        scroll.addView(col);

        statusLabel = text(col, "", true);
        statusRow = new LinearLayout(plugin);
        statusRow.setOrientation(LinearLayout.HORIZONTAL);
        col.addView(statusRow);
        for (UnitStatus s : UnitStatus.values()) {
            Button b = button(statusRow, shortLabel(s), v -> setStatus(s));
            b.setTag(s);
            b.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        }

        header(col, "Open incidents");
        incidentsBox = column(col);
        header(col, "Units");
        unitsBox = column(col);
        TextView foot = text(col, "Your status taps update CrowdCAD dispatch. Not linked to a unit yet? Set your ATAK callsign "
                + "to your CrowdCAD unit name (e.g. Team 1). Patient details stay in CrowdCAD.", false);
        foot.setPadding(0, dp(12), 0, 0);
        return scroll;
    }

    private void render() {
        if (root == null)
            return;
        long now = System.currentTimeMillis();
        IucadUnit me = reporter.current();
        statusLabel.setText("My status: " + me.status.label + (me.incidentId.isEmpty() ? "" : " · " + me.incidentId));
        for (int i = 0; i < statusRow.getChildCount(); i++) {
            View b = statusRow.getChildAt(i);
            b.setAlpha(b.getTag() == me.status ? 1f : 0.55f);
        }

        incidentsBox.removeAllViews();
        List<Incident> open = board.openIncidents(now);
        if (open.isEmpty())
            text(incidentsBox, "No open incidents.", false);
        String myUid = MapView.getDeviceUid();
        for (Incident i : open)
            incidentCard(i, now, i.assigned.contains(myUid));

        unitsBox.removeAllViews();
        List<Unit> units = board.units(now);
        if (units.isEmpty())
            text(unitsBox, "No units reporting.", false);
        for (Unit u : units) {
            TextView row = text(unitsBox, u.callsign + "  —  " + u.status.label
                    + (u.incidentId.isEmpty() ? "" : " · " + u.incidentId) + "  (" + ago(u.since, now) + ")", false);
            row.setTextColor(color(unitColor(u.status)));
            row.setPadding(0, dp(3), 0, dp(3));
        }
    }

    private void incidentCard(Incident i, long now, boolean mine) {
        LinearLayout card = new LinearLayout(plugin);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(8), dp(6), dp(8), dp(6));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(color(R.color.cc_bg_card));
        bg.setCornerRadius(dp(6));
        bg.setStroke(dp(mine ? 2 : 1), color(incidentColor(i.status)));
        card.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, dp(3), 0, dp(3));
        incidentsBox.addView(card, lp);

        text(card, (i.priority == 1 ? "P1  " : "") + i.id + "  " + i.type, true);
        TextView state = text(card, i.status.label + (mine ? "  · assigned to you" : ""), false);
        state.setTextColor(color(incidentColor(i.status)));
        List<String> who = new ArrayList<>();
        for (String uid : i.assigned)
            who.add(board.callsign(uid));
        String floor = i.floorLabel();
        text(card, i.location + (floor.isEmpty() ? "" : " · " + floor) + " · " + ago(i.created, now) + " · "
                + (who.isEmpty() ? "no unit" : android.text.TextUtils.join(", ", who)), false);
        if (!i.w3w.isEmpty())
            text(card, "///" + i.w3w, false);
        if (i.positionIsEstimate())
            text(card, "Position is an estimate: confirm the spot by radio", false)
                    .setTextColor(color(incidentColor(IncidentStatus.DISP)));
        card.setOnClickListener(v -> centreOn(i));

        if (!i.id.equals(reporter.current().incidentId)) {
            Button respond = button(card, mine ? "Respond (assigned)" : "Respond", v -> {
                reporter.set(UnitStatus.RESP, i.id);
                render();
            });
            respond.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT));
        }
    }

    private void setStatus(UnitStatus status) {
        // Keep the incident being worked through On Scene / Transporting; AVL/OOS clear it.
        reporter.set(status, reporter.current().incidentId);
        render();
    }

    private void centreOn(Incident i) {
        MapView mv = getMapView();
        GeoPoint p = new GeoPoint(i.lat, i.lon);
        MapItem item = mv.getRootGroup().deepFindUID(i.uid);
        if (item instanceof PointMapItem && ((PointMapItem) item).getPoint().isValid())
            p = ((PointMapItem) item).getPoint();
        mv.getMapController().panZoomTo(p, Math.max(mv.getMapScale(), VENUE_SCALE), true);
    }

    // --- small helpers ----------------------------------------------------------------------

    static String ago(long ms, long now) {
        long minutes = Math.max(0, (now - ms) / 60_000);
        return minutes < 60 ? minutes + "m" : (minutes / 60) + "h" + String.format("%02d", minutes % 60);
    }

    private static String shortLabel(UnitStatus s) {
        switch (s) {
            case AVL: return "AVL";
            case RESP: return "RESP";
            case ONSC: return "ON SC";
            case TRAN: return "TRAN";
            default: return "OOS";
        }
    }

    private static int incidentColor(IncidentStatus s) {
        switch (s) {
            case NEW: return R.color.cc_new;
            case DISP: return R.color.cc_disp;
            case ONSC: return R.color.cc_onsc;
            case TRAN: return R.color.cc_tran;
            default: return R.color.cc_oos;
        }
    }

    private static int unitColor(UnitStatus s) {
        switch (s) {
            case AVL: return R.color.cc_avl;
            case RESP: return R.color.cc_disp;
            case ONSC: return R.color.cc_onsc;
            case TRAN: return R.color.cc_tran;
            default: return R.color.cc_oos;
        }
    }

    private int color(int res) {
        return plugin.getResources().getColor(res);
    }

    private int dp(int value) {
        return Math.round(value * plugin.getResources().getDisplayMetrics().density);
    }

    private LinearLayout column(ViewGroup parent) {
        LinearLayout box = new LinearLayout(plugin);
        box.setOrientation(LinearLayout.VERTICAL);
        parent.addView(box);
        return box;
    }

    private void header(ViewGroup parent, String label) {
        TextView view = text(parent, label.toUpperCase(), false);
        view.setPadding(0, dp(14), 0, dp(4));
        view.setTextSize(11);
    }

    private TextView text(ViewGroup parent, String value, boolean bold) {
        TextView view = new TextView(plugin);
        view.setText(value);
        view.setTextColor(color(bold ? R.color.cc_text_primary : R.color.cc_text_secondary));
        if (bold)
            view.setTypeface(Typeface.DEFAULT_BOLD);
        parent.addView(view);
        return view;
    }

    private Button button(ViewGroup parent, String label, View.OnClickListener onClick) {
        Button button = new Button(plugin);
        button.setText(label);
        button.setAllCaps(false);
        button.setOnClickListener(onClick);
        parent.addView(button);
        return button;
    }

    // --- DropDown lifecycle -------------------------------------------------------------------

    @Override
    protected void disposeImpl() {
        board.removeListener(this);
        ui.removeCallbacksAndMessages(null);
    }

    @Override
    public void onDropDownSelectionRemoved() {
    }

    @Override
    public void onDropDownVisible(boolean visible) {
        this.visible = visible;
        ui.removeCallbacks(tick);
        if (visible)
            ui.post(tick);
    }

    @Override
    public void onDropDownSizeChanged(double width, double height) {
    }

    @Override
    public void onDropDownClose() {
        visible = false;
        ui.removeCallbacks(tick);
    }
}
