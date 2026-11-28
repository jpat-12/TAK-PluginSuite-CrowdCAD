"""CrowdCAD for TAK inside the infra-TAK console — attached at runtime, on any infra-TAK version.

attach() receives the console's freshly loaded `app` module and adds, *if the hook point
exists in this version*:

    app + login_required  →  /crowdcad: bridge status, unplaced calls/teams, settings form, and the
                             "Install CloudTAK plugin" button with its progress bar (tracker R41)
    detect_modules        →  a "CrowdCAD" module card on the console dashboard
    render_sidebar        →  a "CrowdCAD" link in the left nav

Same mechanism as InfraTAK-Plugin-Aleph (see crowdcad_infratak_boot.py for why app.py is never
patched). Each piece is wrapped separately so one failure can't take the others — or the
console — down. Runs inside the console's own Python: stdlib only, plus the Flask objects the
console hands us.

Root or not (tracker R43): infra-TAK 0.x runs the console as root; 10.x runs it as `takwerx`.
Everything that needs root — saving settings/secrets, installing a TAK client certificate,
starting the CloudTAK job — is a request to bin/crowdcad_admin.py (run directly by a root
console, by crowdcad-tak-admin.path otherwise) through <HOME>/console/. The page reads what it
shows from console/view.json, which that helper writes.
"""

import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import base64
import time
import urllib.parse
import urllib.request
import uuid

HOME = os.environ.get("CROWDCAD_TAK_HOME", "/opt/crowdcad-tak")
DATA_DIR = os.path.join(HOME, "data")
CONSOLE_DIR = os.path.join(HOME, "console")      # requests/answers/view shared with the root helper (R43)
ADMIN = os.path.join(HOME, "bin", "crowdcad_admin.py")
UNIT = "/etc/systemd/system/crowdcad-tak.service"
SERVICE_USER = "crowdcad-tak"

_status_cache = {"at": 0.0, "value": None}


def _log(message):
    print(f"[crowdcad-tak] {message}", file=sys.stderr, flush=True)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
            return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, value, mode):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
    try:
        import pwd  # POSIX only; the hook is also imported by tests on Windows
        user = pwd.getpwnam(SERVICE_USER)
        os.chown(tmp, user.pw_uid, user.pw_gid)
    except (ImportError, KeyError, OSError):
        pass  # dev box / not installed: the file still lands, the service just can't read it
    os.replace(tmp, path)


def _write_console_file(path, text):
    """A file the console (maybe non-root) reads: 0640, group = the console dir's group (setgid)."""
    tmp = path + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640), "w", encoding="utf-8") as stream:
        stream.write(text)
    try:
        os.chown(tmp, -1, os.stat(os.path.dirname(path)).st_gid)
    except (AttributeError, OSError):
        pass
    os.replace(tmp, path)


_ADMIN_INLINE = None   # tests set this to crowdcad_admin.run


def _is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _admin(action, payload=None, timeout=45, wait=True):
    """Ask the root helper (tracker R43). → {"ok": bool, "message": str, ...}."""
    if not os.path.isdir(CONSOLE_DIR):
        if not _is_root():
            return {"ok": False, "message": "This CrowdCAD install predates the console helper — re-run "
                                            "sudo bash /opt/crowdcad-tak/src/install.sh on the server."}
        os.makedirs(CONSOLE_DIR, mode=0o2770, exist_ok=True)
    rid = uuid.uuid4().hex
    req = os.path.join(CONSOLE_DIR, rid + ".req")
    res = os.path.join(CONSOLE_DIR, rid + ".res")
    tmp = req + ".tmp"   # not *.req until complete, so the path unit never sees half a file
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as stream:
        json.dump({"action": action, "payload": payload or {}}, stream)
    os.replace(tmp, req)
    if _ADMIN_INLINE is not None:            # tests: run the helper in-process
        _ADMIN_INLINE(req)
    elif _is_root() and os.path.exists(ADMIN):
        subprocess.run([sys.executable, ADMIN, "run", req], capture_output=True, timeout=max(timeout, 30))
    if not wait:
        return {"ok": True, "message": "queued"}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(res):
            answer = _read_json(res)
            try:
                os.remove(res)
            except OSError:
                pass
            return answer or {"ok": False, "message": "empty answer from the helper"}
        time.sleep(0.25)
    try:
        os.remove(req)
    except OSError:
        pass
    return {"ok": False, "message": "The CrowdCAD helper didn't answer. On the server: "
                                    "systemctl status crowdcad-tak-admin.path (re-run install.sh if it's missing)."}


