#!/bin/bash
# crowdcad_update_job.sh — the job behind the console's "Install update" buttons (tracker R49).
#
# Started by the root helper (crowdcad_admin.py, action "update") as the transient systemd unit
# crowdcad-update, never as a child of the console: the installer it runs restarts the console,
# and a CloudTAK rebuild takes 5–15 min. Output goes to <HOME>/console/update.log; the page shows
# the latest "==> " line and the log, and "==> EXIT <code>" (always last) ends the job.
#
# Every update brings the whole suite to GitHub main, because the bridge, the console page and
# the plugins are one release:
#   1. back up the bridge's settings and certificates (and CrowdCAD's data for a CrowdCAD update)
#   2. put the source checkout on main (fetch, check out, fast-forward; refuses local changes)
#   3. re-run install.sh --no-pull with this server's options, which the helper passes in
#      (board domain, --webtak if installed, --no-crowdcad if CrowdCAD runs elsewhere), plus
#      cloudtak: --cloudtak <dir>   (rebuilds CloudTAK)
#      crowdcad: --crowdcad-ref <the release main's crowdcad_app.py supports>
#   4. check the bridge answers
#
# Usage (only via the helper):  bash crowdcad_update_job.sh COMPONENT [install.sh options...]

set -uo pipefail

COMPONENT="${1:?component}"; shift
CROWDCAD_HOME="${CROWDCAD_HOME:-/opt/crowdcad-tak}"
[ -n "${HOME:-}" ] || export HOME=/root          # systemd-run gives an empty HOME (git and CloudTAK need one)
SRC="${CROWDCAD_SRC:-$CROWDCAD_HOME/src}"
BACKUPS="$CROWDCAD_HOME/backups"

finish() { echo "==> EXIT $1"; exit "$1"; }
fail() { echo "==> ERROR $*"; finish 1; }

echo "==> Update started $(date -u +%Y-%m-%dT%H:%M:%SZ): $COMPONENT"
[ -d "$SRC/.git" ] || fail "$SRC isn't a git checkout — update with the install command instead"

echo "==> Backing up settings and certificates"
mkdir -p "$BACKUPS"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
parts=()
want=(data certs)
[ "$COMPONENT" = "crowdcad" ] && want+=(crowdcad/pb_data crowdcad/app.json crowdcad/credentials.json)
for p in "${want[@]}"; do [ -e "$CROWDCAD_HOME/$p" ] && parts+=("$p"); done
[ "${#parts[@]}" -gt 0 ] || fail "nothing to back up in $CROWDCAD_HOME — is CrowdCAD for TAK installed?"
tar czf "$BACKUPS/update-$stamp.tgz" -C "$CROWDCAD_HOME" "${parts[@]}" 2>/dev/null \
    || fail "backup failed — nothing changed"
chmod 600 "$BACKUPS/update-$stamp.tgz"
echo "    $BACKUPS/update-$stamp.tgz"

echo "==> Getting main from GitHub"
git -C "$SRC" fetch --quiet origin main || fail "couldn't reach GitHub (git fetch origin main)"
if [ -n "$(git -C "$SRC" status --porcelain --untracked-files=no)" ]; then
    fail "$SRC has local changes — move them aside (git stash) and try again; nothing changed"
fi
git -C "$SRC" checkout --quiet main 2>/dev/null || git -C "$SRC" checkout --quiet -b main origin/main \
    || fail "couldn't switch $SRC to main"
git -C "$SRC" merge --quiet --ff-only origin/main || fail "main can't fast-forward to GitHub's main"
echo "    now at $(git -C "$SRC" log -1 --format='%h %s') (version $(tr -d '[:space:]' < "$SRC/VERSION"))"

args=("$@")
if [ "$COMPONENT" = "crowdcad" ]; then
    ref="$(python3 -I -c 'import re,sys;print(re.search(r"^DEFAULT_REF = \"([^\"]+)\"", open(sys.argv[1]).read(), re.M).group(1))' \
        "$SRC/infratak/crowdcad_app.py" 2>/dev/null)" || fail "couldn't read the supported CrowdCAD release"
    echo "    CrowdCAD release supported on main: $ref"
    args+=(--crowdcad-ref "$ref")
fi

echo "==> Installing (install.sh --no-pull ${args[*]})"
bash "$SRC/install.sh" --no-pull "${args[@]}"
rc=$?
[ "$rc" -eq 0 ] || fail "install.sh failed (exit $rc) — see the lines above; the backup is $BACKUPS/update-$stamp.tgz"

echo "==> Checking the bridge"
listen="$(python3 -I -c 'import json,sys;print(json.load(open(sys.argv[1])).get("status_listen") or "127.0.0.1:8782")' \
    "$CROWDCAD_HOME/data/config.json" 2>/dev/null || echo 127.0.0.1:8782)"
for _ in $(seq 1 20); do
    if version="$(curl -sf --max-time 3 "http://$listen/status" | python3 -I -c 'import json,sys;print(json.load(sys.stdin).get("version",""))' 2>/dev/null)" \
            && [ -n "$version" ]; then
        echo "==> Done: bridge $version is running"
        finish 0
    fi
    sleep 3
done
fail "the bridge didn't answer on $listen after the update — journalctl -u crowdcad-tak -n 50"
