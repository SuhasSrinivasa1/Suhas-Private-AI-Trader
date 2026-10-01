import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from psscanner_quant.constants import IST, VERSION
from psscanner_quant import analytics, db as dbmod, engine, lifecycle
from psscanner_quant.specialized import _etf_missed_freeze_recovery_allowed


class V661IntegrityTests(unittest.TestCase):
    def setUp(self):
        self._old_db_path=dbmod.DB_PATH
        self.tmp=tempfile.TemporaryDirectory()
        dbmod.DB_PATH=Path(self.tmp.name)/"ps_scanner_test.db"
        dbmod.init_db()

    def tearDown(self):
        dbmod.DB_PATH=self._old_db_path
        self.tmp.cleanup()

    def _insert(self, rec_id, book, period_key, symbol, state="LIVE", result=None,
                side="LONG", created_at="2026-10-01T09:00:00+05:30", current=102.0):
        closed_at=created_at if state=="CLOSED" else None
        with dbmod.db() as con:
            con.execute(
                """INSERT INTO recommendations(
                    recommendation_id,book,period_key,symbol,exchange,side,state,score,confidence,
                    entry_price,current_price,target_price,stop_price,target_pct,horizon,regime,
                    created_at,updated_at,closed_at,result,close_reason
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rec_id,book,period_key,symbol,"NSE",side,state,80.0,.8,100.0,current,105.0,98.0,5.0,
                 "MONTHLY" if book=="MONTHLY" else ("WEEKLY" if book=="WEEKLY" else "INTRADAY"),
                 "RANGE",created_at,created_at,closed_at,result,"TEST_CLOSE" if closed_at else None),
            )

    def test_version_and_policy(self):
        self.assertEqual(VERSION,"6.7.1")
        self.assertEqual(lifecycle.lifecycle_payload()["policy_version"],
                         "V671_NONBLOCKING_HEALTH_AND_VALIDATION")

    def test_weekly_monthly_overlap_stays_exclusive_after_early_close(self):
        self._insert("W-CLOSED","WEEKLY","2026-09-28","OVERLAP",state="CLOSED",result="WIN")
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert("M-LIVE","MONTHLY","2026-10","OVERLAP")

    def test_non_overlapping_weekly_monthly_periods_may_reuse_symbol(self):
        self._insert("W-OLD","WEEKLY","2026-09-21","REUSE",state="CLOSED",result="WIN")
        self._insert("M-NEW","MONTHLY","2026-10","REUSE")
        with dbmod.db() as con:
            n=con.execute("SELECT COUNT(*) FROM recommendations WHERE symbol='REUSE'").fetchone()[0]
        self.assertEqual(n,2)

    def test_application_conflict_query_includes_closed_frozen_identity(self):
        self._insert("W-CLOSED","WEEKLY","2026-09-28","BLOCKME",state="CLOSED",result="LOSS")
        self.assertIn("BLOCKME",engine._weekly_monthly_conflicts("MONTHLY","2026-10"))

    def test_intraday_bootstrap_requires_actual_complete_pass_before_no_opportunity(self):
        first=engine._merge_intraday_bootstrap_pass(
            "2026-10-01",
            {"pass_started":0,"completed_pass":False,"ready":4},
            {"processed":2,"full_nse_universe":10,"near_misses":[],
             "funnel":{"universe_total":10,"history_ready":2,"publication_ready":0}},
            0,
        )
        self.assertFalse(first["exhaustive_cached_ready_pass"])
        self.assertEqual(first["classification"],"SEARCH_INCOMPLETE")
        second=engine._merge_intraday_bootstrap_pass(
            "2026-10-01",
            {"pass_started":0,"completed_pass":True,"ready":4},
            {"processed":2,"full_nse_universe":10,"near_misses":[],
             "funnel":{"universe_total":10,"history_ready":2,"publication_ready":0}},
            0,
        )
        self.assertTrue(second["exhaustive_cached_ready_pass"])
        self.assertEqual(second["scanned"],4)
        self.assertEqual(second["classification"],"NO_QUALIFIED_OPPORTUNITY_IN_CACHED_READY_UNIVERSE")

    def test_etf_missed_freeze_recovery_is_market_hours_bounded(self):
        during=datetime(2026,10,1,15,28,tzinfo=IST)
        after=datetime(2026,10,1,20,0,tzinfo=IST)
        self.assertTrue(_etf_missed_freeze_recovery_allowed(during,0,5,False))
        self.assertFalse(_etf_missed_freeze_recovery_allowed(after,0,5,False))

    def test_every_connection_reasserts_wal_synchronous_policy(self):
        with dbmod.db() as con:
            self.assertEqual(str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower(),"wal")
            self.assertEqual(int(con.execute("PRAGMA synchronous").fetchone()[0]),1)

    def test_performance_exposes_loss_and_miss_rates(self):
        pk="2026-10-01"
        self._insert("P-WIN","INTRADAY",pk,"PWIN",state="CLOSED",result="WIN",current=103.0)
        self._insert("P-LOSS","INTRADAY",pk,"PLOSS",state="CLOSED",result="LOSS",current=98.0)
        self._insert("P-MISS","INTRADAY",pk,"PMISS",state="CLOSED",result="MISS",current=100.0)
        total=analytics.performance("INTRADAY","book",1000)["total"]
        self.assertEqual(total["trading_count"],3)
        self.assertEqual(total["win_rate"],.3333)
        self.assertEqual(total["loss_rate"],.3333)
        self.assertEqual(total["miss_rate"],.3333)


if __name__=="__main__":
    unittest.main()
