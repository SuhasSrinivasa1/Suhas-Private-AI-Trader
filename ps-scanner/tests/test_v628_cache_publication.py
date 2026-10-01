import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from psscanner_quant.constants import IST, VERSION
from psscanner_quant import data, engine


class V628CachePublicationTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(VERSION, "6.4.3")

    def test_cached_only_history_does_not_require_instrument_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            old = data._CACHE
            try:
                data._CACHE = Path(td)
                p = data._history_path("ABC", "1day")
                candles = [
                    [f"2026-08-{(i % 28) + 1:02d}T10:00:00", 100+i, 101+i, 99+i, 100.5+i, 1000+i, None]
                    for i in range(35)
                ]
                p.write_text(json.dumps({"candles": candles}))
                with patch.object(data, "instrument", side_effect=AssertionError("instrument lookup must not run")):
                    df = data.history("ABC", "1day", allow_network=False)
                self.assertEqual(len(df), 28)  # duplicate dates collapse to unique timestamps
            finally:
                data._CACHE = old

    def test_publication_uses_scan_anchor(self):
        anchor = datetime(2026, 9, 25, 15, 4, tzinfo=IST)
        with patch.object(engine, "_publication_window_open", side_effect=lambda dt=None, book="WEEKLY": dt == anchor), \
             patch.object(engine, "period_key", return_value="2026-09-21"), \
             patch.object(engine, "db") as dbmock:
            con = dbmock.return_value.__enter__.return_value
            con.execute.return_value.fetchone.return_value = [1]
            self.assertEqual(engine._publish_frozen("WEEKLY", publication_anchor=anchor), 0)
            self.assertTrue(con.execute.called)

    def test_intraday_outside_window_clears_stale_detail(self):
        fake_now = datetime(2026, 9, 25, 15, 20, tzinfo=IST)
        states = {}
        with patch.object(engine, "datetime") as dt, \
             patch.object(engine, "set_state", side_effect=lambda k, v: states.__setitem__(k, v)):
            dt.now.return_value = fake_now
            engine.run_intraday_cycle()
        self.assertEqual(states["scan_detail_INTRADAY"]["status"], "OUTSIDE_LIVE_WINDOW")

    def test_daily_history_worker_is_independent(self):
        src = Path(engine.__file__).read_text()
        self.assertIn('("daily_history",', src)
        self.assertIn("warm_daily_history", src)


if __name__ == "__main__":
    unittest.main()
