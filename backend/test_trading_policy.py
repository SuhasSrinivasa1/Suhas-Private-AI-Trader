from datetime import datetime, timedelta, timezone

from trading_policy import TradingPolicy, build_agentic_opportunity, coarse_rank, evaluate_entry


def base_request():
    return {
        "symbol": "AAPL",
        "market": "NASDAQ",
        "direction": "long",
        "current_price": 101.0,
        "reference_price": 100.0,
        "entry_price": 101.0,
        "stop_loss": 99.0,
        "target_price": 105.0,
        "quantity": 10,
        "portfolio_value": 100000.0,
        "price_timestamp": datetime.now(timezone.utc),
        "quote_source": "verified-live-feed",
        "confirmation_source_count": 2,
        "news_checked": True,
        "technical_checked": True,
        "portfolio_checked": True,
    }


def strong_quote():
    return {
        "last_price": 103.0,
        "day_change_perc": 1.4,
        "bid_price": 102.95,
        "offer_price": 103.0,
        "total_buy_quantity": 700000,
        "total_sell_quantity": 300000,
        "volume": 2500000,
        "ohlc": {"open": 100.0, "high": 104.0, "low": 99.5, "close": 101.0},
    }


def test_valid_long_is_buy_in_paper_mode():
    result = evaluate_entry(**base_request())
    assert result["eligible"] is True
    assert result["action"] == "BUY"
    assert result["execution_mode"] == "paper"


def test_live_execution_is_blocked_by_default():
    request = base_request()
    request["live_execution_requested"] = True
    result = evaluate_entry(**request)
    assert result["eligible"] is False
    assert result["execution_mode"] == "paper"


def test_chasing_is_rejected():
    request = base_request()
    request["current_price"] = 103.0
    result = evaluate_entry(**request)
    assert result["action"] == "WAIT"
    assert any("Do not chase" in reason for reason in result["reasons"])


def test_controlled_policy_override_can_enable_live_mode():
    request = base_request()
    request["live_execution_requested"] = True
    result = evaluate_entry(**request, policy=TradingPolicy(allow_live_execution=True))
    assert result["eligible"] is True
    assert result["execution_mode"] == "live"


def test_coarse_rank_prefers_upper_range_momentum():
    result = coarse_rank(
        symbol="TEST",
        exchange="NSE",
        last_price=103,
        ohlc={"open": 100, "high": 104, "low": 99.5, "close": 101},
        market_regime_score=70,
    )
    assert result["eligible"] is True
    assert result["coarse_score"] > 60


def test_multi_agent_engine_can_generate_buy():
    result = build_agentic_opportunity(
        symbol="TEST",
        exchange="NSE",
        quote=strong_quote(),
        portfolio_value=500000,
        market_regime_score=72,
        news_score=0.2,
        portfolio_exposure_pct=0,
        policy=TradingPolicy(min_buy_confidence=65),
    )
    assert result["state"] == "BUY"
    assert result["action"] == "BUY"
    assert result["entry_price"] > result["stop_loss"]
    assert result["target_price"] > result["entry_price"]
    assert result["quantity"] >= 1
    assert result["risk_vetoes"] == []


def test_risk_agent_vetoes_weak_market():
    result = build_agentic_opportunity(
        symbol="TEST",
        exchange="NSE",
        quote=strong_quote(),
        portfolio_value=500000,
        market_regime_score=20,
        news_score=0,
        portfolio_exposure_pct=0,
    )
    assert result["state"] == "WAIT"
    assert any("market regime" in reason.lower() for reason in result["risk_vetoes"])


def test_position_exposure_cap_can_veto_buy():
    result = build_agentic_opportunity(
        symbol="TEST",
        exchange="NSE",
        quote=strong_quote(),
        portfolio_value=500000,
        market_regime_score=75,
        news_score=0.2,
        portfolio_exposure_pct=25,
    )
    assert result["state"] == "WAIT"
    assert any("exposure" in reason.lower() for reason in result["risk_vetoes"])


def test_stale_broker_trade_timestamp_vetoes_buy():
    quote = strong_quote()
    quote["last_trade_time"] = int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp() * 1000)
    result = build_agentic_opportunity(
        symbol="TEST",
        exchange="NSE",
        quote=quote,
        portfolio_value=500000,
        market_regime_score=72,
        news_score=0.2,
        portfolio_exposure_pct=0,
        policy=TradingPolicy(min_buy_confidence=65),
    )
    assert result["state"] == "WAIT"
    assert any("stale" in reason.lower() for reason in result["risk_vetoes"])
