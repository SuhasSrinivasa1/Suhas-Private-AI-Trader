import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from psscanner_quant import data
from psscanner_quant.constants import VERSION


class V635HistoryParserTests(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split("."))), (6, 4, 3))

    def test_parser_accepts_iso_epoch_seconds_numeric_string_and_milliseconds(self):
        base=int(pd.Timestamp("2026-01-01", tz="Asia/Kolkata").timestamp())
        candles=[
            ["2026-01-01T09:15:00",100,101,99,100.5,1000],
            [base+86400,101,102,100,101.5,1100],
            [str(base+2*86400),102,103,101,102.5,"1,200"],
            [(base+3*86400)*1000,103,104,102,103.5,1300],
        ]
        df=data._parse_candles(candles)
        self.assertEqual(len(df),4)
        self.assertEqual(float(df.iloc[-2]["volume"]),1200.0)

    def test_parser_accepts_legacy_dict_rows(self):
        candles=[
            {"timestamp":"2026-01-01 09:15:00","open":"100","high":"101","low":"99","close":"100.5","volume":"10,000"},
            {"time":"2026-01-02 09:15:00","o":101,"h":102,"l":100,"c":101.5,"v":None},
        ]
        df=data._parse_candles(candles)
        self.assertEqual(len(df),2)
        self.assertEqual(float(df.iloc[0]["volume"]),10000.0)
        self.assertEqual(float(df.iloc[1]["volume"]),0.0)

    def test_237_mixed_daily_rows_do_not_collapse_to_fourteen(self):
        base=int(pd.Timestamp("2025-10-01", tz="Asia/Kolkata").timestamp())
        candles=[]
        for i in range(237):
            ts=base+i*86400
            if i%4==0: stamp=ts
            elif i%4==1: stamp=str(ts)
            elif i%4==2: stamp=ts*1000
            else: stamp=pd.Timestamp(ts,unit="s",tz="UTC").tz_convert("Asia/Kolkata").strftime("%Y-%m-%dT%H:%M:%S")
            vol=f"{100000+i:,}" if i%5==0 else 100000+i
            candles.append([stamp,100+i/10,101+i/10,99+i/10,100.5+i/10,vol,None])
        df=data._parse_candles(candles)
        self.assertEqual(len(df),237)

    def test_cached_coverage_reports_ready_from_existing_raw_cache(self):
        with tempfile.TemporaryDirectory() as td:
            old=data._CACHE
            try:
                data._CACHE=Path(td)
                base=int(pd.Timestamp("2025-10-01",tz="Asia/Kolkata").timestamp())
                candles=[[str(base+i*86400),100,101,99,100.5,"1,000"] for i in range(80)]
                data._history_path("ABC","1day").write_text(json.dumps({"candles":candles}))
                cov=data.cached_history_coverage(["ABC"],"1day",30)
                self.assertEqual(cov["raw_rows"],80)
                self.assertEqual(cov["parsed_rows"],80)
                self.assertEqual(cov["ready"],1)
                self.assertEqual(cov["parse_loss"],0)
            finally:
                data._CACHE=old

    def test_bad_volume_does_not_discard_valid_ohlc(self):
        candles=[["2026-01-01T09:15:00",100,101,99,100.5,"not-a-volume"]]
        df=data._parse_candles(candles)
        self.assertEqual(len(df),1)
        self.assertEqual(float(df.iloc[0]["volume"]),0.0)


if __name__ == "__main__":
    unittest.main()
