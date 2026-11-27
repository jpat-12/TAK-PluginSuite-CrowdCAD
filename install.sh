#!/bin/bash
# install.sh — the one command for an infra-TAK host: CrowdCAD + the bridge, working (tracker R41).
#
# First install (as root on the infra-TAK host; the repo is private, so git asks for a GitHub
# login or uses your token/SSH key):
#
#   sudo git clone -b dev https://github.com/jpat-12/TAK-PluginSuite-CrowdCAD.git /opt/crowdcad-tak/src \
#     && sudo bash /opt/crowdcad-tak/src/install.sh --tak-group ALL
#
# Update later: the same install.sh again (it pulls first):  sudo bash /opt/crowdcad-tak/src/install.sh
#
# What it does: brings the checkout up to date (git pull --ff-only, when it is a clean git
# checkout), then runs infratak/install.sh with --with-crowdcad, so one run gives you CrowdCAD
# itself (Docker, at crowdcad.<fqdn>), the bridge service, its TAK certificate and group, the
# Caddy routes and the infra-TAK console page. It is a thin wrapper: every infratak/install.sh
# option passes straight through (see `infratak/install.sh --help`), and re-running is safe —
# that installer is idempotent and keeps certificates, settings and CrowdCAD's data.
#
# The CloudTAK plugin is installed afterwards from the console (CrowdCAD page → "Install CloudTAK
# plugin", with a progress bar) or here with --cloudtak.
#
# Options of its own (everything else goes to infratak/install.sh):
#   --no-crowdcad      bridge only: you already run CrowdCAD elsewhere (pair with --crowdcad-url)
#   --no-pull          don't update the checkout first
#   --ref REF          check out this branch or tag first (e.g. dev, main, v1.0.0)
#
# If you give --crowdcad-url without --no-crowdcad, the bridge uses that CrowdCAD and none is
# built here (an existing CrowdCAD always wins over building a second one).
# CROWDCAD_BOOTSTRAP_DRY_RUN=1 prints the infratak/install.sh command instead of running it.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGINAL_ARGS=("$@")
WITH_APP=1; DO_PULL=1; REF=""; PASS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --no-crowdcad)   WITH_APP=0 ;;
        --no-pull)       DO_PULL=0 ;;
        --ref)           shift; REF="${1:?--ref needs a branch or tag}" ;;
        --with-crowdcad) WITH_APP=1 ;;                        # the default; accepted for clarity
        --crowdcad-url)  PASS+=("$1" "${2:?--crowdcad-url needs a URL}"); WITH_APP=0; shift ;;
        -h|--help)       sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
        *)               PASS+=("$1") ;;
    esac
    shift
done
[ "$WITH_APP" -eq 1 ] && PASS=(--with-crowdcad "${PASS[@]}")

if [ "${CROWDCAD_BOOTSTRAP_DRY_RUN:-0}" = "1" ]; then
    printf 'infratak/install.sh'; for a in "${PASS[@]}"; do printf ' %q' "$a"; done; echo
    exit 0
fi
[ "$(id -u)" -eq 0 ] || { echo "ERROR: run as root: sudo bash $0 ${ORIGINAL_ARGS[*]}" >&2; exit 1; }

# --- update the checkout, then re-run the (possibly new) copy of this script ---------------------
if [ -z "${CROWDCAD_BOOTSTRAP_UPDATED:-}" ] && [ -d "$HERE/.git" ] && command -v git >/dev/null 2>&1; then
    before="$(git -C "$HERE" rev-parse HEAD)"
    if [ -n "$REF" ]; then
        git -C "$HERE" fetch --quiet origin "$REF" && git -C "$HERE" checkout --quiet "$REF" \
            || { echo "ERROR: couldn't check out $REF" >&2; exit 1; }
    fi
    if [ "$DO_PULL" -eq 1 ] && git -C "$HERE" symbolic-ref -q HEAD >/dev/null; then
        if [ -n "$(git -C "$HERE" status --porcelain --untracked-files=no)" ]; then
            echo "    ⚠ $HERE has local changes — not pulling (pass --no-pull to silence this)" >&2
        else
            git -C "$HERE" pull --quiet --ff-only || echo "    ⚠ git pull failed — installing what's checked out" >&2
        fi
    fi
    if [ "$(git -C "$HERE" rev-parse HEAD)" != "$before" ]; then
        echo "==> Updated to $(git -C "$HERE" log -1 --format='%h %s')"
        CROWDCAD_BOOTSTRAP_UPDATED=1 exec bash "$HERE/install.sh" "${ORIGINAL_ARGS[@]}"
    fi
fi

exec bash "$HERE/infratak/install.sh" "${PASS[@]}"
