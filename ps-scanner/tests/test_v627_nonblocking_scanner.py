import inspect
import unittest

from psscanner_quant.constants import VERSION
from psscanner_quant import engine as engine_mod
from psscanner_quant import specialized


class V627NonblockingScannerTests(unittest.TestCase):
    def test_version_bumped(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split("."))), (6, 4, 3))

    def test_scanner_uses_cached_context_not_sync_refresh(self):
        src=inspect.getsource(engine_mod.scan_equities)
        self.assertIn("allow_network=False", src)
        self.assertIn("get_state(\"last_regime\"", src)
        self.assertIn("get_state(\"global_context\"", src)
        self.assertIn("sector_context_cached", src)
        self.assertNotIn("global_snapshot(force=False)", src)
        self.assertNotIn("sector_context(sym,side)", src)
        self.assertNotIn("news_context(c['symbol'],allow_refresh=True)", src)

    def test_strategy_specs_are_preloaded_once_per_scan(self):
        src=inspect.getsource(engine_mod.scan_equities)
        self.assertIn("specs_by_side", src)
        self.assertIn("specs_by_side.get(side)", src)

    def test_background_context_workers_exist(self):
        src=inspect.getsource(engine_mod.Engine._supervise)
        for name in ("market_snapshot","fundamentals","sector_context","global_context"):
            self.assertIn(f'(\"{name}\"', src)

    def test_scan_progress_reports_stage_and_current_symbol(self):
        src=inspect.getsource(engine_mod.scan_equities)
        self.assertIn('"stage":"PREP"', src)
        self.assertIn('"current_symbol"', src)
        self.assertIn('progress_step', src)
        self.assertIn('stats["processed"]%progress_step==0', src)
        self.assertIn('"near_misses"', src)

    def test_circuit_reports_live_progress(self):
        src=inspect.getsource(specialized.run_circuit_cycle)
        self.assertIn("set_state('scan_status_CIRCUIT',stats)", src)
        self.assertIn("stats['processed']=idx", src)
        self.assertIn("sector_context_cached", src)

    def test_ui_distinguishes_scanning_from_no_candidate(self):
        from pathlib import Path
        html=(Path(__file__).resolve().parents[1]/"static"/"index.html").read_text()
        self.assertIn("SCANNING NOW", html)
        self.assertIn("Candidates are not declared absent until this scan completes", html)
