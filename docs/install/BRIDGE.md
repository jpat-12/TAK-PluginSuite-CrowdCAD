# Install: the bridge (`bridge/` + `infratak/`)

**Release 1.0.0.** The bridge is the only component that talks to CrowdCAD. It follows a
CrowdCAD event live and publishes it as CoT through TAK Server and as a token-protected board
API for the web clients. Back to the [install index](README.md).

The guided version of this, with screenshots-to-be and a pre-event checklist, is
[guides/SETUP_GUIDE.md](../../guides/SETUP_GUIDE.md) steps 1–4. This page is the reference:
what the installer does, every setting, and how to install by hand.

> **Never run `install.sh` or `uninstall.sh` against a production host during a live event.**
> It makes TAK certificates, changes TAK groups, edits Caddy and restarts the console.
> Do the first run against a practice CrowdCAD event.

---

## Requirements

| Need | Notes |
|---|---|
| infra-TAK host, Ubuntu 22.04+ | TAK Server installed under `/opt/tak` (the installer uses its `makeCert.sh`, `UserManager.jar` and CA) |
| Python ≥ 3.10 (system `python3`) | Bridge is stdlib-only: no venv, no pip |
| CrowdCAD on PocketBase | [CROWDCAD.md](CROWDCAD.md). Or pass `--with-crowdcad` (needs Docker) |
| The TAK group your devices are in | Case-sensitive, from TAK Server's admin UI or TAK Portal |
| DNS `crowdcad-tak.<fqdn>` → host | Only for the CloudTAK / WebTAK plugins |

---

## Install on infra-TAK (recommended)

**One command (tracker R41)** — CrowdCAD and the bridge together, as root on the infra-TAK host:

```bash
sudo git clone -b dev https://github.com/jpat-12/TAK-PluginSuite-CrowdCAD.git /opt/crowdcad-tak/src   && sudo bash /opt/crowdcad-tak/src/install.sh --tak-group <TAK group>
```

[`install.sh`](../../install.sh) at the repo root updates the checkout (`git pull --ff-only`), then
runs `infratak/install.sh --with-crowdcad` plus whatever you pass. Re-run it to update. Already run
CrowdCAD elsewhere? Add `--crowdcad-url https://…` (or `--no-crowdcad`) and it installs the bridge
only. The steps below are the same install, done one piece at a time.

1. **Get the code onto the host.** The repo is private: use a deploy key or a personal access
   token, or copy the folder with `scp`.

   ```bash
   git clone https://github.com/jpat-12/TAK-PluginSuite-CrowdCAD.git
   ```

2. **Run the installer** with your devices' TAK group:

   ```bash
   sudo bash TAK-PluginSuite-CrowdCAD/infratak/install.sh --tak-group <TAK group>
   ```

   Add `--with-crowdcad` to run CrowdCAD on the same host, and `--cloudtak` / `--webtak` for
   the web clients (or add them later by re-running with those flags).

3. **Connect it to CrowdCAD:** infra-TAK console → **CrowdCAD** → fill in the PocketBase URL,
   CrowdCAD app URL and bridge account → **Save and restart bridge**. Field-by-field:
   [SETUP_GUIDE step 3](../../guides/SETUP_GUIDE.md#step-3-connect-the-bridge-to-crowdcad).
   Skip this with `--with-crowdcad`.

4. **Verify** (below).

### What the installer does

In order (see the header of [`infratak/install.sh`](../../infratak/install.sh)):

1. Checks for Python 3.10+, creates the `crowdcad-tak` system user, copies the bridge to
   `/opt/crowdcad-tak/app`, and writes the `crowdcad-tak` CLI to `/usr/local/bin`.
2. **TAK client certificate:** runs TAK's `makeCert.sh client crowdcad` once (never a second
   time), copies `crowdcad.pem` / `.key` to `/opt/crowdcad-tak/certs/` (0640, group
   `crowdcad-tak`), copies TAK's CA (`/opt/tak/certs/files/ca.pem`, or `--tak-ca`), and puts the
   cert in each `--tak-group` with `UserManager.jar certmod`.
3. **Settings:** seeds `config.json` and `secrets.json` once. It reads the key passphrase from
   TAK's `cert-metadata.sh`, and generates a random `board_token` and `manage_token`. It never
   overwrites values already set.
4. Installs and starts `crowdcad-tak.service` (status on `127.0.0.1:8782`).
5. **Console integration:** an import hook in the infra-TAK console's site-packages adds the
   CrowdCAD page, dashboard card and sidebar link. It never patches `app.py`, because infra-TAK's
   **Update Now** runs `git checkout --force` and would erase the patch. `--console-hook none`
   skips this (then edit `config.json` by hand).
