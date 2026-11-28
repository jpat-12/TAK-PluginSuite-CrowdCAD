#!/bin/bash
# uninstall.sh — remove CrowdCAD for TAK from this host. Reverses install.sh.
#
# Usage:
#   sudo bash /opt/crowdcad-tak/bin/uninstall.sh            keep settings + certs in /opt/crowdcad-tak
#   sudo bash /opt/crowdcad-tak/bin/uninstall.sh --purge    delete everything, including its TAK cert copy
#   add --cloudtak [DIR] / --webtak [DIR] to also remove those plugins (CloudTAK is rebuilt)
#   add --crowdcad to also stop CrowdCAD (install.sh --with-crowdcad); with --purge that deletes
#   its data (every venue, event and call). Without --crowdcad, CrowdCAD keeps running, its site
#   stays in Caddy, and --purge keeps /opt/crowdcad-tak/crowdcad.
#
# The `crowdcad` cert itself stays in TAK Server's /opt/tak/certs/files (revoke it there if
# the bridge is gone for good). Markers already on devices age off within their stale time.
# Safe to run twice; every step no-ops if already undone.

set -uo pipefail
CROWDCAD_HOME="${CROWDCAD_HOME:-/opt/crowdcad-tak}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"
# shellcheck disable=SC1091
[ -f "$CROWDCAD_HOME/bin/crowdcad.env" ] && source "$CROWDCAD_HOME/bin/crowdcad.env"

PURGE=0; CLOUDTAK=""; WEBTAK=""; CROWDCAD=0
while [ $# -gt 0 ]; do
    case "$1" in
        --purge)    PURGE=1 ;;
        --crowdcad) CROWDCAD=1 ;;
        --cloudtak) if [ -n "${2:-}" ] && [ "${2#--}" = "$2" ]; then CLOUDTAK="$2"; shift; else CLOUDTAK="auto"; fi ;;
        --webtak)   if [ -n "${2:-}" ] && [ "${2#--}" = "$2" ]; then WEBTAK="$2"; shift; else WEBTAK="/opt/tak/extract/webtak"; fi ;;
        *)       echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done
[ "$(id -u)" -eq 0 ] || { echo "ERROR: run as root" >&2; exit 1; }

# Heal first, or it would re-add the hook we remove below.
systemctl disable --now crowdcad-tak-heal.path 2>/dev/null
rm -f /etc/systemd/system/crowdcad-tak-heal.path /etc/systemd/system/crowdcad-tak-heal.service
systemctl disable --now crowdcad-tak-admin.path 2>/dev/null   # console helper (R43)
rm -f /etc/systemd/system/crowdcad-tak-admin.path /etc/systemd/system/crowdcad-tak-admin.service
rm -rf "${CROWDCAD_HOME:-/opt/crowdcad-tak}/console"

[ -f "$CROWDCAD_HOME/bin/crowdcad_caddy.py" ] && python3 "$CROWDCAD_HOME/bin/crowdcad_caddy.py" remove --reload
if [ "$CROWDCAD" -eq 1 ]; then
    [ -f "$CROWDCAD_HOME/bin/crowdcad_caddy.py" ] && python3 "$CROWDCAD_HOME/bin/crowdcad_caddy.py" app-remove --reload
    [ -f "$CROWDCAD_HOME/bin/crowdcad_app.py" ] && python3 "$CROWDCAD_HOME/bin/crowdcad_app.py" --home "$CROWDCAD_HOME" remove \
        $([ "$PURGE" -eq 1 ] && echo --purge)
fi

if [ -n "$CLOUDTAK" ] && [ -f "$CROWDCAD_HOME/src/cloudtak/install.sh" ]; then
    bash "$CROWDCAD_HOME/src/cloudtak/install.sh" --remove $([ "$CLOUDTAK" != "auto" ] && echo "$CLOUDTAK")
fi
if [ -n "$WEBTAK" ] && [ -f "$CROWDCAD_HOME/src/webtak/install.sh" ]; then
    WEBTAK_DIR="$WEBTAK" bash "$CROWDCAD_HOME/src/webtak/install.sh" --remove
fi

if py="$(find_console_python)"; then remove_pth_hook "$py"; fi
CONSOLE_DIR="${CONSOLE_DIR:-$(find_console_dir || true)}"
[ -n "$CONSOLE_DIR" ] && remove_append_hook "$CONSOLE_DIR"

systemctl disable --now crowdcad-tak.service 2>/dev/null
rm -f /etc/systemd/system/crowdcad-tak.service /usr/local/bin/crowdcad-tak
systemctl daemon-reload

if [ "$PURGE" -eq 1 ] && [ -d "$CROWDCAD_HOME/crowdcad" ]; then
    # CrowdCAD (left running without --crowdcad) keeps its folder; everything else goes.
    find "$CROWDCAD_HOME" -mindepth 1 -maxdepth 1 ! -name crowdcad -exec rm -rf {} +
    userdel crowdcad-tak 2>/dev/null
    log "Removed $CROWDCAD_HOME except crowdcad/ (CrowdCAD still runs; add --crowdcad to remove it)."
elif [ "$PURGE" -eq 1 ]; then
    rm -rf "$CROWDCAD_HOME"
    userdel crowdcad-tak 2>/dev/null
    log "Removed $CROWDCAD_HOME."
else
    rm -rf "$CROWDCAD_HOME/app"
    log "Kept $CROWDCAD_HOME/data, certs and src. Use --purge to delete them."
fi
[ -n "$CONSOLE_DIR" ] && restart_console
echo "✓ CrowdCAD for TAK removed."
