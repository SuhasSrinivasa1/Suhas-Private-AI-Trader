import inspect
import unittest
from datetime import datetime

from psscanner_quant import engine, specialized, data, main
from psscanner_quant.constants import IST


class V649RecoveryExecutionTests(unittest.TestCase):
    def test_monthly_switches_to_next_period_after_final_close(self):
        before=engine._horizon_target_context('MONTHLY', datetime(2026,9,30,14,0,tzinfo=IST))
        self.assertEqual(before['period_key'],'2026-09')
        self.assertFalse(before['preperiod'])
        after=engine._horizon_target_context('MONTHLY', datetime(2026,9,30,15,40,tzinfo=IST))
        self.assertEqual(after['period_key'],'2026-10')
        self.assertTrue(after['preperiod'])
        self.assertEqual(after['first_period_session'],'2026-10-01')

    def test_weekly_switches_to_next_week_after_prior_period_close(self):
        # Oct 2, 2026 is an NSE holiday; Oct 1 is therefore the packaged weekly period end.
        ctx=engine._horizon_target_context('WEEKLY', datetime(2026,10,1,15,40,tzinfo=IST))
        self.assertTrue(ctx['preperiod'])
        self.assertEqual(ctx['period_key'],'2026-10-05')
        self.assertEqual(ctx['first_period_session'],'2026-10-05')

    def test_recovery_is_staged_but_not_gate_relaxed(self):
        src=inspect.getsource(engine.run_single_horizon_cycle)
        self.assertIn('STAGED_CONTRACT_RECOVERY_LONG_ONLY_NO_GATE_RELAXATION',src)
        self.assertIn('_recovery_symbol_batch',src)
        self.assertIn('sides_override=("LONG",)',src)
        scan=inspect.getsource(engine.scan_equities)
        self.assertIn('TARGET_CAPACITY_PREFILTER',scan)
        self.assertIn("ti['decision']!='ELIGIBLE'",scan)
        self.assertIn("not tf['target_qualified']",scan)

    def test_preperiod_rows_are_not_closed_as_rollover(self):
        src=inspect.getsource(engine._close_expired_period_books)
        self.assertIn('str(r["period_key"]) < str(current[book])',src)
        self.assertIn('str(r["period_key"]) == str(current[book])',src)

    def test_intraday_zero_live_uses_priority_bootstrap_and_ignores_quarantine_identity(self):
        src=inspect.getsource(engine.run_intraday_cycle)
        self.assertIn('PRIORITY_BOOTSTRAP_ZERO_LIVE_NO_GATE_RELAXATION',src)
        self.assertIn("state IN ('LIVE','CLOSED')",src)
        self.assertIn('STALE_DATA/VOID quarantine rows',src)

    def test_etf_is_cached_first(self):
        src=inspect.getsource(specialized.run_etf_cycle)
        self.assertIn('RECOVERY_SCANNING_CACHED_ETFS',src)
        self.assertIn("scan_etfs(sides=('LONG',),target_now=target_now)",src)
        # Network warmup must no longer precede cached scanning in the freeze worker.
        self.assertNotIn('\n    warm_etf_history()',src)

    def test_international_transport_is_bounded_and_partial_success(self):
        src=inspect.getsource(data.international_batch_history)
        self.assertIn('chunk_size',src)
        self.assertIn('timeout_seconds',src)
        self.assertIn('BOUNDED_CHUNK_PARTIAL_SUCCESS_NO_STALE_FALLBACK',src)
        cyc=inspect.getsource(specialized.run_international_cycle)
        self.assertIn('FETCHING_BOUNDED_DAILY_RECOVERY_DATA',cyc)
        self.assertIn('NO_FRESH_DAILY_DATA',cyc)

    def test_api_reports_v649_patch(self):
        src=inspect.getsource(main.health)
        self.assertIn('6.4.9',src)
        self.assertIn('RECOVERY_EXECUTION_AND_PREPERIOD_FREEZE',src)


if __name__=='__main__':
    unittest.main()
