import inspect
import unittest
from pathlib import Path

from psscanner_quant.constants import VERSION
from psscanner_quant.db import get_state, set_state
import psscanner_quant.engine as engine
import psscanner_quant.orders as orders


class V638HorizonSidePolicyTests(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split("."))), (6, 4, 3))

    def test_indian_horizon_execution_is_long_only(self):
        self.assertEqual(engine.HORIZON_EXECUTABLE_SIDES["WEEKLY"], ("LONG",))
        self.assertEqual(engine.HORIZON_EXECUTABLE_SIDES["MONTHLY"], ("LONG",))
        self.assertEqual(engine.HORIZON_EXECUTABLE_SIDES["ETF"], ("LONG",))
        src = inspect.getsource(engine._publish_frozen)
        self.assertIn("HORIZON_EXECUTABLE_SIDES.get", src)

    def test_runtime_fails_closed_if_legacy_horizon_short_survives(self):
        src = inspect.getsource(engine.update_live_books)
        self.assertIn("HORIZON_SHORT_RESEARCH_ONLY_POLICY", src)
        self.assertIn('book in HORIZON_EXECUTABLE_SIDES and side == "SHORT"', src)

    def test_order_readiness_has_horizon_short_guard(self):
        src = inspect.getsource(orders.execution_readiness)
        self.assertIn("horizon_short_research_only", src)
        self.assertIn('("WEEKLY","MONTHLY","ETF")', src.replace(" ", ""))

    def test_restart_clears_persisted_running_scan_state(self):
        key = "scan_detail_WEEKLY"
        original = get_state(key, {})
        try:
            set_state(key, {"book":"WEEKLY","running":True,"stage":"SCORING","processed":17})
            touched = engine.reset_transient_scan_states()
            out = get_state(key,{})
            self.assertGreaterEqual(touched, 1)
            self.assertFalse(out.get("running"))
            self.assertEqual(out.get("status"), "INTERRUPTED_BY_PROCESS_RESTART")
            self.assertEqual(out.get("previous_stage"), "SCORING")
        finally:
            set_state(key, original or {})

    def test_frozen_period_skips_expensive_rescan(self):
        src = inspect.getsource(engine.run_single_horizon_cycle)
        self.assertIn("_freeze_contract_count", src)
        self.assertIn("PERIOD_BOOK_ALREADY_FROZEN", src)

    def test_void_rows_do_not_poison_corrected_period(self):
        src = inspect.getsource(engine._publish_frozen)
        self.assertIn("COALESCE(result,'')<>'VOID'", src)

    def test_upgrade_voids_legacy_horizon_shorts(self):
        install = (Path(__file__).resolve().parents[1] / "install.sh").read_text()
        self.assertIn("V638_HORIZON_SHORT_RESEARCH_ONLY_RESET", install)
        self.assertIn("book IN ('WEEKLY','MONTHLY','ETF') AND side='SHORT'", install)


    def test_etf_worker_respects_frozen_book_and_morning_window(self):
        import psscanner_quant.specialized as specialized
        src = inspect.getsource(specialized.run_etf_cycle)
        self.assertIn("_freeze_contract_count", src)
        self.assertIn("_horizon_freeze_window", src)
        self.assertIn("publication_anchor=completion", src)

    def test_ui_hides_executable_short_panel_for_horizon_books(self):
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text()
        self.assertIn("LONG ONLY", html)
        self.assertIn("bearish horizon signals remain visible as RESEARCH ONLY", html)
        self.assertIn("shortPanel.classList.toggle('hidden',horizon)", html)


if __name__ == "__main__":
    unittest.main()
