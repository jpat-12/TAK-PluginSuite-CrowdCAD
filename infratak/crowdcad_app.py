#!/usr/bin/env python3
"""Run CrowdCAD itself on this infra-TAK host (install.sh --with-crowdcad; docs/PLAN.md Phase 2).

CrowdCAD (github.com/evanqua/crowdcad, unmodified) on its PocketBase backend, built from a
pinned release tag with Docker. Everything lives under <home>/crowdcad/:

    src/                 the CrowdCAD checkout at --ref
    docker-compose.yml   ours, written here (project "crowdcad"; both ports on loopback only)
    pb_data/             PocketBase's data: every venue, event and call. Back this up.
    pb_hooks/            our compare-and-swap route for native TAK dispatch (pb_hooks/crowdcad_tak.pb.js
                         in this repo); CrowdCAD itself never calls it
    app.json             what was deployed (host, ref, ports), read by install.sh / heal / uninstall
    credentials.json     0600: PocketBase superuser, the first CrowdCAD admin, the bridge account

Caddy publishes it at one host (crowdcad_caddy.py app_block), so the browser's baked-in
NEXT_PUBLIC_POCKETBASE_URL is that same origin. The bridge reads PocketBase on loopback.

Public sign-up is closed by default: CrowdCAD lets any signed-in user read every event
(calls carry patient details), so on an internet-facing host accounts are made here
(`add-user`) or in PocketBase's admin UI (/_/). --signup open restores CrowdCAD's default.

    crowdcad_app.py install --host H [--ref TAG] [--admin-email E] [--signup closed|open] ...
    crowdcad_app.py add-user EMAIL [--admin]      prints a generated password once
    crowdcad_app.py remove [--purge]              --purge also deletes pb_data (all CrowdCAD data)
    crowdcad_app.py status

Stdlib only (system python3); git and Docker Compose v2 do the rest.
"""

import argparse
import hashlib
import json
import os
import secrets as tokens
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

LOG = "==>"
DEFAULT_HOME = "/opt/crowdcad-tak"
DEFAULT_REPO = "https://github.com/evanqua/crowdcad.git"
# The release the bridge's mapping was checked against (docs/ICD.md + src/app/types.ts).
DEFAULT_REF = "v1.6.0"
DEFAULT_WEB_PORT = 3100       # infra-TAK's TAK Portal already has 3000
DEFAULT_PB_PORT = 8090
PROJECT = "crowdcad"
PB_CONTAINER = "crowdcad-pocketbase"
NODE_IMAGE = "node:22-alpine"  # runs CrowdCAD's provisioning script (it needs Node ≥ 22 fetch)
# v1.6.0's Dockerfile COPYs next-env.d.ts, which the tag doesn't contain (fixed upstream after
# the tag). This is the file Next.js itself generates; types only, no effect on the build output.
NEXT_ENV_D_TS = ('/// <reference types="next" />\n/// <reference types="next/image-types/global" />\n\n'
                 "// NOTE: This file should not be edited\n")


def log(message):
    print(f"{LOG} {message}", flush=True)


def warn(message):
    print(f"    ⚠ {message}", file=sys.stderr, flush=True)


class AppError(RuntimeError):
    pass


# --- files -------------------------------------------------------------------------------------

def paths(home):
    base = os.path.join(home, "crowdcad")
    return {
        "base": base,
        "src": os.path.join(base, "src"),
        "compose": os.path.join(base, "docker-compose.yml"),
        "pb_data": os.path.join(base, "pb_data"),
        "pb_hooks": os.path.join(base, "pb_hooks"),
        "app": os.path.join(base, "app.json"),
        "credentials": os.path.join(base, "credentials.json"),
    }


def read_json(path):
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
            return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, value, mode, like=None):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.chmod(tmp, mode)
    if like and os.path.exists(like):
        stat = os.stat(like)
        try:
            os.chown(tmp, stat.st_uid, stat.st_gid)
        except PermissionError:
            pass
    os.replace(tmp, path)


def new_password():
    # URL-safe: no $, # or spaces, which Docker Compose / shells would mangle.
    return tokens.token_urlsafe(18)


