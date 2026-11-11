# CLAUDE.md — CrowdCAD for TAK (plugin suite)

Facts an agent needs that the code can't show. Workspace-wide rules: `../CLAUDE.md`.

## Shape
- One bridge (`bridge/`, Python) + infra-TAK integration (`infratak/`) + three clients:
  ATAK (`atak/`, reads CoT), CloudTAK and WebTAK (`cloudtak/`, `webtak/`, read the board API).
- The repo folder was meant to be renamed `TAK-PluginSuite-CrowdCAD` (Aleph's convention); the
  rename was blocked by a file lock on 2026-11-09. Docs already use the new name.

## Contracts (change together)
- **Wire format is IU Event CAD's**, owned by
  `../TAK-PluginSuite-IndianaUniversity/ATAK5.6-Eventcad/docs/COT_FORMAT.md`. Follow it; never
  change `__iucad_*` names/values here first. After any CoT change, run
  `python bridge/tests/make_atak_fixture.py` so the ATAK tests check the new output.
- **docs/API.md** is the board contract: `bridge/tests/test_api.py`, `cloudtak/plugin/lib/types.ts`
  and `webtak/test/board.test.mjs` (which renders a board the Python bridge just built) all pin it.
- **CrowdCAD's data shape** comes from its `docs/ICD.md` + `src/app/types.ts` (v1.6.0, checked
  2026-11-09). Status lists in `mapping.py` are transcribed from CrowdCAD source (named in comments).
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
- WebTAK: `node --test webtak/test/`. CloudTAK: `CLOUDTAK_DIR=… node cloudtak/check-in-cloudtak.mjs`
  (needs a CloudTAK checkout with npm deps installed — not on this machine as of 2026-11-09).

## Versioning
- Root `VERSION` only (bridge, APK via build.gradle, WebTAK via build.py). `cloudtak/plugin/package.json`
  and `webtak/plugin/plugin.json` "version" must match. PATCH bumps per build unless Jon asks.
- `board.API_VERSION` / clients' `SUPPORTED_API` change only on a breaking API change.

## Never run without Jon asking
- `infratak/install.sh` / `uninstall.sh` on a real host (makes TAK certs, changes groups, edits
  Caddy), `cloudtak/install.sh` against a live CloudTAK (rebuilds it), `webtak/install.sh` on a
  live TAK Server.
- `crowdcad-tak serve` against a live CrowdCAD + TAK Server during a real event.
- Anything that pushes or tags.

## Gotchas
- `GROUPS` is a bash builtin array; install.sh uses `TAK_GROUPS`. No apostrophes inside
  `${VAR:?message}` in scripts (bash parses them as quotes).
- makeCert.sh client keys are encrypted with cert-metadata.sh's PASS (usually `${CAPASS}`).
- webtak/build.py concatenates modules and drops import lines: no `import { x as y }` in webtak/plugin.
- Fixture people and patients are invented; keep it that way (no real mission data).
