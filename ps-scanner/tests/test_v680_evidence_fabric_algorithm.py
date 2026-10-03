import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from psscanner_quant import db as dbmod
from psscanner_quant import evidence_fabric
from psscanner_quant import institutional_intelligence as ii
from psscanner_quant import main, specialized, trading_algorithm
from psscanner_quant.constants import VERSION
from psscanner_quant.features import latest_features
from psscanner_quant.lifecycle import lifecycle_payload
from psscanner_quant.strategy_library import build_library, seed_library


class V680EvidenceFabricAlgorithmTests(unittest.TestCase):
    def setUp(self):
        self.old_db=dbmod.DB_PATH
        self.tmp=tempfile.TemporaryDirectory()
        dbmod.DB_PATH=Path(self.tmp.name)/"psscanner_quant.db"
        dbmod.init_db()

    def tearDown(self):
        dbmod.DB_PATH=self.old_db
        self.tmp.cleanup()

    def test_version_and_lifecycle(self):
        self.assertEqual(VERSION,"6.8.1")
        self.assertEqual(lifecycle_payload()["policy_version"],
                         "V680_SHARED_EVIDENCE_FABRIC_ADAPTIVE_ALGORITHM")

    def test_accumulation_features_are_numeric(self):
        idx=pd.date_range("2026-01-01",periods=40,freq="D")
        close=pd.Series([100+i*.4+(1 if i%3==0 else 0) for i in range(40)],index=idx)
        df=pd.DataFrame({
            "open":close-.3,"high":close+1.0,"low":close-1.0,
            "close":close,"volume":[100000+i*2500 for i in range(40)]
        },index=idx)
        f=latest_features(df)
        for key in ("cmf20","mfi14","obv","obv_trend5"):
            self.assertIn(key,f)
            self.assertIsInstance(f[key],float)

    def test_institutional_family_is_challenger_only_at_seed(self):
        self.assertTrue(any(x.family=="INSTITUTIONAL_ACCUMULATION" for x in build_library()))
        seed_library()
        with dbmod.db() as con:
            rows=con.execute(
                "SELECT DISTINCT status FROM strategies WHERE family='INSTITUTIONAL_ACCUMULATION'"
            ).fetchall()
        self.assertEqual({r[0] for r in rows},{"CHALLENGER"})

    def test_accuracy_target_is_never_manufactured(self):
        low=trading_algorithm._metrics([{"result":"WIN","entry_price":100,"current_price":110,"side":"LONG"}]*4)
        self.assertAlmostEqual(low["target_hit_rate"],1.0)
        self.assertFalse(low["observed_target_met"])
        self.assertFalse(low["confidence_supported_80"])
        self.assertIn("never a guaranteed",low["claim_policy"])

    def test_algorithm_version_is_deterministic_for_manifest(self):
        rows=[{"strategy_id":"A","family":"F","status":"CHAMPION","version":1}]
        self.assertEqual(trading_algorithm._manifest_hash(rows),trading_algorithm._manifest_hash(rows))

    def test_fabric_records_reuse_contract(self):
        out=evidence_fabric.publish("unit_test",source="ONE_FETCH",consumers=("A","B"),payload={"n":1},network_fetch=True,ttl_seconds=60)
        self.assertEqual(out["network_fetch_runs"],1)
        st=evidence_fabric.status()["domains"]["unit_test"]
        self.assertEqual(st["consumers"],["A","B"])
        self.assertTrue(st["fresh"])

    def test_live_update_consumes_cached_prices(self):
        from psscanner_quant import engine
        src=inspect.getsource(engine.update_live_books)
        self.assertIn("allow_network=False",src)
        self.assertIn("max_age_seconds=90",src)

    def test_scheduler_has_shared_producers_without_lowering_scanner_cadence(self):
        from psscanner_quant import engine
        src=Path(engine.__file__).read_text()
        for worker in ('"priority_quotes"','"news"','"events"','"institutional"','"algorithm"'):
            self.assertIn(worker,src)
        self.assertIn('settings.get("intraday_worker_interval_seconds",120)',src)
        self.assertIn('settings.get("horizon_worker_interval_seconds",300)',src)
        self.assertIn('settings.get("circuit_worker_interval_seconds",120)',src)
        self.assertIn('settings.get("international_worker_interval_seconds",120)',src)
        self.assertIn('settings.get("etf_worker_interval_seconds",600)',src)

    def test_core_scanner_uses_shared_symbol_context(self):
        from psscanner_quant import engine
        src=inspect.getsource(engine.scan_equities)
        self.assertIn("fabric_symbol_context",src)
        self.assertIn("institutional_ctx=ictx",src)

    def test_institutional_context_separates_direct_and_inferred_evidence(self):
        state={"status":"READY","captured_at":"2026-10-03T10:00:00+05:30","flows":{},
               "large_deals":[{"symbol":"ABC","kind":"BULK","side":"BUY","quantity":1000,"price":100,"value_rupees":100000,"client":"Fund"}]}
        with patch.object(ii,"cached_status",return_value=state):
            out=ii.context("ABC",features={"cmf20":.15,"mfi14":65,"obv_trend5":.2,"volume_ratio":1.6},fundamentals={"heldPercentInstitutions":.20})
        self.assertEqual(out["large_deal_evidence"]["direction"],"BUY")
        self.assertIn("does not identify the buyer",out["identity_caution"])
        self.assertEqual(out["live_scoring_mode"],"ADVISORY_UNTIL_CHALLENGER_OOS_PROMOTION")

    def test_shared_international_cache_prevents_duplicate_transport(self):
        specialized._INTL_SHARED.clear()
        fake={"SPY":pd.DataFrame({"close":[1.0]})}
        with patch.object(specialized,"international_batch_history",return_value=fake) as fetch:
            a=specialized._shared_international_history(["SPY"],"5d","5m",90)
            b=specialized._shared_international_history(["SPY"],"5d","5m",90)
        self.assertIn("SPY",a);self.assertIn("SPY",b)
        self.assertEqual(fetch.call_count,1)

    def test_api_and_ui_expose_algorithm_and_fabric(self):
        paths={r.path for r in main.app.routes}
        self.assertIn("/api/algorithm",paths)
        self.assertIn("/api/evidence/fabric",paths)
        self.assertIn("/api/institutional",paths)
        ui=(Path(__file__).resolve().parents[1]/"static"/"index.html").read_text()
        self.assertIn('data-view="ALGORITHM"',ui)
        self.assertIn("80% is an evidence target, not a guarantee",ui)
        self.assertIn("FULL NSE BREADTH",ui)


if __name__=="__main__":
    unittest.main()
