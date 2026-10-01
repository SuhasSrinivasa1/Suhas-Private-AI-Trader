import inspect
import unittest
from datetime import datetime
from pathlib import Path

from psscanner_quant.constants import VERSION, IST
from psscanner_quant import engine, specialized, main, global_context, cross_market, orders


class V630DeadlineGlobalTests(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split("."))), (6, 4, 3))

    def test_circuit_nextday_period_rolls_at_1500(self):
        before=datetime(2026,9,25,14,59,tzinfo=IST)
        after=datetime(2026,9,25,15,1,tzinfo=IST)
        self.assertEqual(engine.period_key('CIRCUIT_NEXTDAY',before),'2026-09-25')
        self.assertEqual(engine.period_key('CIRCUIT_NEXTDAY',after),'2026-09-28')

    def test_global_india_period_rolls_after_user_cutoff(self):
        before=datetime(2026,9,25,14,59,tzinfo=IST)
        after=datetime(2026,9,25,15,1,tzinfo=IST)
        self.assertEqual(engine.period_key('GLOBAL_INDIA_LONG',before),'2026-09-25')
        self.assertEqual(engine.period_key('GLOBAL_INDIA_SHORT',after),'2026-09-28')

    def test_short_deadline_gate_rejects_too_late(self):
        f={'atr_pct':0.5,'ret5':-1.0,'ret20':-1.5}
        early=engine._intraday_short_deadline_feasibility(f,0.6,datetime(2026,9,25,14,20,tzinfo=IST))
        late=engine._intraday_short_deadline_feasibility(f,0.6,datetime(2026,9,25,14,50,tzinfo=IST))
        self.assertTrue(early['feasible'])
        self.assertFalse(late['feasible'])
        self.assertEqual(late['deadline'],'15:00 IST')

    def test_international_is_long_only_and_weekly_frozen(self):
        src=inspect.getsource(specialized.run_international_cycle)
        self.assertIn("side='LONG'",src)
        self.assertNotIn("for side in ('LONG','SHORT')",src)
        self.assertIn("AFTER_FRIDAY_CLOSE_TO_MONDAY_OPEN",src)
        self.assertIn("CONTRACT_FULFILLED",src)
        self.assertIn("expected_net_weekly_edge_pct",src)

    def test_circuit_same_day_has_1500_deadline_gate(self):
        src=inspect.getsource(specialized.run_circuit_cycle)
        self.assertIn('CIRCUIT_LIVE_CUTOFF',src)
        self.assertIn('deadline_reject',src)
        self.assertIn('SAME_SESSION_TARGET_BY_15_00_IST',src)

    def test_nextday_circuit_freeze_worker_and_routes_exist(self):
        src=inspect.getsource(engine.Engine._supervise)
        self.assertIn('"circuit_nextday"',src)
        paths={getattr(r,'path',None) for r in main.app.routes}
        self.assertIn('/api/circuit/board',paths)
        self.assertIn('/api/international/board',paths)
        self.assertIn('/api/global/markets',paths)

    def test_global_context_covers_major_regions_and_company_clusters(self):
        for key in ('SP500','NASDAQ','STOXX50','FTSE100','DAX','NIKKEI225','HANGSENG','SHANGHAI','KOSPI','ASX200','USDINR','CRUDE','US_TECH','US_BANKS','MSFT','JPM','XOM','LLY','TSLA','BHP'):
            self.assertIn(key,global_context.PROXIES)

    def test_cross_market_mapping_uses_sector_and_cross_asset_drivers(self):
        tech=cross_market._drivers('Information Technology - Software')
        bank=cross_market._drivers('Banks')
        energy=cross_market._drivers('Oil Gas & Consumable Fuels')
        self.assertIn('MSFT',tech)
        self.assertIn('JPM',bank)
        self.assertIn('CRUDE',energy)

    def test_order_short_cutoff_is_1500(self):
        src=inspect.getsource(orders.execution_readiness)
        self.assertIn('SHORT_HARD_EXIT',src)
        self.assertIn('short_entry_cutoff_1500',src)

    def test_ui_contains_new_three_lane_boards(self):
        html=(Path(__file__).resolve().parents[1]/'static'/'index.html').read_text()
        self.assertIn('3:00 PM · NEXT SESSION UPPER-CIRCUIT WATCHLIST',html)
        self.assertIn('GLOBAL → INDIA OVERNIGHT MAP',html)
        self.assertIn('U.S. WEEKLY LONG · STOCKS + ETFs',html)
        self.assertIn('WEEKLY FROZEN',html)
        self.assertIn('15:00 IST',html)


if __name__=='__main__':
    unittest.main()
