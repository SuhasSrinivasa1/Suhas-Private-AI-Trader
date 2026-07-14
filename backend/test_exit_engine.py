from exit_engine import evaluate_exit_signal


def test_five_percent_profit_generates_trim_plan():
    result = evaluate_exit_signal(
        symbol="TEST",
        quantity=20,
        average_price=100,
        current_price=105.5,
        pattern={"available": True, "score": 70},
        news={"available": True, "sentiment": 0.1},
    )
    assert result["action"] == "TRIM_15"
    assert result["pnl_pct"] > 5


def test_strong_negative_news_escalates_sell_review():
    result = evaluate_exit_signal(
        symbol="TEST",
        quantity=10,
        average_price=100,
        current_price=101,
        pattern={"available": True, "score": 65},
        news={"available": True, "sentiment": -0.8},
    )
    assert result["action"] == "REVIEW_SELL"
    assert result["urgency"] == "high"
