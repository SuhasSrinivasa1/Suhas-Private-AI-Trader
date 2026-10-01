import inspect
import unittest
from unittest.mock import patch

import pandas as pd

from psscanner_quant.constants import VERSION
from psscanner_quant import data
from psscanner_quant.broker import GrowwBroker
from psscanner_quant.config import load_settings


class V643FullBreadthHydrationTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(VERSION, "6.4.3")

    def test_ltp_keeps_partial_success_when_one_batch_fails(self):
        b=GrowwBroker()
        calls={"n":0}
        def fake_request(*args, **kwargs):
            calls["n"]+=1
            syms=(kwargs.get("params") or {}).get("exchange_symbols","").split(",")
            if calls["n"]==2:
                raise RuntimeError("one LTP batch failed")
            return {s: float(i+1) for i,s in enumerate(syms)}
        symbols=[f"NSE_S{i:03d}" for i in range(120)]
        with patch.object(b,"_request",side_effect=fake_request), patch("psscanner_quant.broker.health"):
            out=b.ltp(symbols)
        self.assertEqual(len(out),70)
        self.assertEqual(b._last_ltp_status["failed_batches"],1)
        self.assertEqual(b._last_ltp_status["requested"],120)
        self.assertEqual(b._last_ltp_status["received"],70)


    def test_ltp_400_batch_uses_bounded_ten_symbol_fallback(self):
        import requests
        b=GrowwBroker()
        calls=[]
        def fake_request(*args, **kwargs):
            syms=(kwargs.get("params") or {}).get("exchange_symbols","").split(",")
            calls.append(len(syms))
            if len(syms)==50:
                resp=type("Resp",(),{"status_code":400})()
                err=requests.HTTPError("bad member in batch")
                err.response=resp
                raise err
            return {sym: 1.0 for sym in syms}
        symbols=[f"NSE_F{i:03d}" for i in range(50)]
        with patch.object(b,"_request",side_effect=fake_request), patch("psscanner_quant.broker.health"):
            out=b.ltp(symbols)
        self.assertEqual(len(out),50)
        self.assertEqual(calls,[50,10,10,10,10,10])
        self.assertEqual(b._last_ltp_status["fallback_batches"],5)

    def test_live_price_cache_exposes_batch_telemetry(self):
        data._LTP_CACHE={"prices":{},"updated":{}}
        with patch.object(data.broker,"ltp",return_value={"NSE_A":100.0}), \
             patch.object(data.broker,"_last_ltp_status",{"requested":2,"received":1,"failed_batches":1}), \
             patch.object(data,"set_state") as ss:
            out=data.live_prices(["A","B"],allow_network=True,max_age_seconds=0)
        self.assertEqual(out.get("A"),100.0)
        payload=[c.args[1] for c in ss.call_args_list if c.args and c.args[0]=="live_price_cache_status"][-1]
        self.assertEqual(payload["ltp_batches"]["failed_batches"],1)

    def test_daily_warmer_prioritises_industry_anchors_before_generic_missing(self):
        metas=[
            {"symbol":"A","industry":"UNKNOWN"},
            {"symbol":"B","industry":"BANKS"},
            {"symbol":"C","industry":"IT"},
        ]
        calls=[]
        def hist(sym,*args,**kwargs):
            calls.append(sym)
            return pd.DataFrame({"close":list(range(30))})
        with patch.object(data,"universe",return_value=metas), \
             patch.object(data,"_active_nse_recommendation_symbols",return_value=[]), \
             patch.object(data,"_history_path",side_effect=lambda sym,interval:sym), \
             patch.object(data,"_load_raw_candles",return_value=[]), \
             patch.object(data,"history",side_effect=hist), \
             patch.object(data,"get_state",side_effect=lambda key,default=None: {} if key=="universe_status" else default), \
             patch.object(data,"set_state"):
            out=data.warm_daily_history(2)
        self.assertEqual(calls[:2],["B","C"])
        self.assertEqual(out["priority_industry_anchors"],2)

    def test_missing_history_no_longer_gets_fake_activity_rank(self):
        src=inspect.getsource(data._activity_rank_full_breadth)
        self.assertNotIn("1e6",src)
        self.assertIn("actual live movers",src)

    def test_hydration_defaults_are_scaled_for_full_breadth(self):
        s=load_settings()
        self.assertGreaterEqual(s["daily_history_warm_batch"],64)
        self.assertGreaterEqual(s["intraday_history_warm_batch"],40)
        self.assertLessEqual(s["sector_context_interval_seconds"],300)

    def test_universe_status_surfaces_live_price_refresh_telemetry(self):
        with patch.object(data,"get_state") as gs:
            def fake(key, default=None):
                if key=="universe_status": return {"n":3}
                if key=="full_breadth_discovery": return {"universe":3,"status":"CURRENT","daily_history_ready":1,"intraday_history_ready":1,"live_prices":2,"evaluated":3,"new_or_limited_history":2,"at":"x"}
                if key=="live_price_cache_status": return {"network_received":2,"ltp_batches":{"failed_batches":1}}
                return default
            gs.side_effect=fake
            out=data.universe_status()
        self.assertEqual(out["live_price_refresh"]["network_received"],2)
        self.assertEqual(out["live_price_refresh"]["ltp_batches"]["failed_batches"],1)


if __name__ == "__main__":
    unittest.main()
