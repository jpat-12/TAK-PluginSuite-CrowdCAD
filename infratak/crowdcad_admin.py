#!/usr/bin/env python3
"""crowdcad_admin.py — the root half of the infra-TAK console's CrowdCAD page (tracker R43).

Why it exists: infra-TAK 10.x runs its console as the unprivileged `takwerx` user ("born
non-root"; privileged work goes through infra-TAK's own broker, which only knows infra-TAK's
commands). The CrowdCAD page needs root for exactly three things: writing the bridge's
settings and secrets, installing a TAK client certificate, and starting the CloudTAK plugin
install job. So the page writes a request file into the console dir and this script, run as
root by crowdcad-tak-admin.path, carries it out and writes the answer next to it.

    <HOME>/console/                 root:<console group> 2770, made by install.sh
        <id>.req                    request (JSON); renamed to <id>.work while handled
        <id>.res                    answer (JSON): {"ok": bool, "message": str, ...}
        view.json                   what the page may show: config, "password set" flags,
                                    board token, current certificate subject/expiry
        cloudtak-install.log        the CloudTAK install job's log (progress bar)

A root console (infra-TAK 0.x, ILWG-Server1) runs `crowdcad_admin.py run <file>` directly;
the rename to .work means the path unit and a direct run never both handle one request.

Requests carry passwords and certificates for a moment: the dir is closed to everyone but root
and the console's group, and every request is deleted as soon as it's read. Nothing secret
goes on a command line (openssl reads passwords from 0600 files) or into a log.

Usage:  crowdcad_admin.py process      (path unit: handle every pending request, refresh view)
        crowdcad_admin.py run FILE     (one request, synchronously)
        crowdcad_admin.py view         (refresh view.json only; install.sh)
"""

import base64
import filecmp
import glob
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crowdcad_infratak as hook  # noqa: E402  (same dir: settings parsing, JSON writes, job start)

MAX_FILE = 64 * 1024          # a client cert, key or truststore is a few KB


# Paths are read from the hook module at call time (tests point it at a temp dir).
def _data(name):
    return os.path.join(hook.DATA_DIR, name)


def _certs(name=""):
    # Installed certificate files go here; the ones install.sh made with makeCert.sh stay beside them.
    return os.path.join(hook.HOME, "certs", name)


class Refused(Exception):
    """A request we won't carry out; the message goes to the operator as is."""


def _log(message):
    print(f"[crowdcad-tak] admin: {message}", file=sys.stderr, flush=True)


# --- certificates ------------------------------------------------------------------------------

def _blob(payload, key):
    value = payload.get(key)
    if not value:
        return None
    try:
        data = base64.b64decode(value, validate=True)
    except ValueError:
        raise Refused(f"{key}: not a valid upload")
    if len(data) > MAX_FILE:
        raise Refused(f"{key}: {len(data)} bytes is too big for a certificate file")
    return data


def _openssl(args, password, tmp):
    """openssl with the password in a 0600 file (never argv/env). → (ok, stderr)."""
    pw = os.path.join(tmp, "pw")
    with open(os.open(pw, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
        stream.write(password or "")
    out = subprocess.run(["openssl"] + args + ["-passin", f"file:{pw}"], capture_output=True, text=True, timeout=30)
    os.remove(pw)
    return out.returncode == 0, (out.stderr or "").strip()


def _from_p12(data, password, tmp, want_key):
    """PKCS#12 → PEM text. want_key: the client cert + its key (unencrypted); else every cert
    (a truststore). TAK's .p12 files often use RC2/3DES, which OpenSSL 3 only reads with -legacy."""
    src = os.path.join(tmp, "in.p12")
    with open(src, "wb") as stream:
        stream.write(data)
    outs = {}
    jobs = [("cert", ["-clcerts", "-nokeys"]), ("key", ["-nocerts", "-nodes"])] if want_key else [("certs", ["-nokeys"])]
    for name, flags in jobs:
        dest = os.path.join(tmp, name + ".pem")
        base = ["pkcs12", "-in", src, "-out", dest] + flags
        ok, err = _openssl(base, password, tmp)
        if not ok:
            ok, err2 = _openssl(base + ["-legacy"], password, tmp)
            err = err2 or err
        if not ok:
            if "mac verify" in err.lower() or "password" in err.lower():
                raise Refused("wrong password for the .p12 file")
            raise Refused(f"couldn't read the .p12 file: {err.splitlines()[-1] if err else 'openssl failed'}")
        with open(dest) as stream:
            outs[name] = stream.read()
    return outs


def _subject(cert_path):
    out = subprocess.run(["openssl", "x509", "-in", cert_path, "-noout", "-subject", "-enddate"],
                         capture_output=True, text=True, timeout=15)
    if out.returncode != 0:
        return {}
    info = {}
    for line in out.stdout.splitlines():
        key, _, value = line.partition("=")
        info["subject" if key.strip() == "subject" else "expires"] = value.strip()
    return info


def _install_file(text_or_bytes, dest):
    data = text_or_bytes.encode() if isinstance(text_or_bytes, str) else text_or_bytes
    tmp = dest + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640), "wb") as stream:
        stream.write(data)
    try:
        import grp
        os.chown(tmp, 0, grp.getgrnam(hook.SERVICE_USER).gr_gid)
    except (ImportError, KeyError, OSError):
        pass
    os.replace(tmp, dest)


