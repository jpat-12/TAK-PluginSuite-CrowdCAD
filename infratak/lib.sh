#!/bin/bash
# lib.sh — functions shared by install.sh, heal.sh and uninstall.sh. Sourced, never run.
# Console discovery and hook install mirror InfraTAK-Plugin-Aleph's lib.sh (verified there on
# every infra-TAK release); keep the two in step.

CROWDCAD_HOME="${CROWDCAD_HOME:-/opt/crowdcad-tak}"
CONSOLE_SERVICE="${CONSOLE_SERVICE:-takwerx-console}"
HOOK_BEGIN="# >>> crowdcad-tak console hook"
HOOK_END="# <<< crowdcad-tak console hook"

log()  { echo "==> $*"; }
warn() { echo "    ⚠ $*" >&2; }

find_console_dir() {
    local d
    # The running console's own directory wins. infra-TAK 10.x runs from /opt/infratak (settings
    # in its .config), while the operator's clone (e.g. /home/ubuntu/infra-TAK) is only the
    # installer source with no settings — picking it loses the FQDN (tracker R41).
    d="$(systemctl show -p WorkingDirectory --value "$CONSOLE_SERVICE" 2>/dev/null || true)"
    [ -n "$d" ] && [ -f "$d/app.py" ] && { echo "$d"; return 0; }
    for d in /opt/infratak /opt/infra-TAK /opt/infra-tak /root/infra-TAK /root/infra-tak "$HOME/infra-TAK" "$HOME/infra-tak"; do
        [ -f "$d/app.py" ] && { echo "$d"; return 0; }
    done
    d="$(find /root /home /opt -maxdepth 3 -name app.py -path '*infra*' 2>/dev/null | head -1)"
    [ -n "$d" ] && dirname "$d"
}

# The interpreter that runs the console: `<venv>/bin/gunicorn ... app:app` or `<python> app.py`.
find_console_python() {
    local exec_start bin py
    exec_start="$(systemctl show -p ExecStart --value "$CONSOLE_SERVICE" 2>/dev/null | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -1)"
    if [ -z "$exec_start" ] && [ -f "/etc/systemd/system/$CONSOLE_SERVICE.service" ]; then
        exec_start="$(sed -n 's/^ExecStart=\([^ ]*\).*/\1/p' "/etc/systemd/system/$CONSOLE_SERVICE.service" | head -1)"
    fi
    bin="$exec_start"
    case "$(basename "${bin:-x}")" in
        gunicorn*) for py in "$(dirname "$bin")/python3" "$(dirname "$bin")/python"; do
                       [ -x "$py" ] && { echo "$py"; return 0; }
                   done ;;
        python*)   [ -x "$bin" ] && { echo "$bin"; return 0; } ;;
    esac
    return 1
}

console_site_packages() {
    "$1" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])'
}

# Default hook: two modules + a .pth line in the console's site-packages. Untracked by
# infra-TAK's git, so "Update Now" (git checkout --force) leaves it alone.
install_pth_hook() {
    local py="$1" site
    site="$(console_site_packages "$py")" || return 1
    mkdir -p "$site"
    install -m 0644 "$CROWDCAD_HOME/bin/crowdcad_infratak.py" "$CROWDCAD_HOME/bin/crowdcad_infratak_boot.py" "$site/"
    install -m 0644 "$CROWDCAD_HOME/bin/crowdcad_infratak.pth" "$site/crowdcad_infratak.pth"
    "$py" -c 'import crowdcad_infratak_boot, crowdcad_infratak' || return 1
    echo "$site"
}

remove_pth_hook() {
    local py="$1" site
    site="$(console_site_packages "$py" 2>/dev/null)" || return 0
    rm -f "$site/crowdcad_infratak.pth" "$site/crowdcad_infratak.py" "$site/crowdcad_infratak_boot.py"
}

# Fallback for consoles not run from a findable interpreter: a guarded block in app.py.
# "Update Now" wipes it; crowdcad-tak-heal puts it back.
install_append_hook() {
    local app="$1/app.py"
    grep -qF "$HOOK_BEGIN" "$app" && return 0
    python3 - "$app" "$CROWDCAD_HOME/bin" "$HOOK_BEGIN" "$HOOK_END" <<'PYEOF'
import re, sys
path, bindir, begin, end = sys.argv[1:]
src = open(path, encoding="utf-8").read()
block = (f"{begin} (re-added by crowdcad-tak-heal after infra-TAK updates)\n"
         "try:\n"
         f"    import sys as _cc_sys; _cc_sys.path.insert(0, {bindir!r})\n"
         "    import crowdcad_infratak as _cc; _cc.attach(globals())\n"
         "except Exception as _cc_error:\n"
         "    print(f'[crowdcad-tak] console hook skipped: {_cc_error!r}', flush=True)\n"
         f"{end}\n")
match = list(re.finditer(r"^if __name__ == ['\"]__main__['\"]:", src, re.M))
if match and match[-1].start() > len(src) // 2:
    src = src[:match[-1].start()] + block + "\n" + src[match[-1].start():]
else:
    src = src.rstrip("\n") + "\n\n" + block
open(path, "w", encoding="utf-8").write(src)
PYEOF
}

remove_append_hook() {
    local app="$1/app.py"
    [ -f "$app" ] || return 0
    python3 - "$app" "$HOOK_BEGIN" "$HOOK_END" <<'PYEOF'
import sys
path, begin, end = sys.argv[1:]
src = open(path, encoding="utf-8").read()
while begin in src and end in src:
    start = src.index(begin)
    stop = src.index(end, start) + len(end)
    src = src[:start] + src[stop:].lstrip("\n")
open(path, "w", encoding="utf-8").write(src)
PYEOF
}

# Restart the console without killing ourselves: a direct `systemctl restart` from a child of
# the console's cgroup takes this script down with it (see InfraTAK-Module-MigrateAuthentik).
restart_console() {
    systemctl list-unit-files "$CONSOLE_SERVICE.service" >/dev/null 2>&1 || return 0
    if command -v systemd-run >/dev/null 2>&1; then
        systemd-run --no-block --collect --quiet -- systemctl restart "$CONSOLE_SERVICE" 2>/dev/null \
            && log "Console restart scheduled ($CONSOLE_SERVICE)" || warn "Restart $CONSOLE_SERVICE manually"
    else
        (systemctl restart "$CONSOLE_SERVICE" 2>/dev/null &)
    fi
}
