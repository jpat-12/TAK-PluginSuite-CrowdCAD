#!/bin/bash
# install.sh — install or update CrowdCAD for TAK on an infra-TAK host: the bridge, and
# optionally the CloudTAK and WebTAK plugins. (The ATAK plugin is an APK; see atak/.)
#
# What it sets up, and why it's shaped this way:
#
#   1. The bridge runs on its own: /opt/crowdcad-tak, its own system user and systemd unit
#      (crowdcad-tak.service, status on 127.0.0.1:8782). Stdlib-only Python, so it runs on the
#      system python3 with no venv. Its board API (/api/v1/*, token-protected) is published
#      at crowdcad-tak.<fqdn> for the web clients, below infra-TAK's Caddy user-blocks marker.
#   2. Its own TAK client certificate, `crowdcad`, made with TAK Server's makeCert.sh — the
#      same least-privilege pattern infra-TAK uses for Node-RED's nodered.pem — and put in the
#      TAK groups given with --tak-group. Without a group, TAK Server puts the bridge in
#      __ANON__ and no device in a real group sees its markers.
#   3. The console integration (dashboard card, sidebar link, /crowdcad status + settings
#      page) is an import hook in the console's site-packages, never an app.py patch: infra-TAK's
#      "Update Now" runs `git checkout --force`, which erases app.py edits.
#
#   4. Optionally (--with-crowdcad), CrowdCAD itself: the unmodified upstream release on its
#      PocketBase backend, built with Docker (infratak/crowdcad_app.py), published at
#      crowdcad.<fqdn>, with the bridge pointed at it and accounts made for it. Public sign-up
#      is closed by default (any CrowdCAD user can read every event's calls).
#
# Usage:
#   sudo bash infratak/install.sh [options]          install, or update in place (idempotent)
#
# Options:
#   --tak-group NAME       TAK group the bridge publishes into (repeatable; default: none, which
#                          means __ANON__ — set this to the group your medics' devices are in)
#   --crowdcad-url URL     seed the CrowdCAD PocketBase URL (else set it on the console page)
#   --tak-ca PATH          CA that signed TAK Server's 8089 cert (default /opt/tak/certs/files/ca.pem)
#   --console-hook MODE    pth (default) | append (guarded block in app.py; re-added after
#                          updates) | none (bridge only; edit /opt/crowdcad-tak/data/config.json by hand)
#   --domain HOST          public host for the board API (default: crowdcad-tak.<infra-TAK fqdn>)
#   --no-caddy             don't touch the Caddyfile (the web clients then can't reach the board)
#   --cloudtak [DIR]       also install the CloudTAK plugin into DIR (default: the running
#                          CloudTAK, else ~/CloudTAK) and rebuild CloudTAK (5–15 min)
#   --webtak [DIR]         also install the WebTAK plugin into DIR (default /opt/tak/extract/webtak)
#   --with-crowdcad        also run CrowdCAD on this host (Docker; first build takes several minutes)
#   --crowdcad-domain HOST its public host (default crowdcad.<infra-TAK fqdn>; a bare label gets the fqdn)
#   --crowdcad-ref TAG     CrowdCAD release to build (default v1.6.0, the one the bridge is checked against)
#   --crowdcad-admin EMAIL first CrowdCAD admin + PocketBase superuser (default admin@<crowdcad host>)
#   --crowdcad-signup MODE closed (default: accounts via crowdcad_app.py add-user) | open (CrowdCAD's default)
#   --crowdcad-rebuild     rebuild CrowdCAD's images even if nothing changed (re-runs skip the build)
#   --no-restart           don't restart the infra-TAK console (hook loads on its next restart)
#   --pull                 git pull the source checkout first (/opt/crowdcad-tak/src)
#
# Re-run any time; it upgrades the bridge and re-applies every integration. It never makes a
# second certificate or overwrites settings already made.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CROWDCAD_HOME="${CROWDCAD_HOME:-/opt/crowdcad-tak}"
TAK_CERTS="${TAK_CERTS:-/opt/tak/certs}"
# shellcheck source=lib.sh
source "$SRC_DIR/infratak/lib.sh"

