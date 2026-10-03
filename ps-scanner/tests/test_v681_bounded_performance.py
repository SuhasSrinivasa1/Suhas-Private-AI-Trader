import inspect
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from psscanner_quant import analytics, db as dbmod, main
from psscanner_quant.constants import VERSION
from psscanner_quant.lifecycle import lifecycle_payload


class V681BoundedPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.old_db=dbmod.DB_PATH
        self.tmp=tempfile.TemporaryDirectory()
        dbmod.DB_PATH=Path(self.tmp.name)/"psscanner_quant.db"
        dbmod.init_db()

    def tearDown(self):
        dbmod.DB_PATH=self.old_db
        self.tmp.cleanup()

    def _insert_closed(self,n=1200):
        rows=[]
        for i in range(n):
            ts=f"2026-09-{1+(i%28):02d}T{9+(i%6):02d}:{i%60:02d}:00+05:30"
            rows.append((
                f"R{i}","INTRADAY",ts[:10],f"S{i}","NSE","LONG","CLOSED",80,.8,
                100.0,101.0,102.0,99.0,2.0,"INTRADAY","RANGE","[]","{}","{}",.9,
                ts,ts,ts,"WIN","TEST","{}",
            ))
        with dbmod.db() as con:
            con.executemany(
                """INSERT INTO recommendations(
                    recommendation_id,book,period_key,symbol,exchange,side,state,score,confidence,
                    entry_price,current_price,target_price,stop_price,target_pct,horizon,regime,
                    strategy_ids_json,rationale_json,feature_snapshot_json,data_confidence,
                    created_at,updated_at,closed_at,result,close_reason,audit_envelope_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",rows
            )

    def test_version_and_lifecycle_policy(self):
        self.assertEqual(VERSION,"6.8.1")
        self.assertEqual(lifecycle_payload()["policy_version"],
                         "V680_SHARED_EVIDENCE_FABRIC_ADAPTIVE_ALGORITHM")

    def test_schema_indexes_closed_ledger_chronology(self):
        with dbmod.db() as con:
            indexes={r[1] for r in con.execute("PRAGMA index_list(recommendations)")}
            plan=" ".join(str(r[3]) for r in con.execute(
                "EXPLAIN QUERY PLAN SELECT book,result,entry_price,current_price,stop_price,created_at,updated_at,closed_at "
                "FROM recommendations WHERE state='CLOSED' "
                "ORDER BY COALESCE(closed_at,updated_at,created_at) ASC LIMIT 1000"
            ).fetchall())
        self.assertIn("idx_recs_state_closed_time",indexes)
        self.assertIn("idx_recs_book_state_closed_time",indexes)
        self.assertIn("idx_recs_state_closed_time",plan)

    def test_book_projection_does_not_load_large_json_envelopes(self):
        cols=analytics._performance_select_columns("book")
        self.assertNotIn("rationale_json",cols)
        self.assertNotIn("feature_snapshot_json",cols)
        self.assertNotIn("audit_envelope_json",cols)
        self.assertIn("rationale_json",analytics._performance_select_columns("behavior_cluster"))
        self.assertIn("strategy_ids_json",analytics._performance_select_columns("family"))

    def test_http_performance_path_is_bounded_passive_single_snapshot(self):
        self._insert_closed()
        started=time.monotonic()
        out=main.performance(group_by="book",limit=1000)
        elapsed=time.monotonic()-started
        self.assertTrue(out["complete"],out.get("degraded"))
        self.assertEqual(out["rows_scanned"],1000)
        c=out["performance_contract"]
        self.assertTrue(c["passive"])
        self.assertFalse(c["network_calls"])
        self.assertTrue(c["bounded"])
        self.assertEqual(c["db_snapshot_connections"],1)
        self.assertLess(elapsed,3.5)

    def test_sql_budget_interrupt_degrades_truthfully_instead_of_hanging(self):
        class InterruptedCon:
            def set_progress_handler(self,*args):
                pass
            def execute(self,*args):
                raise sqlite3.OperationalError("interrupted")
        class InterruptedDb:
            def __enter__(self):
                return InterruptedCon()
            def __exit__(self,*args):
                return False
        started=time.monotonic()
        with patch.object(analytics,"db",return_value=InterruptedDb()):
            out=analytics.performance(group_by="book",limit=50000,query_budget_seconds=.1,db_timeout_seconds=.05)
        elapsed=time.monotonic()-started
        self.assertFalse(out["complete"])
        self.assertEqual(out["status"],"DEGRADED")
        self.assertEqual(out["degraded"]["reason"],"SQL_BUDGET_EXCEEDED")
        self.assertIsNone(out["total"])
        self.assertEqual(out["groups"],[])
        self.assertLess(elapsed,1.0)

    def test_learning_path_does_not_apply_passive_budget(self):
        src=inspect.getsource(analytics.learning_evidence_snapshot)
        self.assertIn('performance(group_by="book", limit=limit)',src)
        self.assertNotIn("query_budget_seconds",src)

    def test_internal_unbounded_analytics_does_not_silently_drop_db_errors(self):
        class BrokenDb:
            def __enter__(self):
                raise sqlite3.OperationalError("database is locked")
            def __exit__(self,*args):
                return False
        with patch.object(analytics,"db",return_value=BrokenDb()):
            with self.assertRaises(sqlite3.OperationalError):
                analytics.performance(group_by="book",limit=1000)


if __name__=="__main__":
    unittest.main()
