import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from psscanner_quant.constants import VERSION
from psscanner_quant import config


class V634InstallContextTests(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split("."))), (6, 4, 3))

    def test_load_settings_self_heals_legacy_observation_gates(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "settings.json"
            p.write_text(json.dumps({
                "weekly_min_observations": 6,
                "monthly_min_observations": 4,
                "expected_static_ip": "169.150.209.215",
                "unknown_future_key": "keep-me",
            }))
            with patch.object(config, "SETTINGS_PATH", p):
                d = config.load_settings()
            self.assertEqual(d["weekly_min_observations"], 1)
            self.assertEqual(d["monthly_min_observations"], 1)
            raw = json.loads(p.read_text())
            self.assertEqual(raw["weekly_min_observations"], 1)
            self.assertEqual(raw["monthly_min_observations"], 1)
            self.assertEqual(raw["expected_static_ip"], "169.150.209.215")
            self.assertEqual(raw["unknown_future_key"], "keep-me")

    def test_installer_runs_migration_from_target_app_and_verifies_target_file(self):
        src = (Path(__file__).resolve().parents[1] / "install.sh").read_text()
        self.assertIn('cd "$APP"', src)
        self.assertIn('$APP/data/settings.json', src)
        self.assertIn('target settings verification: weekly=1 monthly=1', src)

    def test_update_settings_cannot_reintroduce_pseudo_observation_gate(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "settings.json"
            p.write_text('{}')
            with patch.object(config, "SETTINGS_PATH", p):
                out = config.update_settings({"weekly_min_observations": 9, "monthly_min_observations": 8})
            self.assertEqual(out["weekly_min_observations"], 1)
            self.assertEqual(out["monthly_min_observations"], 1)


if __name__ == "__main__":
    unittest.main()
