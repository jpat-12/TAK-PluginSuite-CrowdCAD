#!/bin/bash
# crowdcad_cloudtak_job.sh — the job behind the console's "Install CloudTAK plugin" button (tracker R41).
#
# The console (crowdcad_infratak.py) starts this as a transient systemd unit
# (crowdcad-cloudtak-install), not as a child of the console: a CloudTAK rebuild takes 5–15 min
# and must survive the console being restarted or updated meanwhile. Everything it prints goes
# to $CROWDCAD_HOME/data/cloudtak-install.log, which the console's status endpoint reads to
# draw the progress bar. The "==> " lines are the progress markers it looks for — keep them in
# step with _PROGRESS_STEPS in crowdcad_infratak.py:
#
#   ==> CloudTAK <ver> at <dir>       (cloudtak/install.sh: found CloudTAK)
#   ==> Backed up … / ==> Nothing to back up
#   ==> Installed web half …          (plugin, server route and settings copied)
#   ==> Rebuilding …                  (docker compose build; BuildKit "[ k/n]" lines = sub-progress)
#   ==> Restarting …
#   ==> Done …
#   ==> Healthy / ==> ERROR …         (this script's own health check)
#   ==> EXIT <code>                   (always last)
#
# Tokens are read here from the bridge's data files, never passed on a command line (process
# arguments and unit properties are visible to anyone who can list processes).
#
# Usage (normally only via the console):  bash crowdcad_cloudtak_job.sh [CLOUDTAK_DIR]

set -uo pipefail

CROWDCAD_HOME="${CROWDCAD_HOME:-/opt/crowdcad-tak}"
DATA="$CROWDCAD_HOME/data"
SRC="${CROWDCAD_SRC:-$CROWDCAD_HOME/src}"
HEALTH_URL="${CLOUDTAK_HEALTH_URL:-http://127.0.0.1:5000/api/server}"
HEALTH_WAIT="${CLOUDTAK_HEALTH_WAIT:-180}"     # seconds the API gets to come back after the restart
BACKUPS="$CROWDCAD_HOME/backups"

finish() { echo "==> EXIT $1"; exit "$1"; }

echo "==> Job started $(date -u +%Y-%m-%dT%H:%M:%SZ) (CrowdCAD for TAK $(tr -d '[:space:]' < "$SRC/VERSION" 2>/dev/null || echo '?'))"
[ -f "$SRC/cloudtak/install.sh" ] || { echo "==> ERROR no $SRC/cloudtak/install.sh — re-run the server install"; finish 1; }

read_key() {   # read_key FILE KEY → value, or nothing
    python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get(sys.argv[2], "") or "")
except Exception: pass' "$1" "$2"
}
CROWDCAD_TAK_URL="$(read_key "$DATA/config.json" public_url)"
CROWDCAD_TAK_TOKEN="$(read_key "$DATA/secrets.json" board_token)"
CROWDCAD_TAK_MANAGE_TOKEN="$(read_key "$DATA/secrets.json" manage_token)"
if [ -z "$CROWDCAD_TAK_URL" ] || [ -z "$CROWDCAD_TAK_TOKEN" ]; then
    echo "==> ERROR the board isn't published yet (no public URL or board token) — run the server install first"
    finish 1
fi
export CROWDCAD_TAK_URL CROWDCAD_TAK_TOKEN CROWDCAD_TAK_MANAGE_TOKEN

mkdir -p "$BACKUPS"
bash "$SRC/cloudtak/install.sh" --backup "$BACKUPS" "$@"
rc=$?
[ "$rc" -eq 0 ] || { echo "==> ERROR cloudtak/install.sh failed (exit $rc) — see the lines above"; finish "$rc"; }

# Healthy = the API answers HTTP at all (401 without a login is the normal answer).
for _ in $(seq 1 "$((HEALTH_WAIT / 3))"); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$HEALTH_URL" 2>/dev/null || true)"
    case "$code" in
        2??|3??|401|403) echo "==> Healthy: CloudTAK API answered $code at $HEALTH_URL"; finish 0 ;;
    esac
    sleep 3
done
echo "==> ERROR CloudTAK didn't answer at $HEALTH_URL within ${HEALTH_WAIT}s — docker logs cloudtak-api-1"
finish 1
