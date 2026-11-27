# Install: the CloudTAK plugin (`cloudtak/`)

**Release 1.0.0.** CrowdCAD Dispatch for CloudTAK: the dispatcher's board, incident view, unit
radar, **+ New** call, assign, unit status and **+ Add** units, all run by the bridge with
CrowdCAD's own dispatch handlers. Back to the [install index](README.md).

Install the [bridge](BRIDGE.md) first: the plugin needs its public board URL and tokens.

> **The install rebuilds CloudTAK's API container (5–15 minutes).** CloudTAK is unavailable while
> it rebuilds. Never run it against a live CloudTAK during an event.

---

## How it is wired

The plugin has two halves, and both are copied into the CloudTAK checkout:

| Half | Source | Lands in (CloudTAK 13.1xx+) | Lands in (older layout) |
|---|---|---|---|
| Web (Vue, runs in the browser) | `cloudtak/plugin/` | `app/plugins/crowdcad/` | `api/web/plugins/crowdcad/` |
| Server route (relays to the bridge) | `cloudtak/server/plugin-crowdcad.ts` | `api/stateless/routes/plugin-crowdcad.ts` | `api/routes/plugin-crowdcad.ts` |

The browser only talks to CloudTAK. The server half calls the bridge at
`https://crowdcad-tak.<fqdn>` with the tokens, so **no token ever reaches the browser** and
nothing is typed into the plugin. It reads three keys from `<CloudTAK>/api/.env` (a JSON file
CloudTAK loads at start and git ignores):

| Key | Value | Effect if missing |
|---|---|---|
| `CROWDCAD_TAK_URL` | `https://crowdcad-tak.<fqdn>` (the bridge's `public_url`) | Plugin can't reach the bridge |
| `CROWDCAD_TAK_TOKEN` | the bridge's `board_token` | Plugin can't read the board |
| `CROWDCAD_TAK_MANAGE_TOKEN` | the bridge's `manage_token` | No New event / End event; board and Dispatch still work |

CloudTAK's `WEB_PLUGINS` mechanism isn't used because it can't carry a server route and nests
the web entry one level too deep for Vite's `plugins/*/index.ts` glob. Editing only `api/.env`
means infra-TAK's CloudTAK updates (`git pull --autostash`) leave the settings alone.

---

## Install from the infra-TAK console (recommended, tracker R41)

infra-TAK console → **CrowdCAD** → **Install CloudTAK plugin**. Leave *CloudTAK directory* blank to
use the running CloudTAK, or give its path (e.g. `/root/CloudTAK`). A progress bar then follows the
job step by step:

| Step | What happens |
|---|---|
| Backup | The installed plugin and server route are saved to `/opt/crowdcad-tak/backups/cloudtak-crowdcad-<time>.tgz` |
| Copy | The new plugin, server route and settings (`api/.env`) go in |
| Rebuild | `docker compose build --no-cache api`, 5–15 min. The bar follows the build's own steps |
| Restart | `docker compose up -d --force-recreate api`. CloudTAK is unreachable for about 30 s (502s) |
| Health check | Waits for CloudTAK's API to answer again (up to 3 min) |

The job runs as the transient systemd unit `crowdcad-cloudtak-install`, so it keeps going if the
console restarts. Only one runs at a time, and its full log is in
`/opt/crowdcad-tak/data/cloudtak-install.log`. When it says **Done**, in each browser: CloudTAK →
**Settings → Refresh App**. The button stays disabled until the bridge's board is published (the
server install did that).

## Install with the bridge installer

On the infra-TAK host that also runs CloudTAK:

```bash
sudo bash TAK-PluginSuite-CrowdCAD/infratak/install.sh --tak-group <TAK group> --cloudtak
```

It finds CloudTAK from the running `cloudtak-api-1` container (else `~/CloudTAK`; or pass
`--cloudtak /path/to/CloudTAK`), passes the URL and both tokens from the bridge's
`secrets.json`, and rebuilds.

## Install by hand

Needs bash, python3 and Docker Compose on the CloudTAK host, and a copy of this repo there.

```bash
sudo cat /opt/crowdcad-tak/data/secrets.json     # on the bridge host: board_token, manage_token
```

```bash
CROWDCAD_TAK_URL=https://crowdcad-tak.tak.example.org \
CROWDCAD_TAK_TOKEN='<board token>' \
CROWDCAD_TAK_MANAGE_TOKEN='<manage token>' \
  bash cloudtak/install.sh /path/to/CloudTAK
```

- Omit the path to use the running `cloudtak-api-1` container's compose directory, else `~/CloudTAK`.
- `--no-build` copies files and writes `api/.env` without rebuilding (rebuild later with
  `docker compose build --no-cache api && docker compose up -d --force-recreate api` in the
  CloudTAK directory).
- The rebuild also runs CloudTAK's lint and type-check on the plugin, so a broken plugin fails
  the build instead of shipping. To check before touching a deploy, on a CloudTAK checkout with
  `npm install` done: `CLOUDTAK_DIR=/path/to/CloudTAK node cloudtak/check-in-cloudtak.mjs`.

## After the install

1. In the browser: CloudTAK → **Settings → Refresh App**. A browser hard refresh is not enough.
2. **Import the iconset once** so calls draw with the CrowdCAD priority icons: CloudTAK →
   Iconsets → import `atak/app/src/main/assets/iconsets/CrowdCAD.zip` from this repo. Until then
   calls show CloudTAK's default marker.
3. The CloudTAK users who dispatch must share a TAK group with the bridge's certificate
   ([BRIDGE.md › TAK groups](BRIDGE.md#tak-groups)), or units carried by phones never show a
   position.

---

## Verify

1. Menu → **CrowdCAD Dispatch**: the header says **Bridge OK** and the board loads.
2. **Units → + Add** a unit carried by a test phone's TAK contact: within about 3 minutes its row
   shows a position. If it stays *not heard yet*, fix TAK groups.
3. **+ New** call with a map click: the row is red; in CrowdCAD the call's location is
   "lat, lon" and its notes end with a `[TAK] …` line.
4. **Assign** the unit, set **On Scene**, then **Close**: the marker leaves CloudTAK and ATAK at once.

Full list: [docs/VERIFY.md › CloudTAK dispatcher](../VERIFY.md#cloudtak-dispatcher-crowdcad-dispatch).

| You see | Fix |
|---|---|
| No CrowdCAD in the menu | Settings → **Refresh App**; check the rebuild finished (`docker compose ps` in the CloudTAK dir) |
| *speaks API vN; this plugin needs vM* | Plugin and bridge from different checkouts → re-run with `--cloudtak` from the bridge's checkout |
| Bridge errors in the header | `CROWDCAD_TAK_URL` / tokens in `api/.env` wrong or stale (tokens rotated) → re-run the installer |
| No New event / End event | `CROWDCAD_TAK_MANAGE_TOKEN` not set |
| Native dispatch refuses to save | The bridge's CrowdCAD account can't update that event → share it with the bridge account or make it an org event |
| Calls are plain dots | Iconset not imported (step 2 above) |

## Remove

```bash
bash cloudtak/install.sh --remove /path/to/CloudTAK          # or: uninstall.sh --cloudtak
```

Removes both halves and the three `api/.env` keys, then rebuilds CloudTAK.
