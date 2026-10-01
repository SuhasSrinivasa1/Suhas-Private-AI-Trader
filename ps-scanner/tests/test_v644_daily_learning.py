import inspect
import unittest
from psscanner_quant import strategy_lab

class V644DailyLearningContractTests(unittest.TestCase):
    def test_daily_trading_day_validation_is_present(self):
        src=inspect.getsource(strategy_lab.maybe_weekly_jobs)
        self.assertIn('strategy_validation_day',src)
        self.assertIn('is_regular_trading_day(now.date())',src)
        self.assertIn('now.hour>=18',src)
        self.assertIn('last_daily_strategy_validation',src)

    def test_sunday_post_discovery_validation_has_independent_marker(self):
        src=inspect.getsource(strategy_lab.maybe_weekly_jobs)
        self.assertIn('now.weekday()==6',src)
        self.assertIn('strategy_validation_week',src)
        self.assertEqual(src.count('set_state("strategy_validation_week",week)'),1)

    def test_daily_pass_does_not_consume_weekly_marker(self):
        src=inspect.getsource(strategy_lab.maybe_weekly_jobs)
        daily=src.split('if is_regular_trading_day(now.date())',1)[1].split('# Independent marker:',1)[0]
        self.assertNotIn('strategy_validation_week',daily)

    def test_promotion_contract_is_not_bypassed(self):
        src=inspect.getsource(strategy_lab.validate_strategies)
        self.assertIn('shadow_ok',src)
        self.assertIn("m['hold']",src)
        self.assertIn("m['walk']",src)
        self.assertIn('multiple_testing_penalty',src)

if __name__ == '__main__':
    unittest.main()