def install_cert(payload):
    """Client cert as one .p12 (+ password) or .pem + .key (+ key password if encrypted); CA as an
    optional truststore .p12 (+ password) or .pem. Everything is checked before anything is
    replaced; then config/secrets point at the new files and the bridge restarts."""
    p12, pem, key = _blob(payload, "client_p12"), _blob(payload, "client_pem"), _blob(payload, "client_key")
    trust, ca_pem = _blob(payload, "truststore_p12"), _blob(payload, "ca_pem")
    password = payload.get("client_password") or ""
    if not (p12 or (pem and key)):
        raise Refused("Upload the client certificate: the .p12, or the .pem together with the .key.")
    with tempfile.TemporaryDirectory(prefix="crowdcad-cert-") as tmp:
        os.chmod(tmp, 0o700)
        if p12:
            parts = _from_p12(p12, password, tmp, want_key=True)
            cert_text, key_text, key_password = parts["cert"], parts["key"], ""
        else:
            cert_text, key_text, key_password = pem.decode("utf-8", "replace"), key.decode("utf-8", "replace"), password
        if "-----BEGIN CERTIFICATE-----" not in cert_text:
            raise Refused("The client certificate isn't a PEM certificate.")
        if "PRIVATE KEY-----" not in key_text:
            raise Refused("The key file has no private key in it.")
        if "ENCRYPTED" in key_text and not key_password:
            raise Refused("The key is encrypted: enter its password.")
        cert_file, key_file = os.path.join(tmp, "c.pem"), os.path.join(tmp, "k.pem")
        for path, text in ((cert_file, cert_text), (key_file, key_text)):
            with open(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600), "w") as stream:
                stream.write(text)
        try:   # the same call the bridge makes: the cert and key must match, the password must open it
            # A callable, never None: with None, OpenSSL would prompt on a terminal for a password.
            ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_cert_chain(
                cert_file, key_file, password=key_password or (lambda: ""))
        except ssl.SSLError as error:
            reason = (error.reason or str(error)).lower()
            if "bad decrypt" in reason or "bad password" in reason:
                raise Refused("Wrong password for the key.")
            raise Refused(f"The certificate and key don't work together: {error.reason or error}")
        except (TypeError, ValueError):
            raise Refused("Wrong password for the key.")
        ca_text = None
        if trust:
            ca_text = _from_p12(trust, payload.get("truststore_password") or "", tmp, want_key=False)["certs"]
        elif ca_pem:
            ca_text = ca_pem.decode("utf-8", "replace")
        if ca_text is not None:
            ca_file = os.path.join(tmp, "ca.pem")
            with open(ca_file, "w") as stream:
                stream.write(ca_text)
            try:
                ssl.create_default_context(cafile=ca_file)
            except ssl.SSLError:
                raise Refused("The truststore / CA has no usable certificate in it.")
        info = _subject(cert_file)

    os.makedirs(_certs(), exist_ok=True)
    client_cert, client_key, client_ca = _certs("tak-client.pem"), _certs("tak-client.key"), _certs("tak-ca.pem")
    _install_file(cert_text, client_cert)
    _install_file(key_text, client_key)
    cfg = hook._read_json(_data("config.json"))
    secrets = hook._read_json(_data("secrets.json"))
    cfg.update(tak_cert=client_cert, tak_key=client_key)
    if ca_text is not None:
        _install_file(ca_text, client_ca)
        cfg["tak_ca"] = client_ca
    secrets["tak_key_password"] = key_password
    hook._write_json(_data("config.json"), cfg, 0o640)
    hook._write_json(_data("secrets.json"), secrets, 0o600)
    connected = _restart_and_check()
    who = info.get("subject") or "the uploaded certificate"
    message = (f"Certificate installed: the bridge now connects to TAK as {who}"
               + (f" (expires {info['expires']})" if info.get("expires") else "") + ". ")
    message += ("TAK connected." if connected else
                "TAK not connected yet — if this certificate was just made in TAK Portal, TAK may have "
                "cached 'no groups': restart the bridge again in a minute (Save below does it).")
    _log(f"client certificate replaced ({who})")
    return {"message": message, "connected": connected}


