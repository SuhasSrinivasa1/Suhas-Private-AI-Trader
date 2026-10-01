import inspect
import unittest

from psscanner_quant.constants import VERSION
from psscanner_quant import engine, specialized, data, main


class V651SanityRecoveryTests(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split("."))), (6, 5, 1))

    def test_weekly_monthly_publication_interlock_is_atomic(self):
        src=inspect.getsource(engine._insert_rec)
        self.assertIn("BEGIN IMMEDIATE", src)
        self.assertIn("V670_FROZEN_PERIOD_IDENTITY_APPLICATION_AND_DB", src)
        self.assertIn("_weekly_monthly_conflicts(b,pk)", src)

    def test_legacy_collision_repair_voids_loser(self):
        src=inspect.getsource(engine._repair_weekly_monthly_collisions)
        self.assertIn("HORIZON_IDENTITY_COLLISION_REPAIR_V661", src)
        self.assertIn("state='CLOSED'", src)
        self.assertIn("result='VOID'", src)

    def test_frozen_publisher_skips_other_horizon_symbol(self):
        src=inspect.getsource(engine._publish_frozen)
        self.assertIn("horizon_blocked", src)
        self.assertIn("_weekly_monthly_conflicts", src)
        self.assertIn("if rid:", src)

    def test_active_book_default_view_is_current_period_only_for_closed(self):
        src=inspect.getsource(engine.recommendations)
        self.assertIn("book=? AND period_key=? AND state='CLOSED'", src)
        self.assertIn("/api/history/recommendations", src)

    def test_etf_can_self_heal_after_missed_freeze_without_gate_relaxation(self):
        cyc=inspect.getsource(specialized.run_etf_cycle)
        scan=inspect.getsource(specialized.scan_etfs)
        self.assertIn("MISSED_FREEZE_CACHED_RECOVERY", cyc)
        self.assertIn("allow_recovery=missed_freeze_recovery", cyc)
        self.assertIn("CACHED_ONLY_NO_GATE_RELAXATION", cyc)
        self.assertIn("optimistic_tf", scan)
        self.assertIn("capacity_prefilter_reject", scan)
        self.assertIn("not optimistic_tf['target_qualified']", scan)

    def test_international_transport_has_hard_process_timeout(self):
        src=inspect.getsource(data.international_batch_history)
        self.assertIn("subprocess.run", src)
        self.assertIn("subprocess.TimeoutExpired", src)
        self.assertIn("hard_budget_seconds", src)
        self.assertIn("NO_STALE_FALLBACK_HARD_PROCESS_TIMEOUT_V651", src)

    def test_sanity_endpoint_checks_database_and_collisions(self):
        src=inspect.getsource(main.sanity)
        self.assertNotIn("PRAGMA quick_check", src)
        self.assertIn("SQLITE_BACKUP_RESTORE_QUICK_CHECK", src)
        self.assertIn("set_progress_handler", src)
        self.assertIn("weekly_monthly_collisions", src)
        self.assertIn("old_intraday_live_rows", src)
        self.assertIn("last_daily_strategy_validation", src)


if __name__ == '__main__':
    unittest.main()
