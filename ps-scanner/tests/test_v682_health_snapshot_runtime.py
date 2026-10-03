import inspect
import tempfile
import unittest
from pathlib import Path

from psscanner_quant import db as dbmod, main
from psscanner_quant.constants import VERSION


class V682HealthSnapshotRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.old_db = dbmod.DB_PATH
        self.tmp = tempfile.TemporaryDirectory()
        dbmod.DB_PATH = Path(self.tmp.name) / "psscanner_quant.db"
        dbmod.init_db()

    def tearDown(self):
        dbmod.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_version(self):
        self.assertEqual(VERSION, "6.8.2")

    def test_health_prioritizes_execution_snapshot_before_optional_telemetry(self):
        src = inspect.getsource(main.health)
        order_pos = src.index("SELECT COUNT(*) FROM orders")
        state_pos = src.index("SELECT key,value_json FROM system_state")
        decision_pos = src.index("SELECT decision,COUNT(*) FROM trade_decisions")
        fundamental_pos = src.index("FROM fundamental_snapshots")
        self.assertLess(order_pos, decision_pos)
        self.assertLess(state_pos, decision_pos)
        self.assertLess(order_pos, fundamental_pos)
        self.assertIn('"execution_snapshot_available":order_count is not None', src)
        self.assertIn('"health_snapshot_patch"', src)
        self.assertIn('"static_ip_policy":"EXECUTION_ONLY"', src)

    def test_recent_decision_health_query_uses_time_leading_index(self):
        with dbmod.db() as con:
            plan = con.execute(
                """EXPLAIN QUERY PLAN
                   SELECT decision,COUNT(*)
                   FROM trade_decisions
                   WHERE ts>=datetime('now','-1 day')
                   GROUP BY decision"""
            ).fetchall()
        detail = " ".join(str(r[3]) for r in plan)
        self.assertIn("idx_trade_decisions_ts_decision", detail)

    def test_daily_order_count_uses_day_state_expression_index(self):
        with dbmod.db() as con:
            plan = con.execute(
                """EXPLAIN QUERY PLAN
                   SELECT COUNT(*)
                   FROM orders
                   WHERE substr(created_at,1,10)=?
                     AND state NOT IN ('FAILED','CANCELLED')""",
                ("2026-10-03",),
            ).fetchall()
        detail = " ".join(str(r[3]) for r in plan)
        self.assertIn("idx_orders_created_day_state", detail)

    def test_installer_prefers_modern_python_and_rebuilds_disposable_venv(self):
        root = Path(__file__).resolve().parents[1]
        install = (root / "install.sh").read_text()
        requirements = (root / "requirements.txt").read_text()
        self.assertIn("python3.12 python3.11 python3.10 python3", install)
        self.assertIn("rm -rf .venv", install)
        self.assertIn('"$RUNTIME_PYTHON" -m venv .venv', install)
        self.assertIn('urllib3>=1.26.20,<2; python_version < "3.10"', requirements)


if __name__ == "__main__":
    unittest.main()
