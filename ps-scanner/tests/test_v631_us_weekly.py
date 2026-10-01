import inspect
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from psscanner_quant.constants import VERSION, IST
from psscanner_quant import engine, specialized, main, data


class V631USWeeklyTests(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split("."))), (6, 4, 3))

    def test_international_period_is_new_york_week_monday(self):
        # 00:30 IST Friday is Thursday in New York; both belong to Monday Sep 21 week.
        dt=datetime(2026,9,25,0,30,tzinfo=IST)
        self.assertEqual(engine.period_key('INTERNATIONAL',dt),'2026-09-21')

    def test_weekly_universe_contains_stocks_and_etfs(self):
        self.assertIn('AAPL',data.US_WEEKLY_UNIVERSE)
        self.assertIn('SPY',data.US_WEEKLY_UNIVERSE)
        self.assertIn('QQQ',data.US_WEEKLY_UNIVERSE)
        self.assertIn('XLK',data.US_WEEKLY_UNIVERSE)

    def test_weekly_geometry_has_cost_reserve_and_rr(self):
        g=specialized._international_weekly_geometry({'atr_pct':2.0,'ret5':2.0,'ret20':5.0},5,.5,8.0)
        self.assertGreaterEqual(g['target_pct']/g['stop_pct'],1.6-1e-9)
        self.assertAlmostEqual(g['expected_net_target_pct'],g['target_pct']-.5,places=3)

    def test_international_is_immutable_weekly_book(self):
        with patch('psscanner_quant.engine.db') as fake_db:
            con=fake_db.return_value.__enter__.return_value
            con.execute.return_value.fetchall.return_value=[]
            out=engine.recommendations('INTERNATIONAL')
        p=out['policy']
        self.assertTrue(p['immutable_period_book'])
        self.assertTrue(p['no_rank_replacement'])
        self.assertTrue(p['no_backfill_after_close'])
        self.assertEqual(p['international_session_policy'],'US_WEEKLY_FROZEN_LONG_ONLY')
        self.assertEqual(p['target_policy'],'FROZEN_US_WEEKLY_EXPECTED_NET_EDGE')

    def test_cycle_has_no_daily_replacement_semantics(self):
        src=inspect.getsource(specialized.run_international_cycle)
        self.assertIn('international_weekly_freeze_',src)
        self.assertIn('WEEKLY_BOOK_FROZEN',src)
        self.assertIn('FREEZE_CONTRACT_SHORTAGE_RECOVERY_REQUIRED',src)
        self.assertIn('PREWEEK_OR_RECOVERY_RECENT_DAILY_CLOSE',src)
        self.assertIn('ONE_FROZEN_ENTRY_PER_SYMBOL_PER_WEEK_NO_REPLACEMENT',src)
        self.assertNotIn("for side in ('LONG','SHORT')",src)

    def test_updater_closes_at_week_end_not_daily_close(self):
        src=inspect.getsource(specialized.update_international_books)
        self.assertIn('US_WEEK_END',src)
        self.assertNotIn("reason='US_SESSION_END'",src)

    def test_international_board_policy_is_weekly(self):
        paths={getattr(r,'path',None) for r in main.app.routes}
        self.assertIn('/api/international/board',paths)
        src=inspect.getsource(main.international_board)
        self.assertIn('us_horizon',src)
        self.assertIn('us_no_replacement_after_contract_complete',src)
        self.assertIn('us_freeze_contract_minimum',src)

    def test_ui_removes_foreign_short_column_and_keeps_global_india(self):
        html=(Path(__file__).resolve().parents[1]/'static'/'index.html').read_text()
        self.assertIn('U.S. WEEKLY LONG · STOCKS + ETFs',html)
        self.assertIn('GLOBAL → INDIA OVERNIGHT MAP',html)
        self.assertIn("shortPanel.classList.add('hidden')",html)
        self.assertIn('Ranking maximizes expected net weekly edge',html)


if __name__=='__main__':
    unittest.main()
