import inspect
import unittest
from unittest.mock import patch

from psscanner_quant.constants import VERSION
from psscanner_quant import data, engine


class V641EquityShareUniverseTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(VERSION, "6.4.3")

    def test_nse_share_series_excludes_debt_funds_and_other_cash_securities(self):
        allowed = ["EQ","BE","BZ","SM","ST","SZ","E1","EA","X1","XZ"]
        blocked = ["N0","N1","NA","Y3","Z4","GB","GS","SG","MF","IV","RR","P1","Q1","W1","D1","S1",""]
        for series in allowed:
            self.assertTrue(data._is_equity_share_series(series), series)
        for series in blocked:
            self.assertFalse(data._is_equity_share_series(series), series)

    def test_cash_eq_type_alone_does_not_admit_ncd(self):
        base={"exchange":"NSE","segment":"CASH","instrument_type":"EQ","trading_symbol":"X","name":"X"}
        self.assertTrue(data._is_nse_cash_equity_row({**base,"series":"EQ"}))
        self.assertFalse(data._is_nse_cash_equity_row({**base,"series":"N0","trading_symbol":"1003IIFL29","name":"IIFL NCD"}))
        self.assertFalse(data._is_nse_cash_equity_row({**base,"series":"GB","trading_symbol":"SGBTEST","name":"Sovereign Gold Bond"}))
        self.assertFalse(data._is_nse_cash_equity_row({**base,"series":"EQ","trading_symbol":"NIFTYBEES","name":"Nippon India ETF Nifty BeES"}))

    def test_universe_status_prefers_current_breadth_readiness(self):
        with patch.object(data,"get_state") as gs:
            def fake(key, default=None):
                if key=="universe_status": return {"n":3520,"source":"GROWW_NSE_EQUITY_SHARE_MASTER_V642"}
                if key=="full_breadth_discovery": return {"universe":3520,"status":"CURRENT","daily_history_ready":205,"intraday_history_ready":120,"live_prices":3400,"evaluated":3520,"new_or_limited_history":3300,"at":"x"}
                if key=="daily_history_warm_status": return {"coverage":{"ready":80}}
                if key=="last_intraday_history_warm": return {"ready":24}
                return default
            gs.side_effect=fake
            out=data.universe_status()
        self.assertEqual(out["daily_ready"],205)
        self.assertEqual(out["intraday_ready"],120)

    def test_stale_v640_mixed_universe_is_rebuilt_before_use(self):
        import json, tempfile
        from pathlib import Path
        rows=[{"exchange":"NSE","segment":"CASH","instrument_type":"EQ","series":"EQ","trading_symbol":"REAL","groww_symbol":"NSE-REAL"}]
        with tempfile.TemporaryDirectory() as td:
            up=Path(td)/"universe.json"
            up.write_text(json.dumps({"source":"GROWW_NSE_FULL_CASH_EQUITY_MASTER","symbols":[{"symbol":"1003IIFL29"}]}))
            with patch.object(data,"UNIVERSE_PATH",up), patch.object(data,"instrument_rows",return_value=rows), patch.object(data,"_nifty500_constituents",return_value=[]), patch.object(data,"set_state"):
                out=data.universe()
        self.assertEqual([x["symbol"] for x in out],["REAL"])

    def test_circuit_missing_cache_alone_does_not_trigger_exact_quote(self):
        import inspect
        from psscanner_quant import specialized
        src=inspect.getsource(specialized.run_circuit_cycle)
        self.assertIn("exact_needed=bool(move is not None and move>=1.0) or sym in new_symbols",src)
        self.assertIn("intraday_move",src)
        self.assertNotIn("if limited or (move is not None and move>=1.0)",src)

    def test_scan_missing_cache_fast_path_avoids_empty_dataframe_churn(self):
        src=inspect.getsource(engine.scan_equities)
        self.assertIn("if not path.exists()",src)
        self.assertIn("raw_hist=_load_raw_candles(path)",src)
        self.assertIn("limited_history_samples",src)

    def test_closed_horizon_state_reports_current_universe_separately(self):
        captured={}
        with patch.object(engine,"get_state",return_value={"book":"WEEKLY","universe":80,"stage":"SCORING"}), \
             patch.object(engine,"universe_status",return_value={"n":3522}), \
             patch.object(engine,"set_state",side_effect=lambda k,v: captured.update({k:v})):
            engine._mark_scan_detail_idle("WEEKLY","MORNING_FREEZE_WINDOW_CLOSED")
        d=captured["scan_detail_WEEKLY"]
        self.assertEqual(d["last_scan_universe"],80)
        self.assertEqual(d["current_universe"],3522)
        self.assertFalse(d["running"])


if __name__ == "__main__":
    unittest.main()
