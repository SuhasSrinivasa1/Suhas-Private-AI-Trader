import unittest
from unittest.mock import patch
from datetime import date, datetime

import pandas as pd

from psscanner_quant.constants import IST
from psscanner_quant.trading_calendar import is_regular_trading_day, period_end_date, remaining_sessions, add_trading_sessions
from psscanner_quant.trade_intelligence import evaluate
from psscanner_quant.strategy_lab import _shadow_due, _shadow_exit_price
from psscanner_quant.event_calendar import _RBI_MPC_DECISION_DATES


class V620EvidenceTests(unittest.TestCase):
    def test_official_nse_2026_holiday_is_not_session(self):
        self.assertFalse(is_regular_trading_day(date(2026,10,2)))
        self.assertTrue(is_regular_trading_day(date(2026,10,1)))

    def test_weekly_period_end_moves_before_friday_holiday(self):
        now=datetime(2026,9,28,12,0,tzinfo=IST)
        self.assertEqual(period_end_date('WEEKLY',now),date(2026,10,1))

    def test_remaining_sessions_uses_exchange_holidays(self):
        now=datetime(2026,9,30,15,31,tzinfo=IST)
        self.assertEqual(remaining_sessions('WEEKLY',now),1.0)

    def test_shadow_weekly_due_uses_trading_sessions(self):
        opened=datetime(2026,9,28,12,0,tzinfo=IST)
        due=_shadow_due('WEEKLY',opened)
        # Oct 2 is an NSE holiday, so five trading sessions end on Oct 6.
        self.assertEqual(due.date(),date(2026,10,6))


    def test_rbi_mpc_schedule_has_remaining_2026_decisions(self):
        self.assertIn("2026-10-07", _RBI_MPC_DECISION_DATES)
        self.assertIn("2026-12-04", _RBI_MPC_DECISION_DATES)

    def test_sector_context_can_supply_filters(self):
        f={'close':100,'atr_pct':2,'gap_pct':0,'relative_strength20':2,'ret20':5,'ret60':8,'trend':1,'volume_ratio':1.5,'turnover20':2_000_000,'range20_pos':.7,'ema12':102,'ema26':100,'adx14':25,'higher_tf_trend':1}
        sec={'status':'PASS','industry':'IT','trend_up_pct':70,'trend_down_pct':10,'positive_pct':65,'stock_vs_industry_ret20_pct':3,'supportive':True,'sample':10}
        out=evaluate(book='WEEKLY',symbol='TEST',side='LONG',features=f,fundamentals={},regime_state={'regime':'TREND_UP','trend_vote':.5,'breadth_up_pct':65,'breadth_down_pct':35},sector_ctx=sec,event_ctx={},target_pct=10,stop_pct=3,strategy_ids=['A','B'],data_confidence=.9)
        by_rank={x['rank']:x for x in out['filters']}
        self.assertNotEqual(by_rank[11]['status'],'UNKNOWN')
        self.assertNotEqual(by_rank[12]['status'],'UNKNOWN')
        self.assertNotEqual(by_rank[14]['status'],'UNKNOWN')


    @patch("psscanner_quant.strategy_lab.history")
    def test_overdue_shadow_uses_due_timestamp_not_current_quote(self, hist):
        idx=pd.DatetimeIndex([datetime(2026,9,24,10,0,tzinfo=IST),datetime(2026,9,24,11,0,tzinfo=IST)])
        hist.return_value=pd.DataFrame({"close":[100.0,130.0]},index=idx)
        row={"symbol":"TEST","horizon":"INTRADAY","due_at":datetime(2026,9,24,10,30,tzinfo=IST).isoformat()}
        px=_shadow_exit_price(row,datetime(2026,9,24,12,0,tzinfo=IST),{"TEST":150.0})
        self.assertEqual(px,100.0)

    def test_intraday_high_impact_event_is_hard_gate(self):
        f={'close':100,'atr_pct':2,'gap_pct':0,'relative_strength20':2,'ret20':5,'ret60':8,'trend':1,'volume_ratio':1.5,'turnover20':2_000_000,'range20_pos':.7,'ema12':102,'ema26':100,'adx14':25,'higher_tf_trend':1}
        ev={'events':[{'title':'earnings'}],'high_impact_events':[{'title':'earnings'}]}
        out=evaluate(book='INTRADAY',symbol='TEST',side='LONG',features=f,fundamentals={},regime_state={'regime':'TREND_UP','trend_vote':.5,'breadth_up_pct':65,'breadth_down_pct':35},event_ctx=ev,target_pct=3,stop_pct=1,strategy_ids=['A','B'],data_confidence=.9)
        self.assertEqual(out['decision'],'NO_TRADE')
        self.assertTrue(any('Corporate-action' in x or 'event' in x.lower() for x in out['hard_blockers']))


if __name__=='__main__':unittest.main()
