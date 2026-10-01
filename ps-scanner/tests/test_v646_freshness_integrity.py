import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from psscanner_quant import freshness_guard, groww_guard

IST=ZoneInfo('Asia/Kolkata')
class V646FreshnessIntegrityTests(unittest.TestCase):
    def test_previous_session_is_not_fresh(self):
        now=datetime(2026,9,29,12,0,tzinfo=IST)
        x=freshness_guard.assess_feature_freshness({'asof':'2026-09-28 15:25:00+05:30'},now)
        self.assertFalse(x['fresh']); self.assertEqual(x['reason'],'FEATURE_FROM_DIFFERENT_SESSION')
    def test_recent_same_session_is_fresh(self):
        now=datetime(2026,9,29,12,0,tzinfo=IST)
        x=freshness_guard.assess_feature_freshness({'asof':'2026-09-29 11:55:00+05:30'},now)
        self.assertTrue(x['fresh'])
    def test_old_same_session_is_held(self):
        now=datetime(2026,9,29,13,0,tzinfo=IST)
        old=now-timedelta(seconds=freshness_guard.MAX_FEATURE_AGE_SECONDS+1)
        x=freshness_guard.assess_feature_freshness({'asof':old.isoformat()},now)
        self.assertFalse(x['fresh']); self.assertEqual(x['reason'],'FEATURE_TOO_OLD_FOR_NEW_INTRADAY_CALL')
    def test_missing_asof_is_held(self):
        self.assertFalse(freshness_guard.assess_feature_freshness({})['fresh'])
    def test_normal_groww_categories_still_wait_not_drop(self):
        self.assertEqual(groww_guard._groww_category('https://api.groww.in/v1/live-data/ltp'),'LIVE_DATA')
        self.assertIsNone(groww_guard._groww_category('https://api.groww.in/v1/historical/candles'))
        self.assertEqual(groww_guard.OFFICIAL_LIMITS['LIVE_DATA']['per_minute'],300)
    def test_transport_telemetry_contract(self):
        p=groww_guard._SlidingWindowPacer().status()['LIVE_DATA']
        for key in ('completed_responses','successful_responses','failed_responses','last_success_at','last_status_code'):
            self.assertIn(key,p)

if __name__=='__main__': unittest.main()
