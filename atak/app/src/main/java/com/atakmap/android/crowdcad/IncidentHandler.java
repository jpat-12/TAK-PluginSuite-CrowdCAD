package com.atakmap.android.crowdcad;

import android.os.Handler;
import android.os.Looper;

import com.atakmap.android.cot.detail.CotDetailHandler;
import com.atakmap.android.crowdcad.cot.IucadIncident;
import com.atakmap.android.crowdcad.model.Board;
import com.atakmap.android.crowdcad.model.Incident;
import com.atakmap.android.maps.MapItem;
import com.atakmap.android.maps.MapView;
import com.atakmap.comms.CommsMapComponent;
import com.atakmap.coremap.cot.event.CotDetail;
import com.atakmap.coremap.cot.event.CotEvent;

import java.util.HashSet;
import java.util.Set;

/**
 * Reads {@code <__iucad_incident>} from every incoming incident — the CrowdCAD bridge's, or an
 * IU Event CAD device's — into the {@link Board}. Also the medic side of an assignment: the
 * first time this device's uid appears in an incident's `assigned`, it raises the alert.
 */
final class IncidentHandler extends CotDetailHandler {

    interface AssignmentListener {
        /** UI thread. This device was just assigned to {@code incident}. */
        void onAssigned(Incident incident);
    }

    private final Board board;
    private final AssignmentListener listener;
    private final Handler ui = new Handler(Looper.getMainLooper());
    // Incident ids already alerted for, so a re-sent incident doesn't alert again. Import thread only.
    private final Set<String> alerted = new HashSet<>();

    IncidentHandler(Board board, AssignmentListener listener) {
        super(IucadIncident.ELEMENT);
        this.board = board;
        this.listener = listener;
    }

    @Override
    public CommsMapComponent.ImportResult toItemMetadata(MapItem item, CotEvent event, CotDetail detail) {
        Incident incident = IucadIncident.parse(detail::getAttribute, event.getUID(),
                event.getCotPoint().getLat(), event.getCotPoint().getLon(), event.getStale().getMilliseconds());
        if (incident == null)
            return CommsMapComponent.ImportResult.IGNORE;
        Board.Change change = board.put(incident);
        if (change == Board.Change.CLOSED) {
            // Closed: off the map now rather than after the 90 s stale (same as IU Event CAD).
            ui.post(item::removeFromGroup);
        } else if (change != Board.Change.IGNORED && incident.assigned.contains(MapView.getDeviceUid())
                && alerted.add(incident.id)) {
            ui.post(() -> listener.onAssigned(incident));
        }
        return CommsMapComponent.ImportResult.SUCCESS;
    }

    // Incidents are authored by dispatch (the bridge), never re-serialised from this device's items.
    @Override
    public boolean toCotDetail(MapItem item, CotEvent event, CotDetail root) {
        return false;
    }
}
