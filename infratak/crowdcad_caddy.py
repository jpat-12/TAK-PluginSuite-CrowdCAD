#!/usr/bin/env python3
"""Keep the bridge's board API site in infra-TAK's Caddyfile, on any infra-TAK version.

Publishes crowdcad-tak.<fqdn> → the bridge's /api/v1/* and /healthz only, for the WebTAK and
CloudTAK plugins (ATAK needs nothing: it reads CoT). Everything else on that host is a 404,
so the console-only /status never leaves the box.

With --app-host (install.sh --with-crowdcad), a second managed block publishes the CrowdCAD
app this host runs itself (crowdcad_app.py): one site, Next.js plus PocketBase behind it.

infra-TAK rewrites /etc/caddy/Caddyfile whenever a module is deployed, but since v0.2.0
carries everything below "# --- User-added blocks (do not remove) ---" into the new file, so
the block goes there. crowdcad-tak-heal.path re-runs `ensure` after any rewrite that drops it.
Same mechanics as InfraTAK-Plugin-Aleph's aleph_caddy.py. Stdlib only (system python3).

    crowdcad_caddy.py ensure [--reload] [--caddyfile F] [--console-dir D] [--data D] [--domain H]
                             [--app-host H --app-web ADDR --app-pocketbase ADDR]
    crowdcad_caddy.py remove [--reload] [--caddyfile F]        (the board block only)
    crowdcad_caddy.py app-remove [--reload] [--caddyfile F]    (the CrowdCAD app block only)
    crowdcad_caddy.py host   [--console-dir D] [--data D] [--domain H]
    crowdcad_caddy.py app-host [--console-dir D] [--app-domain H]   (default crowdcad.<fqdn>)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

BEGIN = "# >>> crowdcad-tak (managed by TAK-PluginSuite-CrowdCAD — edits here are overwritten)"
END = "# <<< crowdcad-tak"
APP_BEGIN = "# >>> crowdcad-app (managed by TAK-PluginSuite-CrowdCAD — edits here are overwritten)"
APP_END = "# <<< crowdcad-app"
USER_BLOCKS_MARKER = "# --- User-added blocks (do not remove) ---"
DEFAULT_CADDYFILE = "/etc/caddy/Caddyfile"
DEFAULT_DATA = "/opt/crowdcad-tak/data"
CONSOLE_DIRS = ("/opt/infra-TAK", "/opt/infra-tak", "/root/infra-TAK", "/root/infra-tak")


def find_console_dir():
    for directory in CONSOLE_DIRS + (os.path.expanduser("~/infra-TAK"), os.path.expanduser("~/infra-tak")):
        if os.path.isfile(os.path.join(directory, "app.py")):
            return directory
    return None


def read_json(path):
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return {}


def fqdn(console_dir):
    settings = read_json(os.path.join(console_dir, ".config", "settings.json")) if console_dir else {}
    return (settings.get("fqdn") or "").strip()


def site_host(console_dir=None, data=DEFAULT_DATA, override=None):
    """infra-TAK's domain rule: `crowdcad_tak_domain` override (a bare label gets the base FQDN
    appended), else crowdcad-tak.<fqdn>, else whatever public_url we wrote last time."""
    settings = read_json(os.path.join(console_dir, ".config", "settings.json")) if console_dir else {}
    base = fqdn(console_dir)
    custom = (override or settings.get("crowdcad_tak_domain") or "").strip()
    if custom:
        return custom if "." in custom or not base else f"{custom}.{base}"
    if base:
        return f"crowdcad-tak.{base}"
    public = read_json(os.path.join(data, "config.json")).get("public_url", "")
    return public.split("://", 1)[-1].strip("/") or None


def app_site_host(console_dir=None, override=None):
    """Where install.sh --with-crowdcad publishes CrowdCAD: --crowdcad-domain (a bare label gets
    the base FQDN appended), else crowdcad.<fqdn>."""
    base = fqdn(console_dir)
    custom = (override or "").strip()
    if custom:
        return custom if "." in custom or not base else f"{custom}.{base}"
    return f"crowdcad.{base}" if base else None


def upstream(data=DEFAULT_DATA):
    return read_json(os.path.join(data, "config.json")).get("status_listen") or "127.0.0.1:8782"


def block(host, target):
    # Not behind Authentik forward_auth: the board is read by the CloudTAK server relay and by
    # WebTAK pages on another origin, both with the bearer board token.
    return "\n".join([
        BEGIN,
        f"{host} {{",
        "    encode gzip",
        "    @bridge path /api/v1/* /healthz",
        "    handle @bridge {",
        f"        reverse_proxy {target}",
        "    }",
        "    handle {",
        "        respond 404",
        "    }",
        "}",
        END,
    ])


def app_block(host, web, pocketbase):
    """The CrowdCAD app (PLAN.md Phase 2): one host, so the browser's NEXT_PUBLIC_POCKETBASE_URL
    is this same origin. Not behind Authentik forward_auth: CrowdCAD has its own login, and
    forward_auth would break PocketBase's API for the bridge and the app. No gzip on PocketBase
    paths: compressing its realtime SSE stream would buffer it."""
    return "\n".join([
        APP_BEGIN,
        f"{host} {{",
        "    handle /api/contact* {",           # Next.js's only API route
        f"        reverse_proxy {web}",
        "    }",
        "    @pocketbase path /api/* /_/*",     # PocketBase REST + realtime, and its admin UI
        "    handle @pocketbase {",
        f"        reverse_proxy {pocketbase}",
        "    }",
        "    handle {",
        "        encode gzip",
        f"        reverse_proxy {web}",
        "    }",
        "}",
        APP_END,
    ])


def strip(text, begin=BEGIN, end=END):
    while begin in text and end in text:
        start = text.index(begin)
        stop = text.index(end, start) + len(end)
        text = text[:start].rstrip("\n") + "\n" + text[stop:].lstrip("\n")
    return text


def ensure(text, new_block, begin=BEGIN, end=END, after=None):
    """Our block, below the user-blocks marker, with as little movement as possible:
    already there (below the marker) → replaced in place, so an unchanged block means a
    byte-identical file wherever it sits. Moving it to the end every time ping-pongs with
    other plugins' heal units doing the same (Aleph's), each write re-triggering the other.
    Missing → inserted right after the `after` block if given, else appended at the end."""
    marker = text.find(USER_BLOCKS_MARKER)
    start = text.find(begin)
    if marker >= 0 and start > marker and text.find(end, start) > start:
        stop = text.index(end, start) + len(end)
        return text[:start] + new_block + strip(text[stop:], begin, end)
    text = strip(text, begin, end)
    if after and after in text and text.find(after) > text.find(USER_BLOCKS_MARKER) >= 0:
        cut = text.index(after) + len(after)
        return text[:cut] + "\n\n" + new_block + text[cut:]
    text = text.rstrip("\n")
    if USER_BLOCKS_MARKER not in text:
        text += "\n\n" + USER_BLOCKS_MARKER
    return text + "\n\n" + new_block + "\n"


def _validate(path):
    caddy = shutil.which("caddy")
    if not caddy:
        return True, "caddy binary not found; skipped validation"
    result = subprocess.run([caddy, "validate", "--config", path, "--adapter", "caddyfile"],
                            capture_output=True, text=True, timeout=60)
    return result.returncode == 0, (result.stdout + result.stderr)[-2000:]


def write_and_reload(path, new_text, reload):
    with open(path, encoding="utf-8") as stream:
        old_text = stream.read()
    if old_text == new_text:
        return "unchanged"   # also what ends the heal loop: our own write re-triggers the path unit
    backup = f"{path}.crowdcad-bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, backup)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(new_text)
    if not reload:
        return "written"
    ok, output = _validate(path)
    if ok:
        ok = subprocess.run(["systemctl", "reload", "caddy"], capture_output=True, timeout=60).returncode == 0
        output = output if ok else "systemctl reload caddy failed"
    if not ok:
        shutil.copy2(backup, path)
        subprocess.run(["systemctl", "reload", "caddy"], capture_output=True, timeout=60)
        raise RuntimeError(f"Caddy rejected the crowdcad-tak block; restored {backup}.\n{output}")
    return "reloaded"


def update_config(data, host, console_dir):
    """Record the public URL (the console page shows it; client installers read it) and, once,
    seed CORS with the origins WebTAK is usually served from on this host."""
    path = os.path.join(data, "config.json")
    if not host or not os.path.isdir(data):
        return
    config = read_json(path)
    changed = False
    if config.get("public_url") != f"https://{host}":
        config["public_url"], changed = f"https://{host}", True
    base = fqdn(console_dir)
    if base and not config.get("cors_origins"):
        # infra-TAK publishes WebTAK at takserver.<fqdn> (Caddy → 8446); the others are direct ports.
        config["cors_origins"] = [f"https://{base}:8443", f"https://{base}:8446", f"https://tak.{base}",
                                  f"https://takserver.{base}"]
        changed = True
    if not changed:
        return
    stat = os.stat(data)
    with open(path + ".tmp", "w", encoding="utf-8") as stream:
        json.dump(config, stream, indent=2, sort_keys=True)
    try:
        os.chown(path + ".tmp", stat.st_uid, stat.st_gid)
    except (AttributeError, PermissionError):
        pass
    os.replace(path + ".tmp", path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("ensure", "remove", "app-remove", "host", "app-host"))
    parser.add_argument("--caddyfile", default=DEFAULT_CADDYFILE)
    parser.add_argument("--console-dir", default=None)
    parser.add_argument("--data", default=DEFAULT_DATA)
    parser.add_argument("--domain", default=None)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--app-host", default=None, help="also publish the CrowdCAD app at this host")
    parser.add_argument("--app-web", default="127.0.0.1:3100")
    parser.add_argument("--app-pocketbase", default="127.0.0.1:8090")
    parser.add_argument("--app-domain", default=None, help="app-host: override for crowdcad.<fqdn>")
    args = parser.parse_args(argv)
    console_dir = args.console_dir or find_console_dir()
    host = site_host(console_dir, args.data, args.domain)

    if args.action == "host":
        print(host or "")
        return 0 if host else 1
    if args.action == "app-host":
        app_host = app_site_host(console_dir, args.app_domain)
        print(app_host or "")
        return 0 if app_host else 1
    if not os.path.isfile(args.caddyfile):
        print(f"[crowdcad-tak] {args.caddyfile} not found — deploy Caddy in infra-TAK first, then re-run.")
        return 2
    with open(args.caddyfile, encoding="utf-8") as stream:
        text = stream.read()
    if args.action == "remove":
        print(f"[crowdcad-tak] caddy: {write_and_reload(args.caddyfile, strip(text), args.reload)}")
        return 0
    if args.action == "app-remove":
        print(f"[crowdcad-tak] caddy app: {write_and_reload(args.caddyfile, strip(text, APP_BEGIN, APP_END), args.reload)}")
        return 0
    if not host:
        print("[crowdcad-tak] No base FQDN in infra-TAK settings and no --domain; web clients can't reach the board.")
        return 3
    # Each block in place (see ensure): a re-run with nothing changed is byte-identical, which
    # is what ends the heal path unit's own re-trigger and never moves a neighbour's block.
    text = ensure(text, block(host, upstream(args.data)))
    if args.app_host:
        text = ensure(text, app_block(args.app_host, args.app_web, args.app_pocketbase), APP_BEGIN, APP_END, after=END)
    result = write_and_reload(args.caddyfile, text, args.reload)
    print(f"[crowdcad-tak] caddy {host}{' + ' + args.app_host if args.app_host else ''}: {result}")
    update_config(args.data, host, console_dir)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        print(f"[crowdcad-tak] {error}", file=sys.stderr)
        sys.exit(1)
