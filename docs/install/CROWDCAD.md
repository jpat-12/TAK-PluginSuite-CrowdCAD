# Install: CrowdCAD (the dispatch board)

**Release 1.0.0.** [CrowdCAD](https://github.com/evanqua/crowdcad) (Berkeley MRC, AGPL-3.0) is
the dispatch board this suite reads. The suite never modifies it. Back to the
[install index](README.md).

The bridge needs CrowdCAD on its **PocketBase** backend. The Firebase backend has no API the
bridge can follow. The bridge's mapping is checked against CrowdCAD **v1.6.0**
(`docs/ICD.md` + `src/app/types.ts` of that release).

Pick one:

- **[Option A](#option-a-you-already-run-crowdcad):** you already run CrowdCAD on PocketBase.
- **[Option B](#option-b-the-bridge-installer-runs-crowdcad-for-you):** let `infratak/install.sh --with-crowdcad` build and run it on the infra-TAK host.

---

## Option A: you already run CrowdCAD

1. **Find the PocketBase URL.** It is whatever CrowdCAD's `NEXT_PUBLIC_POCKETBASE_URL` points at,
   e.g. `https://pb.crowdcad.example.org` or `http://10.0.0.5:8090`. This is **not** the Next.js
   site's address unless both are served from one origin. The bridge host must reach it.
2. **Create a CrowdCAD user for the bridge**, e.g. `tak-bridge@example.org`. Reading needs no
   special role: CrowdCAD's PocketBase rules let any signed-in user read every event.
   For CloudTAK dispatch on events not created from CloudTAK, share the event with this account
   or make it an org event, or native dispatch can't save.
3. **Build the venue by GeoJSON import.** CrowdCAD stores posts as percent-of-image positions;
   only a GeoJSON-imported layer has real coordinates. A plain-image venue works only if you
   type map bounds for each layer on the console page (`layer_bounds` in `config.json`).
   Otherwise calls and teams land in *Not on the map* and nothing reaches TAK.
4. **If a proxy sits in front of PocketBase**, let it pass Server-Sent Events unbuffered
   (`/api/realtime`). Otherwise the bridge falls back to polling about every 30 s and the
   console banner says *polling — realtime unavailable*.

Then install the bridge ([BRIDGE.md](BRIDGE.md)) and enter on the console page:

| Console field | Value |
|---|---|
| CrowdCAD PocketBase URL | the URL from step 1 |
| CrowdCAD app URL | the site dispatchers sign in to (turns on the **Dispatch** button in the web clients) |
| Bridge account / password | the user from step 2 |

Or seed the URL at install with `--crowdcad-url <PocketBase URL>`.

---

## Option B: the bridge installer runs CrowdCAD for you

Needs Docker with Compose v2 and git on the infra-TAK host, and a DNS record
`crowdcad.<fqdn>` → the host.

```bash
sudo bash TAK-PluginSuite-CrowdCAD/infratak/install.sh --tak-group <TAK group> --with-crowdcad
```

What it does (`infratak/crowdcad_app.py`, see its docstring):

- Clones upstream CrowdCAD at `--crowdcad-ref` (default `v1.6.0`) into
  `/opt/crowdcad-tak/crowdcad/src` and builds it with Docker. The first build takes several
  minutes; re-runs skip an unchanged ref (`--crowdcad-rebuild` forces it).
- Runs the web app on `127.0.0.1:3100` and PocketBase on `127.0.0.1:8090` (loopback only), and
  Caddy publishes both at `https://crowdcad.<fqdn>` (`--crowdcad-domain` to change it).
- Adds a PocketBase hook (`infratak/pb_hooks/`) giving the bridge a compare-and-swap route for
  TAK dispatch. CrowdCAD itself never calls it.
- Creates a PocketBase superuser, the first CrowdCAD admin (`--crowdcad-admin <email>`, default
  `admin@<crowdcad host>`) and the bridge account, and points the bridge at
  `http://127.0.0.1:8090`. **No console step is needed.**
- **Closes public sign-up**, because any signed-in CrowdCAD user can read every event's calls.
  `--crowdcad-signup open` restores CrowdCAD's default (not recommended on an internet-facing host).

After install:

| Task | How |
|---|---|
| Sign-in details | `sudo cat /opt/crowdcad-tak/crowdcad/credentials.json` (root only, 0600): `admin` is the CrowdCAD login, `superuser` is PocketBase's admin UI at `https://crowdcad.<fqdn>/_/` |
| Add a person | `sudo python3 /opt/crowdcad-tak/bin/crowdcad_app.py add-user <email> [--admin]` (prints a one-time password) |
| Status | `sudo python3 /opt/crowdcad-tak/bin/crowdcad_app.py status` |
| Back up | `/opt/crowdcad-tak/crowdcad/pb_data/` holds every venue, event and call. Use PocketBase admin → Settings → Backups, or copy the folder with the stack stopped |

Re-running the installer never changes a password or touches `pb_data/`.

### Upgrading CrowdCAD

Before you change `--crowdcad-ref`: the CloudTAK native dispatch is a port of CrowdCAD v1.6.0's
own handlers (`bridge/crowdcad_tak/dispatch.py`). Diff those handlers against the new release and
update `dispatch.py` and its tests first, or TAK dispatch writes records the new CrowdCAD doesn't
expect. Never upgrade a live system without this check.

### Removing

```bash
sudo bash /opt/crowdcad-tak/bin/uninstall.sh --crowdcad            # stop CrowdCAD, keep its data
sudo bash /opt/crowdcad-tak/bin/uninstall.sh --crowdcad --purge    # ALSO deletes every event and call
```

Without `--crowdcad`, uninstalling the bridge leaves CrowdCAD running with its data and its
Caddy site. Back up `pb_data/` before any `--purge`.

---

## Verify

From the bridge host:

```bash
crowdcad-tak check      # ✓ CrowdCAD: signed in …
```

With Option B, also run checks C1–C6 in [docs/VERIFY.md](../VERIFY.md#crowdcad-on-the-same-host---with-crowdcad)
(sign-up refused, ports 3100/8090 refused from outside, re-run is a no-op).
