# CrowdCAD for ATAK

**An ATAK 5.6 plugin that shows a CrowdCAD event's live medical calls and team status on the
map and in a panel, alerts a medic when dispatch assigns their team, and puts the medic's own
status on their position report.** It is the field client of the CrowdCAD for TAK suite
(github.com/jpat-12/TAK-PluginSuite-CrowdCAD). A bridge service turns
[CrowdCAD](https://github.com/evanqua/crowdcad) dispatch data into CoT. This plugin only reads
CoT that ATAK already receives from its TAK Server.

**Key idea:** the plugin has no network surface of its own. It requests no INTERNET permission,
opens no sockets and needs no settings. Everything arrives as CoT in IU Event CAD's
`__iucad_incident` / `__iucad_unit` format, specified in [docs/COT_FORMAT.md](docs/COT_FORMAT.md).
Devices without the plugin still see the same markers as plain CoT.

## Build

Needs JDK 17 and the ATAK CIV 5.6.0 SDK.

```bash
cp local.properties.example local.properties   # edit the paths; never commit it
./gradlew assembleCivRelease testCivDebugUnitTest
```

On the TAK.gov pipeline, set `takrepo.url`, `takrepo.user` and `takrepo.password`. takdev 3.+
then comes from artifactory and supplies the ATAK API, so no local SDK path is needed.
`VERSION` sets the plugin version: the APK's versionName is `<VERSION>+atak5.6`, and the
versionCode is derived from it.

## Files

```
VERSION                          plugin version (copied in from the suite repo root)
build.gradle, settings.gradle    Gradle root; rootProject "CrowdCadTAK" → -repackageclasses atakplugin.CrowdCadTAK
gradle/wrapper/                  Gradle 8.13 wrapper (jar tracked so the pipeline can bootstrap)
.takdev/aars/takdevlint.aar      takdev's lint rules
local.properties.example         machine-local SDK paths template (Windows + macOS)
docs/COT_FORMAT.md               the CoT the plugin reads (from the suite's docs/)
docs/SUBMISSION.md               TAK.gov submission sheet: permissions, data, test status
app/build.gradle                 civ/mil/gov flavors, version scheme, signing, proguard wiring
app/proguard-gradle*.txt         stock template rules + keep for com.atakmap.android.crowdcad.**
app/src/main/
  AndroidManifest.xml            VIBRATE only; plugin-api meta-data; app.component discovery
  assets/plugin.xml              IPlugin entry → plugin.CrowdCadLifecycle
  java/com/atakmap/android/crowdcad/
    plugin/CrowdCadLifecycle     IPlugin lifecycle; registers the map component and toolbar tool
    plugin/CrowdCadTool          toolbar button that opens the panel
    CrowdCadMapComponent         wires the CoT handlers, board, panel and assignment alert (vibrate + toast)
    CrowdCadDropDown             panel: my-status buttons, open incidents (P1 first), units
    IncidentHandler, UnitHandler CoT detail handlers: __iucad_incident / __iucad_unit → Board
    StatusReporter               adds this device's status to its own PLI (via AtakBroadcast)
    cot/                         pure parsers for the two CoT details (+ Attrs helpers)
    model/                       Board (canonical in-memory state), Incident, Unit, status enums
app/src/test/                    9 JVM tests; bridge-demo.cot is real bridge output (invented people)
```