ORIGINAL_ARGS=("$@")
TAK_GROUPS=(); CROWDCAD_URL=""; TAK_CA=""; HOOK_MODE="pth"; DO_RESTART=1; DO_PULL=0
DOMAIN=""; DO_CADDY=1; CLOUDTAK=""; WEBTAK=""
WITH_CROWDCAD=0; CROWDCAD_DOMAIN=""; CROWDCAD_REF=""; CROWDCAD_ADMIN=""; CROWDCAD_SIGNUP=""; CROWDCAD_REBUILD=0
usage() { sed -n '/^# Usage:/,/^# Re-run/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
    case "$1" in
        --tak-group)    shift; TAK_GROUPS+=("${1:-}") ;;
        --crowdcad-url) shift; CROWDCAD_URL="${1:-}" ;;
        --tak-ca)       shift; TAK_CA="${1:-}" ;;
        --console-hook) shift; HOOK_MODE="${1:-}" ;;
        --domain)       shift; DOMAIN="${1:-}" ;;
        --no-caddy)     DO_CADDY=0 ;;
        --cloudtak)     if [ -n "${2:-}" ] && [ "${2#--}" = "$2" ]; then CLOUDTAK="$2"; shift; else CLOUDTAK="auto"; fi ;;
        --webtak)       if [ -n "${2:-}" ] && [ "${2#--}" = "$2" ]; then WEBTAK="$2"; shift; else WEBTAK="/opt/tak/extract/webtak"; fi ;;
        --with-crowdcad)    WITH_CROWDCAD=1 ;;
        --crowdcad-domain)  shift; CROWDCAD_DOMAIN="${1:-}" ;;
        --crowdcad-ref)     shift; CROWDCAD_REF="${1:-}" ;;
        --crowdcad-admin)   shift; CROWDCAD_ADMIN="${1:-}" ;;
        --crowdcad-signup)  shift; CROWDCAD_SIGNUP="${1:-}" ;;
        --crowdcad-rebuild) CROWDCAD_REBUILD=1 ;;
        --no-restart)   DO_RESTART=0 ;;
        --pull)         DO_PULL=1 ;;
        -h|--help)      usage; exit 0 ;;
        *)              echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done
case "$HOOK_MODE" in pth|append|none) ;; *) echo "--console-hook must be pth, append or none" >&2; exit 2 ;; esac
case "$CROWDCAD_SIGNUP" in ""|open|closed) ;; *) echo "--crowdcad-signup must be open or closed" >&2; exit 2 ;; esac
[ "$(id -u)" -eq 0 ] || { echo "ERROR: run as root (sudo bash $0)" >&2; exit 1; }

# --- 0. Source checkout ---------------------------------------------------------------------
if [ "$DO_PULL" -eq 1 ]; then
    git -C "$CROWDCAD_HOME/src" pull --ff-only
    args=()
    for a in "${ORIGINAL_ARGS[@]}"; do [ "$a" != "--pull" ] && args+=("$a"); done
    exec bash "$CROWDCAD_HOME/src/infratak/install.sh" "${args[@]}"
fi
if [ "$SRC_DIR" != "$CROWDCAD_HOME/src" ]; then
    log "Copying source to $CROWDCAD_HOME/src"
    mkdir -p "$CROWDCAD_HOME"
    rm -rf "$CROWDCAD_HOME/src.new"
    cp -a "$SRC_DIR" "$CROWDCAD_HOME/src.new"
    rm -rf "$CROWDCAD_HOME/src"
    mv "$CROWDCAD_HOME/src.new" "$CROWDCAD_HOME/src"
fi
SRC="$CROWDCAD_HOME/src"
VERSION="$(tr -d '[:space:]' < "$SRC/VERSION")"
log "CrowdCAD for TAK $VERSION"

python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
    || { echo "ERROR: Python 3.10+ required (found $(python3 --version 2>&1)). Ubuntu 22.04+ ships it." >&2; exit 1; }

