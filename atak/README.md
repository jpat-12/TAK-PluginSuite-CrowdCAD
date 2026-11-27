# CrowdCAD for ATAK

**An ATAK 5.6 plugin that shows a CrowdCAD event's live medical calls and team status on the
map and in a panel, alerts a medic when dispatch assigns their team, and lets the medic
acknowledge the call.** Medics can't change status; dispatch does that in CrowdCAD. It is the field client of the CrowdCAD for TAK suite
(github.com/jpat-12/TAK-PluginSuite-CrowdCAD). A bridge service turns
[CrowdCAD](https://github.com/evanqua/crowdcad) dispatch data into CoT. This plugin only reads
CoT that ATAK already receives from its TAK Server.

**Key idea:** the plugin has no network surface of its own. It requests no INTERNET permission,
opens no sockets and needs no settings. Everything arrives as CoT in IU Event CAD's
`__iucad_incident` / `__iucad_unit` format, specified in [docs/COT_FORMAT.md](docs/COT_FORMAT.md).
Devices without the plugin still see the same markers as plain CoT, with ATAK's default incident
icon. Only plugin devices get the priority-coloured EMS icon.

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
    IconsetInstaller             on load: imports assets/iconsets/CrowdCAD.zip into ATAK (skips if that version is in); error → dialog with Retry
    IncidentStyler               incident markers → EMS Star-of-Life icon tinted by priority (re-applied after every import)
    CrowdCadDropDown             panel: my assignment (read-only), open incidents (P1 first, Acknowledge on mine), units
    IncidentHandler, UnitHandler CoT detail handlers: __iucad_incident / __iucad_unit → Board
    AckReporter                  Acknowledge → <__crowdcad_ack incident at> on this device's PLI; acked ids in prefs
    cot/                         pure parsers for the two CoT details (+ Attrs helpers)
    model/                       Board (canonical in-memory state), Incident, Unit, status enums,
                                 Assignment (is a call mine: device uid, or unlinked team matching my callsign),
                                 Priority (P1 red #E03131, P2 orange #F76707, P3 yellow #FCC419)
  assets/iconsets/CrowdCAD.zip   EMS iconset built by the suite's iconset/build_iconset.py; uid and file names are API
  res/drawable-nodpi/cc_incident_ems.png  the PNG embedded in the suite's
                                 iconset/svgs/incdnt-comand-white-solid-genric-ems-plain_2026_11_25.svg (white disc;
                                 MULTIPLY-tinted at runtime, so ring and star stay dark)
  res/raw/alert_*.wav            assignment alert sounds (soft pulses default, hi-lo by dispatcher);
                                 made by tools/make_alert_sounds.py, never by hand
tools/make_alert_sounds.py       regenerates the alert WAVs (--all DIR: all seven candidates)
app/src/test/                    16 JVM tests; bridge-demo.cot is real bridge output (invented people)
```
