import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import requests
import inspect

from psscanner_quant import history_control
from psscanner_quant import data
from psscanner_quant.strategy_lab import validate_strategies


class V621ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "history_control.json"
        self.old_state_path = history_control._STATE_PATH
        history_control._STATE_PATH = self.state_path
        history_control._GLOBAL_COOLDOWN_UNTIL = 0.0
        history_control._CONSECUTIVE_429 = 0

    def tearDown(self):
        history_control._STATE_PATH = self.old_state_path
        history_control._GLOBAL_COOLDOWN_UNTIL = 0.0
        history_control._CONSECUTIVE_429 = 0
        self.tmp.cleanup()

    def test_429_creates_global_cooldown(self):
        with patch("psscanner_quant.history_control.load_settings", return_value={"history_429_backoff_base_seconds": 1.0, "history_429_backoff_max_seconds": 5.0, "history_min_request_interval_seconds": 0.25}):
            delay = history_control.record_rate_limit(None)
            self.assertGreaterEqual(delay, 1.0)
            st = history_control.status()
            self.assertGreater(st["global_cooldown_remaining_seconds"], 0)
            self.assertEqual(st["rate_limit_events"], 1)

    def test_invalid_history_quarantine_persists(self):
        with patch("psscanner_quant.history_control.load_settings", return_value={"history_invalid_symbol_quarantine_hours": 12.0, "history_min_request_interval_seconds": 1.25}), patch("psscanner_quant.history_control.health"):
            history_control.quarantine("NSE-BAD", "1day", "HTTP 400", status_code=400)
            st = history_control.quarantine_status("NSE-BAD", "1day")
            self.assertTrue(st["quarantined"])
            self.assertEqual(st["status_code"], 400)
            self.assertTrue(self.state_path.exists())

    def test_allow_network_false_never_calls_broker(self):
        cache = Path(self.tmp.name) / "TEST.1day.json"
        cache.write_text(json.dumps({"candles": [[1704067200,100,101,99,100.5,1000]]}))
        with patch("psscanner_quant.data.instrument", return_value={"symbol":"TEST","groww_symbol":"NSE-TEST"}), \
             patch("psscanner_quant.data._history_path", return_value=cache), \
             patch.object(data.broker, "historical") as hist:
            df = data.history("TEST", "1day", allow_network=False)
            self.assertEqual(len(df), 1)
            hist.assert_not_called()

    def test_allow_network_false_without_cache_returns_empty(self):
        cache = Path(self.tmp.name) / "MISSING.1day.json"
        with patch("psscanner_quant.data.instrument", return_value={"symbol":"MISSING","groww_symbol":"NSE-MISSING"}), \
             patch("psscanner_quant.data._history_path", return_value=cache), \
             patch.object(data.broker, "historical") as hist:
            df = data.history("MISSING", "1day", allow_network=False)
            self.assertTrue(df.empty)
            hist.assert_not_called()

    def test_400_retries_shorter_window_before_quarantine(self):
        cache = Path(self.tmp.name) / "NEWLIST.1day.json"
        response=requests.Response();response.status_code=400
        bad=requests.HTTPError("400 bad request",response=response)
        candles=[[1704067200,100,101,99,100.5,1000]]
        with patch("psscanner_quant.data.instrument", return_value={"symbol":"NEWLIST","groww_symbol":"NSE-NEWLIST"}), \
             patch("psscanner_quant.data._history_path", return_value=cache), \
             patch("psscanner_quant.data.wait_for_slot"), \
             patch("psscanner_quant.data.record_success"), \
             patch("psscanner_quant.data.clear_quarantine"), \
             patch("psscanner_quant.data.quarantine") as quarantine_mock, \
             patch.object(data.broker,"historical",side_effect=[bad,candles]) as hist:
            df=data.history("NEWLIST","1day",force=True)
            self.assertEqual(len(df),1)
            self.assertEqual(hist.call_count,2)
            quarantine_mock.assert_not_called()

    def test_champion_validator_assigns_bar_timestamp_before_pit_resolution(self):
        src=inspect.getsource(validate_strategies)
        self.assertIn("bar_ts=df.index[i]",src)
        self.assertLess(src.index("bar_ts=df.index[i]"),src.index("pit_fund=resolve_snapshot"))


if __name__ == "__main__":
    unittest.main()