# --- 1. Service user and files -----------------------------------------------------------------
id crowdcad-tak >/dev/null 2>&1 || useradd --system --home-dir "$CROWDCAD_HOME" --no-create-home --shell /usr/sbin/nologin crowdcad-tak
mkdir -p "$CROWDCAD_HOME/app" "$CROWDCAD_HOME/bin" "$CROWDCAD_HOME/data" "$CROWDCAD_HOME/certs"
rm -rf "$CROWDCAD_HOME/app/crowdcad_tak"
cp -a "$SRC/bridge/crowdcad_tak" "$CROWDCAD_HOME/app/crowdcad_tak"
cp "$SRC/VERSION" "$CROWDCAD_HOME/app/VERSION"
find "$CROWDCAD_HOME/app" -name __pycache__ -prune -exec rm -rf {} +
for f in crowdcad_infratak.py crowdcad_infratak_boot.py crowdcad_infratak.pth crowdcad_caddy.py crowdcad_app.py lib.sh heal.sh uninstall.sh \n         crowdcad_cloudtak_job.sh; do   # the last one runs the console's CloudTAK install button (R41)
    install -m 0755 "$SRC/infratak/$f" "$CROWDCAD_HOME/bin/$f"
done
mkdir -p "$CROWDCAD_HOME/bin/pb_hooks"
install -m 0644 "$SRC/infratak/pb_hooks/crowdcad_tak.pb.js" "$CROWDCAD_HOME/bin/pb_hooks/crowdcad_tak.pb.js"

cat > /usr/local/bin/crowdcad-tak <<EOF
#!/bin/bash
# CrowdCAD for TAK CLI, as the service user: crowdcad-tak check | preview [event.json] | version
exec runuser -u crowdcad-tak -- env CROWDCAD_TAK_DATA_DIR=$CROWDCAD_HOME/data PYTHONPATH=$CROWDCAD_HOME/app /usr/bin/python3 -m crowdcad_tak "\$@"
EOF
chmod 755 /usr/local/bin/crowdcad-tak

# --- 2. TAK client certificate -------------------------------------------------------------------
CERT_FILES="$TAK_CERTS/files"
if [ -s "$CROWDCAD_HOME/certs/crowdcad.pem" ]; then
    log "TAK client cert already in place (kept)"
elif [ -x "$TAK_CERTS/makeCert.sh" ]; then
    if [ ! -s "$CERT_FILES/crowdcad.pem" ]; then
        log "Making TAK client cert 'crowdcad'"
        (cd "$TAK_CERTS" && echo y | sudo -u tak ./makeCert.sh client crowdcad >/dev/null)
    fi
    install -m 0640 -o root -g crowdcad-tak "$CERT_FILES/crowdcad.pem" "$CROWDCAD_HOME/certs/crowdcad.pem"
    install -m 0640 -o root -g crowdcad-tak "$CERT_FILES/crowdcad.key" "$CROWDCAD_HOME/certs/crowdcad.key"
else
    warn "No TAK Server at $TAK_CERTS — put crowdcad.pem/.key in $CROWDCAD_HOME/certs yourself."
fi
CA_SRC="${TAK_CA:-$CERT_FILES/ca.pem}"
if [ -s "$CA_SRC" ]; then
    install -m 0644 "$CA_SRC" "$CROWDCAD_HOME/certs/ca.pem"
else
    warn "TAK CA $CA_SRC not found — pass --tak-ca, or the bridge can't verify TAK Server."
fi
if [ "${#TAK_GROUPS[@]}" -gt 0 ] && [ -f /opt/tak/utils/UserManager.jar ] && [ -s "$CERT_FILES/crowdcad.pem" ]; then
    cmd=(java -jar /opt/tak/utils/UserManager.jar certmod)
    for g in "${TAK_GROUPS[@]}"; do cmd+=(-g "$g"); done
    um_dir="$(mktemp -d)"
    (cd "$um_dir" && "${cmd[@]}" "$CERT_FILES/crowdcad.pem" >/dev/null) && log "Bridge cert in TAK group(s): ${TAK_GROUPS[*]}" \
        || warn "Group assignment failed — set it in TAK Server's user management."
    rm -rf "$um_dir"
