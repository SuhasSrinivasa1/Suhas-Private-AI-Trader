import inspect
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from psscanner_quant.constants import VERSION, IST
from psscanner_quant import analytics, db as dbmod, engine, lifecycle, trade_intelligence


class V660ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self._old_db_path=dbmod.DB_PATH
        self.tmp=tempfile.TemporaryDirectory()
        dbmod.DB_PATH=Path(self.tmp.name)/"ps_scanner_test.db"
        dbmod.init_db()

    def tearDown(self):
        dbmod.DB_PATH=self._old_db_path
        self.tmp.cleanup()

    def _insert(self, rec_id, book, period_key, symbol, state="CLOSED", result="WIN",
                entry=100.0, current=102.0, side="LONG", ts=None):
        ts=ts or datetime.now(IST).isoformat(timespec="seconds")
        closed=ts if state=="CLOSED" else None
        with dbmod.db() as con:
            con.execute(
                """INSERT INTO recommendations(
                    recommendation_id,book,period_key,symbol,exchange,side,state,score,confidence,
                    entry_price,current_price,target_price,stop_price,target_pct,horizon,regime,
                    created_at,updated_at,closed_at,result,close_reason
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rec_id,book,period_key,symbol,"NSE",side,state,80.0,.8,entry,current,105.0,98.0,5.0,
                 "INTRADAY" if book in ("INTRADAY","CIRCUIT") else "WEEKLY","RANGE",ts,ts,closed,result,
                 "TEST_CLOSE" if closed else None),
            )

    def test_version_and_central_lifecycle_contract(self):
        self.assertEqual(VERSION,"6.7.0")
        payload=lifecycle.lifecycle_payload()
        self.assertEqual(payload["policy_version"],"V670_PRODUCTION_INTEGRITY_AND_REPLAY")
        self.assertIn("PERFORMANCE",payload["pages"])
        self.assertEqual(payload["books"]["INTRADAY"]["default_ui"],"current session LIVE + CLOSED only")

    def test_active_intraday_payload_is_current_period_only_but_history_keeps_both(self):
        today=engine.period_key("INTRADAY")
        prior=(datetime.now(IST).date()-timedelta(days=1)).isoformat()
        self._insert("CUR","INTRADAY",today,"CURSYM",result="WIN")
        self._insert("OLD","INTRADAY",prior,"OLDSYM",result="LOSS",current=98.0)
        active=engine.recommendations("INTRADAY")
        self.assertEqual([r["recommendation_id"] for r in active["closed"]],["CUR"])
        hist=analytics.history_rows("INTRADAY",limit=10)
        self.assertEqual({r["recommendation_id"] for r in hist},{"CUR","OLD"})

    def test_live_payload_exposes_current_quote_freshness(self):
        pk=engine.period_key("INTRADAY")
        self._insert("LIVE","INTRADAY",pk,"FRESHME",state="LIVE",result=None)
        live=engine.recommendations("INTRADAY")["live"]["long"][0]
        self.assertIn(live["freshness"]["state"],{"FRESH","AGING","STALE","INVALID"})
        self.assertIn("quote_asof",live["freshness"])

    def test_weekly_monthly_exclusivity_is_enforced_by_database_trigger(self):
        self._insert("W","WEEKLY",engine.period_key("WEEKLY"),"DUPSYM",state="LIVE",result=None)
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert("M","MONTHLY",engine.period_key("MONTHLY"),"DUPSYM",state="LIVE",result=None)

    def test_void_is_counted_but_excluded_from_performance_denominator(self):
        pk=engine.period_key("INTRADAY")
        self._insert("WIN","INTRADAY",pk,"WINNER",result="WIN",current=103.0)
        self._insert("VOID","INTRADAY",pk,"VOIDED",result="VOID",current=50.0)
        out=analytics.performance("INTRADAY","book",1000)
        self.assertEqual(out["total"]["trading_count"],1)
        self.assertEqual(out["total"]["wins"],1)
        self.assertEqual(out["total"]["voids"],1)
        self.assertEqual(out["total"]["win_rate"],1.0)

    def test_wilson_interval_exposes_small_sample_uncertainty(self):
        lo,hi=analytics.wilson_interval(3,4)
        self.assertLess(lo,.5)
        self.assertGreater(hi,.9)

    def test_single_strategy_is_advisory_not_trade_intelligence_hard_fail(self):
        out=trade_intelligence.evaluate(
            book="WEEKLY",symbol="TEST",side="LONG",
            features={"close":100.0,"atr_pct":2.0,"avg_turnover20":2_000_000,"volume_ratio":1.5},
            fundamentals={},regime_state={"regime":"RANGE"},target_pct=10.0,stop_pct=5.0,
            strategy_ids=["ONE_AUDITED_STRATEGY"],suspended_strategy_ids=[],data_confidence=.9,
        )
        f50=next(x for x in out["filters"] if int(x["rank"])==50)
        self.assertEqual(f50["status"],"PASS")
        self.assertFalse(f50["hard_fail"])

    def test_scan_funnel_tracks_advisory_family_diversity(self):
        src=inspect.getsource(engine.scan_equities)
        self.assertIn("family_vote_advisory",src)
        self.assertIn("strategy_evidence_reject",src)
        self.assertIn("V660_UNVALIDATED_FAMILY_VOTE_IS_ADVISORY",src)
        self.assertIn('"funnel"',src)
        self.assertIn("distance_to_threshold",src)
        self.assertIn("freshness_reject",src)
        self.assertIn('base_min=76 if book=="INTRADAY" else 74',src)
        self.assertNotIn('if not exists and c["score"]>=76',src)

    def test_missed_freeze_recovery_and_session_rollover_are_explicit(self):
        horizon=inspect.getsource(engine.run_single_horizon_cycle)
        live=inspect.getsource(engine.update_live_books)
        self.assertIn("MISSED_FREEZE_CACHED_RECOVERY",horizon)
        self.assertIn("allow_recovery=missed_freeze_recovery",horizon)
        self.assertIn("INTRADAY_SESSION_ROLLOVER",live)
        self.assertIn("CIRCUIT_SESSION_ROLLOVER",live)

    def test_worker_status_exposes_hung_and_restart_telemetry(self):
        src=inspect.getsource(engine.Engine.worker_status)
        self.assertIn('"hung"',src)
        self.assertIn('"timeout_seconds"',src)
        self.assertIn('"restart_count"',src)
        self.assertIn('"rejection_counters"',src)


if __name__=="__main__":
    unittest.main()