def _view(refresh=False):
    """(config, secrets-for-display, cert info) for the page (R43): direct for a root console,
    else console/view.json from the helper (refreshed in the background on each page load)."""
    if refresh:
        try:
            _admin("view", wait=_is_root(), timeout=10)
        except Exception as error:
            _log(f"view refresh skipped: {error!r}")
    view = _read_json(os.path.join(CONSOLE_DIR, "view.json"))
    if _is_root() and not view:
        return (_read_json(os.path.join(DATA_DIR, "config.json")),
                _read_json(os.path.join(DATA_DIR, "secrets.json")), {})
    return view.get("config") or {}, view.get("secrets") or {}, view.get("cert") or {}


def _service_status(fresh=False):
    """(installed, running, detail) — cached 10 s; detect_modules runs on every page load."""
    if not fresh and time.monotonic() - _status_cache["at"] < 10 and _status_cache["value"]:
        return _status_cache["value"]
    installed = os.path.exists(UNIT)
    running, detail = False, {}
    if installed:
        listen = _read_json(os.path.join(DATA_DIR, "config.json")).get("status_listen") or "127.0.0.1:8782"
        try:
            with urllib.request.urlopen(f"http://{listen}/status", timeout=1.5) as response:
                detail = json.loads(response.read())
                running = True
        except Exception:
            running = False
    _status_cache.update(at=time.monotonic(), value=(installed, running, detail))
    return installed, running, detail


def module_entry():
    installed, running, _ = _service_status()
    return {"name": "CrowdCAD", "installed": installed, "running": running,
            "description": "Event medical dispatch (CrowdCAD) on the TAK map: calls, teams, venue zones",
            "icon": "\U0001F691", "route": "/crowdcad", "priority": 15}


# --- hook points --------------------------------------------------------------------------

def _wrap_detect_modules(g):
    original = g["detect_modules"]
    if getattr(original, "_crowdcad", False):
        return
    def detect_modules(*args, **kwargs):
        modules = original(*args, **kwargs)
        try:
            modules["crowdcad"] = module_entry()
            modules = dict(sorted(modules.items(), key=lambda item: item[1].get("priority", 99)))
        except Exception as error:
            _log(f"module card skipped: {error!r}")
        return modules
    detect_modules._crowdcad = True
    g["detect_modules"] = detect_modules


def _wrap_render_sidebar(g):
    original = g["render_sidebar"]
    if getattr(original, "_crowdcad", False):
        return
    def render_sidebar(modules, active_path, *args, **kwargs):
        markup = original(modules, active_path, *args, **kwargs)
        try:
            if (modules or {}).get("crowdcad", {}).get("installed") and "</nav>" in markup \
                    and 'href="/crowdcad"' not in markup:
                active = " active" if (active_path or "").strip("/").startswith("crowdcad") else ""
                link = (f'<a href="/crowdcad" class="nav-item{active}" title="CrowdCAD for TAK">'
                        '<span class="nav-icon material-symbols-outlined">ambulance</span>CrowdCAD</a>\n')
                cut = markup.rindex("</nav>")
                markup = markup[:cut] + "  " + link + markup[cut:]
        except Exception as error:
            _log(f"sidebar link skipped: {error!r}")
        return markup
    render_sidebar._crowdcad = True
    g["render_sidebar"] = render_sidebar


# --- the /crowdcad page ---------------------------------------------------------------------