def credentials(path, host, admin_email=None):
    """Generated once and then kept: re-running install never changes a password."""
    creds = read_json(path)
    changed = False
    defaults = {
        "superuser": {"email": admin_email or f"admin@{host}"},
        "admin": {"email": admin_email or f"admin@{host}"},
        "bridge": {"email": f"crowdcad-bridge@{host}"},
    }
    for role, value in defaults.items():
        entry = creds.get(role) if isinstance(creds.get(role), dict) else {}
        if not entry.get("email"):
            entry["email"], changed = value["email"], True
        if not entry.get("password"):
            entry["password"], changed = new_password(), True
        creds[role] = entry
    if changed:
        write_json(path, creds, 0o600)
    return creds


def compose_spec(host, ref, web_port, pb_port):
    """Docker Compose file as JSON (valid YAML). Differs from CrowdCAD's own compose file in:
    loopback-only ports (Caddy is the only way in), web on web_port not 3000, PocketBase
    selected and its public URL baked in at build time, unique container names."""
    return {
        "x-generated-by": "TAK-PluginSuite-CrowdCAD infratak/crowdcad_app.py — edit there, not here",
        "name": PROJECT,
        "services": {
            "pocketbase": {
                "build": {"context": "./src", "dockerfile": "Dockerfile.pocketbase"},
                "image": f"crowdcad-pocketbase:{ref}",
                "container_name": PB_CONTAINER,
                "restart": "unless-stopped",
                "ports": [f"127.0.0.1:{pb_port}:8090"],
                "volumes": ["./pb_data:/pb/pb_data", "./pb_hooks:/pb/pb_hooks:ro"],
            },
            "web": {
                "build": {
                    "context": "./src",
                    "dockerfile": "Dockerfile",
                    "args": {
                        "NEXT_PUBLIC_BACKEND": "pocketbase",
                        "NEXT_PUBLIC_POCKETBASE_URL": f"https://{host}",
                    },
                },
                "image": f"crowdcad-web:{ref}",
                "container_name": "crowdcad-web",
                "restart": "unless-stopped",
                "depends_on": ["pocketbase"],
                "ports": [f"127.0.0.1:{web_port}:3000"],
                "environment": {
                    "NODE_ENV": "production",
                    "NEXT_TELEMETRY_DISABLED": "1",
                    "DISABLE_TELEMETRY": "true",
                },
            },
        },
    }


# --- PocketBase REST ---------------------------------------------------------------------------

class PocketBaseAdmin:
    def __init__(self, base_url, email, password, timeout=15):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.token = self._call("POST", "/api/collections/_superusers/auth-with-password",
                                {"identity": email, "password": password})["token"]

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if getattr(self, "token", None):
            request.add_header("Authorization", self.token)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:500]
            raise AppError(f"PocketBase {method} {path}: HTTP {error.code} {detail}") from None
        return json.loads(raw) if raw else {}

    def find_user(self, email):
        query = urllib.parse.urlencode({"filter": f'email="{email}"', "perPage": 1})
        items = self._call("GET", f"/api/collections/users/records?{query}").get("items") or []
        return items[0] if items else None

    def ensure_user(self, email, password, admin=False, name=None, reset_password=False):
        """Create the user (verified) if missing. An existing user keeps their password unless
        reset_password (the bridge's own account, so its stored secret stays the truth)."""
        user = self.find_user(email)
        if user is None:
            body = {"email": email, "password": password, "passwordConfirm": password,
                    "verified": True, "emailVisibility": False, "isAdmin": bool(admin)}
            if name:
                body["name"] = name
            self._call("POST", "/api/collections/users/records", body)
            return "created"
        patch = {}
        if admin and not user.get("isAdmin"):
            patch["isAdmin"] = True
        if reset_password:
            patch.update({"password": password, "passwordConfirm": password})
        if patch:
            self._call("PATCH", f"/api/collections/users/records/{user['id']}", patch)
            return "updated"
        return "unchanged"

    def set_signup(self, open_signup):
        """CrowdCAD's own users createRule (setup-pocketbase.js) when open; superuser-only when
        closed. setup-pocketbase.js re-opens it on every run, so install re-applies this after."""
        rule = "(@request.body.isAdmin:isset = false || @request.body.isAdmin = false)" if open_signup else None
        self._call("PATCH", "/api/collections/users", {"createRule": rule})


