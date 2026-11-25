"""The bridge: CrowdCAD event records in, CoT out.

Publisher is the canonical record of what TAK has been told (one entry per CoT uid). It is
pure apart from the injected `send` and `clock_ms`, so tests drive it with plain dicts.
Runner owns the threads and IO around it.

Send rules (docs/COT_FORMAT.md):
- An item is sent when its content changes, with `updated` bumped (receivers keep the newest).
- Everything live is re-sent every heartbeat with the SAME `updated`, so stale can be short.
- Closed items (finished call, ended event, deleted thing) are sent once with a 90 s stale,
  then remembered as done. Something first seen already closed — e.g. last night's calls when
  the bridge restarts — is remembered without being sent.
"""

import json
import sys
import threading
import time

from . import LOG_PREFIX, cot, mapping
from .pocketbase import PocketBaseError


def log(message):
    print(f"{LOG_PREFIX} {message}", file=sys.stderr, flush=True)


def _fingerprint(item):
    return json.dumps([item.lat, item.lon, item.closed, item.fields], sort_keys=True, default=str)


class Publisher:
    def __init__(self, config, send, clock_ms=lambda: int(time.time() * 1000)):
        self.config = config
        self.send = send
        self.clock_ms = clock_ms
        self.sent = {}     # CoT uid → {event, item, fp, created, updated, done}
        self.events = {}   # event id → {name, unplaced, counts}
        self.lock = threading.RLock()

    def selected(self, record):
        selection = self.config.get("events", "active")
        if selection == "active":
            return record.get("status") == "active" and not record.get("ended")
        return record.get("id") in (selection or [])

    def _emit(self, entry, now):
        stale = int(self.config.get("stale_seconds") or 300)
        self.send(cot.render(entry["item"], now, entry["created"], entry["updated"], stale))

    def apply(self, record):
        """Publish one event record's current state. Returns the number of messages sent."""
        with self.lock:
            eid = record.get("id")
            items, unplaced = mapping.build(record, self.config)
            now = self.clock_ms()
            count = 0
            for uid, item in items.items():
                prev = self.sent.get(uid)
                fp = _fingerprint(item)
                if prev and prev["fp"] == fp:
                    continue
                if item.closed and (prev is None or prev["done"]):
                    self.sent[uid] = {"event": eid, "item": item, "fp": fp, "done": True,
                                      "created": prev["created"] if prev else now,
                                      "updated": prev["updated"] if prev else now}
                    continue
                created = prev["created"] if prev else (item.created_ms or now)
                # created comes from CrowdCAD's clock (call log), updated from ours: never let
                # skew between the two make an incident look updated before it was created.
                updated = max(now, created, prev["updated"] + 1 if prev else 0)
                entry = {"event": eid, "item": item, "fp": fp, "done": item.closed,
                         "created": created, "updated": updated}
                self.sent[uid] = entry
                self._emit(entry, now)
                count += 1
            # Gone from the record (call deleted, team removed, zone erased): close it once.
            for uid, entry in list(self.sent.items()):
                if entry["event"] == eid and uid not in items and not entry["done"]:
                    count += self._close(entry, now)
            self.events[eid] = {
                "name": record.get("name") or eid, "ended": bool(record.get("ended")),
                "owner": record.get("userId"),   # the bridge's own events can be ended from TAK
                "date": record.get("date"),        # tells two same-named events apart in the web pickers
                "unplaced": [vars(u) for u in unplaced],
                "device_teams": mapping.device_teams(record, self.config),
                "free_units": mapping.free_units(record, self.config),   # claimable by an ATAK callsign
                "counts": {kind: sum(1 for e in self.sent.values()
                                     if e["event"] == eid and not e["done"] and e["item"].kind == kind)
                           for kind in ("incident", "unit", "zone", "post")},
            }
            return count

    def _close(self, entry, now):
        entry["item"].closed = True
        if entry["item"].kind == "incident":
            entry["item"].fields = {**entry["item"].fields, "status": "CLOSED"}
        entry["updated"] = max(now, entry["updated"] + 1)
        entry["fp"], entry["done"] = _fingerprint(entry["item"]), True
        self._emit(entry, now)
        return 1

    def remove_event(self, eid):
        """The event was deleted or is no longer selected: take everything of it off the map."""
        with self.lock:
            now = self.clock_ms()
            count = sum(self._close(e, now) for e in self.sent.values() if e["event"] == eid and not e["done"])
            self.events.pop(eid, None)
            return count

    def resync(self, records):
        """A full listing: apply each selected record and retire known events missing from it."""
        with self.lock:
            listed = {r.get("id") for r in records if self.selected(r)}
            for record in records:
                if record.get("id") in listed:
                    self.apply(record)
            for eid in list(self.events):
                if eid not in listed:
                    self.remove_event(eid)

    def on_change(self, action, record):
        eid = record.get("id")
        if action == "delete" or not self.selected(record):
            if eid in self.events:
                self.remove_event(eid)
            return
        self.apply(record)

    def heartbeat(self):
        """Re-send everything live, unchanged (same `updated`), to refresh its stale time."""
        with self.lock:
            now = self.clock_ms()
            live = [e for e in self.sent.values() if not e["done"]]
            for entry in live:
                self._emit(entry, now)
            return len(live)

    def status(self):
        with self.lock:
            return {"events": [{"id": eid, **info} for eid, info in self.events.items()]}