STYLE = """:root{--bg-deep:#080b14;--bg-surface:#0f1219;--bg-card:#161b26;--border:#1e2736;--text-primary:#f1f5f9;--text-secondary:#cbd5e1;--text-dim:#94a3b8;--cyan:#06b6d4;--green:#10b981;--red:#ef4444;--yellow:#eab308}
*{box-sizing:border-box;margin:0;padding:0}body{background:var(--bg-deep);color:var(--text-primary);font-family:'DM Sans',sans-serif;min-height:100vh;display:flex}
.sidebar{width:220px;min-width:220px;background:var(--bg-surface);border-right:1px solid var(--border);padding:24px 0;display:flex;flex-direction:column}
.material-symbols-outlined{font-family:'Material Symbols Outlined';font-size:20px;line-height:1;-webkit-font-smoothing:antialiased}
.sidebar-logo{padding:0 20px 24px;border-bottom:1px solid var(--border);margin-bottom:16px}.sidebar-logo span{font-size:15px;font-weight:700}.sidebar-logo small{display:block;font-size:10px;color:var(--text-dim);font-family:'JetBrains Mono',monospace}
.nav-item{display:flex;align-items:center;gap:10px;padding:9px 20px;color:var(--text-secondary);text-decoration:none;font-size:13px;font-weight:500;border-left:2px solid transparent}
.nav-item:hover{color:var(--text-primary);background:rgba(255,255,255,.03)}.nav-item.active{color:var(--cyan);background:rgba(6,182,212,.06);border-left-color:var(--cyan)}
.nav-icon{font-size:15px;width:18px;text-align:center}.main{flex:1;min-width:0;padding:32px;overflow-y:auto;max-width:1100px}
h1{font-size:22px}h2{font-size:15px;margin-bottom:12px}.sub{color:var(--text-secondary);font-size:13px;margin:4px 0 24px}
.banner{padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:13px}
.ok{background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.2);color:var(--green)}.bad{background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.25);color:var(--red)}.warn{background:rgba(234,179,8,.08);border:1px solid rgba(234,179,8,.25);color:var(--yellow)}
.card{background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px}.item{background:#0a0e1a;border-radius:8px;padding:12px 14px}
.label{font-size:11px;color:var(--text-dim);text-transform:uppercase;margin-bottom:3px}.value{font-family:'JetBrains Mono',monospace;font-size:13px;word-break:break-all}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--border)}th{color:var(--text-dim);font-weight:500}
form label{display:block;font-size:12px;color:var(--text-dim);margin:12px 0 4px}input[type=text],input[type=password],textarea{width:100%;background:#0a0e1a;border:1px solid var(--border);color:var(--text-primary);border-radius:6px;padding:8px;font-family:'JetBrains Mono',monospace;font-size:12px}
.checks label{display:inline-flex;gap:6px;margin-right:16px;color:var(--text-secondary)}
.btn{margin-top:16px;padding:10px 18px;border:0;border-radius:8px;background:var(--cyan);color:#001;font-weight:600;font-size:13px;cursor:pointer}
.dim{color:var(--text-dim);font-size:12px;margin-top:8px}code{font-family:'JetBrains Mono',monospace;font-size:12px}"""

HEAD = ('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '<title>CrowdCAD — infra-TAK</title>'
        '<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">'
        '<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0" rel="stylesheet">'
        f'<style>{STYLE}</style></head><body>')

E = html.escape


def _when(ms):
    return time.strftime("%H:%M:%S", time.localtime(ms / 1000)) if ms else "—"


def _status_html(installed, running, detail):
    if not installed:
        return '<div class="banner bad">● Bridge not installed — run <code>sudo bash infratak/install.sh</code></div>'
    if not running:
        return '<div class="banner bad">● Installed but not responding — <code>journalctl -u crowdcad-tak -n 50</code></div>'
    if detail.get("configured") is False:
        return '<div class="banner warn">● Running, waiting for settings — fill in CrowdCAD below</div>'
    cc, tak = detail.get("crowdcad") or {}, detail.get("tak") or {}
    mode = cc.get("mode")
    cc_text = {"live": "live (realtime)", "polling": "polling — realtime unavailable",
               "down": "unreachable", "starting": "connecting"}.get(mode, mode or "?")
    healthy = mode == "live" and tak.get("connected")
    out = [f'<div class="banner {"ok" if healthy else "warn"}">● CrowdCAD {E(cc_text)} · TAK '
           f'{"connected" if tak.get("connected") else "not connected"}</div>',
           '<div class="card"><div class="grid">',
           f'<div class="item"><div class="label">CrowdCAD</div><div class="value">{E(cc.get("url") or "—")}</div></div>',
           f'<div class="item"><div class="label">Last full sync</div><div class="value">{_when(cc.get("last_sync"))}</div></div>',
           f'<div class="item"><div class="label">TAK Server</div><div class="value">{E(tak.get("host") or "—")} · {int(tak.get("sent") or 0)} sent</div></div>',
           f'<div class="item"><div class="label">Bridge version</div><div class="value">{E(str(detail.get("version", "—")))}</div></div>',
           '</div>']
    for label, value in (("CrowdCAD error", cc.get("last_error")), ("TAK error", tak.get("last_error"))):
        if value:
            out.append(f'<div class="dim">{label}: <code>{E(str(value))}</code></div>')
    out.append("</div>")
    events = detail.get("events") or []
    out.append('<div class="card"><h2>Events on the map</h2>')
    if not events:
        out.append('<div class="dim">No active CrowdCAD events selected.</div>')
    else:
        out.append("<table><tr><th>Event</th><th>Calls</th><th>Teams</th><th>Zones</th><th>Not on the map</th></tr>")
        for event in events:
            counts = event.get("counts") or {}
            missing = "<br>".join(f'{E(u["kind"])} <b>{E(u["label"])}</b> at “{E(u["location"])}”'
                                  for u in event.get("unplaced") or []) or "—"
            out.append(f'<tr><td>{E(event.get("name") or "")}<div class="dim">{E(event.get("id") or "")}</div></td>'
                       f'<td>{counts.get("incident", 0)}</td><td>{counts.get("unit", 0)}</td>'
                       f'<td>{counts.get("zone", 0)}</td><td>{missing}</td></tr>')
        out.append("</table><div class=\"dim\">Calls and teams can only be placed when their location is a post on a "
                   "venue layer with map bounds (GeoJSON-imported, or bounds set below).</div>")
    out.append("</div>")
    return "".join(out)