def can_sign_in(base_url, email, password, timeout=10):
    """Whether a CrowdCAD user's password already works (so install leaves it alone)."""
    body = json.dumps({"identity": email, "password": password}).encode()
    request = urllib.request.Request(base_url.rstrip("/") + "/api/collections/users/auth-with-password",
                                     data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return bool(json.loads(response.read() or b"{}").get("token"))
    except (urllib.error.URLError, OSError, ValueError):
        return False


def build_fingerprint(spec, src):
    """What the images were built from: each service's build section (the public URL is baked
    into the web image) and the exact CrowdCAD commit. Ports and volumes aren't in it: changing
    those recreates a container, never rebuilds. Same fingerprint + images present = no rebuild."""
    commit = subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    builds = {name: {"build": svc.get("build"), "image": svc.get("image")} for name, svc in spec["services"].items()}
    return hashlib.sha256((json.dumps(builds, sort_keys=True) + commit).encode()).hexdigest()


HOOK_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pb_hooks", "crowdcad_tak.pb.js")


def install_hooks(target):
    """Copy our PocketBase hook in (PocketBase reloads pb_hooks on change by itself)."""
    os.makedirs(target, exist_ok=True)
    source = HOOK_SOURCE if os.path.exists(HOOK_SOURCE) else None
    if not source:
        warn(f"{HOOK_SOURCE} missing: native TAK dispatch falls back to read-then-write")
        return
    with open(source, encoding="utf-8") as stream:
        text = stream.read()
    path = os.path.join(target, os.path.basename(source))
    try:
        with open(path, encoding="utf-8") as stream:
            if stream.read() == text:
                return
    except OSError:
        pass
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.chmod(path, 0o644)


def images_present(ref):
    return all(subprocess.run(["docker", "image", "inspect", f"{name}:{ref}"], capture_output=True).returncode == 0
               for name in ("crowdcad-web", "crowdcad-pocketbase"))


def wait_healthy(base_url, seconds=120):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url.rstrip("/") + "/api/health", timeout=5) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    return False


# --- bridge settings ---------------------------------------------------------------------------

def seed_bridge(data_dir, pb_url, identity, password, app_url=None):
    """Point the bridge at this CrowdCAD (and the web clients' Dispatch button at its site),
    unless someone already pointed it elsewhere on the console page. Returns True if anything
    changed (the bridge then needs a restart)."""
    config_path = os.path.join(data_dir, "config.json")
    secrets_path = os.path.join(data_dir, "secrets.json")
    config, secrets = read_json(config_path), read_json(secrets_path)
    current = (config.get("crowdcad_url") or "").rstrip("/")
    if current and current != pb_url:
        return False
    wanted_app = config.get("crowdcad_app_url") or app_url or ""
    if (current == pb_url and config.get("crowdcad_identity") == identity
            and secrets.get("crowdcad_password") == password
            and (config.get("crowdcad_app_url") or "") == wanted_app):
        return False
    config.update({"crowdcad_url": pb_url, "crowdcad_identity": identity, "crowdcad_app_url": wanted_app})
    secrets["crowdcad_password"] = password
    write_json(config_path, config, 0o640, like=config_path)
    write_json(secrets_path, secrets, 0o600, like=secrets_path)
    return True


# --- commands ----------------------------------------------------------------------------------

def run(cmd, **kwargs):
    kwargs.setdefault("check", True)
    return subprocess.run(cmd, **kwargs)


def require_tools():
    for tool in ("git", "docker"):
        if not shutil.which(tool):
            raise AppError(f"{tool} not found. Install it (infra-TAK hosts already have Docker), then re-run.")
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0:
        raise AppError("Docker Compose v2 (`docker compose`) not found.")


