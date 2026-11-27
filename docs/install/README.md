# Install guides: CrowdCAD for TAK

**Release 1.0.0.** Install every component from the same checkout (see *Versions must match*).

One guide per component, plus this page on how they connect. They are reference guides for
installing each piece on its own or by hand. For the guided, operator-facing walkthrough (one
infra-TAK host, start to finish, with a pre-event checklist) use
[guides/SETUP_GUIDE.md](../../guides/SETUP_GUIDE.md). For the release smoke test use
[docs/VERIFY.md](../VERIFY.md).

| Guide | Component | Runs on |
|---|---|---|
| [CROWDCAD.md](CROWDCAD.md) | CrowdCAD itself (PocketBase backend), existing or `--with-crowdcad` | infra-TAK host (Docker) or anywhere reachable |
| [BRIDGE.md](BRIDGE.md) | The bridge service (`bridge/`) and its infra-TAK integration (`infratak/`) | infra-TAK host |
| [ATAK.md](ATAK.md) | The ATAK plugin APK (`atak/`): build, `adb install`, getting it to load | Build PC, then each Android device |
| [CLOUDTAK.md](CLOUDTAK.md) | The CloudTAK plugin, CrowdCAD Dispatch (`cloudtak/`) | The CloudTAK host |
| [WEBTAK.md](WEBTAK.md) | The WebTAK board plugin (`webtak/`) | The TAK Server host (extracted WebTAK) |

All hosts, names and passwords in these guides are placeholders: `tak.example.org` is your
infra-TAK FQDN, `<board token>` means the value from the bridge's `secrets.json`, and so on.
Never paste real tokens or passwords into a doc, ticket or chat.

---

## Install order

1. **CrowdCAD** must exist first, on its **PocketBase** backend (Firebase has no API the bridge
   can follow). Either you already run it, or the bridge installer builds it for you.
2. **Bridge** on the infra-TAK host. It is the only component that talks to CrowdCAD.
3. **ATAK plugin** on devices. Optional: plain ATAK, WinTAK and iTAK already show the markers.
4. **CloudTAK** and/or **WebTAK** plugins, if anyone uses them. Both need the bridge's public
   board URL, so install them after the bridge.

---

## How the pieces connect

```
                        REST + realtime (SSE), signed in as the bridge account
 CrowdCAD (PocketBase) ◀────────────────────────────────────────────┐
   crowdcad.<fqdn>                                                   │
                                                          ┌──────────┴───────────┐
                                                          │  bridge (crowdcad-tak)│
                                                          │  /opt/crowdcad-tak    │
                                                          │  127.0.0.1:8782       │
                                                          └──┬─────────────────┬──┘
              mutual TLS, client cert "crowdcad", port 8089  │                 │  HTTP, loopback
                                                             ▼                 ▼
                                                    TAK Server          Caddy: crowdcad-tak.<fqdn>
                                                     │      ▲            (only /api/v1/* and /healthz)
                         CoT (__iucad_* details)     │      │ PLI with        │            │
                                                     ▼      │ __crowdcad_ack  │ board token│ board token
                                            ATAK / WinTAK / iTAK ──────┘      │ manage token│ (baked in bundle,
                                            (+ CrowdCAD ATAK plugin)          ▼            ▼  CORS-checked)
                                                                   CloudTAK server half   WebTAK plugin
                                                                   (api/.env) → browser   (browser)
```

### Links, credentials and where each lives

| Link | How | Credential | Set in |
|---|---|---|---|
| Bridge → CrowdCAD | PocketBase REST + realtime SSE (falls back to polling every ~30 s) | A CrowdCAD user for the bridge | `config.json`: `crowdcad_url` (the **PocketBase** URL), `crowdcad_identity`; `secrets.json`: `crowdcad_password` |
| Bridge → TAK Server | Mutual TLS CoT stream, default `127.0.0.1:8089` | TAK client cert `crowdcad.pem` / `.key`, TAK's CA `ca.pem`, key passphrase | `config.json`: `tak_host`, `tak_port`, `tak_cert`, `tak_key`, `tak_ca`; `secrets.json`: `tak_key_password` |
| TAK Server → devices | Ordinary CoT, delivered by **TAK group** | The bridge cert must share a group with the devices | `--tak-group` at install, or TAK Portal / LDAP (see [BRIDGE.md](BRIDGE.md#tak-groups)) |
| ATAK plugin → bridge | The medic's **Acknowledge** rides on the device's own PLI as `<__crowdcad_ack>`; the bridge hears it through its TAK link | none of its own (the plugin has no network permission) | Teams ↔ device UIDs: console page or `team_uids` |
| CloudTAK → bridge | CloudTAK's **server half** calls the board API; tokens never reach the browser | `board_token` (read), `manage_token` (dispatch, create/end events) | `<CloudTAK>/api/.env` keys `CROWDCAD_TAK_URL`, `CROWDCAD_TAK_TOKEN`, `CROWDCAD_TAK_MANAGE_TOKEN` |
| WebTAK → bridge | The browser calls `/api/v1/board` directly | `board_token` only, baked into the bundle at install (never the manage token) | Bundle built by `webtak/build.py`; WebTAK's page origin must be in `cors_origins` |
| Console → bridge | infra-TAK console page reads `/status` | loopback only, never proxied | n/a |

### Files on the infra-TAK host

| Path | What |
|---|---|
| `/opt/crowdcad-tak/data/config.json` | Bridge settings (0640). Written by the console page or by hand; read at bridge start. Every key and its default: [`bridge/crowdcad_tak/config.py`](../../bridge/crowdcad_tak/config.py) |
| `/opt/crowdcad-tak/data/secrets.json` | Passwords and tokens (0600): `crowdcad_password`, `tak_key_password`, `board_token`, `manage_token`, `w3w_api_key` |
| `/opt/crowdcad-tak/certs/` | The bridge's TAK client cert, key and TAK's CA |
| `/opt/crowdcad-tak/crowdcad/` | Only with `--with-crowdcad`: CrowdCAD source, `pb_data/` (all CrowdCAD data, back it up), `credentials.json` (0600) |

### Ports

| Port | Bound to | Who |
|---|---|---|
| 8782 | 127.0.0.1 | Bridge: `/status` (console), `/api/v1/*` (Caddy proxies only this) |
| 8089 | TAK Server | TAK's TLS CoT input; the bridge connects as a client |
| 3100, 8090 | 127.0.0.1 | Only with `--with-crowdcad`: CrowdCAD web app and PocketBase; Caddy publishes both at `crowdcad.<fqdn>` |
| 443 | Caddy | `crowdcad-tak.<fqdn>` (board API) and `crowdcad.<fqdn>` (CrowdCAD app) |

### DNS

- `crowdcad-tak.<fqdn>` → the infra-TAK host, needed by the CloudTAK and WebTAK plugins.
- `crowdcad.<fqdn>` → the infra-TAK host, only with `--with-crowdcad`.

### Versions must match

Root [`VERSION`](../../VERSION) is the one version for the bridge, the APK, and the CloudTAK and
WebTAK plugins. The board API is versioned separately (`board.API_VERSION`); a web plugin that
says *"speaks API vN; this plugin needs vM"* means the bridge and the plugin came from different
checkouts. Re-install the plugin from the same checkout as the bridge.

---

## Patient data

Whichever components you install, the PHI boundary is the same: age, sex, notes, call and team
logs and member names never leave CrowdCAD. The chief complaint goes out as the incident type.
See [docs/COT_FORMAT.md](../COT_FORMAT.md) for the rule and the tests that enforce it.
