"""Loaded at interpreter start by crowdcad_infratak.pth in the infra-TAK console's site-packages.

Why not patch app.py like the older InfraTAK-Module-* installers? infra-TAK's "Update Now"
runs `git checkout --force <tag>`, which silently discards every edit to app.py — and the
text anchors such patches need differ between releases. Instead this installs an import hook:
when the console's `app` module finishes loading (gunicorn imports `app:app`), attach() adds
CrowdCAD's routes and card to the live objects. Nothing tracked by infra-TAK's git is touched.
(Same mechanism as InfraTAK-Plugin-Aleph, which verified it on every infra-TAK release.)

Fails closed: any error here is printed and swallowed — the console always starts.
Opt out without uninstalling: CROWDCAD_DISABLE_CONSOLE_HOOK=1 in the console's environment.
"""

import importlib.abc
import importlib.machinery
import os
import sys


def _is_infratak(origin):
    """infra-TAK's app.py sits next to its start.sh launcher in every release."""
    if not origin or os.path.basename(origin) != "app.py":
        return False
    return os.path.isfile(os.path.join(os.path.dirname(origin), "start.sh"))


class CrowdCadConsoleFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "app":
            return None
        # Ask the finders *after* this one rather than PathFinder directly: Python stops at
        # the first finder that answers, so if Aleph for TAK's finder is installed too, this
        # is how its wrapped spec is obtained (and wrapped again) instead of bypassed.
        # .pth files run alphabetically and each inserts at 0, so ours (crowdcad_) sits ahead
        # of aleph_'s.
        spec = None
        later = sys.meta_path[sys.meta_path.index(self) + 1:] if self in sys.meta_path else []
        for finder in later or [importlib.machinery.PathFinder]:
            spec = finder.find_spec(fullname, path, target) if hasattr(finder, "find_spec") else None
            if spec is not None:
                break
        if spec is None or spec.loader is None or not _is_infratak(spec.origin):
            return None
        original = spec.loader.exec_module

        def exec_module(module):
            original(module)
            try:
                import crowdcad_infratak
                crowdcad_infratak.attach(module)
            except Exception as error:  # the console must start even if this hook is broken
                print(f"[crowdcad-tak] console hook skipped: {error!r}", file=sys.stderr, flush=True)

        spec.loader.exec_module = exec_module
        return spec


if os.environ.get("CROWDCAD_DISABLE_CONSOLE_HOOK") != "1" and not any(
        type(finder).__name__ == "CrowdCadConsoleFinder" for finder in sys.meta_path):
    sys.meta_path.insert(0, CrowdCadConsoleFinder())
