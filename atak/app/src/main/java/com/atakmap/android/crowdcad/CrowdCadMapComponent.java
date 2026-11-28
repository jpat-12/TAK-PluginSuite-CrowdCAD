package com.atakmap.android.crowdcad;

import android.content.Context;
import android.content.Intent;
import android.widget.Toast;

import com.atakmap.android.cot.detail.CotDetailManager;
import com.atakmap.android.crowdcad.model.Board;
import com.atakmap.android.crowdcad.model.Incident;
import com.atakmap.android.crowdcad.model.Roster;
import com.atakmap.android.dropdown.DropDownMapComponent;
import com.atakmap.android.ipc.AtakBroadcast.DocumentedIntentFilter;
import com.atakmap.android.maps.MapView;

/**
 * Owns the plugin's long-lived objects and their teardown: the {@link Board}, the two CoT
 * detail handlers that feed it, this device's {@link AckReporter}, the incident icons, the unit
 * icons ({@link UnitIdentity} for this phone, {@link UnitStyler} for others, both coloured by the
 * bridge's {@link Roster}), and the panel.
 */
public class CrowdCadMapComponent extends DropDownMapComponent {

    static final String TAG = "CrowdCAD";

    private Board board;
    private IncidentHandler incidentHandler;
    private UnitHandler unitHandler;
    private AckReporter acks;
    private IncidentStyler styler;
    private IconsetInstaller iconset;
    private Roster roster;
    private UnitIdentity identity;
    private UnitStyler unitStyler;
    private SupervisorRequest supervisor;

    @Override
    public void onCreate(Context context, Intent intent, MapView view) {
        context.setTheme(com.atakmap.android.crowdcad.plugin.R.style.ATAKPluginTheme);
        super.onCreate(context, intent, view);
        board = new Board();
        acks = new AckReporter(view);
        roster = new Roster();
        identity = new UnitIdentity(view, roster);
        unitStyler = new UnitStyler(context, view, roster);
        supervisor = new SupervisorRequest();
        identity.setAssignedCheck(() -> {
            long now = System.currentTimeMillis();
            for (Incident i : board.openIncidents(now))
                if (com.atakmap.android.crowdcad.model.Assignment.isMine(i.assigned, MapView.getDeviceUid(),
                        view.getDeviceCallsign()))
                    return true;
            return false;
        });
        board.addListener(() -> view.post(identity::refresh));
        CrowdCadDropDown dropDown = new CrowdCadDropDown(view, context, board, acks, identity, supervisor);
        styler = new IncidentStyler(context, view);
        incidentHandler = new IncidentHandler(board,
                incident -> alertAssigned(context, view, dropDown, incident, roster.alert()), styler);
        unitHandler = new UnitHandler(board);
        CotDetailManager.getInstance().registerHandler(incidentHandler);
        CotDetailManager.getInstance().registerHandler(unitHandler);
        CotDetailManager.getInstance().registerHandler(unitStyler);

        DocumentedIntentFilter filter = new DocumentedIntentFilter();
        filter.addAction(CrowdCadDropDown.SHOW_PLUGIN, "Show the CrowdCAD board");
        registerDropDownReceiver(dropDown, filter);
        acks.start();
        identity.start();
        iconset = new IconsetInstaller(context, view);
        dropDown.setIconsetInstaller(iconset);
        iconset.start();          // skipped once the operator chose "Stop loading it" (tracker R42)
    }

    /** UI thread. Loud on purpose: an assignment a medic doesn't notice is a patient waiting. */
    private static void alertAssigned(Context plugin, MapView view, CrowdCadDropDown dropDown, Incident incident,
            String sound) {
        Context ctx = view.getContext();
        Toast.makeText(ctx, "CrowdCAD: assigned to " + incident.id + " — " + incident.type
                + " at " + incident.location, Toast.LENGTH_LONG).show();
        AssignmentAlarm.fire(ctx, plugin, sound);   // the dispatcher's sound at full alarm volume + 5 s hard vibration
        dropDown.showIncident(incident);
    }

    @Override
    protected void onDestroyImpl(Context context, MapView view) {
        if (acks != null)
            acks.stop();
        if (identity != null)
            identity.stop();
        if (supervisor != null)
            supervisor.stop();
        if (unitStyler != null) {
            CotDetailManager.getInstance().unregisterHandler(unitStyler);
            unitStyler.stop();
        }
        AssignmentAlarm.stop(view.getContext());
        if (incidentHandler != null)
            CotDetailManager.getInstance().unregisterHandler(incidentHandler);
        if (unitHandler != null)
            CotDetailManager.getInstance().unregisterHandler(unitHandler);
        if (styler != null)
            styler.stop();
        if (iconset != null)
            iconset.stop();
        super.onDestroyImpl(context, view);
    }
}
