import unittest
from datetime import datetime
from psscanner_quant.constants import IST
from psscanner_quant.engine import _required_session_move, _target_feasibility


class HorizonTests(unittest.TestCase):
    def test_required_weekly_long_move_is_positive(self):
        self.assertGreater(_required_session_move(10.0, "LONG", 5.0), 0)

    def test_required_monthly_short_move_is_positive(self):
        self.assertGreater(_required_session_move(50.0, "SHORT", 20.0), 0)

    def test_low_volatility_cannot_claim_50pct_monthly_capacity(self):
        f={"atr_pct":0.8,"ret5":1.0,"ret20":2.0,"ret60":4.0,"volume_ratio":1.0,"adx14":18.0}
        d=_target_feasibility("MONTHLY","LONG",f,90,0.8,0.9,70,datetime(2026,9,2,12,0,tzinfo=IST))
        self.assertFalse(d["target_qualified"])
        self.assertLess(d["estimated_directional_move_pct"],50.0)

    def test_target_gate_is_not_label_only(self):
        f={"atr_pct":1.0,"ret5":0.0,"ret20":0.0,"ret60":0.0,"volume_ratio":1.0,"adx14":15.0}
        d=_target_feasibility("WEEKLY","LONG",f,95,1.0,1.0,80,datetime(2026,9,21,12,0,tzinfo=IST))
        self.assertFalse(d["target_qualified"])
        self.assertIn("MODELLED_MOVE_CAPACITY_BELOW_TARGET",d["rejection_reasons"])

if __name__ == '__main__':
    unittest.main()
