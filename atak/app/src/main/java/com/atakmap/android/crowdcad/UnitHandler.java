package com.atakmap.android.crowdcad;

import com.atakmap.android.cot.detail.CotDetailHandler;
import com.atakmap.android.crowdcad.cot.IucadUnit;
import com.atakmap.android.crowdcad.model.Board;
import com.atakmap.android.crowdcad.model.Unit;
import com.atakmap.android.maps.MapItem;
import com.atakmap.comms.CommsMapComponent;
import com.atakmap.coremap.cot.event.CotDetail;
import com.atakmap.coremap.cot.event.CotEvent;

/**
 * Reads {@code <__iucad_unit>} from other units' PLIs and from the bridge's team markers into
 * the {@link Board}. ATAK calls this on its CoT import thread.
 */
final class UnitHandler extends CotDetailHandler {

    private final Board board;

    UnitHandler(Board board) {
        super(IucadUnit.ELEMENT);
        this.board = board;
    }

    @Override
    public CommsMapComponent.ImportResult toItemMetadata(MapItem item, CotEvent event, CotDetail detail) {
        IucadUnit d = IucadUnit.parse(detail::getAttribute);
        if (d == null)
            return CommsMapComponent.ImportResult.IGNORE;
        board.put(new Unit(event.getUID(), item.getTitle(), d.status, d.incidentId, d.since,
                event.getStale().getMilliseconds()));
        return CommsMapComponent.ImportResult.SUCCESS;
    }

    // Other units' status is theirs to report; never re-serialised onto their markers.
    @Override
    public boolean toCotDetail(MapItem item, CotEvent event, CotDetail root) {
        return false;
    }
}
