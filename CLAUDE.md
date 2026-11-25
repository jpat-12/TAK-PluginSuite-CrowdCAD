# CLAUDE.md — CrowdCAD for TAK (plugin suite)

Facts an agent needs that the code can't show. Workspace-wide rules: `../CLAUDE.md`.

## Shape
- One bridge (`bridge/`, Python) + infra-TAK integration (`infratak/`) + three clients:
  ATAK (`atak/`, reads CoT), CloudTAK and WebTAK (`cloudtak/`, `webtak/`, read the board API).
- Repo: github.com/jpat-12/TAK-PluginSuite-CrowdCAD (private); folder renamed to match 2026-11-19.

## Contracts (change together)
- **Wire format is IU Event CAD's**, owned by
  `../TAK-PluginSuite-IndianaUniversity/ATAK5.6-Eventcad/docs/COT_FORMAT.md`. Follow it; never
  change `__iucad_*` names/values here first. After any CoT change, run
  `python bridge/tests/make_atak_fixture.py` so the ATAK tests check the new output.
- **docs/API.md** is the board contract: `bridge/tests/test_api.py`, `cloudtak/plugin/lib/types.ts`
  and `webtak/test/board.test.mjs` (which renders a board the Python bridge just built) all pin it.
- **CrowdCAD's data shape** comes from its `docs/ICD.md` + `src/app/types.ts` (v1.6.0, checked
  2026-11-09). Status lists in `mapping.py` are transcribed from CrowdCAD source (named in comments).
- **Notes are write-only from TAK** (`bridge/crowdcad_tak/calldetails.py`): the bridge writes one
  `[TAK] …` line into a call's notes and NEVER reads notes to send anywhere. Board/CoT read TAK details
  from the bridge's own store (`data_dir/call_details.json`). A map point goes into CrowdCAD's own
  `location` as "lat, lon", and mapping.py places any call whose location parses that way.
- **Use CrowdCAD's words** in every client: Calls, Teams, Supervisors, Add Call, Add Team, Add Supervisor,
  Chief Complaint, Source, Mark as Priority, and CrowdCAD's own status text (board `crowdcadStatus`).
  Check CrowdCAD's source (components/modals/event/*, dispatch/page.tsx) before naming a new control.
- **PHI boundary is `mapping.build`.** Never add a Call/Staff field to `Item.fields`/`Item.meta`
  without updating the PHI tests (bridge, board, ATAK fixture). age/gender/notes/log/members never go out.

## infra-TAK rules (same as Aleph)
- Never patch infra-TAK's `app.py` by default: "Update Now" (`git checkout --force`) erases it.
- The boot finder must delegate to later meta-path finders, not PathFinder directly, or it
  bypasses Aleph's hook (`test_every_version_gets_the_integration` checks both attach).
- `infratak/lib.sh` and `crowdcad_caddy.py` mirror Aleph's; keep them in step.

## Commands
- Bridge: `cd bridge && python -m unittest discover -s tests` (hook tests skip without Flask).
- Hook × real infra-TAK: `INFRATAK_REPO=../../infra-TAK <python with flask+psutil> -m unittest discover -s tests -p test_infratak_hook.py`
- ATAK: `cd atak && JAVA_HOME="C:/Program Files/Android/Android Studio/jbr" ./gradlew assembleCivDebug testCivDebugUnitTest`
  (and `assembleCivRelease`; it needs `bundle.storeArchive.enable=false`, already set).
  ATAK 5.7 from the same tree: add `-Patak.version=5.7.0` and `-Patak.sdk.path/-Psdk.path/-Ptakdev.plugin`
  pointing at the 5.7 SDK (README "Build & test"). `-P` beats local.properties, which stays on 5.6.
  No kotlinx-serialization pin needed (no deps beyond JUnit); add one only if a dep pulls kotlinx in.
  `gradlew` isn't executable in git on Linux: run `bash ./gradlew`.
- TAK.gov pipeline zip: `python atak/package-submission.py`. The pipeline gets only the `atak/` Gradle project, so
  build.gradle prefers `atak/VERSION` (the packager's copy, gitignored) over `../VERSION`, and release signing falls
  back to `${buildDir}/android_keystore` (takdev's) when there is no `atak.sdk.path`. Verify by unzipping outside the
  repo and building there. Keep `atak/docs/SUBMISSION.md` (permissions/data answers) true when the manifest changes.
- CloudTAK incident icon: `python cloudtak/make_incident_icon.py` after changing the ATAK drawable
  `cc_incident_ems.png` (one icon, both clients; don't hand-edit `incident-icon-data.ts`).
- WebTAK: `node --test webtak/test/board.test.mjs` (Node 22 no longer takes a directory). CloudTAK: `CLOUDTAK_DIR=… node cloudtak/check-in-cloudtak.mjs`
  (needs a CloudTAK checkout with npm deps installed — not on this machine as of 2026-11-09).

## Versioning
- Root `VERSION` only (bridge, APK via build.gradle, WebTAK via build.py). `cloudtak/plugin/package.json`
  and `webtak/plugin/plugin.json` "version" must match. PATCH bumps per build unless Jon asks.
- `board.API_VERSION` / clients' `SUPPORTED_API` change only on a breaking API change.

## Never run without Jon asking
- `infratak/install.sh` / `uninstall.sh` on a real host (makes TAK certs, changes groups, edits
  Caddy; `--with-crowdcad` builds and runs CrowdCAD in Docker; `uninstall.sh --crowdcad --purge`
  deletes every CrowdCAD event and call), `cloudtak/install.sh` against a live CloudTAK (rebuilds it), `webtak/install.sh` on a
  live TAK Server.
- `crowdcad-tak serve` against a live CrowdCAD + TAK Server during a real event.
- Anything that pushes or tags.

## Gotchas
- `GROUPS` is a bash builtin array; install.sh uses `TAK_GROUPS`. No apostrophes inside
  `${VAR:?message}` in scripts (bash parses them as quotes).
- makeCert.sh client keys are encrypted with cert-metadata.sh's PASS (usually `${CAPASS}`).
- webtak/build.py concatenates modules and drops import lines: no `import { x as y }` in webtak/plugin.
- Fixture people and patients are invented; keep it that way (no real mission data).
- `crowdcad_caddy.py` manages two blocks (board, CrowdCAD app). Re-applying must be byte-identical
  or the heal path unit re-triggers itself: strip both, write both back in one fixed order.
- **Native dispatch is a port of CrowdCAD v1.6.0's handlers** (`bridge/crowdcad_tak/dispatch.py`,
  sources named in its docstring). On ANY CrowdCAD upgrade (`--crowdcad-ref`), diff those handlers
  first and update dispatch.py + tests/test_dispatch.py, or TAK dispatch writes records CrowdCAD
  no longer expects. Live hook test: `CROWDCAD_LIVE_PB_IMAGE=crowdcad-pocketbase:<ref>
  CROWDCAD_SRC=/opt/crowdcad-tak/crowdcad/src python -m unittest discover -s tests -p test_pb_hook_live.py`.
- PocketBase JS hooks run each handler in an isolated VM: helpers must live inside the handler.
- CrowdCAD's PocketBase rules let any signed-in user read every event; `--with-crowdcad` closes
  sign-up for that reason. `setup-pocketbase.js` re-opens it on every run, so install re-closes it after.
