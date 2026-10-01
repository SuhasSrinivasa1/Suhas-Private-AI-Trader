import inspect
import json
import tempfile
import unittest
import threading
import time
from pathlib import Path
from unittest.mock import patch

from psscanner_quant.constants import VERSION
from psscanner_quant import data, engine, specialized, main
from psscanner_quant.config import load_settings, update_settings


class V640FullNSEBreadthTests(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split("."))), (6, 4, 3))

    def test_universe_uses_full_groww_nse_equity_master_without_cap(self):
        rows=[]
        series=("EQ","BE","BZ","SM","ST","SZ")
        for i in range(4200):
            rows.append({
                "exchange":"NSE","segment":"CASH","instrument_type":"EQ",
                "series":series[i % len(series)],"trading_symbol":f"S{i:04d}",
                "groww_symbol":f"NSE-S{i:04d}","name":f"Stock {i}","isin":f"INE{i:09d}",
                "tick_size":"0.05","buy_allowed":"0" if i==3 else "1",
                "sell_allowed":"1","is_intraday":"1",
            })
        rows += [
            # Partly-paid equity is still an equity share and must remain discoverable.
            {"exchange":"NSE","segment":"CASH","instrument_type":"EQ","series":"E1","trading_symbol":"PARTPAID","groww_symbol":"NSE-PARTPAID","name":"Partly Paid Equity"},
            # CASH + instrument_type=EQ is not enough: these series are not shares.
            {"exchange":"NSE","segment":"CASH","instrument_type":"EQ","series":"N0","trading_symbol":"1003IIFL29","groww_symbol":"NSE-1003IIFL29","name":"IIFL NCD"},
            {"exchange":"NSE","segment":"CASH","instrument_type":"EQ","series":"GB","trading_symbol":"SGBTEST","groww_symbol":"NSE-SGBTEST","name":"Sovereign Gold Bond"},
            {"exchange":"NSE","segment":"CASH","instrument_type":"ETF","series":"EQ","trading_symbol":"NOTSTOCK"},
            {"exchange":"NSE","segment":"FNO","instrument_type":"EQ","series":"EQ","trading_symbol":"NOTCASH"},
            {"exchange":"BSE","segment":"CASH","instrument_type":"EQ","series":"EQ","trading_symbol":"NOTNSE"},
        ]
        with tempfile.TemporaryDirectory() as td:
            up=Path(td)/"universe.json"
            with patch.object(data,"UNIVERSE_PATH",up), \
                 patch.object(data,"instrument_rows",return_value=rows), \
                 patch.object(data,"_nifty500_constituents",return_value=[]), \
                 patch.object(data,"set_state"):
                out=data.refresh_universe(force=True)
        self.assertEqual(out["n"],4201)
        self.assertEqual(out["source"],"GROWW_NSE_EQUITY_SHARE_MASTER_V642")
        self.assertIn("SM",out["series_counts"])
        self.assertIn("E1",out["series_counts"])
        self.assertEqual(len(out["symbols"]),4201)
        symbols=[x["symbol"] for x in out["symbols"]]
        self.assertIn("PARTPAID",symbols)
        self.assertNotIn("1003IIFL29",symbols)
        self.assertNotIn("SGBTEST",symbols)
        self.assertIn("N0",out["excluded_non_share_series_counts"])
        self.assertIn("GB",out["excluded_non_share_series_counts"])

    def test_scanners_no_longer_use_liquidity_rank_as_universe_cap(self):
        src=inspect.getsource(engine.scan_equities)
        self.assertIn("metas=universe()",src)
        self.assertIn("FULL_GROWW_NSE_EQUITY_SHARES_NO_TOP_N_CAP",src)
        self.assertNotIn("syms = liquidity_rank(size)",src)
        self.assertIn("finalists=raw",src)
        cycle=inspect.getsource(engine.run_intraday_cycle)
        horizon=inspect.getsource(engine.run_single_horizon_cycle)
        self.assertNotIn("[:40]",cycle)
        self.assertNotIn("[:60]",horizon)

    def test_circuit_coarse_screens_full_nse_before_exact_quotes(self):
        src=inspect.getsource(specialized.run_circuit_cycle)
        self.assertIn("pool=full_nse_symbols()",src)
        self.assertIn("breadth_screened",src)
        self.assertIn("exact_quote_candidates",src)
        self.assertNotIn("liquidity_rank(max(100",src)

    def test_market_snapshot_and_regime_are_full_breadth(self):
        src=inspect.getsource(engine.Engine._market_snapshot)
        self.assertIn("full_nse_symbols()",src)
        self.assertIn("full_breadth_discovery_snapshot",src)

    def test_legacy_scan_caps_are_policy_disabled(self):
        s=load_settings()
        self.assertEqual(s["universe_size"],0)
        self.assertEqual(s["intraday_scan_size"],0)
        self.assertEqual(s["horizon_scan_size"],0)
        self.assertTrue(s["full_nse_breadth_enabled"])

    def test_ui_exposes_actual_dynamic_nse_universe(self):
        html=(Path(__file__).resolve().parents[1]/"static"/"index.html").read_text()
        self.assertIn("NSE UNIVERSE",html)
        self.assertIn("u.n??0",html)
        self.assertIn("FULL NSE BREADTH",html)

    def test_history_coverage_endpoint_defaults_to_full_universe(self):
        src=inspect.getsource(main.history_coverage)
        self.assertIn("full_nse_symbols()",src)
        self.assertIn("if int(limit)>0",src)

    def test_full_market_ltp_refresh_does_not_block_cached_readers(self):
        # A many-batch network refresh must not monopolize the in-process LTP cache lock.
        data._LTP_CACHE={"prices":{"OLD":123.0},"updated":{"OLD":time.time()}}
        entered=threading.Event();release=threading.Event()
        def slow_ltp(keys):
            entered.set();release.wait(1.0);return {"NSE_NEW":10.0}
        with patch.object(data.broker,"ltp",side_effect=slow_ltp), patch.object(data,"set_state"):
            t=threading.Thread(target=lambda:data.live_prices(["NEW"],allow_network=True,max_age_seconds=0),daemon=True)
            t.start();self.assertTrue(entered.wait(.5))
            started=time.monotonic();got=data.cached_live_prices(["OLD"],max_age_seconds=600);elapsed=time.monotonic()-started
            release.set();t.join(1.0)
        self.assertEqual(got.get("OLD"),123.0)
        self.assertLess(elapsed,.2)

    def test_refresh_marks_new_listings_without_dropping_them_for_missing_history(self):
        rows=[]
        for sym in ("OLD1","OLD2","NEWIPO"):
            rows.append({"exchange":"NSE","segment":"CASH","instrument_type":"EQ","series":"EQ","trading_symbol":sym,"groww_symbol":f"NSE-{sym}","buy_allowed":"1","sell_allowed":"1"})
        with tempfile.TemporaryDirectory() as td:
            up=Path(td)/"universe.json"
            up.write_text(json.dumps({"source":"GROWW_NSE_EQUITY_SHARE_MASTER_V642","symbols":[{"symbol":"OLD1"},{"symbol":"OLD2"}]}))
            with patch.object(data,"UNIVERSE_PATH",up), patch.object(data,"instrument_rows",return_value=rows), patch.object(data,"_nifty500_constituents",return_value=[]), patch.object(data,"set_state"):
                out=data.refresh_universe(force=True)
        self.assertIn("NEWIPO",out["new_since_last_refresh"])
        self.assertIn("NEWIPO",[x["symbol"] for x in out["symbols"]])
        self.assertEqual(out["new_since_last_refresh_count"],1)


if __name__ == "__main__":
    unittest.main()
