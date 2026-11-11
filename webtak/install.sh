#!/usr/bin/env bash
#
# install.sh — install the CrowdCAD board plugin into TAK Server's extracted WebTAK app.
#
# Same mechanism as WebTAK-Plugin-Channels / VideoViewer: copy one classic-script bundle into
# <webtak>/plugins/crowdcad-board/ and add it to webtak-manifest.json's "plugins" array (as a
# plain string — this WebTAK's manifest validator rejects object entries). The difference: the
# bundle is BUILT here (python3 build.py), with the bridge's public URL and board token baked
# in, so nothing generated is committed and operators don't have to type a token.
#
# Usually run for you by `infratak/install.sh --webtak`.
#
# Usage:
#   CROWDCAD_TAK_URL=https://crowdcad-tak.example.org CROWDCAD_TAK_TOKEN=… sudo ./install.sh
#   sudo ./install.sh --remove
#   WEBTAK_DIR=/path/to/webtak overrides the default /opt/tak/extract/webtak
set -euo pipefail

WEBTAK_DIR="${WEBTAK_DIR:-/opt/tak/extract/webtak}"
PLUGIN_ID="crowdcad-board"
BUNDLE="crowdcad-board.plugin.js"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MANIFEST="$WEBTAK_DIR/webtak-manifest.json"
DEST_DIR="$WEBTAK_DIR/plugins/$PLUGIN_ID"
REL_PATH="plugins/$PLUGIN_ID/$BUNDLE"

command -v python3 >/dev/null || { echo "ERROR: python3 required."; exit 1; }
[ -f "$MANIFEST" ] || { echo "ERROR: $MANIFEST not found. Set WEBTAK_DIR."; exit 1; }
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$MANIFEST" 2>/dev/null \
  || { echo "ERROR: $MANIFEST is not valid JSON. Fix it first, then re-run."; exit 1; }

REMOVE=0
case "${1:-}" in
  --remove) REMOVE=1 ;;
  "")       ;;
  *)        echo "Unknown arg: $1"; exit 1 ;;
esac

if [ "$REMOVE" = "1" ]; then
  rm -rf "$DEST_DIR"
else
  : "${CROWDCAD_TAK_URL:?set CROWDCAD_TAK_URL (e.g. https://crowdcad-tak.example.org)}"
  : "${CROWDCAD_TAK_TOKEN:?set CROWDCAD_TAK_TOKEN (board_token from /opt/crowdcad-tak/data/secrets.json)}"
  mkdir -p "$DEST_DIR"
  python3 "$HERE/build.py" --out "$DEST_DIR/$BUNDLE"
  # Match the manifest's ownership so WebTAK's server process can read the bundle.
  chown --reference="$MANIFEST" "$DEST_DIR" "$DEST_DIR/$BUNDLE" 2>/dev/null || true
fi

cp "$MANIFEST" "$MANIFEST.bak.$(date +%s)"
python3 - "$MANIFEST" "$REL_PATH" "$REMOVE" <<'PY'
import json, os, sys
manifest, rel, remove = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
with open(manifest) as f:
    data = json.load(f)
plugins = data.get("plugins") if isinstance(data.get("plugins"), list) else []
def entry_path(e):
    return e if isinstance(e, str) else (e.get("path") if isinstance(e, dict) else None)
plugins = [e for e in plugins if entry_path(e) != rel]
if not remove:
    plugins.append(rel)
data["plugins"] = plugins
mode = os.stat(manifest).st_mode
with open(manifest + ".tmp", "w") as f:
    json.dump(data, f, indent=2)
# Keep the original permissions whatever the umask: an unreadable manifest is WebTAK's grey
# screen (the Video Viewer plugin's incident).
os.chmod(manifest + ".tmp", mode)
os.replace(manifest + ".tmp", manifest)
print(("Removed" if remove else "Registered") + f" plugin entry: {rel}")
PY

echo "Done. Hard-refresh WebTAK (Ctrl-Shift-R)."
