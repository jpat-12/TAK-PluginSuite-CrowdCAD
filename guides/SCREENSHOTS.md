# Screenshot shot list

Real screenshots to replace the mockups in the guides. They're ordered so you can take them in
one pass, from a fresh install through to a finished call. Save each file into `guides/images/`
under the name given, then update the image link in the guide (the **Replaces / goes in**
column) and run `bash guides/build_pdfs.sh`.

## Before you start

- **Use a practice event with invented data.** Make up the event name, the calls (e.g. *Ankle
  injury*, *Fall*) and the callsigns (MEDIC-1, MEDIC-2, EMS-SUP). Never use real patients or a
  real event.
- **Hide secrets before you save the file.** Blur or crop the board **token** on the console page, the
  CrowdCAD password field, any real domain you don't want public, and device UIDs if you prefer.
  **Never screenshot `credentials.json`.**
- **Set up the same test picture every time:** one GeoJSON-imported venue, three units (Team 1, Team 2,
  Supervisor 1), two devices running ATAK (A = Team 2 and B), plus one call with a free-text location
  so that *Not on the map* has an entry.
- **Size:** browser windows at about 1440 px wide, PNG format. Take phones in landscape so the
  map and the CrowdCAD panel both show.

## Setup Guide

| # | File | What to capture | State needed | Replaces / goes in |
|---|---|---|---|---|
| S1 | `install-output.png` | Terminal: the end of `install.sh --tak-group …` with the ✓ summary | Fresh or re-run install | New, under *What success looks like* (Step 2); can sit next to the text block |
| S2 | `console-waiting.png` | Console → CrowdCAD with the **yellow** *waiting for settings* banner and the empty Settings form | Before Step 3 is filled in | `images/console-settings.svg` (Step 3) |
| S3 | `console-settings-filled.png` | Same form filled in: PocketBase URL, app URL, bridge account, a few `Team N = ANDROID-…` lines. **Blur the password** | Step 3 filled, before saving | Step 3, with the A–D callout table (add the callouts in an editor, or drop the table letters) |
| S4 | `tak-admin-uid.png` | TAK Server admin UI where a connected client's **UID** (`ANDROID-…`) is shown | Device connected | New, Step 3 callout C and Step 6.6. **Also confirms the guide's claim about where to find the UID**; fix the text if it's elsewhere (e.g. an ATAK menu) |
| S5 | `check-preview.png` | Terminal: `crowdcad-tak check` (two ✓) and the first lines of `crowdcad-tak preview` | Bridge connected, event active | New, Step 4 |
| S6 | `console-live.png` | Console page, whole page: **green** banner, status tiles, *Events on the map*, *Not on the map* with one entry, Clients card. **Blur the token** | Event active, one free-text call | `../docs/images/console.svg` (Step 4) |
| S7 | `cloudtak-refresh-app.png` | CloudTAK Settings with **Refresh App** visible | After `--cloudtak` install | New, Step 5 |
| S8 | `webtak-origin-error.png` *(optional)* | WebTAK's *can't reach the bridge* message | Before the origin is added | Troubleshooting |
| S9 | `atak-plugin-load.png` | ATAK Plugins screen with **CrowdCAD** listed and loaded | APK installed | New, Step 6.4 |
| S10 | `atak-toolbar.png` | ATAK toolbar showing the CrowdCAD button | Plugin loaded | New, Step 6.4 |
| S11 | `crowdcad-venue-geojson.png` | CrowdCAD venue screen showing the GeoJSON-imported map with posts | Venue built | New, Step 1.3 |

## User Guide

| # | File | What to capture | State needed | Replaces / goes in |
|---|---|---|---|---|
| U1 | `map-markers.png` | Any TAK map (ATAK without the panel open): a call marker with its label, a team marker and a zone shape | Event active, one call at a post | New, *What you see on the map* |
| U2 | `atak-panel.png` | ATAK **device A** landscape: the map with the CrowdCAD panel open showing My status, open incidents (one with a thick border, meaning assigned to you), and units | Team 2 assigned to a call | `../docs/images/atak.svg` (*Medics: ATAK*) |
| U3 | `atak-alert.png` | Device A at the moment of assignment: the **toast** plus the opened call. Assign from a second screen and be ready to capture | Assign Team 2 in Dispatch | New, *When you're assigned a call* |
| U4 | `atak-status-responding.png` | Device **B**'s panel showing Team 2 as *Responding* after A tapped Respond | After U3 + Respond | New, *Set your status* |
| U5 | `crowdcad-log-via-atak.png` | CrowdCAD's call log entry reading *via ATAK: MEDIC-2* | After U4 | New, *Set your status* (shows that the tap reached CrowdCAD) |
| U6 | `cloudtak-panel.png` | CloudTAK menu → CrowdCAD: the events list with **+ New event**, **Dispatch**, **CrowdCAD ↗** and **End** buttons | Event created from CloudTAK | New, top of *Dispatchers: CloudTAK* |
| U7 | `cloudtak-new-event.png` | The New CrowdCAD event form filled in, with three contacts picked (2 Team, 1 Supervisor) | Before you tap Create | `images/cloudtak-new-event.svg` |
| U8 | `cloudtak-dispatch.png` | The Dispatch pane with the map beside it: New call form, one P1 call with no unit, one call with Team 2 *On Scene*, units list | Two open calls | `images/cloudtak-dispatch.svg` |
| U9 | `cloudtak-post-suggest.png` *(optional)* | The Location field showing post suggestions while you type | Typing in New call | *Create a call*, step 1 |
| U10 | `cloudtak-crowdcad-pane.png` | CrowdCAD's own screen open in the floating pane (**CrowdCAD ↗**) | Signed in to CrowdCAD | *Good to know* |
| U11 | `cloudtak-board.png` | CloudTAK CrowdCAD board (read-only view): open calls, teams, *Not on the map* | Same state as U8 | Left half of `../docs/images/web-clients.svg` |
| U12 | `webtak-board.png` | WebTAK sidebar → CrowdCAD drawer showing the same board | Same state | Right half of `web-clients.svg` (put U11 + U12 side by side, or use two images) |
| U13 | `webtak-dispatch-window.png` | WebTAK's floating CrowdCAD dispatch window | Signed in | *WebTAK dispatchers* |
| U14 | `board-bridge-down.png` | Any web board showing the **warning above the last good board** | `systemctl stop crowdcad-tak` on a **test host only**, then start it again | *Command staff and EOC*, and *When something looks wrong* |
| U15 | `atak-stale.png` *(optional)* | ATAK markers after about 5 minutes with the bridge stopped (grey or gone) | Same as U14 | *When something looks wrong*; also answers the open question in `docs/VERIFY.md` step 9 |
| U16 | `call-closed.png` *(optional)* | Board right after a call is resolved (it's gone) next to CrowdCAD showing it Delivered | Resolve a call | *Game day* |

## Keep as drawings

These are diagrams, not screens, so don't replace them: `images/setup-roadmap.svg`,
`../docs/images/architecture.svg` and `../docs/images/call-lifecycle.svg`.

## While you're there, check these against the real UI

- Where ATAK or TAK Server shows the device UID (S4).
- ATAK status button labels: **AVL / RESP / ON SC / TRAN / OOS**, and **Respond (assigned)**.
- The toast wording, *CrowdCAD: assigned to CC-008 — …*.
- What ATAK does with stale markers: grey, or removed (U15).
- Whether the New event venue list really shows *not on the map* for venues without a GeoJSON map.