def _settings_html(cfg, secrets, saved):
    publish = cfg.get("publish") or {}
    events = cfg.get("events", "active")
    team_lines = "\n".join(f"{k} = {v}" for k, v in sorted((cfg.get("team_uids") or {}).items()))
    checks = "".join(
        f'<label><input type="checkbox" name="publish_{key}"{" checked" if publish.get(key, default) else ""}> {label}</label>'
        for key, label, default in (("calls", "Calls", True), ("teams", "Teams", True), ("zones", "Zones", True),
                                    ("posts", "Posts", False), ("clinic_walkups", "Clinic walk-ups", False)))
    return f"""<div class="card"><h2>Settings</h2>{'<div class="banner ok">Saved — bridge restarted.</div>' if saved else ''}
<form method="post" action="/crowdcad/settings">
<label>CrowdCAD PocketBase URL (what CrowdCAD's NEXT_PUBLIC_POCKETBASE_URL points at)</label>
<input type="text" name="crowdcad_url" value="{E(cfg.get('crowdcad_url') or '')}" placeholder="https://crowdcad.example.org or http://127.0.0.1:8090">
<label>CrowdCAD app URL — the site dispatchers sign in to; enables the Dispatch button in CloudTAK and WebTAK</label>
<input type="text" name="crowdcad_app_url" value="{E(cfg.get('crowdcad_app_url') or '')}" placeholder="https://crowdcad.example.org">
<label>Bridge account (a CrowdCAD user; read-only use)</label>
<input type="text" name="crowdcad_identity" value="{E(cfg.get('crowdcad_identity') or '')}" placeholder="tak-bridge@example.org">
<label>Password {'(set — leave blank to keep)' if secrets.get('crowdcad_password') else ''}</label>
<input type="password" name="crowdcad_password" autocomplete="new-password">
<label>Events: <code>active</code> for every active event, or event ids separated by commas</label>
<input type="text" name="events" value="{E(events if isinstance(events, str) else ', '.join(events))}">
<label>Publish to TAK</label><div class="checks">{checks}</div>
<label>Teams carried by their own ATAK device — one per line: <code>Team 1 = ANDROID-abc123</code></label>
<textarea name="team_uids" rows="4">{E(team_lines)}</textarea>
<label>Map bounds for layers without GeoJSON import — JSON: <code>{{"layer-id": {{"north": .., "south": .., "east": .., "west": ..}}}}</code></label>
<textarea name="layer_bounds" rows="3">{E(json.dumps(cfg.get('layer_bounds') or {}))}</textarea>
<label>WebTAK page origins allowed to read the board — one per line (CloudTAK doesn't need one)</label>
<textarea name="cors_origins" rows="3">{E(chr(10).join(cfg.get('cors_origins') or []))}</textarea>
<button class="btn" type="submit">Save and restart bridge</button></form>
<div class="dim">Patient fields (age, sex, notes, call log) never leave CrowdCAD — see the repo's docs/COT_FORMAT.md.</div></div>
{_clients_html(cfg, secrets)}"""


def _clients_html(cfg, secrets):
    url = cfg.get("public_url") or ""
    token = secrets.get("board_token") or ""
    return f"""<div class="card"><h2>Clients</h2><div class="grid">
<div class="item"><div class="label">ATAK</div><div class="value">CrowdCAD APK — reads the bridge's CoT; nothing to configure</div></div>
<div class="item"><div class="label">Board URL (CloudTAK / WebTAK)</div><div class="value">{E(url or "not published — needs an FQDN and Caddy")}</div></div>
</div>
<details class="dim"><summary>Board token</summary><code>{E(token or "none — re-run install.sh")}</code>
<div>Read-only and patient-data-free, but treat it as a secret. The installer bakes it into the CloudTAK
server config and the WebTAK bundle (<code>install.sh --cloudtak --webtak</code>). To rotate: remove
<code>board_token</code> from /opt/crowdcad-tak/data/secrets.json and re-run that command.</div></details></div>"""


# --- "Install CloudTAK plugin" button (tracker R41) ------------------------------------------
# The job is bin/crowdcad_cloudtak_job.sh in a transient systemd unit (so a 5–15 min CloudTAK
# rebuild survives the console restarting); it writes data/cloudtak-install.log, and the
# progress bar is drawn from that log's "==> " marker lines. The unit name doubles as the
# one-job-at-a-time lock.

JOB_UNIT = "crowdcad-cloudtak-install"
_job_proc = {"p": None}      # fallback when there's no systemd-run (dev boxes); never on infra-TAK

