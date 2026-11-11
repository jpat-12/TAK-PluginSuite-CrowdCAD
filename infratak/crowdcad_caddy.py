#!/usr/bin/env python3
"""Keep the bridge's board API site in infra-TAK's Caddyfile, on any infra-TAK version.

Publishes crowdcad-tak.<fqdn> → the bridge's /api/v1/* and /healthz only, for the WebTAK and
CloudTAK plugins (ATAK needs nothing: it reads CoT). Everything else on that host is a 404,
so the console-only /status never leaves the box.

infra-TAK rewrites /etc/caddy/Caddyfile whenever a module is deployed, but since v0.2.0
carries everything below "# --- User-added blocks (do not remove) ---" into the new file, so
the block goes there. crowdcad-tak-heal.path re-runs `ensure` after any rewrite that drops it.
Same mechanics as InfraTAK-Plugin-Aleph's aleph_caddy.py. Stdlib only (system python3).

    crowdcad_caddy.py ensure [--reload] [--caddyfile F] [--console-dir D] [--data D] [--domain H]
    crowdcad_caddy.py remove [--reload] [--caddyfile F]
    crowdcad_caddy.py host   [--console-dir D] [--data D] [--domain H]
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


def strip(text):
    while BEGIN in text and END in text:
        start = text.index(BEGIN)
        stop = text.index(END, start) + len(END)
        text = text[:start].rstrip("\n") + "\n" + text[stop:].lstrip("\n")
    return text


def ensure(text, new_block):
    text = strip(text).rstrip("\n")
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
        config["cors_origins"] = [f"https://{base}:8443", f"https://{base}:8446", f"https://tak.{base}"]
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
    parser.add_argument("action", choices=("ensure", "remove", "host"))
    parser.add_argument("--caddyfile", default=DEFAULT_CADDYFILE)
    parser.add_argument("--console-dir", default=None)
    parser.add_argument("--data", default=DEFAULT_DATA)
    parser.add_argument("--domain", default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)
    console_dir = args.console_dir or find_console_dir()
    host = site_host(console_dir, args.data, args.domain)

    if args.action == "host":
        print(host or "")
        return 0 if host else 1
    if not os.path.isfile(args.caddyfile):
        print(f"[crowdcad-tak] {args.caddyfile} not found — deploy Caddy in infra-TAK first, then re-run.")
        return 2
    with open(args.caddyfile, encoding="utf-8") as stream:
        text = stream.read()
    if args.action == "remove":
        print(f"[crowdcad-tak] caddy: {write_and_reload(args.caddyfile, strip(text), args.reload)}")
        return 0
    if not host:
        print("[crowdcad-tak] No base FQDN in infra-TAK settings and no --domain; web clients can't reach the board.")
        return 3
    result = write_and_reload(args.caddyfile, ensure(text, block(host, upstream(args.data))), args.reload)
    print(f"[crowdcad-tak] caddy {host}: {result}")
    update_config(args.data, host, console_dir)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        print(f"[crowdcad-tak] {error}", file=sys.stderr)
        sys.exit(1)
