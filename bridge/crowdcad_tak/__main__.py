"""crowdcad-tak command line.

    python -m crowdcad_tak serve              run the bridge (what systemd runs)
    python -m crowdcad_tak check              sign in to CrowdCAD and open the TAK TLS link, then exit
    python -m crowdcad_tak preview [FILE]     print the CoT a CrowdCAD event would produce, sending
                                              nothing: FILE is an event record as JSON (e.g. saved
                                              from /api/collections/events/records/<id>); without
                                              FILE, every selected event on the live instance
"""

import json
import os
import signal
import sys
import threading

from . import VERSION, api, config as configuration
from .bridge import Publisher, Runner
from .calldetails import CallDetails
from .fieldstatus import FieldStatus
from .manage import Manager
from .pocketbase import PocketBase, PocketBaseError
from .takclient import TakClient


def _clients(cfg, secrets):
    pb = PocketBase(cfg["crowdcad_url"], cfg["crowdcad_identity"], secrets["crowdcad_password"])
    tak = TakClient(cfg["tak_host"], cfg["tak_port"], cfg["tak_cert"], cfg["tak_key"], cfg["tak_ca"],
                    key_password=secrets.get("tak_key_password"))
    return pb, tak


def serve(cfg, secrets):
    if not cfg["crowdcad_url"] or not cfg["crowdcad_identity"]:
        # Not configured yet (fresh install): stay up so the console shows "needs setup"
        # instead of systemd restart-looping.
        print("[crowdcad-tak] not configured: set CrowdCAD URL and account in infra-TAK → CrowdCAD",
              file=sys.stderr, flush=True)

        api.make_server(cfg["status_listen"], lambda: {"version": VERSION, "configured": False},
                        lambda: None, secrets.get("board_token"), cfg.get("cors_origins"))
        threading.Event().wait()
    pb, tak = _clients(cfg, secrets)
    data_dir = os.environ.get("CROWDCAD_TAK_DATA_DIR", configuration.DATA_DIR)
    # TAK-side call details (floor, description, what3words): one store, read by the Publisher
    # (CoT + board) and written by the manage API (calldetails.py).
    details = CallDetails(os.path.join(data_dir, "call_details.json"))
    runner = Runner(cfg, pb, tak, details=details)
    # Its own PocketBase client (same account): HTTP threads never share the runner's.
    manager = Manager(PocketBase(cfg["crowdcad_url"], cfg["crowdcad_identity"], secrets["crowdcad_password"]),
                      cfg.get("crowdcad_app_url"),
                      log=lambda line: print(f"[crowdcad-tak] {line}", file=sys.stderr, flush=True),
                      timezone=cfg.get("timezone"), layer_bounds=cfg.get("layer_bounds"),
                      details=details, w3w_key=secrets.get("w3w_api_key"))
    try:
        manager.pb.ensure_auth()   # learn the bridge's own user id, for the board's `endable`
    except PocketBaseError as error:
        print(f"[crowdcad-tak] manage API: CrowdCAD sign-in failed for now ({error})", file=sys.stderr, flush=True)
    field = None
    if cfg.get("field_status", True):
        # ATAK Acknowledge taps → a line in the CrowdCAD call log, through the same compare-and-swap
        # store as CloudTAK dispatch. Field users never change status (fieldstatus.py).
        field = FieldStatus(runner.publisher, manager.store, cfg,
                            log=lambda line: print(f"[crowdcad-tak] {line}", file=sys.stderr, flush=True))
        tak.on_message = field.offer
        field.start()
    api.make_server(cfg["status_listen"], runner.status, api.runner_board(runner, manager, field),
                    secrets.get("board_token"), cfg.get("cors_origins"),
                    manager=manager, manage_token=secrets.get("manage_token"))
    signal.signal(signal.SIGTERM, lambda *_: (runner.stop(), sys.exit(0)))
    print(f"[crowdcad-tak] {VERSION}: {cfg['crowdcad_url']} → TAK {cfg['tak_host']}:{cfg['tak_port']}",
          file=sys.stderr, flush=True)
    runner.run()


def check(cfg, secrets):
    ok = True
    pb, tak = _clients(cfg, secrets)
    try:
        events = pb.list_events(cfg.get("events", "active"))
        print(f"✓ CrowdCAD: signed in as {cfg['crowdcad_identity']}; {len(events)} event(s) selected")
        for event in events:
            print(f"    {event.get('id')}  {event.get('name')!r}  {len(event.get('calls') or [])} calls")
    except PocketBaseError as error:
        ok = False
        print(f"✗ CrowdCAD: {error}")
    tak.start()
    if tak.wait_connected(15):
        print(f"✓ TAK Server: TLS link up to {tak.host}:{tak.port}")
    else:
        ok = False
        print(f"✗ TAK Server: {tak.last_error or 'no connection within 15 s'}")
    tak.stop()
    return 0 if ok else 1


def preview(cfg, secrets, path=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # callsigns carry "·"; Windows consoles default to cp1252
        except (AttributeError, ValueError):
            pass
    if path:
        with open(path, encoding="utf-8") as stream:
            records = [json.load(stream)]
    else:
        records = PocketBase(cfg["crowdcad_url"], cfg["crowdcad_identity"],
                             secrets["crowdcad_password"]).list_events(cfg.get("events", "active"))
    publisher = Publisher(cfg, print)
    for record in records:
        publisher.apply(record)
    for event in publisher.status()["events"]:
        for missing in event["unplaced"]:
            print(f"# not on the map ({event['name']}): {missing['kind']} {missing['label']!r} "
                  f"at {missing['location']!r} — not a post on a georeferenced layer", file=sys.stderr)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv.pop(0) if argv else "help"
    cfg, secrets = configuration.load(os.environ.get("CROWDCAD_TAK_DATA_DIR", configuration.DATA_DIR))
    if command == "serve":
        return serve(cfg, secrets)
    if command == "check":
        return check(cfg, secrets)
    if command == "preview":
        return preview(cfg, secrets, argv[0] if argv else None)
    if command == "version":
        print(VERSION)
        return 0
    print(__doc__)
    return 0 if command in ("help", "-h", "--help") else 2


if __name__ == "__main__":
    sys.exit(main())