# (step key, label, percent when reached, marker prefixes) — keep in step with the job script header.
_PROGRESS_STEPS = [
    ("start", "Starting", 2, ("==> Job started",)),
    ("detect", "Found CloudTAK", 8, ("==> CloudTAK ",)),
    ("backup", "Backed up the current plugin", 15, ("==> Backed up", "==> Nothing to back up")),
    ("copy", "Plugin files copied", 25, ("==> Installed web half",)),
    ("build", "Rebuilding CloudTAK (5–15 min)", 30, ("==> Rebuilding",)),
    ("restart", "Restarting CloudTAK", 88, ("==> Restarting",)),
    ("health", "Checking CloudTAK is back up", 92, ("==> Done",)),
    ("healthy", "Installed — CloudTAK is up", 100, ("==> Healthy",)),
]
_BUILD_FROM, _BUILD_TO = 30, 86
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_BUILD_STEP = re.compile(r"\[(?:[\w.-]+ )?\s*(\d+)/(\d+)\]")
_EXIT = re.compile(r"^==> EXIT (\d+)")


def _job_log():
    # console/ so a non-root console can read it (R43); data/ on installs from before the helper.
    return os.path.join(CONSOLE_DIR if os.path.isdir(CONSOLE_DIR) else DATA_DIR, "cloudtak-install.log")


def _job_active():
    """Is an install job running right now? Asked only while the log has no EXIT line."""
    proc = _job_proc["p"]
    if proc is not None and proc.poll() is None:
        return True
    if shutil.which("systemctl"):
        return subprocess.run(["systemctl", "is-active", "--quiet", JOB_UNIT],
                              capture_output=True, timeout=10).returncode == 0
    return False


def _parse_progress(text, active):
    """Log text → {state: idle|running|done|failed, step, label, percent, error, tail}. Pure."""
    if text is None:
        return {"state": "idle", "step": None, "label": "", "percent": 0, "error": "", "tail": []}
    lines = [_ANSI.sub("", raw).rstrip("\r") for raw in text.splitlines()]
    step, label, percent, building, exit_code, error = None, "", 0, False, None, ""
    for line in lines:
        for key, text_label, pct, markers in _PROGRESS_STEPS:
            if line.startswith(markers):
                step, label, percent = key, text_label, max(percent, pct)
                building = key == "build"
        if building:
            match = _BUILD_STEP.search(line)
            if match and int(match.group(2)) > 0:
                done, total = int(match.group(1)), int(match.group(2))
                within = _BUILD_FROM + (_BUILD_TO - _BUILD_FROM) * min(done, total) / total
                percent = max(percent, int(within))
                label = f"Rebuilding CloudTAK — build step {done} of {total}"
        if line.startswith("==> ERROR"):
            error = line[len("==> ERROR"):].strip()
        match = _EXIT.match(line)
        if match:
            exit_code = int(match.group(1))
    tail = [line for line in lines if line.strip()][-40:]
    if exit_code == 0:
        state, percent, label = "done", 100, "Installed — CloudTAK is up"
    elif exit_code is not None:
        state = "failed"
        error = error or next((line for line in reversed(tail) if not line.startswith("==> EXIT")), "failed")
    elif active:
        state = "running"
    else:
        state, error = "failed", "the install job stopped without finishing (see the log below)"
    return {"state": state, "step": step, "label": label, "percent": min(percent, 100),
            "error": error, "tail": tail}


def _cloudtak_status():
    try:
        with open(_job_log(), encoding="utf-8", errors="replace") as stream:
            text = stream.read()
    except OSError:
        text = None
    active = False
    if text is not None and not any(_EXIT.match(line) for line in text.splitlines()):
        active = _job_active()
    return _parse_progress(text, active)


_SAFE_DIR = re.compile(r"^/[A-Za-z0-9._/-]+$")


def _start_job(ct_dir):
    """Start the install job. → None, or the reason it wasn't started."""
    if _cloudtak_status()["state"] == "running":
        return "An install is already running."
    script = os.path.join(HOME, "bin", "crowdcad_cloudtak_job.sh")
    log = _job_log()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(log, "w", encoding="utf-8") as stream:
        stream.write("==> Queued from the infra-TAK console\n")
    command = f"exec /bin/bash {shlex.quote(script)}"
    if ct_dir:
        command += f" {shlex.quote(ct_dir)}"
    command += f" >> {shlex.quote(log)} 2>&1"
    if shutil.which("systemd-run"):
        result = subprocess.run(["systemd-run", "--unit", JOB_UNIT, "--collect", "--quiet",
                                 f"--setenv=CROWDCAD_HOME={HOME}", "/bin/bash", "-c", command],
                                capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "systemd-run failed").strip()
            with open(log, "a", encoding="utf-8") as stream:
                stream.write(f"==> ERROR couldn't start the job: {message}\n==> EXIT 1\n")
            return f"Couldn't start the install job: {message}"
    else:
        _job_proc["p"] = subprocess.Popen(["/bin/bash", "-c", command], start_new_session=True,
                                          env={**os.environ, "CROWDCAD_HOME": HOME})
    _log(f"CloudTAK plugin install started{' for ' + ct_dir if ct_dir else ''}")
    return None


