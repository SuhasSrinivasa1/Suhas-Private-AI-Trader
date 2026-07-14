import asyncio

import production22_main


def test_production22_exposes_mode_macd_and_agent_routes():
    paths = {route.path for route in production22_main.app.routes}
    assert {
        "/api/production22/status",
        "/api/trading-mode",
        "/api/specialist-agents",
        "/api/indicators/{symbol}",
    }.issubset(paths)
    assert production22_main.app.version in {"2.2.0", "2.3.0"}


def test_status_has_macd_and_twelve_specialist_agents():
    status = production22_main.production22_status()
    assert status["macd_enabled"] is True
    assert status["macd_parameters"] == {"fast": 12, "slow": 26, "signal": 9}
    assert status["specialist_agent_count"] >= 12


def test_intraday_and_delivery_map_to_mis_and_cnc(tmp_path):
    overlay = production22_main.overlay
    original_path = overlay._mode_path
    original_mode = overlay._mode
    try:
        overlay._mode_path = tmp_path / "trading_mode.json"
        intraday = asyncio.run(production22_main.set_trading_mode(production22_main.TradingModeRequest(mode="intraday")))
        assert intraday["profile"]["broker_product"] == "MIS"
        delivery = asyncio.run(production22_main.set_trading_mode(production22_main.TradingModeRequest(mode="delivery")))
        assert delivery["profile"]["broker_product"] == "CNC"
    finally:
        overlay._mode_path = original_path
        overlay._mode = original_mode
