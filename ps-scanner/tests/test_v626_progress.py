import inspect
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from psscanner_quant import data, engine, specialized


class V626ProgressTests(unittest.TestCase):
    def test_liquidity_rank_uses_fast_raw_json_and_cache(self):
        src=inspect.getsource(data.liquidity_rank)
        self.assertIn("_raw_turnover20", src)
        self.assertIn("_LIQUIDITY_RANK_CACHE", src)
        self.assertNotIn("_parse_candles", src)

    def test_raw_turnover_reads_last_twenty(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"x.json"
            candles=[]
            for i in range(25):
                candles.append([1700000000+i,1,1,1,100+i,10])
            p.write_text(json.dumps({"candles":candles}))
            got=data._raw_turnover20(p)
            expected=sum((100+i)*10 for i in range(5,25))/20
            self.assertAlmostEqual(got, expected)

    def test_weekly_and_monthly_are_separate_workers(self):
        src=inspect.getsource(engine.Engine._supervise)
        self.assertIn('("weekly"',src)
        self.assertIn('("monthly"',src)
        self.assertNotIn('("horizon"',src)

    def test_single_horizon_cycle_function_exists(self):
        self.assertTrue(callable(engine.run_single_horizon_cycle))

    def test_scan_progress_has_processed_counter(self):
        src=inspect.getsource(engine.scan_equities)
        self.assertIn('"processed":0',src)
        self.assertIn('progress_step',src)
        self.assertIn('stats["processed"]%progress_step==0',src)

    def test_circuit_uses_full_dynamic_universe(self):
        src=inspect.getsource(specialized.run_circuit_cycle)
        self.assertIn("pool=full_nse_symbols()",src)
        self.assertIn("FULL_NSE_COARSE_SCREEN_NO_LIQUIDITY_CAP",src)
        self.assertIn("NO_SCANNABLE_UNIVERSE",src)


if __name__=='__main__':
    unittest.main()
