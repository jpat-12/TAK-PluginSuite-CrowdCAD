"""infratak/crowdcad_caddy.py: the board site block survives infra-TAK's Caddyfile rewrites and
only ever exposes the board API."""

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

INFRATAK = Path(__file__).resolve().parents[2] / "infratak"
sys.path.insert(0, str(INFRATAK))
caddy = importlib.import_module("crowdcad_caddy")
sys.path.remove(str(INFRATAK))

INFRATAK_CADDYFILE = """tak.example.org {
    reverse_proxy 127.0.0.1:8443
}

# --- User-added blocks (do not remove) ---

aleph.example.org {
    reverse_proxy 127.0.0.1:8781
}
"""


class CaddyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        (self.d / "console" / ".config").mkdir(parents=True)
        (self.d / "console" / ".config" / "settings.json").write_text(json.dumps({"fqdn": "example.org"}))
        (self.d / "data").mkdir()
        (self.d / "data" / "config.json").write_text("{}")
        self.caddyfile = self.d / "Caddyfile"
        self.caddyfile.write_text(INFRATAK_CADDYFILE)

    def run_ensure(self, *extra):
        return caddy.main(["ensure", "--caddyfile", str(self.caddyfile), "--console-dir", str(self.d / "console"),
                           "--data", str(self.d / "data"), *extra])

    def test_block_below_marker_api_only(self):
        self.assertEqual(self.run_ensure(), 0)
        text = self.caddyfile.read_text(encoding="utf-8")
        self.assertLess(text.index(caddy.USER_BLOCKS_MARKER), text.index("crowdcad-tak.example.org {"))
        self.assertIn("aleph.example.org", text)                      # neighbours untouched
        self.assertIn("@bridge path /api/v1/* /healthz", text)
        self.assertIn("respond 404", text)                             # /status never proxied
        config = json.loads((self.d / "data" / "config.json").read_text())
        self.assertEqual(config["public_url"], "https://crowdcad-tak.example.org")
        self.assertIn("https://example.org:8443", config["cors_origins"])

    def test_idempotent_and_survives_a_rewrite(self):
        self.run_ensure()
        once = self.caddyfile.read_text(encoding="utf-8")
        self.run_ensure()
        self.assertEqual(self.caddyfile.read_text(encoding="utf-8"), once)              # no-op: ends the heal loop
        self.assertEqual(once.count(caddy.BEGIN), 1)
        self.caddyfile.write_text("tak.example.org {\n}\n")             # v0.1.x-style rewrite, no marker
        self.run_ensure()
        text = self.caddyfile.read_text(encoding="utf-8")
        self.assertIn(caddy.USER_BLOCKS_MARKER, text)
        self.assertIn("crowdcad-tak.example.org", text)

    def test_custom_domain_and_operator_cors_kept(self):
        (self.d / "data" / "config.json").write_text(json.dumps({"cors_origins": ["https://webtak.local"]}))
        self.run_ensure("--domain", "medical")
        self.assertIn("medical.example.org {", self.caddyfile.read_text(encoding="utf-8"))
        config = json.loads((self.d / "data" / "config.json").read_text())
        self.assertEqual(config["cors_origins"], ["https://webtak.local"])

    def test_remove(self):
        self.run_ensure()
        caddy.main(["remove", "--caddyfile", str(self.caddyfile)])
        self.assertNotIn("crowdcad-tak", self.caddyfile.read_text(encoding="utf-8"))
        self.assertIn("aleph.example.org", self.caddyfile.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