def _cloudtak_html(cfg, secrets):
    ready = bool(cfg.get("public_url") and secrets.get("board_token"))
    status = _cloudtak_status()
    initial = json.dumps(status).replace("<", "\\u003c")   # safe inside <script>; outside the f-string (py3.10)
    why = "" if ready else ('<div class="banner warn">The board isn\'t published yet (no public URL or board '
                            'token) — run the server install first.</div>')
    return f"""<div class="card" id="cc-cloudtak"><h2>CloudTAK plugin</h2>{why}
<div class="dim">Installs CrowdCAD Dispatch into the CloudTAK on this host: backs up the current plugin,
copies the new one in, rebuilds CloudTAK (5–15 min; CloudTAK is down for about 30 s at the end) and checks
it came back. Then, in each browser: CloudTAK → Settings → Refresh App.</div>
<form id="cc-ct-form" onsubmit="return ccStart(event)">
<label>CloudTAK directory (blank = the running CloudTAK)</label>
<input type="text" name="cloudtak_dir" value="{E(cfg.get('cloudtak_dir') or '')}" placeholder="/root/CloudTAK">
<button class="btn" id="cc-ct-btn" type="submit"{'' if ready else ' disabled'}>Install CloudTAK plugin</button></form>
<div id="cc-ct-progress" style="margin-top:16px;display:none">
<div class="label" id="cc-ct-label"></div>
<div style="background:#0a0e1a;border-radius:6px;height:12px;overflow:hidden;margin:6px 0">
<div id="cc-ct-bar" style="height:100%;width:0;background:var(--cyan);transition:width .6s"></div></div>
<div class="dim" id="cc-ct-error" style="color:var(--red)"></div>
<details class="dim"><summary>Install log</summary><pre id="cc-ct-log" style="white-space:pre-wrap;font-size:11px;max-height:260px;overflow:auto"></pre></details>
</div></div>
<script>
const ccInitial = {initial};
let ccTimer = null;
function ccShow(s) {{
  const box = document.getElementById('cc-ct-progress');
  if (s.state === 'idle') {{ box.style.display = 'none'; return; }}
  box.style.display = 'block';
  const bar = document.getElementById('cc-ct-bar');
  bar.style.width = s.percent + '%';
  bar.style.background = s.state === 'failed' ? 'var(--red)' : s.state === 'done' ? 'var(--green)' : 'var(--cyan)';
  document.getElementById('cc-ct-label').textContent =
    (s.state === 'failed' ? 'Failed' : s.state === 'done' ? 'Done' : 'Installing') + ' · ' + (s.label || '…') + ' · ' + s.percent + '%';
  document.getElementById('cc-ct-error').textContent = s.state === 'failed' ? s.error : '';
  document.getElementById('cc-ct-log').textContent = (s.tail || []).join('\\n');
  const running = s.state === 'running';
  document.getElementById('cc-ct-btn').disabled = running || {'false' if ready else 'true'};
  if (running && !ccTimer) ccTimer = setInterval(ccPoll, 2000);
  if (!running && ccTimer) {{ clearInterval(ccTimer); ccTimer = null; }}
}}
async function ccPoll() {{
  try {{ ccShow(await (await fetch('/crowdcad/cloudtak/status', {{credentials: 'same-origin'}})).json()); }}
  catch (e) {{ document.getElementById('cc-ct-label').textContent = 'Status unavailable — retrying…'; }}
}}
async function ccStart(event) {{
  event.preventDefault();
  document.getElementById('cc-ct-btn').disabled = true;
  const r = await fetch('/crowdcad/cloudtak/install', {{method: 'POST', credentials: 'same-origin',
    body: new FormData(document.getElementById('cc-ct-form'))}});
  const body = await r.json().catch(() => ({{}}));
  if (!r.ok) {{ ccShow({{state: 'failed', percent: 0, label: '', error: body.error || ('HTTP ' + r.status), tail: []}}); return false; }}
  ccShow(body.status); ccPoll(); return false;
}}
ccShow(ccInitial);
</script>"""


