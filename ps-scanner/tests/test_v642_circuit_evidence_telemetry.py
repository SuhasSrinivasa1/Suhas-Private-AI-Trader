import inspect
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd

from psscanner_quant.constants import VERSION, IST
from psscanner_quant import data, specialized


class V642CircuitEvidenceTelemetryTests(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split("."))), (6, 4, 3))

    def test_stale_breadth_counts_are_not_exposed_for_smaller_current_universe(self):
        with patch.object(data,"get_state") as gs:
            def fake(key, default=None):
                if key=="universe_status": return {"n":3395,"source":"GROWW_NSE_EQUITY_SHARE_MASTER_V642"}
                if key=="full_breadth_discovery": return {"universe":4290,"evaluated":4290,"live_prices":4093,"new_or_limited_history":4078,"daily_history_ready":212,"intraday_history_ready":121,"status":"CURRENT"}
                if key=="daily_history_warm_status": return {"coverage":{"ready":80}}
                if key=="last_intraday_history_warm": return {"ready":24}
                return default
            gs.side_effect=fake
            out=data.universe_status()
        self.assertEqual(out["breadth_status"],"AWAITING_CURRENT_UNIVERSE_PASS")
        self.assertIsNone(out["live_prices_ready"])
        self.assertIsNone(out["breadth_evaluated"])
        self.assertIsNone(out["new_or_limited_history"])

    def test_fresh_intraday_helper_rejects_previous_session(self):
        now=datetime(2026,9,28,13,20,tzinfo=IST)
        old=pd.DataFrame({"close":[100]*5},index=pd.date_range("2026-09-25 14:55",periods=5,freq="5min",tz=IST))
        ok,age,reason=specialized._fresh_intraday_session_evidence(old,now)
        self.assertFalse(ok)
        self.assertEqual(reason,"latest_bar_not_current_session")

    def test_fresh_intraday_helper_accepts_recent_current_session_bar(self):
        now=datetime(2026,9,28,13,20,tzinfo=IST)
        cur=pd.DataFrame({"close":[100]*5},index=pd.date_range("2026-09-28 12:55",periods=5,freq="5min",tz=IST))
        ok,age,reason=specialized._fresh_intraday_session_evidence(cur,now)
        self.assertTrue(ok)
        self.assertLessEqual(age,30)

    def test_circuit_source_requires_fresh_liquidity_volume_and_execution_permission(self):
        src=inspect.getsource(specialized.run_circuit_cycle)
        self.assertIn("fresh_intraday",src)
        self.assertIn("live_turnover<1_000_000",src)
        self.assertIn("historical_liquidity_unknown_or_failed",src)
        self.assertIn("relative_volume_not_confirmed",src)
        self.assertIn("_circuit_execution_permission",src)
        self.assertIn("V642_FRESH_INTRADAY_LIQUIDITY_EXECUTION",src)

    def test_installer_voids_pre_v642_live_circuit_rows(self):
        from pathlib import Path
        text=(Path(__file__).resolve().parents[1]/"install.sh").read_text()
        self.assertIn("V642_CIRCUIT_EVIDENCE_RESET",text)
        self.assertIn("V642_FRESH_INTRADAY_LIQUIDITY_EXECUTION",text)

if __name__ == "__main__":
    unittest.main()
