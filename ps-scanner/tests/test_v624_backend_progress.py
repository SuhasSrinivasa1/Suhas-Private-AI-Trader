import inspect
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from psscanner_quant.constants import IST
from psscanner_quant import engine, main, specialized


class V624BackendProgressTests(unittest.TestCase):
    def test_low_atr_intraday_geometry_clears_one_point_five_rr(self):
        g=engine._risk_geometry('INTRADAY',{'atr_pct':0.25})
        self.assertGreaterEqual(g['target_pct']/g['stop_pct'],1.5-1e-9)

    def test_high_atr_intraday_geometry_clears_one_point_five_rr(self):
        g=engine._risk_geometry('INTRADAY',{'atr_pct':3.8})
        self.assertLessEqual(g['target_pct'],4.0)
        self.assertGreaterEqual(g['target_pct']/g['stop_pct'],1.5-1e-9)

    def test_intraday_scanner_is_cached_only(self):
        src=inspect.getsource(engine.scan_equities)
        self.assertIn('allow_network=False',src)
        self.assertNotIn('allow_network=(book == "INTRADAY")',src)

    def test_scheduler_has_independent_domain_workers(self):
        src=inspect.getsource(engine.Engine._supervise)
        for name in ('intraday','weekly','monthly','circuit','international','etf','maintenance'):
            self.assertIn(f'"{name}"',src)

    def test_international_period_key_tracks_us_session_date(self):
        # 00:30 IST is still the prior calendar date in New York during September DST.
        dt=datetime(2026,9,25,0,30,tzinfo=IST)
        self.assertEqual(engine.period_key('INTERNATIONAL',dt),'2026-09-21')

    def test_international_policy_is_weekly_frozen(self):
        with patch('psscanner_quant.engine.db') as fake_db:
            con=fake_db.return_value.__enter__.return_value
            con.execute.return_value.fetchall.return_value=[]
            out=engine.recommendations('INTERNATIONAL')
        self.assertEqual(out['policy']['international_session_policy'],'US_WEEKLY_FROZEN_LONG_ONLY')
        self.assertTrue(out['policy']['international_repriced_during_session'])
        self.assertTrue(out['policy']['international_week_end_closes_calls'])

    def test_scan_and_worker_status_routes_exist(self):
        paths={getattr(r,'path',None) for r in main.app.routes}
        self.assertIn('/api/workers',paths)
        self.assertIn('/api/scan/status',paths)

    def test_specialized_cycles_are_no_longer_one_shared_try(self):
        src=inspect.getsource(engine.Engine._supervise)
        self.assertIn('self._circuit',src)
        self.assertIn('self._international',src)
        self.assertIn('self._etf',src)


if __name__=='__main__':
    unittest.main()
