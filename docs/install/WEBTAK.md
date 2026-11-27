# Install: the WebTAK plugin (`webtak/`)

**Release 1.0.0.** A read-only CrowdCAD board for WebTAK users (command staff, medical branch,
EOC): open calls, teams, and anything CrowdCAD couldn't place on the map, refreshed every 5 s.
Its **Dispatch** button opens CrowdCAD's own dispatch screen in a floating window. Markers
reach WebTAK's map as CoT anyway; the plugin adds the board. Back to the [install index](README.md).

Install the [bridge](BRIDGE.md) first: the plugin needs its public board URL and board token.

---

## How it is wired

- WebTAK loads plugins as **one classic script** listed in TAK Server's
  `webtak-manifest.json`. `webtak/build.py` concatenates `webtak/plugin/src/` into
  `crowdcad-board.plugin.js`, with the bridge URL and **board token baked in**. The bundle is
  built at install and **never committed**, because it carries the token.
- It lands in `<webtak>/plugins/crowdcad-board/` (default WebTAK dir
  `/opt/tak/extract/webtak`) and is added to the manifest's `plugins` array as a plain string
  (this WebTAK's validator rejects object entries). The manifest is backed up first
  (`webtak-manifest.json.bak.<time>`), and its owner and permissions are kept.
- The browser calls `https://crowdcad-tak.<fqdn>/api/v1/board` **directly**, so the bridge must
  allow WebTAK's exact page origin (CORS, `cors_origins`). The installer seeds infra-TAK's usual
  WebTAK origins (`https://<fqdn>:8443`, `:8446`, `https://tak.<fqdn>`, `https://takserver.<fqdn>`).
- Only the read-only `board_token` goes in the bundle, never the `manage_token`. Anyone signed in
  to WebTAK can read the bundle; the token unlocks only the patient-data-free board. Rotate it if
  a bundle leaks ([BRIDGE.md › secrets](BRIDGE.md#secretsjson-0600)).

---

## Install with the bridge installer (recommended)

On the infra-TAK host (TAK Server's extracted WebTAK is local):

```bash
sudo bash TAK-PluginSuite-CrowdCAD/infratak/install.sh --tak-group <TAK group> --webtak
```

Pass `--webtak /path/to/webtak` if WebTAK isn't in `/opt/tak/extract/webtak`.

## Install by hand

Needs python3 on the TAK Server host and a copy of this repo there.

```bash
sudo cat /opt/crowdcad-tak/data/secrets.json     # board_token
```

```bash
sudo CROWDCAD_TAK_URL=https://crowdcad-tak.tak.example.org \
     CROWDCAD_TAK_TOKEN='<board token>' \
     WEBTAK_DIR=/opt/tak/extract/webtak \
     bash webtak/install.sh
```

Then make sure WebTAK's page origin is allowed: infra-TAK console → CrowdCAD → **WebTAK page
origins** (or `cors_origins` in `/opt/crowdcad-tak/data/config.json`, then
`systemctl restart crowdcad-tak`). The origin is scheme + host + port exactly as in the browser's
address bar, e.g. `https://takserver.tak.example.org`.

To build the bundle without installing (e.g. to inspect it): `python3 webtak/build.py --out /tmp/crowdcad-board.plugin.js`
(without `--url` / `--token` the panel asks for both in its Settings, stored per browser).

## After the install

Hard-refresh WebTAK (Ctrl + Shift + R) and open the sidebar tool **CrowdCAD**.

---

## Verify

1. The CrowdCAD drawer opens with the same board as CloudTAK and ATAK.
2. A test call at a post appears within 5 s; resolving it removes it.
3. With the **CrowdCAD app URL** set on the console page, **Dispatch** opens CrowdCAD's dispatch
   screen in a floating window.

Automated contract and bundle tests (dev box, Node ≥ 18, no npm):

```bash
node --test webtak/test/board.test.mjs
```

| You see | Fix |
|---|---|
| *can't reach the bridge* | WebTAK's exact page origin missing from `cors_origins` → add it on the console page |
| *speaks API vN; this plugin needs vM* | Bundle built from another checkout than the bridge → re-run with `--webtak` |
| Grey WebTAK screen after install | The manifest became unreadable or invalid → restore the newest `webtak-manifest.json.bak.*` |
| No **Dispatch** button | *CrowdCAD app URL* empty on the console page |
| Board worked, now 401 | `board_token` rotated → re-run the installer to rebuild the bundle |

## Remove

```bash
sudo WEBTAK_DIR=/opt/tak/extract/webtak bash webtak/install.sh --remove     # or: uninstall.sh --webtak
```

Deletes `plugins/crowdcad-board/` and its manifest entry. Hard-refresh WebTAK afterwards.
