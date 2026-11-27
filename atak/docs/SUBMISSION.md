# TAK.gov Third-Party Pipeline: Submission Sheet

| Field | Value |
|---|---|
| Plugin name | CrowdCAD |
| Package / namespace | `com.atakmap.android.crowdcad.plugin` (civ, mil); gov adds `.gov` |
| Plugin version | see `VERSION`. versionName `<VERSION>+atak<ATAK major.minor>` (e.g. `1.0.0+atak5.8`), versionCode `MAJ*1e6 + MIN*1e4 + PATCH*100 + <ATAK minor>` |
| Target ATAK | one zip per ATAK: 5.6.0 or 5.8.0, set by the `atak.version` default in `app/build.gradle` (`plugin-api` = `com.atakmap.app@<ATAK>.CIV`) |
| Flavors | civ (default), mil, gov |
| Build | `./gradlew assembleCivRelease` (JDK 17, Gradle wrapper 8.13, AGP 8.9.0, takdev 3.+) |
| Unit tests | `./gradlew testCivDebugUnitTest`: 19 JVM tests (parsers, board rules, priority colours, iconset header, real bridge output, release builds always alert) |
| Obfuscation | R8, `-repackageclasses atakplugin.CrowdCadTAK` (generated from `rootProject.name`) |
| Runtime dependencies | none; ATAK supplies the API (compileOnly). Test-only: JUnit 4.13.2, org.json 20240303 |
| Native code | none |
| Source repo | github.com/jpat-12/TAK-PluginSuite-CrowdCAD, `atak/` folder |
| Point of contact | _fill in on the TAK.gov form_ |

## What it does

Live CrowdCAD event-medical calls and team status on ATAK. A separate bridge service, which
runs on the TAK Server side and is not part of this submission, publishes CrowdCAD dispatch data
as CoT in IU Event CAD's `__iucad_incident` / `__iucad_unit` format ([COT_FORMAT.md](COT_FORMAT.md)).
The plugin:

- registers CoT detail handlers for those two elements and keeps an in-memory board;
- shows a panel: my assignment (read-only), open incidents (priority first), units. Tapping a card
  centres the map;
- vibrates, shows a toast and opens the call when an incident is assigned to this device's uid;
  release builds always alert (a tester-only mute exists in debug builds only, R35);
- installs its bundled CrowdCAD iconset (EMS icons) into ATAK's icon library on load. If the
  import fails it shows a dialog with Retry;
- on a call assigned to this device, offers **Acknowledge**: it adds `<__crowdcad_ack incident at>`
  to its own PLI through `CotMapComponent.addAdditionalDetail` and asks for an immediate report.
  The user cannot set or change any status.

## Security and data handling

| Item | Answer |
|---|---|
| Permissions | `VIBRATE` only (assignment alert). **No `INTERNET`**, location or storage permission |
| Network | none of its own: all data comes from ATAK's existing TAK Server connection as CoT |
| Broadcast receivers | registered via ATAK's `DocumentedIntentFilter` / `AtakBroadcast`; no system receivers |
| Persistence | one SharedPreferences key (`crowdcad.acked`: ids of calls this user acknowledged, last 50) so Acknowledge isn't offered again after a restart; on load it copies its bundled iconset to `atak/tools/crowdcad/CrowdCAD-iconset.zip` and imports it with ATAK's own `ADD_ICONSET` broadcast (skipped when that version is already installed) |
| Sensitive data | the bridge strips patient details (age, gender, notes, log) before CoT. Incidents carry a chief-complaint string, a post name and status only |
| Credentials / secrets | none in the plugin or in this source |
| Exported components | only the standard `com.atakmap.app.component` discovery activity |

## Known limits (honest status)

- Not yet run on a fielded device against a live CrowdCAD + TAK Server. Debug and release
  APKs build, and the parsers are tested against real bridge output.
- Don't install it alongside IU Event CAD on the same device: both own the same PLI detail.
- Status set in the plugin is not written back to CrowdCAD yet. Other TAK users see it, but
  CrowdCAD does not.
