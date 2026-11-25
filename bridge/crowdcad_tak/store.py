"""Applies a dispatch action (dispatch.py) to a CrowdCAD event without losing anyone's change.

    read the event → compute the patch from it → write it only if what was read is unchanged
    (PocketBase hook, compare-and-swap) → on a conflict, read again and recompute.

So a TAK dispatcher never overwrites a newer change made in CrowdCAD: the action is simply
re-applied on top of it (e.g. "assign Team 2" after someone else assigned Team 1 → both).
A CrowdCAD dispatcher can still overwrite the bridge's change in the instant between their own
read and write, the same window two CrowdCAD dispatchers already share.

Without the hook (a CrowdCAD the bridge didn't install), it falls back to read-then-PATCH and
says so in the log once. Ended events are refused like CrowdCAD refuses them.
"""

from .dispatch import DispatchError
from .pocketbase import PocketBaseError

RETRIES = 4


class EventStore:
    def __init__(self, pb, log=print):
        self.pb = pb
        self.log = log
        self._hook = None

    def hook(self):
        if self._hook is None:
            self._hook = self.pb.hook_available()
            if not self._hook:
                self.log("dispatch: no compare-and-swap hook on this PocketBase; using read-then-write "
                         "(install CrowdCAD with install.sh --with-crowdcad for safe concurrent dispatch)")
        return self._hook

    def apply(self, event_id, action):
        """action(event_record) → patch dict, or (patch, extra). Returns (patch, extra)."""
        self.pb.ensure_auth()
        for _ in range(RETRIES):
            try:
                event = self.pb.get_record("events", event_id)
            except PocketBaseError as error:
                raise DispatchError(f"event not found: {event_id}", 404) from error
            if event.get("ended"):
                raise DispatchError("this event has ended", 409)
            result = action(event)
            patch, extra = result if isinstance(result, tuple) else (result, None)
            if not patch:
                return patch, extra       # CrowdCAD already says so: nothing to write
            if not self.hook():
                self.pb.update_event(event_id, patch)
                return patch, extra
            expect = {key: event.get(key) for key in patch}
            try:
                self.pb.apply_cas(event_id, patch, expect)
                return patch, extra
            except PocketBaseError as error:
                if error.status == 409 and "ended" in str(error):
                    raise DispatchError("this event has ended", 409) from error
                if error.status == 409:
                    continue          # someone changed it since we read it: recompute on top
                if error.status == 403:
                    raise DispatchError("The bridge's CrowdCAD account can't dispatch this event: make it an org "
                                        "event in CrowdCAD or share it with the bridge account.", 403) from error
                raise
        raise DispatchError("the event kept changing while applying this; try again", 409)