6. **Caddy:** adds the `crowdcad-tak.<fqdn>` site, forwarding only `/api/v1/*` and `/healthz`
   (never `/status`), and seeds `cors_origins` with infra-TAK's usual WebTAK origins.
   `--domain` changes the host; `--no-caddy` skips it (the web clients then can't reach the board).
7. A heal unit (`crowdcad-tak-heal.path`) re-applies the console hook and Caddy blocks after
   infra-TAK updates or Caddyfile rewrites.
8. Optionally `--with-crowdcad`, `--cloudtak`, `--webtak`, passing them the public URL and tokens.

Re-running is safe and is how you upgrade: `git pull` (or `--pull`), then the same command.

---

## Configuration reference

Settings live in `/opt/crowdcad-tak/data/`. The console page writes them; the bridge reads them
only at start, so **restart after a hand edit**: `sudo systemctl restart crowdcad-tak`.
Missing keys take their defaults, so an old file keeps working after an upgrade.
Defaults and comments for every key: [`bridge/crowdcad_tak/config.py`](../../bridge/crowdcad_tak/config.py).

### `config.json` (0640)

| Key | Default | Meaning |
|---|---|---|
| `crowdcad_url` | `""` | CrowdCAD's **PocketBase** base URL |
| `crowdcad_app_url` | `""` | CrowdCAD's web app URL; empty hides the web clients' **Dispatch** button |
| `crowdcad_identity` | `""` | The bridge's CrowdCAD login (email) |
| `events` | `"active"` | Every active event, or a list of event ids |
| `tak_host`, `tak_port` | `127.0.0.1`, `8089` | TAK Server's TLS CoT input |
| `tak_cert`, `tak_key`, `tak_ca` | `/opt/crowdcad-tak/certs/crowdcad.pem`, `.key`, `ca.pem` | The bridge's TAK client identity and TAK's CA |
| `publish` | calls, teams, zones on | What goes to TAK (`posts`, `clinic_walkups` off by default) |
| `team_uids` | `{}` | CrowdCAD team name → ATAK device UID, e.g. `{"Team 1": "ANDROID-<device id>"}`. Makes the assignment alert fire on that phone |
| `layer_bounds` | `{}` | Layer id → `{north, south, east, west}`, for venues not built by GeoJSON import |
| `field_status` | `true` | Accept ATAK **Acknowledge** taps as a line in the call's CrowdCAD log |
| `claim_by_callsign` | `true` | An unlinked phone links to the unit whose name matches its callsign on its first tap |
| `cors_origins` | `[]` | Browser origins allowed to call `/api/v1/board` (WebTAK's page origin) |
| `timezone` | `""` | IANA zone for log-line time prefixes; empty = host zone |
| `id_prefix`, `id_prefixes` | `"CC"`, `{}` | Incident ids `CC-007`; per-event override |
| `heartbeat_seconds`, `stale_seconds` | `30`, `300` | Re-send interval and CoT stale, so a dead bridge's markers age off |
| `icon_base` | `""` | Empty = CrowdCAD iconset paths; or a URL folder for icon-by-URL clients |
| `status_listen` | `127.0.0.1:8782` | The bridge's one HTTP listener |
| `public_url` | `""` | Written by the Caddy step; shown on the console and used by client installers |

### `secrets.json` (0600)

| Key | Meaning |
|---|---|
| `crowdcad_password` | Password of `crowdcad_identity` |
| `tak_key_password` | Passphrase of `crowdcad.key` (TAK's `makeCert.sh` uses the CA passphrase from `cert-metadata.sh`) |
| `board_token` | Bearer token for `/api/v1/board`. Shared by the CloudTAK relay and the WebTAK bundle. Empty disables the board |
| `manage_token` | Bearer token for `/api/v1/manage/*` (dispatch, create/end events). CloudTAK's server half only, never WebTAK |
| `w3w_api_key` | Optional what3words key for the CloudTAK dispatcher. Hand-edit only; stays on the bridge |

**Rotating a token:** change it here, restart the bridge, then re-run the installer with
`--cloudtak` / `--webtak` so the plugins get the new value.

---

## TAK groups

The bridge's certificate must share a TAK group with the devices (and CloudTAK users), or the
phones never get calls and alerts and the bridge never hears their positions or Acknowledge
taps. Symptom: units on the dispatcher board stay *not heard yet*.

- **File-based groups:** `--tak-group <group>` (repeatable) does it with `UserManager.jar`.
- **TAK Portal / LDAP groups** (`<auth default="ldap" x509groups="true">`): groups come from the
  directory, so `--tak-group` has no effect. Create a TAK Portal **Global** integration for the
  bridge (no streaming data feed, the devices' groups) and upload its `.p12` (or `.pem` + `.key`),
  its password and the truststore on the console's **CrowdCAD → TAK certificate** card: it checks
  them, installs them, points the bridge at them and restarts it (tracker R43). By hand instead:
  download its cert and key, copy them to
  `/opt/crowdcad-tak/certs/` (owner `root:crowdcad-tak`, mode 0640), set `tak_cert` / `tak_key`
  in `config.json` and the key's passphrase in `tak_key_password`, and restart. If the
  integration is brand new, TAK may cache "no groups" for the first connection: restart once
  more after a minute. Detail: [SETUP_GUIDE](../../guides/SETUP_GUIDE.md#tak-groups-the-bridge-must-share-a-group-with-the-phones).

---

## Install by hand (no infra-TAK)

For a plain TAK Server host, or to try the bridge elsewhere. You provide what the installer
would: a TAK client cert in the right group, the CA, and the settings files.

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin crowdcad-tak
sudo mkdir -p /opt/crowdcad-tak/{app,data,certs}
sudo cp -r bridge/crowdcad_tak /opt/crowdcad-tak/app/
# certs: crowdcad.pem, crowdcad.key, ca.pem → /opt/crowdcad-tak/certs (root:crowdcad-tak, 0640)
```

`/opt/crowdcad-tak/data/config.json` (minimal):

```json
{
  "crowdcad_url": "https://pocketbase.example.org",
  "crowdcad_identity": "tak-bridge@example.org",
  "tak_host": "tak.example.org",
  "tak_port": 8089
}
```

`/opt/crowdcad-tak/data/secrets.json` (mode 0600, owner `crowdcad-tak`):

```json
{
  "crowdcad_password": "<bridge account password>",
  "tak_key_password": "<client key passphrase>",
  "board_token": "<random string>",
  "manage_token": "<a different random string>"
}
```

Generate each token with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`.

Run it with the unit in [`infratak/systemd/crowdcad-tak.service`](../../infratak/systemd/crowdcad-tak.service),
or directly:

```bash
sudo -u crowdcad-tak env CROWDCAD_TAK_DATA_DIR=/opt/crowdcad-tak/data PYTHONPATH=/opt/crowdcad-tak/app \
  python3 -m crowdcad_tak serve
```

To expose the board API, put a reverse proxy in front of `127.0.0.1:8782` that forwards only
`/api/v1/*` and `/healthz`. Never publish `/status`.

### Try it with no servers at all

`preview` with a file prints the CoT an event record would produce and sends nothing:

```bash
cd bridge && python -m crowdcad_tak preview tests/fixtures/event_demo_stadium.json
python -m unittest discover -s tests
```

---

## Verify

```bash
crowdcad-tak check      # ✓ CrowdCAD: signed in …   ✓ TAK Server: TLS link up …
crowdcad-tak preview    # prints the CoT for the active event; sends nothing
crowdcad-tak version
systemctl status crowdcad-tak
journalctl -u crowdcad-tak -f                       # lines start with [crowdcad-tak]
curl -s 127.0.0.1:8782/status                       # status JSON (loopback only)
curl -s https://crowdcad-tak.<fqdn>/api/v1/info     # public: JSON
curl -s -o /dev/null -w '%{http_code}\n' https://crowdcad-tak.<fqdn>/status   # must be 404
```

The console banner should read **CrowdCAD live (realtime) · TAK connected**, and the
**Not on the map** list should be empty before an event. Troubleshooting table:
[SETUP_GUIDE](../../guides/SETUP_GUIDE.md#troubleshooting).

---

## Remove

```bash
sudo bash /opt/crowdcad-tak/bin/uninstall.sh            # keep settings + certs
sudo bash /opt/crowdcad-tak/bin/uninstall.sh --purge    # delete /opt/crowdcad-tak (not CrowdCAD's data)
```

Add `--cloudtak` / `--webtak` to remove those plugins, `--crowdcad` to stop CrowdCAD
([CROWDCAD.md](CROWDCAD.md#removing)). The `crowdcad` cert stays in TAK Server's
`/opt/tak/certs/files`; revoke it there if the bridge is gone for good.