elif [ "${#TAK_GROUPS[@]}" -eq 0 ]; then
    warn "No --tak-group given: the bridge's markers go to __ANON__. Re-run with --tak-group <group>."
fi

# --- 3. Settings (seeded once, then owned by the console page) ----------------------------------
python3 - "$CROWDCAD_HOME/data" "$CROWDCAD_URL" "$CERT_FILES/../cert-metadata.sh" <<'PYEOF'
import json, os, re, sys
import secrets as tokens
data, url, metadata = sys.argv[1:]
def load(name):
    try:
        return json.load(open(os.path.join(data, name)))
    except (OSError, ValueError):
        return {}
config, secrets = load("config.json"), load("secrets.json")
if url and not config.get("crowdcad_url"):
    config["crowdcad_url"] = url.rstrip("/")
if "tak_key_password" not in secrets:
    # makeCert.sh encrypts client keys with cert-metadata.sh's PASS (TAK's stock: atakatak).
    # Stock cert-metadata.sh has PASS="${CAPASS}"; infra-TAK's deploy rewrites CAPASS.
    try:
        text = open(metadata).read()
    except OSError:
        text = ""
    # infra-TAK writes CAPASS through shlex.quote, so it may be single-quoted.
    values = dict(re.findall(r'''^(PASS|CAPASS)=["']?([^"'\n]*)["']?''', text, re.M))
    password = values.get("PASS", "")
    if password in ("$CAPASS", "${CAPASS}"):
        password = values.get("CAPASS", "")
    secrets["tak_key_password"] = password if password and "$" not in password else "atakatak"
if not secrets.get("board_token"):
    secrets["board_token"] = tokens.token_urlsafe(32)   # for the CloudTAK relay and WebTAK bundle
if not secrets.get("manage_token"):
    secrets["manage_token"] = tokens.token_urlsafe(32)  # CloudTAK's server half only (create/end events)
for name, value, mode in (("config.json", config, 0o640), ("secrets.json", secrets, 0o600)):
    path = os.path.join(data, name)
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
    os.replace(path + ".tmp", path)
PYEOF
chown -R crowdcad-tak:crowdcad-tak "$CROWDCAD_HOME/data"
chmod 750 "$CROWDCAD_HOME/data"

# --- 4. Service --------------------------------------------------------------------------------
install -m 0644 "$SRC/infratak/systemd/crowdcad-tak.service" /etc/systemd/system/crowdcad-tak.service
systemctl daemon-reload
systemctl enable --quiet crowdcad-tak.service
systemctl restart crowdcad-tak.service
for _ in $(seq 1 20); do
    curl -fsS http://127.0.0.1:8782/healthz >/dev/null 2>&1 && break
    sleep 0.5
done
curl -fsS http://127.0.0.1:8782/healthz >/dev/null 2>&1 && log "Bridge is up (status on 127.0.0.1:8782)" \
    || warn "Bridge didn't answer; check: journalctl -u crowdcad-tak -n 50"

# --- 5. infra-TAK console integration -------------------------------------------------------------
CONSOLE_DIR="$(find_console_dir || true)"
if [ -z "$CONSOLE_DIR" ]; then
    warn "No infra-TAK console found — bridge only; configure $CROWDCAD_HOME/data/config.json by hand."
    HOOK_MODE="none"
else
    log "infra-TAK console: $CONSOLE_DIR ($(grep -m1 '^VERSION' "$CONSOLE_DIR/app.py" | cut -d'"' -f2 || echo unknown))"
fi
if [ "$HOOK_MODE" = "pth" ]; then
    if CONSOLE_PY="$(find_console_python)" && site="$(install_pth_hook "$CONSOLE_PY")"; then
        log "Console hook installed in $site"
        remove_append_hook "$CONSOLE_DIR"
    else
        warn "Couldn't locate the console's Python; falling back to --console-hook append."
        HOOK_MODE="append"
    fi
