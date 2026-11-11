package com.atakmap.android.crowdcad.model;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * The plugin's one canonical record of incidents and units, fed by the CoT detail handlers
 * (import thread) and read by the panel (UI thread). Pure Java — no ATAK — so its rules are
 * unit-tested:
 *
 * - Newest wins: an incident replaces the held copy only if its `updated` is newer; a unit only
 *   if its `since` is newer or equal (a re-sent PLI refreshes its stale time). Out-of-order
 *   delivery can't roll status back.
 * - A copy with the same `updated` (the bridge's heartbeat) only refreshes stale time.
 * - Closed incidents leave the open list but are remembered, so a late older copy can't
 *   resurrect them.
 * - Anything past its CoT stale time drops off: when the bridge or a device goes quiet, the
 *   board empties instead of showing old truth as current.
 */
public final class Board {

    public enum Change { NEW, UPDATED, CLOSED, IGNORED }

    public interface Listener {
        /** Import or UI thread — implementations hop to the UI thread themselves. */
        void onBoardChanged();
    }

    private final Map<String, Incident> incidents = new HashMap<>();   // by CoT uid
    private final Map<String, Unit> units = new HashMap<>();           // by CoT uid
    private final List<Listener> listeners = new CopyOnWriteArrayList<>();

    public void addListener(Listener l) {
        listeners.add(l);
    }

    public void removeListener(Listener l) {
        listeners.remove(l);
    }

    public Change put(Incident incoming) {
        Change change;
        synchronized (this) {
            Incident held = incidents.get(incoming.uid);
            if (held != null && incoming.updated < held.updated) {
                return Change.IGNORED;
            } else if (held != null && incoming.updated == held.updated) {
                incidents.put(incoming.uid, held.withStaleAt(Math.max(held.staleAt, incoming.staleAt)));
                return Change.IGNORED;
            }
            incidents.put(incoming.uid, incoming);
            change = !incoming.status.isOpen() ? Change.CLOSED : held == null ? Change.NEW : Change.UPDATED;
        }
        fire();
        return change;
    }

    public boolean put(Unit incoming) {
        synchronized (this) {
            Unit held = units.get(incoming.uid);
            if (held != null && incoming.since < held.since)
                return false;
            units.put(incoming.uid, incoming);
        }
        fire();
        return true;
    }

    public void removeUnit(String uid) {
        boolean removed;
        synchronized (this) {
            removed = units.remove(uid) != null;
        }
        if (removed)
            fire();
    }

    /** Open, unstale incidents: priority, then the least-progressed status, then oldest first. */
    public synchronized List<Incident> openIncidents(long now) {
        List<Incident> out = new ArrayList<>();
        for (Incident i : incidents.values())
            if (i.status.isOpen() && i.staleAt > now)
                out.add(i);
        Collections.sort(out, (a, b) -> a.priority != b.priority ? Integer.compare(a.priority, b.priority)
                : a.status != b.status ? Integer.compare(a.status.ordinal(), b.status.ordinal())
                : Long.compare(a.created, b.created));
        return out;
    }

    /** Unstale units, by callsign. */
    public synchronized List<Unit> units(long now) {
        List<Unit> out = new ArrayList<>();
        for (Unit u : units.values())
            if (u.staleAt > now)
                out.add(u);
        Collections.sort(out, (a, b) -> String.CASE_INSENSITIVE_ORDER.compare(a.callsign, b.callsign));
        return out;
    }

    public synchronized Unit unit(String uid) {
        return units.get(uid);
    }

    /** Callsign for a unit uid, or the uid itself if we haven't heard from it. */
    public synchronized String callsign(String uid) {
        Unit u = units.get(uid);
        return u != null && u.callsign != null && !u.callsign.isEmpty() ? u.callsign : uid;
    }

    private void fire() {
        for (Listener l : listeners)
            l.onBoardChanged();
    }
}