def _cert_html(cert, notice):
    """Tracker R43: upload the bridge's TAK client certificate (e.g. a TAK Portal integration's)."""
    now = (f'<div class="grid"><div class="item"><div class="label">Connects to TAK as</div><div class="value">'
           f'{E(cert.get("subject") or "—")}</div></div><div class="item"><div class="label">Expires</div>'
           f'<div class="value">{E(cert.get("expires") or "—")}</div></div><div class="item"><div class="label">'
           f'File</div><div class="value">{E(cert.get("path") or "—")}</div></div></div>')
    return f"""<div class="card" id="cc-cert"><h2>TAK certificate</h2>{notice}{now}
<div class="dim">On a TAK Server whose users come from TAK Portal / LDAP, the bridge's groups come from its
certificate's LDAP identity, so use a TAK Portal <b>Global</b> integration made for the bridge (in the medics'
group) — the certificate the installer makes with makeCert.sh has no LDAP identity there.
Upload its <code>.p12</code> (or the <code>.pem</code> + <code>.key</code>), and optionally the truststore.</div>
<form method="post" action="/crowdcad/cert" enctype="multipart/form-data">
<label>Client certificate (.p12)</label><input type="file" name="client_p12" accept=".p12,.pfx">
<label>— or — certificate (.pem) and key (.key)</label>
<input type="file" name="client_pem" accept=".pem,.crt"> <input type="file" name="client_key" accept=".key,.pem">
<label>Password (for the .p12, or for the key if it's encrypted)</label>
<input type="password" name="client_password" autocomplete="off">
<label>Truststore (.p12) or CA (.pem) — optional; leave empty to keep the current CA</label>
<input type="file" name="truststore_p12" accept=".p12,.pfx"> <input type="file" name="ca_pem" accept=".pem,.crt">
<label>Truststore password</label><input type="password" name="truststore_password" autocomplete="off" placeholder="often atakatak">
<button class="btn" type="submit">Install certificate and restart bridge</button></form>
<div class="dim">Checked before anything is replaced: the key must match the certificate and the passwords must
open them. The old files stay in /opt/crowdcad-tak/certs. If TAK still says not connected with a brand-new
integration, restart the bridge once more after a minute (TAK caches "no groups" on the first connection).</div></div>"""


def _parse_settings(form, cfg, secrets):
    """→ (config, secrets, error). Validates before anything is written."""
    cfg = dict(cfg)
    url = form.get("crowdcad_url", "").strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        return None, None, "CrowdCAD URL must start with http:// or https://"
    cfg["crowdcad_url"] = url
    app_url = form.get("crowdcad_app_url", "").strip().rstrip("/")
    if app_url and not app_url.startswith("https://"):
        return None, None, "CrowdCAD app URL must start with https:// (WebTAK and CloudTAK pages are HTTPS)"
    cfg["crowdcad_app_url"] = app_url
    cfg["crowdcad_identity"] = form.get("crowdcad_identity", "").strip()
    events = form.get("events", "").strip() or "active"
    cfg["events"] = "active" if events == "active" else [e.strip() for e in events.split(",") if e.strip()]
    cfg["publish"] = {key: form.get(f"publish_{key}") == "on"
                      for key in ("calls", "teams", "zones", "posts", "clinic_walkups")}
    teams = {}
    for line in form.get("team_uids", "").splitlines():
        if not line.strip():
            continue
        name, sep, uid = line.partition("=")
        if not sep or not name.strip() or not uid.strip():
            return None, None, f"Team line not 'Team name = device uid': {line!r}"
        teams[name.strip()] = uid.strip()
    cfg["team_uids"] = teams
    try:
        bounds = json.loads(form.get("layer_bounds", "").strip() or "{}")
        if not isinstance(bounds, dict) or not all(
                isinstance(b, dict) and all(isinstance(b.get(k), (int, float)) for k in ("north", "south", "east", "west"))
                for b in bounds.values()):
            raise ValueError("each layer needs numeric north/south/east/west")
    except ValueError as error:
        return None, None, f"Map bounds: {error}"
    cfg["layer_bounds"] = bounds
    origins = [o.strip().rstrip("/") for o in form.get("cors_origins", "").splitlines() if o.strip()]
    bad = [o for o in origins if o != "*" and not o.startswith(("https://", "http://"))]
    if bad:
        return None, None, f"Origins must be like https://tak.example.org:8443 — not {bad[0]!r}"
    cfg["cors_origins"] = origins
    secrets = dict(secrets)
    if form.get("crowdcad_password"):
        secrets["crowdcad_password"] = form["crowdcad_password"]
    return cfg, secrets, None


