import json
import tempfile
import unittest
from pathlib import Path

from psscanner_quant.constants import VERSION
from psscanner_quant.config import migrate_morning_freeze_settings


class V633SettingsMigrationTests(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split("."))), (6, 4, 3))

    def test_upgrade_migrates_old_observation_gates_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "settings.json"
            p.write_text(json.dumps({
                "weekly_min_observations": 6,
                "monthly_min_observations": 4,
                "expected_static_ip": "169.150.209.215",
                "manual_execution_enabled": False,
                "unknown_future_key": "preserve-me",
            }))
            result = migrate_morning_freeze_settings(p)
            self.assertTrue(result["changed"])
            self.assertEqual(result["weekly_before"], 6)
            self.assertEqual(result["monthly_before"], 4)
            data = json.loads(p.read_text())
            self.assertEqual(data["weekly_min_observations"], 1)
            self.assertEqual(data["monthly_min_observations"], 1)
            self.assertEqual(data["expected_static_ip"], "169.150.209.215")
            self.assertFalse(data["manual_execution_enabled"])
            self.assertEqual(data["unknown_future_key"], "preserve-me")

    def test_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "settings.json"
            p.write_text(json.dumps({"weekly_min_observations": 1, "monthly_min_observations": 1, "universe_size": 0, "intraday_scan_size": 0, "horizon_scan_size": 0, "full_nse_breadth_enabled": True}))
            result = migrate_morning_freeze_settings(p)
            self.assertFalse(result["changed"])
            data = json.loads(p.read_text())
            self.assertEqual(data["weekly_min_observations"], 1)
            self.assertEqual(data["monthly_min_observations"], 1)
            self.assertEqual(data["universe_size"], 0)
            self.assertEqual(data["intraday_scan_size"], 0)
            self.assertEqual(data["horizon_scan_size"], 0)
            self.assertTrue(data["full_nse_breadth_enabled"])


if __name__ == "__main__":
    unittest.main()