def _restart_and_check():
    subprocess.run(["systemctl", "restart", "crowdcad-tak"], capture_output=True, timeout=30)
    listen = hook._read_json(_data("config.json")).get("status_listen") or "127.0.0.1:8782"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            with urllib.request.urlopen(f"http://{listen}/status", timeout=2) as response:
                if (json.loads(response.read()).get("tak") or {}).get("connected"):
                    return True
        except Exception:
            pass
    return False


# --- settings and the CloudTAK job ---------------------------------------------------------------

def save_settings(payload):
    form = payload.get("form") or {}
    if not isinstance(form, dict):
        raise Refused("bad settings form")
    cfg = hook._read_json(_data("config.json"))
    secrets = hook._read_json(_data("secrets.json"))
    cfg, secrets, error = hook._parse_settings(form, cfg, secrets)
    if error:
        raise Refused(error)
    os.makedirs(hook.DATA_DIR, exist_ok=True)
    hook._write_json(_data("config.json"), cfg, 0o640)
    hook._write_json(_data("secrets.json"), secrets, 0o600)
    subprocess.run(["systemctl", "restart", "crowdcad-tak"], capture_output=True, timeout=30)
    return {"message": "Saved — bridge restarted."}


# --- what's installed where (tracker R47) ---------------------------------------------------------
# CloudTAK is found the way cloudtak/install.sh finds it (the running api container's compose dir),
# then the usual checkout places; the page shows it instead of asking for a directory.
CLOUDTAK_GUESSES = ["/root/CloudTAK", "/home/takwerx/CloudTAK", "/opt/CloudTAK"]


def _is_cloudtak(path):
    return bool(path) and (os.path.isfile(os.path.join(path, "app", "plugin.ts"))
                           or os.path.isfile(os.path.join(path, "api", "web", "plugin.ts")))


def find_cloudtak(cfg):
    """→ the CloudTAK checkout on this host, or "". A dir set in config wins if it's a checkout."""
    candidates = [cfg.get("cloudtak_dir") or ""]
    try:
        out = subprocess.run(["docker", "inspect", "cloudtak-api-1", "--format",
                              '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}'],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            candidates.append(out.stdout.strip())
    except Exception:
        pass   # no docker / no container: fall back to the usual places (never break the view over a probe)
    candidates += CLOUDTAK_GUESSES + sorted(glob.glob("/home/*/CloudTAK"))
    return next((c.rstrip("/") for c in candidates if _is_cloudtak(c)), "")


def _first_line(path):
    try:
        with open(path, encoding="utf-8") as stream:
            return stream.readline().strip()
    except OSError:
        return ""


OUTDATED = "out of date"   # plugin version not recorded and its files differ from this server's source


def _plugin_version_from_files(web_dir):
    """R48: a plugin installed before cloudtak/install.sh recorded VERSION. Same files as this
    server's source checkout → that checkout's version; different → OUTDATED; no checkout → ""."""
    src = os.path.join(hook.HOME, "src", "cloudtak", "plugin")
    version = _first_line(os.path.join(hook.HOME, "src", "VERSION"))
    if not (version and os.path.isfile(os.path.join(src, "index.ts"))):
        return ""
    for root, _dirs, files in os.walk(src):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), src)
            if rel in ("package.json", "tsconfig.json"):      # not copied into CloudTAK
                continue
            try:
                if not filecmp.cmp(os.path.join(src, rel), os.path.join(web_dir, rel), shallow=False):
                    return OUTDATED
            except OSError:
                return OUTDATED                                # a file the installed copy lacks
    return version


def installed_versions(cfg):
    """Versions the page compares with GitHub main. "" = installed, version unknown; None = not installed."""
    ct_dir = find_cloudtak(cfg)
    plugin = None
    for web in ("app/plugins/crowdcad", "api/web/plugins/crowdcad"):
        if ct_dir and os.path.isfile(os.path.join(ct_dir, web, "index.ts")):
            plugin = (_first_line(os.path.join(ct_dir, web, "VERSION"))   # written by cloudtak/install.sh since R47
                      or _plugin_version_from_files(os.path.join(ct_dir, web)))
            break
    cloudtak = ""
    if ct_dir:
        cloudtak = str(hook._read_json(os.path.join(ct_dir, "package.json")).get("version") or "")
    app = hook._read_json(os.path.join(hook.HOME, "crowdcad", "app.json"))
    return {"cloudtak_dir": ct_dir, "cloudtak": cloudtak, "cloudtak_plugin": plugin,
            "crowdcad": app.get("ref") if app else None}


