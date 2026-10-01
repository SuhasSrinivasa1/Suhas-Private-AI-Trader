import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from psscanner_quant import data
from psscanner_quant.candle_patterns import detect_patterns
from psscanner_quant.constants import VERSION
from psscanner_quant.features import enrich, latest_features
from psscanner_quant.trade_intelligence import evaluate


class V636MissingOpenHistoryTests(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split("."))), (6, 4, 3))

    def _live_shape(self, n=237):
        base = pd.Timestamp("2025-10-10", tz="Asia/Kolkata")
        rows=[]
        for i in range(n):
            ts=(base+pd.Timedelta(days=i)).strftime("%Y-%m-%dT00:00:00")
            close=100.0+i*0.2
            open_px=close-0.1 if i<14 else None
            rows.append([ts,open_px,close+1.0,close-1.0,close,100000+i,None])
        return rows

    def test_live_237_shape_keeps_hlcv_rows_when_open_missing(self):
        df=data._parse_candles(self._live_shape())
        self.assertEqual(len(df),237)
        self.assertTrue(pd.isna(df.iloc[-1]["open"]))
        self.assertAlmostEqual(float(df.iloc[-1]["close"]),147.2)

    def test_coverage_becomes_ready_without_fabricating_open(self):
        with tempfile.TemporaryDirectory() as td:
            old=data._CACHE
            try:
                data._CACHE=Path(td)
                data._history_path("ABC","1day").write_text(json.dumps({"candles":self._live_shape()}))
                cov=data.cached_history_coverage(["ABC"],"1day",30)
                self.assertEqual(cov["raw_rows"],237)
                self.assertEqual(cov["parsed_rows"],237)
                self.assertEqual(cov["ready"],1)
                self.assertEqual(cov["parse_loss"],0)
            finally:
                data._CACHE=old

    def test_hlc_features_remain_available_while_open_features_are_marked_missing(self):
        df=data._parse_candles(self._live_shape())
        x=enrich(df)
        self.assertEqual(len(x),237)
        f=latest_features(df)
        self.assertFalse(f["open_observed"])
        self.assertGreater(f["ret20"],0)
        self.assertGreater(f["atr14"],0)
        self.assertEqual(f["gap_pct"],0.0)  # neutral numeric placeholder; flag carries provenance
        self.assertLess(f["open_coverage_pct"],10.0)

    def test_candle_patterns_abstain_when_current_open_is_missing(self):
        df=data._parse_candles(self._live_shape())
        out=detect_patterns(df)
        self.assertEqual(out["status"],"UNAVAILABLE_DAILY_OPEN_MISSING")
        self.assertEqual(out["hit_count"],0)

    def test_trade_intelligence_marks_gap_filters_unknown(self):
        df=data._parse_candles(self._live_shape())
        f=latest_features(df)
        ti=evaluate(
            book="WEEKLY",symbol="ABC",side="LONG",features=f,fundamentals={},
            regime_state={"regime":"WARMING","trend_vote":0,"breadth_up_pct":50,"breadth_down_pct":50},
            target_pct=10,stop_pct=5,strategy_ids=["A","B"],data_confidence=.9,
        )
        by_rank={x["rank"]:x for x in ti["filters"]}
        self.assertEqual(by_rank[5]["status"],"UNKNOWN")
        self.assertEqual(by_rank[38]["status"],"UNKNOWN")

    def test_missing_high_still_invalidates_row(self):
        df=data._parse_candles([["2026-01-01T00:00:00",None,None,99,100,1000,None]])
        self.assertEqual(len(df),0)


if __name__ == "__main__":
    unittest.main()
