"""Settings (config.json) and secrets (secrets.json, 0600) in the data dir.

Both are written by the infra-TAK console page (/crowdcad) or by hand; the bridge only reads
them, at start. Loading spreads defaults under the file so an old config gains new keys
instead of breaking.
"""

import json
import os

DATA_DIR = os.environ.get("CROWDCAD_TAK_DATA_DIR", "/opt/crowdcad-tak/data")

DEFAULTS = {
    # PocketBase base URL of the CrowdCAD instance, e.g. http://127.0.0.1:8090 or
    # https://crowdcad.example.org (wherever NEXT_PUBLIC_POCKETBASE_URL points).
    "crowdcad_url": "",
    # Public URL of the CrowdCAD web app itself (not PocketBase), e.g. https://crowdcad.example.org.
    # The web clients' Dispatch button opens <this>/events/<id>/dispatch: dispatchers work in
    # CrowdCAD's own screen, signed in as themselves. Empty = no Dispatch button.
    # install.sh --with-crowdcad sets it; otherwise set it on the console page.
    "crowdcad_app_url": "",
    # IANA time zone for the "hhmm - …" prefixes in CrowdCAD logs written by TAK dispatch
    # (CrowdCAD writes browser-local time), e.g. America/Chicago. Empty = the host's zone.
    "timezone": "",
    # Field status: a medic's status taps in the ATAK CrowdCAD plugin update CrowdCAD (fieldstatus.py),
    # for units carried by a device (takUid or team_uids). false = ATAK-only, as before.
    "field_status": True,
    # A tap from a phone no unit is linked to yet links it to the free unit whose name matches its
    # ATAK callsign ("Team 1" ↔ TEAM1), saved as that unit's takUid. false = only picked contacts.
    "claim_by_callsign": True,
    # A CrowdCAD account for the bridge. Read-only use: PocketBase lets any signed-in user
    # list/view every event (ICD §2.3), so it needs no sharing and no admin.
    "crowdcad_identity": "",
    # "active" = every event with status 'active' that hasn't ended; or a list of event ids.
    "events": "active",
    "tak_host": "127.0.0.1",
    "tak_port": 8089,
    "tak_cert": "/opt/crowdcad-tak/certs/crowdcad.pem",
    "tak_key": "/opt/crowdcad-tak/certs/crowdcad.key",
    "tak_ca": "/opt/crowdcad-tak/certs/ca.pem",
    "publish": {"calls": True, "teams": True, "zones": True, "posts": False, "clinic_walkups": False},
    # CrowdCAD team name → that team's ATAK device uid. A mapped team sends no marker of its
    # own (the device's PLI is the truth) and incidents list the device uid in `assigned`,
    # which is what makes the IU plugin alert that phone.
    "team_uids": {},
    # Layer id → {north, south, east, west}, for venue maps that weren't built by GeoJSON
    # import (CrowdCAD only stores geoBounds for those). Without bounds a layer can't be placed.
    "layer_bounds": {},
    # Incident ids are "<prefix>-<call order>", e.g. CC-007. Per-event override in
    # id_prefixes {event_id: prefix} when two events run at once.
    "id_prefix": "CC",
    "id_prefixes": {},
    # Everything live is re-sent this often; stale is set past two misses, so a dead bridge's
    # markers age off TAK instead of lingering as if current.
    "heartbeat_seconds": 120,
    "stale_seconds": 300,
    # One loopback HTTP server: /status for the console, /api/v1/* for the web clients
    # (Caddy publishes only the latter, at crowdcad-tak.<fqdn>).
    "status_listen": "127.0.0.1:8782",
    # https://crowdcad-tak.<fqdn>, written by infratak/crowdcad_caddy.py; shown on the console
    # page and used by the client installers. The bridge itself never reads it.
    "public_url": "",
    # Browser origins allowed to call /api/v1/board directly: the WebTAK plugin's page.
    # (CloudTAK relays server-side and needs no CORS.)
    "cors_origins": [],
}

SECRET_DEFAULTS = {
    "crowdcad_password": "",
    # TAK Server's makeCert.sh encrypts client keys with the CA passphrase (cert-metadata.sh
    # PASS); "atakatak" is TAK Server's stock value.
    "tak_key_password": "atakatak",
    # Bearer token for /api/v1/board, shared by the CloudTAK relay and the WebTAK bundle.
    # Empty = board disabled. install.sh generates one.
    "board_token": "",
    # Bearer token for /api/v1/manage/* (create/end events from TAK). CloudTAK's server half only,
    # never the WebTAK bundle (anyone who loads WebTAK could read it there). Empty = disabled.
    "manage_token": "",
}


def _read(path):
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
            return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}


def load(data_dir=DATA_DIR):
    raw = _read(os.path.join(data_dir, "config.json"))
    config = {**DEFAULTS, **raw}
    config["publish"] = {**DEFAULTS["publish"], **(raw.get("publish") or {})}
    secrets = {**SECRET_DEFAULTS, **_read(os.path.join(data_dir, "secrets.json"))}
    return config, secrets


def save(data_dir, config=None, secrets=None):
    os.makedirs(data_dir, exist_ok=True)
    if config is not None:
        _write(os.path.join(data_dir, "config.json"), config, 0o640)
    if secrets is not None:
        _write(os.path.join(data_dir, "secrets.json"), secrets, 0o600)


def _write(path, value, mode):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
    os.replace(tmp, path)
