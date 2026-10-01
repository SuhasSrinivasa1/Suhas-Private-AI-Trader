import inspect
import unittest
from datetime import datetime, date
from pathlib import Path

from psscanner_quant.constants import VERSION, IST
from psscanner_quant import engine, specialized, config, trading_calendar


class V632MorningFreezeTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(VERSION, "6.4.3")

    def test_weekly_monday_morning_freeze_is_open(self):
        dt=datetime(2026,9,28,9,21,tzinfo=IST)
        st=engine._horizon_freeze_window("WEEKLY",dt)
        self.assertTrue(st["open"])
        self.assertEqual(st["status"],"FIRST_SESSION_RECOVERY")

    def test_afternoon_recovery_window_stays_open_for_missing_contract(self):
        dt=datetime(2026,9,28,14,50,tzinfo=IST)
        self.assertTrue(engine._publication_window_open(dt,"WEEKLY"))
        self.assertEqual(engine._horizon_freeze_window("WEEKLY",dt)["status"],"FIRST_SESSION_RECOVERY")

    def test_monthly_missing_book_can_recover_morning(self):
        dt=datetime(2026,9,28,9,21,tzinfo=IST)
        st=engine._horizon_freeze_window("MONTHLY",dt)
        self.assertTrue(st["open"])
        self.assertEqual(st["status"],"MISSING_BOOK_RECOVERY")

    def test_first_trading_session_helpers(self):
        self.assertEqual(trading_calendar.first_trading_day_of_week(date(2026,9,28)),date(2026,9,28))
        self.assertEqual(trading_calendar.first_trading_day_of_month(date(2026,10,5)),date(2026,10,1))

    def test_same_morning_observation_count_not_publication_gate(self):
        self.assertEqual(config.load_settings()["weekly_min_observations"],1)
        self.assertEqual(config.load_settings()["monthly_min_observations"],1)
        self.assertIn("obs=1",inspect.getsource(engine.run_single_horizon_cycle).replace(" ",""))

    def test_weekly_can_compensate_unknown_fundamentals_with_stricter_quant_evidence(self):
        f={'atr_pct':3.0,'ret5':15.0,'ret20':30.0,'ret60':40.0,'volume_ratio':2.0,'adx14':35.0}
        out=engine._target_feasibility('WEEKLY','LONG',f,90,.8,.85,None,datetime(2026,9,28,9,21,tzinfo=IST))
        self.assertNotIn('FUNDAMENTALS_NOT_READY',out['rejection_reasons'])
        self.assertFalse(out['fundamentals_present'])

    def test_monthly_still_requires_fundamental_evidence(self):
        f={'atr_pct':8.0,'ret5':30.0,'ret20':70.0,'ret60':100.0,'volume_ratio':2.0,'adx14':40.0}
        out=engine._target_feasibility('MONTHLY','LONG',f,95,.9,.9,None,datetime(2026,9,28,9,21,tzinfo=IST))
        self.assertIn('FUNDAMENTALS_NOT_READY',out['rejection_reasons'])

    def test_circuit_exposes_watchlists(self):
        src=inspect.getsource(specialized.run_circuit_cycle)
        self.assertIn('watchlist_long',src)
        self.assertIn('deadline_feasible',src)

    def test_ui_shows_near_misses_and_hides_legacy_international_by_default(self):
        html=(Path(__file__).resolve().parents[1]/'static'/'index.html').read_text()
        self.assertIn('RESEARCH NEAR-MISSES',html)
        self.assertIn('Morning-freeze policy',html)
        self.assertIn('LIVE CIRCUIT WATCH',html)
        self.assertIn('Legacy U.S. daily/audit rows',html)


if __name__=='__main__':
    unittest.main()
