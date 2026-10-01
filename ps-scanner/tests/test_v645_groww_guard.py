import inspect
import unittest
from psscanner_quant import groww_guard

class V645GrowwBudgetGuardTests(unittest.TestCase):
    def test_http_layer_installed(self):
        self.assertTrue(groww_guard.status()['installed'])
        self.assertEqual(groww_guard.status()['http_guard'],'requests.Session.request')
    def test_limits(self):
        x=groww_guard.OFFICIAL_LIMITS
        self.assertEqual(x['AUTHENTICATION']['per_24h'],150)
        self.assertEqual(x['LIVE_DATA']['per_minute'],300)
        self.assertEqual(x['ORDERS']['per_minute'],250)
        self.assertEqual(x['NON_TRADING']['per_minute'],500)
    def test_market_normal_calls_wait_not_drop(self):
        src=inspect.getsource(groww_guard._SlidingWindowPacer.before)
        self.assertIn('time.sleep',src)
        self.assertNotIn('raise ',src)
    def test_history_left_to_existing_controller(self):
        self.assertIsNone(groww_guard._groww_category('https://api.groww.in/v1/historical/candles'))
    def test_auth_classification(self):
        self.assertEqual(groww_guard._classify_error_text(429,'Too Many Requests'),'PROVIDER_RATE_LIMIT')
        self.assertEqual(groww_guard._classify_error_text(403,'GA005 subscription required'),'AUTH_OR_ENTITLEMENT')
    def test_off_hours_preserves_more_auth_budget(self):
        self.assertLess(groww_guard.OFF_HOURS_AUTH_24H_GUARD,groww_guard.MARKET_AUTH_24H_GUARD)
        self.assertLess(groww_guard.MARKET_AUTH_24H_GUARD,150)
    def test_token_not_persisted(self):
        self.assertFalse(groww_guard.status()['auth']['token_persisted_to_disk'])

if __name__=='__main__': unittest.main()