fi
if [ "$HOOK_MODE" = "append" ]; then
    install_append_hook "$CONSOLE_DIR" && log "Console hook block added to $CONSOLE_DIR/app.py"
fi

# --- 5b. CrowdCAD itself (--with-crowdcad, or kept running from an earlier install) -------------
APP_JSON="$CROWDCAD_HOME/crowdcad/app.json"
app_field() { python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get(sys.argv[2],''))" "$APP_JSON" "$1" 2>/dev/null; }
APP_HOST=""; APP_WEB=""; APP_PB=""
if [ "$WITH_CROWDCAD" -eq 1 ]; then
    # Re-runs keep what the first install chose unless an option says otherwise.
    [ -z "$CROWDCAD_DOMAIN" ] && [ -f "$APP_JSON" ] && CROWDCAD_DOMAIN="$(app_field host)"
    [ -z "$CROWDCAD_REF" ] && [ -f "$APP_JSON" ] && CROWDCAD_REF="$(app_field ref)"
    [ -z "$CROWDCAD_SIGNUP" ] && [ -f "$APP_JSON" ] && CROWDCAD_SIGNUP="$(app_field signup)"
    APP_HOST="$(python3 "$CROWDCAD_HOME/bin/crowdcad_caddy.py" app-host --console-dir "$CONSOLE_DIR" \
        ${CROWDCAD_DOMAIN:+--app-domain "$CROWDCAD_DOMAIN"} || true)"
    if [ -z "$APP_HOST" ]; then
        warn "No infra-TAK FQDN for CrowdCAD's host — pass --crowdcad-domain. CrowdCAD not installed."
    else
        log "CrowdCAD app: https://$APP_HOST"
        app_rc=0
        app_out="$(python3 "$CROWDCAD_HOME/bin/crowdcad_app.py" --home "$CROWDCAD_HOME" install --host "$APP_HOST" \
            --data "$CROWDCAD_HOME/data" ${CROWDCAD_REF:+--ref "$CROWDCAD_REF"} \
            ${CROWDCAD_ADMIN:+--admin-email "$CROWDCAD_ADMIN"} ${CROWDCAD_SIGNUP:+--signup "$CROWDCAD_SIGNUP"} \
            $([ "$CROWDCAD_REBUILD" -eq 1 ] && echo --rebuild))" || app_rc=$?
        printf '%s\n' "$app_out" | grep -v '^BRIDGE_CHANGED$' || true
        if [ "$app_rc" -ne 0 ]; then
            warn "CrowdCAD app not (fully) installed — see above. Re-run to retry; its data is kept."
        elif printf '%s\n' "$app_out" | grep -q '^BRIDGE_CHANGED$'; then
            systemctl restart crowdcad-tak.service
        fi
    fi
fi
if [ -f "$APP_JSON" ]; then
    APP_HOST="$(app_field host)"; APP_WEB="127.0.0.1:$(app_field web_port)"; APP_PB="127.0.0.1:$(app_field pb_port)"
fi

cat > "$CROWDCAD_HOME/bin/crowdcad.env" <<EOF
# Written by install.sh; read by heal.sh and uninstall.sh.
CONSOLE_DIR="$CONSOLE_DIR"
HOOK_MODE="$HOOK_MODE"
CROWDCAD_DOMAIN="$DOMAIN"
DO_CADDY="$DO_CADDY"
APP_HOST="$APP_HOST"
APP_WEB="$APP_WEB"
APP_PB="$APP_PB"
EOF

# --- 6. Caddy: the board API for the web clients -------------------------------------------------
if [ "$DO_CADDY" -eq 1 ]; then
    python3 "$CROWDCAD_HOME/bin/crowdcad_caddy.py" ensure --reload --console-dir "$CONSOLE_DIR" ${DOMAIN:+--domain "$DOMAIN"} \
        ${APP_HOST:+--app-host "$APP_HOST" --app-web "$APP_WEB" --app-pocketbase "$APP_PB"} \
        || warn "Caddy not updated (see above). ATAK is unaffected; the web clients can't reach the board."
    chown crowdcad-tak:crowdcad-tak "$CROWDCAD_HOME/data/config.json" 2>/dev/null || true
    systemctl restart crowdcad-tak.service   # pick up the cors_origins crowdcad_caddy.py seeded
