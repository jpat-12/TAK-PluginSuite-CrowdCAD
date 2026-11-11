"""CrowdCAD → TAK bridge: follows a CrowdCAD (PocketBase) instance and publishes its calls,
teams and venue zones to TAK Server as CoT. See docs/COT_FORMAT.md for the wire contract."""

import os

_ROOT = os.path.dirname(os.path.abspath(__file__))


def _read_version():
    # Repo layout (bridge/crowdcad_tak → ../../VERSION) and installed layout (app/VERSION).
    for path in (os.path.join(_ROOT, "..", "..", "VERSION"), os.path.join(_ROOT, "..", "VERSION")):
        try:
            with open(path, encoding="utf-8") as stream:
                return stream.read().strip()
        except OSError:
            continue
    return "0.0.0"


VERSION = _read_version()

# The `v` attribute on every __iucad_* detail. Owned by IU Event CAD's COT_FORMAT.md — this
# bridge produces that format, it doesn't define it. Bump only when that document does.
IUCAD_FORMAT_VERSION = 1

LOG_PREFIX = "[crowdcad-tak]"
