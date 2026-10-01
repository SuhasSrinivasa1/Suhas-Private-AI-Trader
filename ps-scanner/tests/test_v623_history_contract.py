import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from psscanner_quant import data, history_control
from psscanner_quant.constants import IST


class V623HistoryContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_state_path = history_control._STATE_PATH
        history_control._STATE_PATH = Path(self.tmp.name) / "history_control.json"
        history_control._GLOBAL_COOLDOWN_UNTIL = 0.0
        history_control._CONSECUTIVE_429 = 0

    def tearDown(self):
        history_control._STATE_PATH = self.old_state_path
        history_control._GLOBAL_COOLDOWN_UNTIL = 0.0
        history_control._CONSECUTIVE_429 = 0
        self.tmp.cleanup()

    def test_current_groww_contract_limits_are_encoded(self):
        self.assertEqual(data._history_window_limit_days("1day"), 180)
        self.assertEqual(data._history_window_limit_days("5minute"), 30)
        self.assertEqual(data._history_window_limit_days("10minute"), 90)

    def test_daily_requests_are_chunked_below_180_days_and_merged(self):
        cache = Path(self.tmp.name) / "ABB.1day.json"
        calls = []
        base = int(pd.Timestamp("2026-01-01", tz="Asia/Kolkata").timestamp())
        c1 = [[base + i*86400, 100, 101, 99, 100.5, 1000] for i in range(120)]
        c2 = [[base - (i+1)*86400, 90, 91, 89, 90.5, 900] for i in range(120)]

        def fake_hist(groww_symbol, start_time, end_time, interval="1day", exchange="NSE"):
            st = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
            en = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
            calls.append((st, en, interval))
            return c1 if len(calls) == 1 else c2

        settings = {
            "daily_history_ttl_hours": 12,
            "intraday_history_ttl_minutes": 5,
            "history_429_max_retries": 0,
            "history_daily_chunk_days": 175,
            "history_daily_target_days": 350,
            "history_daily_min_rows": 220,
        }
        with patch("psscanner_quant.data.instrument", return_value={"symbol":"ABB","groww_symbol":"NSE-ABB"}), \
             patch("psscanner_quant.data._history_path", return_value=cache), \
             patch("psscanner_quant.data.load_settings", return_value=settings), \
             patch("psscanner_quant.data.quarantine_status", return_value={"quarantined":False}), \
             patch("psscanner_quant.data.wait_for_slot"), \
             patch("psscanner_quant.data.record_success"), \
             patch("psscanner_quant.data.clear_quarantine"), \
             patch.object(data.broker, "historical", side_effect=fake_hist):
            df = data.history("ABB", "1day", force=True)

        self.assertEqual(len(calls), 2)
        for st, en, interval in calls:
            self.assertEqual(interval, "1day")
            self.assertLessEqual((en-st).total_seconds()/86400.0, 175.01)
        self.assertGreaterEqual(len(df), 220)
        self.assertTrue(cache.exists())

    def test_legacy_false_daily_400_quarantines_are_auto_cleared(self):
        future = "2099-01-01T00:00:00+05:30"
        state = {
            "quarantine": {
                "NSE-ABB|1day": {"reason":"HTTP 400 historical request rejected","status_code":400,"until":future},
                "NSE-REALBAD|5minute": {"reason":"HTTP 400 historical request rejected","status_code":400,"until":future},
            },
            "invalid_request_events": 2,
        }
        history_control._STATE_PATH.write_text(json.dumps(state))
        with patch("psscanner_quant.history_control.load_settings", return_value={"history_min_request_interval_seconds":1.25,"history_daily_chunk_days":175,"history_daily_target_days":350}):
            st = history_control.status()
        self.assertEqual(st["active_quarantines"], 1)
        self.assertEqual(st["legacy_false_quarantines_cleared"], 1)
        persisted = json.loads(history_control._STATE_PATH.read_text())
        self.assertNotIn("NSE-ABB|1day", persisted["quarantine"])
        self.assertIn("NSE-REALBAD|5minute", persisted["quarantine"])

    def test_five_minute_first_window_never_exceeds_30_days(self):
        cache = Path(self.tmp.name) / "TEST.5minute.json"
        seen = []
        candle = [[int(pd.Timestamp("2026-09-25 10:00", tz="Asia/Kolkata").timestamp()),100,101,99,100.5,1000]]
        def fake_hist(groww_symbol, start_time, end_time, interval="1day", exchange="NSE"):
            st = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
            en = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
            seen.append((en-st).total_seconds()/86400.0)
            return candle
        settings={"daily_history_ttl_hours":12,"intraday_history_ttl_minutes":5,"history_429_max_retries":0}
        with patch("psscanner_quant.data.instrument", return_value={"symbol":"TEST","groww_symbol":"NSE-TEST"}), \
             patch("psscanner_quant.data._history_path", return_value=cache), \
             patch("psscanner_quant.data.load_settings", return_value=settings), \
             patch("psscanner_quant.data.quarantine_status", return_value={"quarantined":False}), \
             patch("psscanner_quant.data.wait_for_slot"), \
             patch("psscanner_quant.data.record_success"), \
             patch("psscanner_quant.data.clear_quarantine"), \
             patch.object(data.broker, "historical", side_effect=fake_hist):
            df=data.history("TEST","5minute",force=True)
        self.assertEqual(len(df),1)
        self.assertTrue(seen)
        self.assertLessEqual(seen[0],30.01)


if __name__ == "__main__":
    unittest.main()
