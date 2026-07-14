from datetime import datetime, timedelta, timezone

from pattern_engine import analyze_six_month_pattern


def make_candles(days=140, start=100.0, daily_gain=0.25):
    rows = []
    price = start
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(days):
        open_price = price
        close = price * (1 + daily_gain / 100)
        rows.append([(base + timedelta(days=i)).isoformat(), open_price, close * 1.01, open_price * 0.99, close, 100000 + i * 100])
        price = close
    return rows


def test_strong_uptrend_scores_high():
    result = analyze_six_month_pattern(make_candles())
    assert result["available"] is True
    assert result["score"] >= 60
    assert result["label"] in {"strong_uptrend", "constructive"}


def test_insufficient_history_is_not_available():
    result = analyze_six_month_pattern(make_candles(days=20))
    assert result["available"] is False
    assert "insufficient_history" in result["risk_flags"]
