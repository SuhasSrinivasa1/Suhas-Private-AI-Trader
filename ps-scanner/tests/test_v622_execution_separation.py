import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

from psscanner_quant import engine as engine_module
from psscanner_quant import main
from psscanner_quant import orders


class V622ExecutionSeparationTests(unittest.TestCase):
    def test_research_cycle_does_not_reference_static_ip_or_execution_readiness(self):
        src = inspect.getsource(engine_module.run_research_cycle)
        self.assertNotIn("static_ip", src)
        self.assertNotIn("execution_readiness", src)

    def test_recommendation_endpoint_works_when_static_ip_is_not_verified(self):
        fake = {
            "book": "INTRADAY",
            "period_key": "2026-09-25",
            "live": {"long": [{"recommendation_id": "R1", "symbol": "TEST", "side": "LONG"}], "short": []},
            "closed": [],
            "policy": {},
        }
        with patch("psscanner_quant.main.recommendations", return_value=fake), \
             patch.object(orders.broker, "static_ip_status", return_value={"configured": False, "matches": False}):
            out = main.recommendations_api("INTRADAY")
        self.assertEqual(out["live"]["long"][0]["symbol"], "TEST")
        self.assertFalse(out["research_policy"]["recommendations_require_static_ip"])
        self.assertEqual(out["research_policy"]["static_ip_scope"], "ORDER_EXECUTION_ONLY")

    def test_order_readiness_still_blocks_unverified_static_ip(self):
        with patch("psscanner_quant.orders.load_settings", return_value={"manual_execution_enabled": True, "max_open_manual_orders": 8}), \
             patch.object(orders.broker, "static_ip_status", return_value={"configured": False, "matches": False}), \
             patch.object(orders.broker, "status", return_value={"connected": True}), \
             patch("psscanner_quant.orders.is_regular_trading_day", return_value=True), \
             patch("psscanner_quant.orders._today_order_count", return_value=0):
            out = orders.execution_readiness()
        self.assertFalse(out["ready"])
        self.assertIn("static_ip_not_set", out["blockers"])

    def test_ui_has_static_ip_execution_lock_but_research_active_copy(self):
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text()
        self.assertIn("ORDER LOCKED · STATIC IP", html)
        self.assertIn("Static IP does not affect research or recommendation generation", html)
        self.assertIn("Static IP gates order execution only; it never gates recommendations", html)

    def test_recommendations_route_is_registered(self):
        paths = {getattr(r, "path", None) for r in main.app.routes}
        self.assertIn("/api/recommendations", paths)
        self.assertIn("/api/recommendations/{book}", paths)
        self.assertIn("/api/research/readiness", paths)


if __name__ == "__main__":
    unittest.main()
