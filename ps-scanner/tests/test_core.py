import unittest
from psscanner_quant.broker import order_plan
from psscanner_quant.strategy_library import build_library

class CoreTests(unittest.TestCase):
    def test_strategy_library_size(self):
        specs=build_library()
        self.assertGreaterEqual(len(specs),500)
        self.assertEqual(len({s.strategy_id for s in specs}),len(specs))

    def test_long_order_is_cnc_under_cap(self):
        p=order_plan('LONG',123.45,0.05)
        self.assertEqual(p['product'],'CNC')
        self.assertLessEqual(p['estimated_notional'],20000)
        self.assertGreater(p['quantity'],0)

    def test_short_order_is_mis_under_cap(self):
        p=order_plan('SHORT',987.65,0.05)
        self.assertEqual(p['product'],'MIS')
        self.assertLessEqual(p['estimated_notional'],20000)
        self.assertGreater(p['quantity'],0)

    def test_too_expensive_share_disables_order(self):
        p=order_plan('LONG',25000,0.05)
        self.assertEqual(p['quantity'],0)

if __name__=='__main__': unittest.main()