def start_cloudtak(payload):
    ct_dir = (payload.get("dir") or "").strip().rstrip("/")
    cfg = hook._read_json(_data("config.json"))
    secrets = hook._read_json(_data("secrets.json"))
    if not (cfg.get("public_url") and secrets.get("board_token")):
        raise Refused("The board isn't published yet — run the server install first.")
    if ct_dir and (not hook._SAFE_DIR.match(ct_dir) or ".." in ct_dir.split("/")):
        raise Refused("CloudTAK directory must be an absolute path like /root/CloudTAK")
    if ct_dir and ct_dir != (cfg.get("cloudtak_dir") or ""):
        cfg["cloudtak_dir"] = ct_dir            # typed by hand: remember it
        hook._write_json(_data("config.json"), cfg, 0o640)
    ct_dir = ct_dir or find_cloudtak(cfg)       # R47: found automatically otherwise
    if not ct_dir:
        raise Refused("No CloudTAK found on this server. Enter its folder (the one with docker-compose.yml).")
    problem = hook._start_job(ct_dir)
    if problem:
        raise Refused(problem)
    return {"message": "CloudTAK plugin install started."}


ACTIONS = {"cert": install_cert, "settings": save_settings, "cloudtak": start_cloudtak,
           "view": lambda payload: {"message": "ok"}}


# --- what the page may show ----------------------------------------------------------------------

def write_view():
    cfg = hook._read_json(_data("config.json"))
    secrets = hook._read_json(_data("secrets.json"))
    cert = cfg.get("tak_cert") or _certs("crowdcad.pem")
    view = {"config": cfg,
            "secrets": {"crowdcad_password": bool(secrets.get("crowdcad_password")),
                        "board_token": secrets.get("board_token") or ""},
            "cert": dict(_subject(cert), path=cert) if os.path.exists(cert) else {"path": cert},
            "versions": installed_versions(cfg),
            "at": int(time.time())}
    hook._write_console_file(os.path.join(hook.CONSOLE_DIR, "view.json"), json.dumps(view, indent=2))


# --- request handling ----------------------------------------------------------------------------

def run(path):
    """Handle one request file. Returns the answer, or None if another runner took it."""
    work = path[:-4] + ".work" if path.endswith(".req") else path + ".work"
    try:
        os.rename(path, work)
    except OSError:
        return None
    try:
        with open(work, encoding="utf-8") as stream:
            request = json.load(stream)
    except (OSError, ValueError):
        request = {}
    finally:
        try:
            os.remove(work)
        except OSError:
            pass
    action = ACTIONS.get(request.get("action"))
    try:
        if action is None:
            raise Refused(f"unknown request {request.get('action')!r}")
        answer = dict(action(request.get("payload") or {}), ok=True)
    except Refused as error:
        answer = {"ok": False, "message": str(error)}
    except Exception as error:   # never leave the page waiting on a crash
        _log(f"{request.get('action')} failed: {error!r}")
        answer = {"ok": False, "message": f"{request.get('action')} failed on the server: {error}"}
    try:
        write_view()
    except Exception as error:
        _log(f"view not refreshed: {error!r}")
    hook._write_console_file(work[:-5] + ".res", json.dumps(answer))
    return answer


def main(argv):
    if len(argv) >= 2 and argv[1] == "process":
        for path in sorted(glob.glob(os.path.join(hook.CONSOLE_DIR, "*.req"))):
            run(path)
        # answers nobody collected (page closed): drop after 10 min
        for path in glob.glob(os.path.join(hook.CONSOLE_DIR, "*.res")):
            try:
                if time.time() - os.path.getmtime(path) > 600:
                    os.remove(path)
            except OSError:
                pass
        return 0
    if len(argv) >= 3 and argv[1] == "run":
        return 0 if (run(argv[2]) or {}).get("ok") else 1
    if len(argv) >= 2 and argv[1] == "view":
        write_view()
        return 0
    print(__doc__.split("Usage:")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    if shutil.which("openssl") is None:
        _log("openssl not found — certificate uploads will fail")
    sys.exit(main(sys.argv))