def checkout(src, repo, ref):
    have = subprocess.run(["git", "-C", src, "describe", "--tags", "--exact-match"],
                          capture_output=True, text=True).stdout.strip() if os.path.isdir(os.path.join(src, ".git")) else ""
    if have == ref:
        log(f"CrowdCAD {ref} source already in place")
    else:
        log(f"Fetching CrowdCAD {ref} from {repo}")
        shutil.rmtree(src, ignore_errors=True)
        run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1",
             "--branch", ref, repo, src])
    next_env = os.path.join(src, "next-env.d.ts")
    if not os.path.exists(next_env):
        with open(next_env, "w", encoding="utf-8") as stream:
            stream.write(NEXT_ENV_D_TS)


def provision_schema(src, pb_url, superuser):
    """CrowdCAD's own setup-pocketbase.js (collections + access rules), in a throwaway Node
    container on the host network. The password goes in by environment, not argv."""
    env = {**os.environ, "PB_URL": pb_url, "PB_ADMIN_EMAIL": superuser["email"],
           "PB_ADMIN_PASSWORD": superuser["password"]}
    run(["docker", "run", "--rm", "--network", "host",
         "-e", "PB_URL", "-e", "PB_ADMIN_EMAIL", "-e", "PB_ADMIN_PASSWORD",
         "-v", f"{os.path.join(src, 'scripts')}:/scripts:ro", NODE_IMAGE,
         "node", "/scripts/setup-pocketbase.js"], env=env, stdout=subprocess.DEVNULL)


def cmd_install(args):
    require_tools()
    p = paths(args.home)
    os.makedirs(p["base"], exist_ok=True)
    os.makedirs(p["pb_data"], exist_ok=True)
    install_hooks(p["pb_hooks"])
    checkout(p["src"], args.repo, args.ref)
    creds = credentials(p["credentials"], args.host, args.admin_email)
    spec = compose_spec(args.host, args.ref, args.web_port, args.pb_port)
    write_json(p["compose"], spec, 0o644)

    # Rebuild only when something baked into the images changed: a re-run must not restart a
    # CrowdCAD that dispatchers are using (and Docker's build cache can't be relied on for that).
    fingerprint = build_fingerprint(spec, p["src"])
    up = ["docker", "compose", "-f", p["compose"], "up", "-d", "--quiet-pull"]
    if args.rebuild or read_json(p["app"]).get("build") != fingerprint or not images_present(args.ref):
        log(f"Building and starting CrowdCAD {args.ref} (first build takes several minutes)")
        up.append("--build")
    else:
        log(f"CrowdCAD {args.ref} images current (no rebuild; --crowdcad-rebuild forces one)")
    run(up, stdout=None if args.verbose else subprocess.DEVNULL)
    pb_url = f"http://127.0.0.1:{args.pb_port}"
    if not wait_healthy(pb_url):
        raise AppError(f"PocketBase didn't come up on {pb_url}: docker logs {PB_CONTAINER}")

    superuser = creds["superuser"]
    run(["docker", "exec", PB_CONTAINER, "/pb/pocketbase", "superuser", "upsert",
         superuser["email"], superuser["password"], "--dir=/pb/pb_data"], stdout=subprocess.DEVNULL)
    log("Creating CrowdCAD collections and access rules (setup-pocketbase.js)")
    provision_schema(p["src"], pb_url, superuser)

    pb = PocketBaseAdmin(pb_url, superuser["email"], superuser["password"])
    pb.set_signup(args.signup == "open")
    admin, bridge = creds["admin"], creds["bridge"]
    log(f"CrowdCAD admin {admin['email']}: {pb.ensure_user(admin['email'], admin['password'], admin=True, name='Admin')}")
    reset = not can_sign_in(pb_url, bridge["email"], bridge["password"])
    log(f"Bridge account {bridge['email']}: "
        f"{pb.ensure_user(bridge['email'], bridge['password'], name='TAK bridge', reset_password=reset)}")

    write_json(p["app"], {"host": args.host, "ref": args.ref, "repo": args.repo, "web_port": args.web_port,
                          "pb_port": args.pb_port, "signup": args.signup, "build": fingerprint}, 0o644)
    if args.data and os.path.isdir(args.data):
        if seed_bridge(args.data, pb_url, bridge["email"], bridge["password"], f"https://{args.host}"):
            log("Bridge pointed at this CrowdCAD")
            print("BRIDGE_CHANGED")
        else:
            current = read_json(os.path.join(args.data, "config.json")).get("crowdcad_url")
            if current and current.rstrip("/") != pb_url:
                warn(f"Bridge left pointing at {current} (set on the console page). "
                     f"This CrowdCAD's PocketBase is {pb_url}, account in {p['credentials']}.")
    return 0