class Runner:
    """Threads and IO: PocketBase realtime (with polling fallback), TAK writer, heartbeat."""

    def __init__(self, config, pocketbase, tak):
        self.config = config
        self.pb = pocketbase
        self.tak = tak
        self.publisher = Publisher(config, tak.send)
        tak.on_connect = self.publisher.heartbeat   # a fresh TAK connection gets the whole picture
        self.crowdcad = {"mode": "starting", "last_error": None, "last_sync": None}
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()
        self.tak.stop()

    def _resync(self):
        records = self.pb.list_events(self.config.get("events", "active"))
        self.publisher.resync(records)
        self.crowdcad["last_sync"] = int(time.time() * 1000)

    def _heartbeat_loop(self):
        interval = max(10, int(self.config.get("heartbeat_seconds") or 120))
        while not self._stop.wait(interval):
            try:
                self.publisher.heartbeat()
            except Exception as error:  # never let the heartbeat thread die silently
                log(f"heartbeat failed: {error!r}")

    def run(self):
        self.tak.start()
        threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True).start()
        backoff = 1
        while not self._stop.is_set():
            def on_connect():
                # Subscribe first, then list: nothing changed between the two can be missed.
                self._resync()
                self.crowdcad.update(mode="live", last_error=None)
                log("CrowdCAD realtime connected")
            try:
                self.pb.realtime(["events/*"], self._on_record, on_connect=on_connect)
                backoff = 1  # clean close (PocketBase idle timeout): reconnect straight away
                continue
            except PocketBaseError as error:
                self.crowdcad.update(last_error=str(error))
                log(f"CrowdCAD: {error}")
            # Realtime unavailable (e.g. a proxy that buffers SSE): keep data flowing by polling.
            try:
                self._resync()
                self.crowdcad["mode"] = "polling"
            except PocketBaseError as error:
                self.crowdcad.update(mode="down", last_error=str(error))
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30)

    def _on_record(self, action, record):
        try:
            self.publisher.on_change(action, record)
        except Exception as error:  # one malformed record must not drop the stream
            log(f"event {record.get('id')!r} not published: {error!r}")

    def status(self):
        from . import VERSION
        return {"version": VERSION, "crowdcad": dict(self.crowdcad, url=self.pb.base),
                "tak": {"connected": self.tak.connected, "host": f"{self.tak.host}:{self.tak.port}",
                        "sent": self.tak.sent, "last_error": self.tak.last_error},
                **self.publisher.status()}