fi
if [ -n "$CONSOLE_DIR" ] || [ "$DO_CADDY" -eq 1 ]; then
    sed "s#@CONSOLE_DIR@#${CONSOLE_DIR:-/nonexistent}#" "$SRC/infratak/systemd/crowdcad-tak-heal.path" > /etc/systemd/system/crowdcad-tak-heal.path
    install -m 0644 "$SRC/infratak/systemd/crowdcad-tak-heal.service" /etc/systemd/system/crowdcad-tak-heal.service
    systemctl daemon-reload
    systemctl enable --quiet --now crowdcad-tak-heal.path
fi
PUBLIC_URL="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('public_url',''))" "$CROWDCAD_HOME/data/config.json" 2>/dev/null || true)"
BOARD_TOKEN="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('board_token',''))" "$CROWDCAD_HOME/data/secrets.json")"
MANAGE_TOKEN="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('manage_token',''))" "$CROWDCAD_HOME/data/secrets.json")"

# --- 7. Web clients ------------------------------------------------------------------------------
if { [ -n "$CLOUDTAK" ] || [ -n "$WEBTAK" ]; } && [ -z "$PUBLIC_URL" ]; then
    # Not 127.0.0.1: CloudTAK runs in Docker (its loopback is the container) and WebTAK runs in
    # operators' browsers. Both need the published crowdcad-tak.<fqdn>.
    warn "No public URL for the board (no FQDN, or --no-caddy) — skipping the web clients."
    CLOUDTAK=""; WEBTAK=""
fi
if [ -n "$CLOUDTAK" ]; then
    CROWDCAD_TAK_URL="$PUBLIC_URL" CROWDCAD_TAK_TOKEN="$BOARD_TOKEN" CROWDCAD_TAK_MANAGE_TOKEN="$MANAGE_TOKEN" \
        bash "$SRC/cloudtak/install.sh" $([ "$CLOUDTAK" != "auto" ] && echo "$CLOUDTAK") \
        || warn "CloudTAK plugin not installed (see above)."
fi
if [ -n "$WEBTAK" ]; then
    CROWDCAD_TAK_URL="$PUBLIC_URL" CROWDCAD_TAK_TOKEN="$BOARD_TOKEN" WEBTAK_DIR="$WEBTAK" \
        bash "$SRC/webtak/install.sh" || warn "WebTAK plugin not installed (see above)."
fi

[ "$HOOK_MODE" != "none" ] && [ "$DO_RESTART" -eq 1 ] && restart_console

echo
echo "✓ CrowdCAD for TAK $VERSION installed."
echo "  Bridge:   systemctl status crowdcad-tak   (logs: journalctl -u crowdcad-tak -f)"
if [ -n "$APP_HOST" ]; then
    echo "  CrowdCAD: https://$APP_HOST — sign-in details in $CROWDCAD_HOME/crowdcad/credentials.json (root only)"
    echo "            more accounts: sudo python3 $CROWDCAD_HOME/bin/crowdcad_app.py add-user EMAIL [--admin]"
elif [ "$HOOK_MODE" != "none" ]; then
    echo "  Next:     infra-TAK console → CrowdCAD → enter the CrowdCAD URL and bridge account"
else
    echo "  Next:     edit $CROWDCAD_HOME/data/config.json + secrets.json, then systemctl restart crowdcad-tak"
fi
echo "  Verify:   crowdcad-tak check    ·    crowdcad-tak preview   (prints CoT, sends nothing)"
echo "  Board:    ${PUBLIC_URL:-not published (no FQDN / --no-caddy)} — token on the console page"
echo "  ATAK:     install ATAK-Plugin-CrowdCAD-*.apk on medics' and command devices (atak/ in the repo)"
exit 0