def cmd_add_user(args):
    p = paths(args.home)
    app, creds = read_json(p["app"]), read_json(p["credentials"])
    if not app or not creds.get("superuser"):
        raise AppError("CrowdCAD isn't installed here (install.sh --with-crowdcad).")
    pb = PocketBaseAdmin(f"http://127.0.0.1:{app.get('pb_port', DEFAULT_PB_PORT)}",
                         creds["superuser"]["email"], creds["superuser"]["password"])
    password = new_password()
    result = pb.ensure_user(args.email, password, admin=args.admin, name=args.name)
    if result == "created":
        print(f"Created {args.email}{' (admin)' if args.admin else ''}. Password (shown once): {password}")
        print(f"Sign in at https://{app.get('host')} and change it under Profile.")
    else:
        print(f"{args.email} already exists ({result}); password unchanged.")
    return 0


def cmd_remove(args):
    p = paths(args.home)
    if os.path.exists(p["compose"]):
        run(["docker", "compose", "-f", p["compose"], "down", "--remove-orphans"], check=False)
    if args.purge:
        app = read_json(p["app"])
        ref = app.get("ref", DEFAULT_REF)
        subprocess.run(["docker", "image", "rm", f"crowdcad-web:{ref}", f"crowdcad-pocketbase:{ref}"],
                       capture_output=True)
        shutil.rmtree(p["base"], ignore_errors=True)
        log(f"Removed CrowdCAD and its data ({p['base']}).")
    else:
        log(f"CrowdCAD stopped. Data kept in {p['pb_data']} (--purge deletes it).")
    return 0


def cmd_status(args):
    p = paths(args.home)
    app = read_json(p["app"])
    if not app:
        print("CrowdCAD: not installed on this host")
        return 1
    pb_ok = wait_healthy(f"http://127.0.0.1:{app.get('pb_port', DEFAULT_PB_PORT)}", seconds=3)
    print(f"CrowdCAD {app.get('ref')} at https://{app.get('host')}  ·  PocketBase "
          f"{'up' if pb_ok else 'DOWN'}  ·  sign-up {app.get('signup', 'closed')}  ·  data {p['pb_data']}")
    return 0 if pb_ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--home", default=os.environ.get("CROWDCAD_HOME", DEFAULT_HOME))
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install")
    install.add_argument("--host", required=True, help="public host, e.g. crowdcad.tak.example.org")
    install.add_argument("--ref", default=DEFAULT_REF)
    install.add_argument("--repo", default=DEFAULT_REPO)
    install.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT)
    install.add_argument("--pb-port", type=int, default=DEFAULT_PB_PORT)
    install.add_argument("--admin-email", default=None)
    install.add_argument("--signup", choices=("closed", "open"), default="closed")
    install.add_argument("--data", default=None, help="bridge data dir to point at this CrowdCAD")
    install.add_argument("--verbose", action="store_true")
    install.add_argument("--rebuild", action="store_true", help="rebuild the images even if current")
    add = sub.add_parser("add-user")
    add.add_argument("email")
    add.add_argument("--admin", action="store_true")
    add.add_argument("--name", default=None)
    remove = sub.add_parser("remove")
    remove.add_argument("--purge", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    if args.command == "install" and args.admin_email == "":
        args.admin_email = None
    return {"install": cmd_install, "add-user": cmd_add_user, "remove": cmd_remove, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AppError, subprocess.CalledProcessError) as error:
        print(f"[crowdcad-tak] CrowdCAD app: {error}", file=sys.stderr)
        sys.exit(1)
