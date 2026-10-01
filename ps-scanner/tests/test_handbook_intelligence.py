import unittest
import numpy as np
import pandas as pd

from psscanner_quant.broker import order_plan
from psscanner_quant.candle_patterns import detect_patterns
from psscanner_quant.handbook import status as handbook_status, family_evidence_grade
from psscanner_quant.strategy_library import build_library
from psscanner_quant.trade_intelligence import evaluate


class HandbookIntelligenceTests(unittest.TestCase):
    def test_handbook_catalog_counts(self):
        s=handbook_status()
        self.assertEqual(s['strategy_families'],100)
        self.assertEqual(s['candlestick_patterns'],50)
        self.assertEqual(s['intelligence_filters'],50)
        self.assertGreaterEqual(s['mapped_to_local_templates'],40)

    def test_local_library_expands_beyond_original_500(self):
        specs=build_library()
        self.assertGreaterEqual(len(specs),800)
        self.assertGreaterEqual(len({x.family for x in specs}),23)
        self.assertEqual(family_evidence_grade('MOMENTUM'),'A')

    def test_bullish_engulfing_is_numeric_context_not_instruction(self):
        idx=pd.date_range('2026-01-01',periods=35,freq='D')
        close=np.linspace(100,96,35); open_=close+.1
        high=np.maximum(open_,close)+.5; low=np.minimum(open_,close)-.5
        volume=np.full(35,100000.0)
        open_[-2]=97; close[-2]=96; high[-2]=97.2; low[-2]=95.8
        open_[-1]=95.7; close[-1]=97.3; high[-1]=97.5; low[-1]=95.5; volume[-1]=250000
        df=pd.DataFrame({'open':open_,'high':high,'low':low,'close':close,'volume':volume},index=idx)
        out=detect_patterns(df)
        engulf=[x for x in out['hits'] if x['rank']==1]
        self.assertTrue(engulf)
        self.assertEqual(engulf[0]['direction'],'LONG')
        self.assertIn('context',engulf[0])
        self.assertIn('never standalone',out['principle'])

    def test_low_reward_risk_is_hard_failure(self):
        f={
            'close':100,'atr_pct':2,'gap_pct':0,'relative_strength20':2,'ret20':5,'ret60':8,
            'trend':1,'volume_ratio':1.5,'turnover20':2_000_000,'range20_pos':.7,
            'ema12':102,'ema26':100,'adx14':25,'higher_tf_trend':1,
        }
        out=evaluate(
            book='WEEKLY',symbol='TEST',side='LONG',features=f,fundamentals={},
            regime_state={'regime':'TREND_UP','trend_vote':.5,'breadth_up_pct':65,'breadth_down_pct':35},
            target_pct=2,stop_pct=2,strategy_ids=['A','B'],data_confidence=.9,
        )
        self.assertEqual(out['decision'],'NO_TRADE')
        self.assertTrue(any('Reward/risk' in x or 'room to' in x.lower() for x in out['hard_blockers']))

    def test_risk_first_sizing_can_use_less_than_20k(self):
        p=order_plan('LONG',100,0.05,stop_price=90)
        self.assertLess(p['estimated_notional'],20000)
        self.assertLessEqual(p['estimated_risk_to_stop'],500)
        self.assertGreater(p['quantity'],0)


if __name__=='__main__':
    unittest.main()
