import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from psscanner_quant import analytics, db as dbmod, main


class V681PerformanceReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.old_db = dbmod.DB_PATH
        self.tmp = tempfile.TemporaryDirectory()
        dbmod.DB_PATH = Path(self.tmp.name) / "psscanner_quant.db"
        dbmod.init_db()

    def tearDown(self):
        dbmod.DB_PATH = self.old_db
        self.tmp.cleanup()

    def _closed_rows(self, count=1200):
        blob = '{"blob":"' + ("x" * 4096) + '"}'
        rows = []
        for i in range(count):
            ts = f"2026-09-{1 + (i % 28):02d}T10:{i % 60:02d}:00+05:30"
            rows.append((
                f"R{i}", "INTRADAY", ts[:10], f"S{i}", "NSE", "LONG", "CLOSED",
                80.0, .8, 100.0, 102.0, 102.0, 99.0, 2.0, "INTRADAY", "RANGE",
                '["S1"]', blob, blob, .9, ts, ts, ts, "WIN", "TEST", 2.0, -1.0,
                "6.8.1", "cfg", f"D{i}", blob,
            ))
        with dbmod.db() as con:
            con.executemany(
                """INSERT INTO recommendations(
                    recommendation_id,book,period_key,symbol,exchange,side,state,score,confidence,
                    entry_price,current_price,target_price,stop_price,target_pct,horizon,regime,
                    strategy_ids_json,rationale_json,feature_snapshot_json,data_confidence,
                    created_at,updated_at,closed_at,result,close_reason,max_favourable_pct,
                    max_adverse_pct,software_version,config_hash,decision_id,audit_envelope_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )

    def test_closed_performance_query_uses_order_index(self):
        with dbmod.db() as con:
            plan = con.execute(
                """EXPLAIN QUERY PLAN
                   SELECT book,period_key,symbol,side,regime,horizon,result,close_reason,
                          entry_price,current_price,stop_price,created_at,updated_at,closed_at
                   FROM recommendations
                   WHERE state='CLOSED'
                   ORDER BY COALESCE(closed_at,updated_at,created_at) ASC
                   LIMIT 1000"""
            ).fetchall()
        detail = " ".join(str(r[3]) for r in plan)
        self.assertIn("idx_recs_state_closed_order", detail)

    def test_book_performance_avoids_wide_json_decode(self):
        self._closed_rows()
        with patch.object(analytics.json, "loads", side_effect=AssertionError("wide JSON decoded")):
            out = analytics.performance(
                group_by="book", limit=1000, budget_seconds=2.5, db_timeout_seconds=.5
            )
        self.assertTrue(out["complete"])
        self.assertEqual(out["status"], "COMPLETE")
        self.assertEqual(out["rows_scanned"], 1000)
        contract = out["performance_contract"]
        self.assertTrue(contract["passive_bounded"])
        self.assertTrue(contract["narrow_projection"])
        self.assertNotIn("feature_snapshot_json", contract["selected_columns"])
        self.assertNotIn("audit_envelope_json", contract["selected_columns"])
        self.assertFalse(contract["network_calls"])

    def test_bounded_api_failure_is_explicit_and_never_partial(self):
        with patch.object(analytics, "db", side_effect=sqlite3.OperationalError("database is locked")):
            out = analytics.performance(group_by="book", limit=1000, budget_seconds=.1, db_timeout_seconds=.05)
        self.assertFalse(out["complete"])
        self.assertEqual(out["status"], "DEGRADED_BOUNDED")
        self.assertEqual(out["rows_scanned"], 0)
        self.assertEqual(out["groups"], [])
        self.assertFalse(out["performance_contract"]["partial_rows_published"])

    def test_internal_learning_path_does_not_silently_degrade(self):
        with patch.object(analytics, "db", side_effect=sqlite3.OperationalError("database is locked")):
            with self.assertRaises(sqlite3.OperationalError):
                analytics.performance(group_by="book", limit=1000)

    def test_route_uses_passive_budget_not_validator_timeout_inflation(self):
        src = inspect.getsource(main.performance)
        self.assertIn("budget_seconds=2.5", src)
        self.assertIn("db_timeout_seconds=.5", src)


if __name__ == "__main__":
    unittest.main()
