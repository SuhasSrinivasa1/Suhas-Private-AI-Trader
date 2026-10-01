import unittest
from pathlib import Path

from psscanner_quant.constants import VERSION
from psscanner_quant.main import app

ROOT = Path(__file__).resolve().parents[1]

class V625InstallerProbeTests(unittest.TestCase):
    def test_version_bumped(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split("."))), (6, 4, 3))

    def test_groww_probe_route_registered(self):
        paths = {getattr(r, "path", None) for r in app.routes}
        self.assertIn("/api/groww/status", paths)

    def test_health_stays_cached_nonblocking(self):
        text = (ROOT / "psscanner_quant" / "main.py").read_text()
        self.assertIn('"groww":broker.status_cached()', text)

    def test_independent_broker_probe_worker_exists(self):
        text = (ROOT / "psscanner_quant" / "engine.py").read_text()
        self.assertIn('("broker_probe"', text)
        self.assertIn("broker.status()", text)

    def test_installer_explicitly_probes_groww(self):
        text = (ROOT / "install.sh").read_text()
        self.assertIn("/api/groww/status?refresh=true", text)
        self.assertIn("d.get('connected') is True", text)
        self.assertNotIn('g.get("connected") is True)', text[text.find('ok=0\nfor i in {1..60}; do'):text.find('groww_ok=0')])

if __name__ == "__main__":
    unittest.main()
