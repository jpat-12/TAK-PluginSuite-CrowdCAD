"""CrowdCAD for TAK inside the infra-TAK console — attached at runtime, on any infra-TAK version.

attach() receives the console's freshly loaded `app` module and adds, *if the hook point
exists in this version*:

    app + login_required  →  /crowdcad: bridge status, unplaced calls/teams, settings form
    detect_modules        →  a "CrowdCAD" module card on the console dashboard
    render_sidebar        →  a "CrowdCAD" link in the left nav

Same mechanism as InfraTAK-Plugin-Aleph (see crowdcad_infratak_boot.py for why app.py is never
patched). Each piece is wrapped separately so one failure can't take the others — or the
console — down. Runs inside the console's own Python: stdlib only, plus the Flask objects the
console hands us. The console runs as root, which is how it can write the bridge's secrets.
"""

import html
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HOME = os.environ.get("CROWDCAD_TAK_HOME", "/opt/crowdcad-tak")
DATA_DIR = os.path.join(HOME, "data")
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


def _parse_settings(form, cfg, secrets):
    """→ (config, secrets, error). Validates before anything is written."""
    cfg = dict(cfg)
    url = form.get("crowdcad_url", "").strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        return None, None, "CrowdCAD URL must start with http:// or https://"
    cfg["crowdcad_url"] = url
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
    from flask import redirect, request

    def render(saved=False, error=None):
        installed, running, detail = _service_status(fresh=True)
        sidebar = ""
        try:
            if "render_sidebar" in g and "detect_modules" in g:
                sidebar = g["render_sidebar"](g["detect_modules"](), "crowdcad")
        except Exception as exc:
            _log(f"sidebar unavailable on this page: {exc!r}")
        cfg = _read_json(os.path.join(DATA_DIR, "config.json"))
        secrets = _read_json(os.path.join(DATA_DIR, "secrets.json"))
        problem = f'<div class="banner bad">{E(error)}</div>' if error else ""
        return (HEAD + sidebar + '<div class="main"><h1>CrowdCAD for TAK</h1>'
                '<div class="sub">CrowdCAD event-medical dispatch on the TAK map: calls, teams and venue zones, '
                'live, in IU Event CAD\'s CoT format.</div>' + problem + _status_html(installed, running, detail)
                + _settings_html(cfg, secrets, saved) + "</div></body></html>")

    def page():
        return render(saved=request.args.get("saved") == "1")

    def save():
        # Same-origin only (the console's own CSRF baseline, re-checked here because older
        # infra-TAK versions don't apply it to non-/api routes).
        origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
        if origin and urllib.parse.urlsplit(origin).netloc != request.host:
            return "Cross-origin request refused", 403
        cfg = _read_json(os.path.join(DATA_DIR, "config.json"))
        secrets = _read_json(os.path.join(DATA_DIR, "secrets.json"))
        cfg, secrets, error = _parse_settings(request.form, cfg, secrets)
        if error:
            return render(error=error), 400
        os.makedirs(DATA_DIR, exist_ok=True)
        _write_json(os.path.join(DATA_DIR, "config.json"), cfg, 0o640)
        _write_json(os.path.join(DATA_DIR, "secrets.json"), secrets, 0o600)
        subprocess.run(["systemctl", "restart", "crowdcad-tak"], capture_output=True, timeout=30)
        time.sleep(1.5)  # let the bridge's status endpoint come back before we render it
        return redirect("/crowdcad?saved=1")

    app.add_url_rule("/crowdcad", "crowdcad_console_page", login_required(page))
    app.add_url_rule("/crowdcad/settings", "crowdcad_console_settings", login_required(save), methods=["POST"])


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
