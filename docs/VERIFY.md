# Verify — release smoke test

## Automated (dev box)

```bash
cd bridge && python -m unittest discover -s tests            # bridge, API, Caddy, TLS (hook tests skip w/o Flask)
INFRATAK_REPO=../../infra-TAK <python with flask+psutil> -m unittest discover -s tests -p test_infratak_hook.py
cd ../atak && ./gradlew assembleCivDebug assembleCivRelease testCivDebugUnitTest   # JAVA_HOME = Android Studio jbr
cd .. && node --test webtak/test/board.test.mjs
CLOUDTAK_DIR=/path/to/CloudTAK node cloudtak/check-in-cloudtak.mjs   # CloudTAK's own lint + vue-tsc
```

## On an infra-TAK host (not yet run: first time through, write down what differs)

1. `sudo bash infratak/install.sh --tak-group <medical group> --cloudtak --webtak`: ends with ✓,
   no ⚠ about the CA, groups or public URL.
2. Console → **CrowdCAD**: card and sidebar link present; banner says "waiting for settings";
   Clients card shows `https://crowdcad-tak.<fqdn>`.
3. Create a CrowdCAD user for the bridge; enter URL + account on the page → Save. Banner turns
   green: "CrowdCAD live (realtime) · TAK connected".
4. `crowdcad-tak check`: both ✓. `crowdcad-tak preview`: prints CoT for the active event.
   `curl https://crowdcad-tak.<fqdn>/status` → 404 (console-only); `/api/v1/info` → JSON.
5. In CrowdCAD, start an event on a **GeoJSON-imported** venue. Zones appear in ATAK (device in
   the same TAK group) within seconds.
6. Create a call at a post → incident marker at the post, `NEW`, on every client. Assign a team →
   `DISP`; team On Scene → `ONSC`.
7. Create a call with a free-text location → listed under "Not on the map" on the console page
   and in every board; nothing on the map.
8. Resolve the call → gone from boards and (ATAK plugin / IU Event CAD) the map at once; plain
   ATAK within ~90 s. End the event → everything goes the same way.
9. `systemctl stop crowdcad-tak` → markers and board entries go stale within 5 min; note what
   ATAK does with stale markers (grey vs remove) for the README.
10. Run infra-TAK **Update Now**, and redeploy any infra-TAK module (rewrites the Caddyfile) →
    the CrowdCAD page and `crowdcad-tak.<fqdn>` still work.

### CrowdCAD on the same host (`--with-crowdcad`)

C1. `sudo bash infratak/install.sh --tak-group <group> --with-crowdcad`: ends with ✓ and a
    `CrowdCAD: https://crowdcad.<fqdn>` line. `crowdcad_app.py status` says PocketBase up.
C2. `https://crowdcad.<fqdn>` loads; sign in with `admin` from `credentials.json`;
    `https://crowdcad.<fqdn>/_/` is PocketBase's login (superuser).
C3. Sign-up from the app's own screen fails (closed). `crowdcad_app.py add-user x@y` works and
    that account can sign in.
C4. `crowdcad-tak check`: CrowdCAD ✓ against `http://127.0.0.1:8090`, no console step needed.
C5. Re-run C1: no rebuild of an unchanged ref, passwords unchanged, Caddyfile byte-identical.
C6. `curl -sI http://<public IP>:8090` and `:3100` from outside: refused (loopback only).

## Clients

11. **ATAK** (two devices, CrowdCAD APK, same TAK group as the bridge): CrowdCAD toolbar button
    opens the board; open calls listed priority-first; tap a call → map centres on it.
12. Map device A's uid to a team on the console page (`Team 1 = ANDROID-…`), assign that team in
    CrowdCAD → device A vibrates, toasts, opens the call. The panel has **no** status buttons and no
    Respond. Tap **Acknowledge** → it becomes "Acknowledged 0m ago", and the call's CrowdCAD log
    gets "Team 1 acknowledged the call. (via ATAK: <callsign>)" within seconds. Team 1's status in
    CrowdCAD is unchanged.
13. Kill and restart ATAK on A mid-call → the call still shows "Acknowledged" (persisted), and no
    second log line appears.
14. **CloudTAK**: Settings → Refresh App; menu → CrowdCAD shows the same board as ATAK; tap a call
    → map flies to it. Stop the bridge → the panel shows an error but keeps the last board.
15. **WebTAK**: hard-refresh; sidebar tool **CrowdCAD** opens a docked drawer with the board. If
    it says it can't reach the bridge, add WebTAK's exact page origin on the console page
    (WebTAK page origins).

## CloudTAK dispatcher (CrowdCAD Dispatch)

1. CloudTAK → Settings → Refresh App → menu **CrowdCAD Dispatch**: header **Bridge OK**.
2. **Units → + Add** a team carried by a test phone's TAK contact → within ~3 min the row shows a
   position (no *no GPS fix*). If it stays *not heard yet*: TAK groups (README "TAK groups").
3. **+ New** call with a map click → the call row is **red**; in CrowdCAD its location is "lat, lon"
   and its notes end with the `[TAK] …` line.
4. Open it → **Assign** the test unit → the phone vibrates (ATAK plugin); a dashed line joins unit and call.
5. Unit **On Scene** → row and line turn red/blue; **Close** → the marker leaves CloudTAK and ATAK at once.

