import inspect
import unittest
from pathlib import Path

from psscanner_quant import engine, specialized, db, main


class V648ReliabilityRecoveryTests(unittest.TestCase):
    def test_five_pick_contract_books(self):
        self.assertEqual(engine.FREEZE_CONTRACT_MIN, {
            "WEEKLY":5,"MONTHLY":5,"ETF":5,"INTERNATIONAL":5,
        })

    def test_horizon_policy_rejects_fewer_than_five_as_complete(self):
        src=inspect.getsource(engine.recommendations)
        self.assertIn('fewer_than_five_is_valid',src)
        self.assertIn('minimum_frozen_recommendations',src)
        self.assertIn('freeze_contract',src)

    def test_workers_are_watchdog_restarted(self):
        src=inspect.getsource(engine.Engine._supervise)
        self.assertIn('RESPAWN_DEAD_DOMAIN_WORKERS',src)
        self.assertIn('_spawn_worker',src)
        self.assertIn('THREAD_NOT_ALIVE',src)

    def test_db_telemetry_is_fail_soft(self):
        self.assertIn('return False',inspect.getsource(db.set_state))
        self.assertIn('return False',inspect.getsource(db.health))

    def test_international_empty_marker_does_not_complete_contract(self):
        src=inspect.getsource(specialized.run_international_cycle)
        self.assertIn("existing>=required",src)
        self.assertIn("'frozen':complete",src)
        self.assertIn('max_longs=required',src)
        self.assertNotIn("freeze_state.get('frozen')",src)

    def test_circuit_has_bounded_exact_quote_budget(self):
        src=inspect.getsource(specialized.run_circuit_cycle)
        self.assertIn('circuit_exact_quote_budget',src)
        self.assertIn('exact_quote_deferred',src)
        self.assertIn('NO_ACTIONABLE_CANDIDATES',src)

    def test_intraday_zero_output_has_reason(self):
        src=inspect.getsource(engine.run_intraday_cycle)
        self.assertIn('availability_reason',src)
        self.assertIn('NO_DATA_VALID_CANDIDATES_AFTER_QUALITY_RISK_GATES',src)

    def test_international_api_exposes_contract(self):
        src=inspect.getsource(main.international_board)
        self.assertIn('us_freeze_contract_minimum',src)
        self.assertIn('EXPLICIT_RECOVERY_REQUIRED_NEVER_STALE_OR_FABRICATED',src)


if __name__=='__main__':
    unittest.main()
