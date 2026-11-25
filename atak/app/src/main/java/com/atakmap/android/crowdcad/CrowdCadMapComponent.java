package com.atakmap.android.crowdcad;

import android.content.Context;
import android.content.Intent;
import android.os.Vibrator;
import android.widget.Toast;

import com.atakmap.android.cot.detail.CotDetailManager;
import com.atakmap.android.crowdcad.model.Board;
import com.atakmap.android.crowdcad.model.Incident;
import com.atakmap.android.dropdown.DropDownMapComponent;
import com.atakmap.android.ipc.AtakBroadcast.DocumentedIntentFilter;
import com.atakmap.android.maps.MapView;

/**
 * Owns the plugin's long-lived objects and their teardown: the {@link Board}, the two CoT
 * detail handlers that feed it, this device's {@link StatusReporter}, and the panel.
 */
public class CrowdCadMapComponent extends DropDownMapComponent {

    static final String TAG = "CrowdCAD";

    private Board board;
    private IncidentHandler incidentHandler;
    private UnitHandler unitHandler;
    private StatusReporter reporter;
    private IncidentStyler styler;
    private IconsetInstaller iconset;

    @Override
    public void onCreate(Context context, Intent intent, MapView view) {
        context.setTheme(com.atakmap.android.crowdcad.plugin.R.style.ATAKPluginTheme);
        super.onCreate(context, intent, view);
        board = new Board();
        reporter = new StatusReporter(view, board);
        CrowdCadDropDown dropDown = new CrowdCadDropDown(view, context, board, reporter);
        styler = new IncidentStyler(context, view);
        incidentHandler = new IncidentHandler(board, incident -> alertAssigned(view, dropDown, incident), styler);
        unitHandler = new UnitHandler(board);
        CotDetailManager.getInstance().registerHandler(incidentHandler);
        CotDetailManager.getInstance().registerHandler(unitHandler);

        DocumentedIntentFilter filter = new DocumentedIntentFilter();
        filter.addAction(CrowdCadDropDown.SHOW_PLUGIN, "Show the CrowdCAD board");
        registerDropDownReceiver(dropDown, filter);
        reporter.start();
        iconset = new IconsetInstaller(context, view);
        iconset.start();
    }

    /** UI thread. Loud on purpose: an assignment a medic doesn't notice is a patient waiting. */
    private static void alertAssigned(MapView view, CrowdCadDropDown dropDown, Incident incident) {
        Context ctx = view.getContext();
        Toast.makeText(ctx, "CrowdCAD: assigned to " + incident.id + " — " + incident.type
                + " at " + incident.location, Toast.LENGTH_LONG).show();
        Vibrator vibrator = (Vibrator) ctx.getSystemService(Context.VIBRATOR_SERVICE);
        if (vibrator != null)
            vibrator.vibrate(new long[] {0, 400, 200, 400, 200, 400}, -1);
        dropDown.showIncident(incident);
    }

    @Override
    protected void onDestroyImpl(Context context, MapView view) {
        if (reporter != null)
            reporter.stop();
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
