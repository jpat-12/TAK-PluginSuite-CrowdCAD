# Install: the ATAK plugin (`atak/`)

**Release 1.0.0.** The CrowdCAD ATAK plugin gives medics a CrowdCAD panel, priority-coloured call
icons, the assignment alert and an **Acknowledge** button. Back to the [install index](README.md).

It needs **no settings and no network permission**. It reads the CoT the device already gets
from its TAK Server, so the only setup is: the right APK for the ATAK version, loaded in ATAK,
on a device in the same TAK group as the bridge. Devices without the plugin still see every
call, team and zone as plain CoT markers.

Plugin package: `com.atakmap.android.crowdcad.plugin` (CIV flavor). File list and build
internals: [atak/README.md](../../atak/README.md).

---

## 1. Get an APK

APKs are not committed. **One APK per ATAK version**: ATAK refuses a plugin built for another
version (the version is in the manifest). Check the device: ATAK → Settings → About.

### Build it (Windows shown; macOS paths in the example file)

Needs JDK 17 (Android Studio's bundled `jbr` works), the Android SDK, and the ATAK-CIV SDK from
tak.gov matching your devices (5.6.0 or 5.7.0.x).

```bash
cd atak
cp local.properties.example local.properties   # edit the paths, forward slashes only; never commit it
JAVA_HOME="C:/Program Files/Android/Android Studio/jbr" ./gradlew assembleCivDebug testCivDebugUnitTest
```

On Linux, `gradlew` isn't executable in git: run `bash ./gradlew …`.

**For ATAK 5.7** from the same tree, either point the three SDK paths in `local.properties` at
the 5.7 SDK and add `atak.version=5.7.0`, or keep `local.properties` on 5.6 and override on the
command line (`-P` wins):

```bash
S="C:/Users/<you>/Desktop/ATAK Development/ATAK-CIV-5.7.0.x-SDK"
JAVA_HOME="C:/Program Files/Android/Android Studio/jbr" ./gradlew -Patak.version=5.7.0 \
  "-Patak.sdk.path=$S" "-Psdk.path=$S" "-Ptakdev.plugin=$S/atak-gradle-takdev.jar" \
  assembleCivDebug testCivDebugUnitTest
```

Output: `atak/app/build/outputs/apk/civ/debug/ATAK-Plugin-CrowdCAD-1.0.0-ATAK-<5.6|5.7>-civ-debug.apk`
(`assembleCivRelease` → `…/civ/release/…-civ-release.apk`, minified).

Both are signed with the ATAK SDK's **development** key, so they load only on ATAK builds that
accept dev-signed plugins (developer / SDK builds). Devices running Play Store or TAK.gov-signed
ATAK need a **TAK.gov-signed** release: package with `python atak/package-submission.py`
(`--atak 5.7` for 5.7) and submit it to the TAK.gov third-party pipeline. Form answers:
[atak/docs/SUBMISSION.md](../../atak/docs/SUBMISSION.md). A release build always alerts: the
debug-only "Mute assignment alert" switch does not exist in it.

---

## 2. Install over adb

Enable **Developer options → USB debugging** (or Wireless debugging) on the device, connect it,
and confirm it shows up:

```bash
adb devices
```

**Force-stop ATAK before installing.** Re-installing a plugin while ATAK is running resets its
load flag, and the next launch says the plugin "will NOT load".

```bash
adb shell am force-stop com.atakmap.app.civ
adb install -r atak/app/build/outputs/apk/civ/debug/ATAK-Plugin-CrowdCAD-1.0.0-ATAK-5.7-civ-debug.apk
```

- Add `-t` (`adb install -r -t …`) if adb refuses with only "Performing Streamed Install": that
  is a test-only APK (e.g. from Gradle intermediates).
- With several devices attached, pick one: `adb -s <serial> install -r …`.
- Without adb: copy the APK to the device and open it with a file manager (allow installs from
  that app), or push it with your MDM.

---

## 3. Load it in ATAK

Open ATAK → **Settings → Tool Preferences → Plugins** (or the **Plugins** tool), find
**CrowdCAD** and tap **Load**. A CrowdCAD button appears in the toolbar. On first load the plugin
imports its iconset (`CrowdCAD.zip`); if that fails it shows a dialog with **Retry**.

### If it won't load

ATAK loads a plugin at start only when two preferences allow it. Both live in
`/data/data/com.atakmap.app.civ/shared_prefs/com.atakmap.app.civ_preferences.xml`:

| Preference | Must be | Symptom when wrong |
|---|---|---|
| `shouldLoad-com.atakmap.android.crowdcad.plugin` | `true` | "CrowdCAD will NOT load" at start. Usually caused by `adb install -r` while ATAK ran |
| `atakPluginScanningOnStartup` | `true` | **No** plugin loads at start, even with `shouldLoad` true |

The normal fix is in the UI: Plugins → **Load**, and enable plugin scanning on startup in the
plugin settings. On a debuggable ATAK (developer builds) you can set them over adb instead.
Force-stop ATAK first, then:

```bash
adb shell am force-stop com.atakmap.app.civ
adb shell run-as com.atakmap.app.civ cat shared_prefs/com.atakmap.app.civ_preferences.xml | grep -E 'shouldLoad-com.atakmap.android.crowdcad|atakPluginScanningOnStartup'
# edit with run-as … sed -i, or add the line if missing:
#   <boolean name="shouldLoad-com.atakmap.android.crowdcad.plugin" value="true" />
adb shell am start -n com.atakmap.app.civ/com.atakmap.app.ATAKActivityCiv
```

On a non-debuggable ATAK `run-as` is refused: use the UI. On Git Bash for Windows, prefix
commands that contain `/data/…` paths with `MSYS_NO_PATHCONV=1`.

---

## 4. Connect it to the rest of the suite

The plugin itself has nothing to configure. Three things outside it decide whether it works:

1. **TAK group.** The device's TAK user must share a group with the bridge's certificate
   ([BRIDGE.md › TAK groups](BRIDGE.md#tak-groups)). Otherwise the panel stays empty.
2. **Device UID ↔ team.** For the assignment alert, the bridge must know which team this phone
   carries. Either:
   - add `Team 1 = ANDROID-<device id>` under *Teams carried by their own ATAK device* on the
     infra-TAK console page (`team_uids` in `config.json`); TAK Server's admin UI lists each
     connected client's UID;
   - add the unit from CloudTAK's **Units → + Add** "carried by a TAK contact"; or
   - let the phone link itself: its first **Acknowledge** links it when its ATAK callsign matches
     the unit name (`Team 1` ↔ `TEAM1`; `claim_by_callsign`, on by default).
3. **Not alongside IU Event CAD.** Don't install both on one device: both put your status on your
   position report. They do read each other's markers (same wire format).

The plugin's **Acknowledge** is sent on the device's own position report (`<__crowdcad_ack>`)
through TAK Server to the bridge, which adds one line to the call's CrowdCAD log. Medics can't
change status; dispatch does that in CrowdCAD or CloudTAK.

---

## Verify

1. Toolbar → **CrowdCAD** opens the panel: *Assigned to you* or *No call assigned to you*, then
   open incidents (P1 first) and units. Tap a card → the map centres on it.
2. Assign the device's team in CrowdCAD → the phone vibrates, toasts and opens the call.
3. Tap **Acknowledge** → "Acknowledged 0m ago"; the call's CrowdCAD log gets
   "Team 1 acknowledged the call. (via ATAK: <callsign>)" within seconds.

Full device checks: [docs/VERIFY.md › Clients](../VERIFY.md#clients) steps 11–13.

| You see | Fix |
|---|---|
| "will NOT load" at start | `shouldLoad-…` reset by `install -r` while ATAK ran → Load again, force-stop before the next install |
| No plugins load at all | `atakPluginScanningOnStartup` is false |
| Install fails: version / signature | Wrong ATAK version APK, or a dev-signed APK on a release ATAK → build for the right version, or use the TAK.gov-signed build |
| Panel says *No open incidents* while CrowdCAD has calls | Device not in the bridge's TAK group, or every call is *Not on the map* (see the console page) |
| No assignment alert | The team isn't linked to this device UID (step 4.2) |

## Remove

ATAK → Plugins → **Unload**, then:

```bash
adb uninstall com.atakmap.android.crowdcad.plugin
```
