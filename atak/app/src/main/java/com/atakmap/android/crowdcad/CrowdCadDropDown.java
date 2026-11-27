package com.atakmap.android.crowdcad;

import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.atakmap.android.crowdcad.model.Assignment;
import com.atakmap.android.crowdcad.model.Board;
import com.atakmap.android.crowdcad.model.Incident;
import com.atakmap.android.crowdcad.model.IncidentStatus;
import com.atakmap.android.crowdcad.model.Roster;
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
 * The CrowdCAD panel: this device's assignment (read-only), then open incidents (priority first,
 * tap to show on the map), then units. UI only: data comes from the {@link Board}.
 *
 * Field users can't change status (Jon, 2026-11-25): there are no status buttons and no Respond.
 * The one action is Acknowledge on a call assigned to this phone ({@link AckReporter}). The bridge
 * logs it in CrowdCAD and links the phone to the unit named like its callsign if it isn't yet.
 */
public class CrowdCadDropDown extends DropDownReceiver implements DropDown.OnStateListener, Board.Listener,
        Roster.Listener {

    public static final String SHOW_PLUGIN = "com.atakmap.android.crowdcad.SHOW_PLUGIN";
    private static final long TICK_MS = 30_000;               // ages + stale expiry
    private static final double VENUE_SCALE = 1d / 2500;      // the whole venue beside the pane

    private final Context plugin;
    private final Board board;
    private final AckReporter acks;
    private final UnitIdentity identity;
    private final SupervisorRequest supervisor;
    private TextView supervisorLabel;
    private Button requestButton;
    private TextView designationLabel;
    private Button muteButton;              // debug builds only (R35)
    private ImageView bannerIcon;
    private TextView bannerStatus;
    private TextView bannerTitle;
    private LinearLayout settingsBox;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Runnable render = this::render;
    // A request just sent shows until the bridge's roster echoes it (or this long, if it never does).
    private static final long SUPREQ_ECHO_MS = 2 * 60_000;
    // How long "Supervisor request acknowledged" stays after a dispatcher clears the request.
    private static final long SUPREQ_ACK_SHOW_MS = 90_000;     // 1.5 min (Jon, tracker)
    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            render();
            ui.postDelayed(this, TICK_MS);
        }
    };

    private View root;
    private TextView assignmentLabel;
    private LinearLayout incidentsBox;
    private LinearLayout unitsBox;
    private TextView unitsHeader;
    private boolean visible;

    public CrowdCadDropDown(MapView mapView, Context plugin, Board board, AckReporter acks, UnitIdentity identity,
            SupervisorRequest supervisor) {
        super(mapView);
        this.plugin = plugin;
        this.board = board;
        this.acks = acks;
        this.identity = identity;
        this.supervisor = supervisor;
        board.addListener(this);
        identity.roster().addListener(this);
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
    public void onRosterChanged() {
        onBoardChanged();     // the banner's availability comes from the roster
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

        // Banner: [unit icon] CrowdCAD · availability            [settings]
        LinearLayout banner = new LinearLayout(plugin);
        banner.setOrientation(LinearLayout.HORIZONTAL);
        banner.setGravity(android.view.Gravity.CENTER_VERTICAL);
        banner.setPadding(dp(8), dp(6), dp(4), dp(6));
        GradientDrawable bannerBg = new GradientDrawable();
        bannerBg.setColor(color(R.color.cc_bg_card));
        bannerBg.setCornerRadius(dp(6));
        banner.setBackground(bannerBg);
        col.addView(banner);
        bannerIcon = new ImageView(plugin);
        banner.addView(bannerIcon, new LinearLayout.LayoutParams(dp(34), dp(34)));
        TextView title = text(banner, "CrowdCAD", true);
        bannerTitle = title;
        title.setTextSize(16);
        title.setPadding(dp(8), 0, dp(8), 0);
        bannerStatus = text(banner, "", true);
        bannerStatus.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        TextView gear = new TextView(plugin);       // a plain ⚙: looks the same on every ATAK theme
        gear.setText("\u2699");
        gear.setTextSize(24);
        gear.setTextColor(color(R.color.cc_text_primary));
        gear.setGravity(android.view.Gravity.CENTER);
        gear.setContentDescription("Settings");
        gear.setOnClickListener(v -> settingsBox.setVisibility(
                settingsBox.getVisibility() == View.VISIBLE ? View.GONE : View.VISIBLE));
        banner.addView(gear, new LinearLayout.LayoutParams(dp(40), dp(40)));

        // Request Supervisor: red, and confirmed once more so nobody sends it by a stray tap.
        Button request = button(col, "Request Supervisor", v -> confirmSupervisor());
        requestButton = request;
        request.setTextColor(0xFFFFFFFF);
        request.setTextSize(13);
        request.setAllCaps(false);
        request.setMinHeight(0);
        request.setMinimumHeight(0);
        request.setMinWidth(0);
        request.setMinimumWidth(0);
        request.setPadding(dp(12), dp(4), dp(12), dp(4));
        GradientDrawable red = new GradientDrawable();
        red.setColor(0xFFC62828);
        red.setCornerRadius(dp(6));
        request.setBackground(red);
        LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        rp.setMargins(0, dp(6), 0, 0);
        rp.gravity = android.view.Gravity.END;       // compact, right-aligned under the banner
        request.setLayoutParams(rp);
        supervisorLabel = text(col, "", false);
        supervisorLabel.setVisibility(View.GONE);

        // Settings: behind the gear, closed by default.
        settingsBox = column(col);
        settingsBox.setVisibility(View.GONE);
        header(settingsBox, "Settings");
        designationLabel = text(settingsBox, "", false);
        LinearLayout pick = new LinearLayout(plugin);
        pick.setOrientation(LinearLayout.HORIZONTAL);
        settingsBox.addView(pick);
        for (String d : new String[] {"BLS", "ALS", "SUP", "Off"}) {
            button(pick, d, v -> {
                identity.setDesignation("Off".equals(d) ? "" : d);
                showDesignation();
            });
        }
        showDesignation();
        if (AlertMute.available()) {         // tracker R35: debug builds only, never in a release
            muteButton = button(settingsBox, "", v -> {
                AlertMute.set(getMapView().getContext(), !AlertMute.muted(getMapView().getContext()));
                showMute();
            });
            showMute();
        }

        assignmentLabel = text(col, "", true);
        assignmentLabel.setPadding(0, dp(8), 0, 0);
        header(col, "Your calls");
        incidentsBox = column(col);
        unitsHeader = header(col, "Units");
        unitsBox = column(col);
        return scroll;
    }

    /** The unit icon this phone shows others: green available, grey out of service, light red busy. */
    private void showDesignation() {
        String d = identity.designation();
        designationLabel.setText("Unit icon: " + (d.isEmpty() ? "Off" : d));
        // Tracker R40: a Supervisor unit doesn't request a supervisor, so no button for it.
        if (requestButton != null)
            requestButton.setVisibility("SUP".equals(d) ? View.GONE : View.VISIBLE);
        renderBanner(false);
    }

    /** Debug builds (R35): the mute switch's label, and the banner's reminder. */
    private void showMute() {
        if (muteButton != null)
            muteButton.setText(AlertMute.muted(getMapView().getContext())
                    ? "Assignment alert: muted (debug build) · tap to unmute"
                    : "Mute assignment alert (debug build)");
        renderBanner(false);
    }

    /** "Are you sure?" before the request goes to every supervisor and dispatch. */
    private void confirmSupervisor() {
        try {
            showSupervisorDialog();
        } catch (Throwable t) {      // a dialog problem must never take ATAK down
            android.util.Log.e(CrowdCadMapComponent.TAG, "supervisor dialog failed", t);
            android.widget.Toast.makeText(getMapView().getContext(), "Request Supervisor failed: " + t.getMessage(),
                    android.widget.Toast.LENGTH_LONG).show();
        }
    }

    private void showSupervisorDialog() {
        new android.app.AlertDialog.Builder(getMapView().getContext())
                .setTitle("Request a supervisor?")
                .setMessage("This alerts every supervisor and dispatch right away.")
                .setPositiveButton("Yes, request", (dlg, which) -> {
                    try {
                        supervisor.send();
                    } catch (Throwable t) {
                        android.util.Log.e(CrowdCadMapComponent.TAG, "supervisor request failed", t);
                        return;
                    }
                    renderSupervisor(System.currentTimeMillis());
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    /**
     * "Supervisor requested at HH:MM" while this phone's request is open on the dispatcher's board
     * (the bridge's roster echoes it), or just sent and not echoed yet; once a dispatcher clears it,
     * "Supervisor request acknowledged" for a minute, then nothing.
     */
    private void renderSupervisor(long now) {
        if (supervisorLabel == null)
            return;
        Roster roster = identity.roster();
        String uid = MapView.getDeviceUid();
        long open = roster.supervisorRequest(uid);
        long sent = supervisor.lastAt();
        boolean pending = sent > roster.lastSupervisorRequestSeen(uid) && now - sent < SUPREQ_ECHO_MS;
        long acked = roster.acknowledgedAt(uid);
        if (open > 0 || pending) {
            supervisorLabel.setText("Supervisor requested at "
                    + new java.text.SimpleDateFormat("HH:mm", java.util.Locale.US)
                            .format(new java.util.Date(open > 0 ? open : sent)));
            supervisorLabel.setTextColor(0xFFFF8A80);
            supervisorLabel.setVisibility(View.VISIBLE);
        } else if (acked > 0 && now - acked < SUPREQ_ACK_SHOW_MS) {
            supervisorLabel.setText("\u2713 Supervisor request acknowledged");
            supervisorLabel.setTextColor(0xFF81C784);
            supervisorLabel.setVisibility(View.VISIBLE);
        } else {
            supervisorLabel.setVisibility(View.GONE);
        }
    }

    /** The banner: this phone's unit icon in its dispatch colour, and its availability in words. */
    private void renderBanner(boolean tasked) {
        if (bannerIcon == null)
            return;
        Roster roster = identity.roster();
        String uid = MapView.getDeviceUid();
        String s = roster.status(uid);
        Bitmap icon = UnitIcons.bitmap(plugin, identity.designation(), identity.colour());
        if (icon != null)
            bannerIcon.setImageBitmap(icon);
        String label;
        int colour;
        if (tasked) {
            label = "Tasked";
            colour = R.color.cc_disp;
        } else if (s == null) {
            label = "Not on a unit";
            colour = R.color.cc_text_secondary;
        } else {
            switch (s) {
                case "AVL": label = "Available"; colour = R.color.cc_avl; break;
                case "RESP": label = "Responding"; colour = R.color.cc_disp; break;
                case "ONSC": label = "On Scene"; colour = R.color.cc_new; break;
                case "TRAN": label = "Transporting"; colour = R.color.cc_new; break;
                default: label = "Out of Service"; colour = R.color.cc_oos; break;
            }
        }
        String unit = roster.unitName(uid);    // this phone's CrowdCAD callsign, e.g. "Medic 1"
        bannerTitle.setText(unit.isEmpty() ? "CrowdCAD" : "CrowdCAD  ·  " + unit);
        // R35: a tester must not forget the alert is off.
        bannerStatus.setText("·  " + label
                + (AlertMute.muted(getMapView().getContext()) ? "  ·  🔇 alert muted (debug)" : ""));
        bannerStatus.setTextColor(color(colour));
    }

    private void render() {
        if (root == null)
            return;
        long now = System.currentTimeMillis();
        incidentsBox.removeAllViews();
        List<Incident> open = board.openIncidents(now);
        String myUid = MapView.getDeviceUid();
        String myCallsign = getMapView().getDeviceCallsign();
        List<String> mine = new ArrayList<>();
        // A medic sees only the calls assigned to this phone (Jon, tracker "See call scope");
        // other open calls stay on the dispatcher's board and the TAK map.
        for (Incident i : open) {
            if (!Assignment.isMine(i.assigned, myUid, myCallsign))
                continue;
            mine.add(i.id);
            incidentCard(i, now, true);
        }
        if (mine.isEmpty())
            text(incidentsBox, "No calls assigned to you.", false);
        boolean waiting = false;     // assigned a call not acknowledged yet: Tasked, as dispatch sees it
        for (String id : mine)
            waiting |= acks.ackedAt(id) == null;
        renderBanner(waiting);
        renderSupervisor(now);
        assignmentLabel.setText(mine.isEmpty() ? "" : "Assigned: " + android.text.TextUtils.join(", ", mine));
        assignmentLabel.setVisibility(mine.isEmpty() ? View.GONE : View.VISIBLE);

        unitsBox.removeAllViews();
        List<Unit> units = board.units(now);
        // No units: no section at all (no "No units reporting" line).
        unitsHeader.setVisibility(units.isEmpty() ? View.GONE : View.VISIBLE);
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
        TextView state = text(card, i.status.label + (mine ? " · yours" : ""), false);
        state.setTextColor(color(incidentColor(i.status)));
        List<String> who = new ArrayList<>();
        for (String uid : i.assigned)
            who.add(board.callsign(uid));
        String floor = i.floorLabel();
        text(card, i.location + (floor.isEmpty() ? "" : " · " + floor) + " · " + ago(i.created, now) + " · "
                + (who.isEmpty() ? "no unit" : android.text.TextUtils.join(", ", who)), false);
        if (!i.w3w.isEmpty())
            text(card, "///" + i.w3w, false);
        if (!i.notes.isEmpty())
            text(card, "Notes: " + i.notes, false);
        if (i.positionIsEstimate())
            text(card, "Estimated position", false)
                    .setTextColor(color(incidentColor(IncidentStatus.DISP)));
        card.setOnClickListener(v -> centreOn(i));

        if (!mine)
            return;
        Long ackedAt = acks.ackedAt(i.id);
        if (ackedAt != null) {
            text(card, "Acknowledged", false)
                    .setTextColor(color(R.color.cc_avl));
        } else {
            Button ack = button(card, "Acknowledge", v -> {
                AssignmentAlarm.stop(getMapView().getContext());   // the beeps and buzz stop at once
                acks.acknowledge(i.id);
                render();
            });
            ack.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT));
        }
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

    private TextView header(ViewGroup parent, String label) {
        TextView view = text(parent, label.toUpperCase(), false);
        view.setPadding(0, dp(14), 0, dp(4));
        view.setTextSize(11);
        return view;
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