def _register_routes(g):
    app, login_required = g["app"], g["login_required"]
    if "crowdcad_console_page" in app.view_functions:
        return
    from flask import jsonify, redirect, request

    def render(saved=False, error=None, cert_notice=""):
        installed, running, detail = _service_status(fresh=True)
        sidebar = ""
        try:
            if "render_sidebar" in g and "detect_modules" in g:
                sidebar = g["render_sidebar"](g["detect_modules"](), "crowdcad")
        except Exception as exc:
            _log(f"sidebar unavailable on this page: {exc!r}")
        cfg, secrets, cert = _view(refresh=True)
        problem = f'<div class="banner bad">{E(error)}</div>' if error else ""
        if not cfg and not _is_root():
            problem += ('<div class="banner warn">Settings unavailable: the console runs without root and the '
                        'CrowdCAD helper hasn\'t answered yet. Reload in a few seconds; if this stays, re-run '
                        '<code>sudo bash /opt/crowdcad-tak/src/install.sh</code> on the server.</div>')
        return (HEAD + sidebar + '<div class="main"><h1>CrowdCAD for TAK</h1>'
                '<div class="sub">CrowdCAD event-medical dispatch on the TAK map: calls, teams and venue zones, '
                'live, in IU Event CAD\'s CoT format.</div>' + problem + _status_html(installed, running, detail)
                + _cert_html(cert, cert_notice) + _settings_html(cfg, secrets, saved) + _cloudtak_html(cfg, secrets)
                + "</div></body></html>")

    def page():
        return render(saved=request.args.get("saved") == "1")

    def upload_cert():
        if cross_origin():
            return "Cross-origin request refused", 403
        payload = {}
        for name in ("client_p12", "client_pem", "client_key", "truststore_p12", "ca_pem"):
            upload = request.files.get(name)
            data = upload.read(64 * 1024 + 1) if upload else b""
            if data:
                payload[name] = base64.b64encode(data).decode()
        for name in ("client_password", "truststore_password"):
            if request.form.get(name):
                payload[name] = request.form[name]
        answer = _admin("cert", payload, timeout=60)
        kind = "ok" if answer.get("ok") and answer.get("connected") else "warn" if answer.get("ok") else "bad"
        return render(cert_notice=f'<div class="banner {kind}">{E(answer.get("message") or "")}</div>'), \
            (200 if answer.get("ok") else 400)

    def cross_origin():
        # Same-origin only (the console's own CSRF baseline, re-checked here because older
        # infra-TAK versions don't apply it to non-/api routes).
        origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
        return bool(origin) and urllib.parse.urlsplit(origin).netloc != request.host

    def cloudtak_install():
        if cross_origin():
            return jsonify(error="Cross-origin request refused"), 403
        ct_dir = request.form.get("cloudtak_dir", "").strip().rstrip("/")
        if ct_dir and (not _SAFE_DIR.match(ct_dir) or ".." in ct_dir.split("/")):
            return jsonify(error="CloudTAK directory must be an absolute path like /root/CloudTAK"), 400
        answer = _admin("cloudtak", {"dir": ct_dir}, timeout=30)   # the root helper re-checks it all (R43)
        if not answer.get("ok"):
            message = answer.get("message") or "couldn't start"
            code = 400 if "published" in message else 409
            return jsonify(error=message, status=_cloudtak_status()), code
        return jsonify(ok=True, status=_cloudtak_status())

    def cloudtak_status():
        return jsonify(_cloudtak_status())

    def save():
        if cross_origin():
            return "Cross-origin request refused", 403
        answer = _admin("settings", {"form": request.form.to_dict()})   # root helper writes + restarts (R43)
        if not answer.get("ok"):
            return render(error=answer.get("message") or "not saved"), 400
        time.sleep(1.5)  # let the bridge's status endpoint come back before we render it
        return redirect("/crowdcad?saved=1")

    app.add_url_rule("/crowdcad", "crowdcad_console_page", login_required(page))
    app.add_url_rule("/crowdcad/settings", "crowdcad_console_settings", login_required(save), methods=["POST"])
    app.add_url_rule("/crowdcad/cert", "crowdcad_console_cert", login_required(upload_cert), methods=["POST"])
    app.add_url_rule("/crowdcad/cloudtak/install", "crowdcad_console_cloudtak_install",
                     login_required(cloudtak_install), methods=["POST"])
    app.add_url_rule("/crowdcad/cloudtak/status", "crowdcad_console_cloudtak_status", login_required(cloudtak_status))


def attach(module):
    g = module if isinstance(module, dict) else vars(module)
    attached = []
    steps = [
        ("routes", ("app", "login_required"), _register_routes),
        ("module card", ("detect_modules",), _wrap_detect_modules),
        ("sidebar", ("render_sidebar",), _wrap_render_sidebar),
    ]
    for name, needs, step in steps:
        if not all(key in g for key in needs):
            continue
        try:
            step(g)
            attached.append(name)
        except Exception as error:
            _log(f"{name} not attached: {error!r}")
    _log(f"attached to infra-TAK {g.get('VERSION', '?')}: {', '.join(attached) or 'nothing'}")
    return attached
