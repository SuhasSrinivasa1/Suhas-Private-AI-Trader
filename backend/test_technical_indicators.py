from technical_indicators import analyze_indicator_bundle, calculate_macd, calculate_rsi


def rising_closes(count: int = 80) -> list[float]:
    return [100.0 + index * 0.6 for index in range(count)]


def falling_closes(count: int = 80) -> list[float]:
    return [150.0 - index * 0.6 for index in range(count)]


def test_macd_12_26_9_is_available_and_bullish_for_rising_series():
    result = calculate_macd(rising_closes())
    assert result["available"] is True
    assert (result["fast_period"], result["slow_period"], result["signal_period"]) == (12, 26, 9)
    assert result["macd_line"] > result["signal_line"]
    assert result["histogram"] > 0
    assert result["state"] == "bullish"


def test_macd_is_bearish_for_falling_series():
    result = calculate_macd(falling_closes())
    assert result["available"] is True
    assert result["macd_line"] < result["signal_line"]
    assert result["histogram"] < 0
    assert result["state"] == "bearish"


def test_indicator_bundle_includes_macd_rsi_ema_atr_and_volume():
    closes = rising_closes(90)
    candles = []
    for index, close in enumerate(closes):
        candles.append([index, close - 0.2, close + 0.8, close - 0.8, close, 1000 + index * 20])
    result = analyze_indicator_bundle(candles)
    assert result["available"] is True
    assert result["macd"]["available"] is True
    assert result["rsi"]["available"] is True
    assert result["trend"]["ema20"] > 0
    assert result["trend"]["ema50"] > 0
    assert result["atr"]["available"] is True
    assert result["volume"]["ratio_10_vs_30"] > 0


def test_rsi_marks_extreme_rise_as_overbought():
    result = calculate_rsi(rising_closes())
    assert result["available"] is True
    assert result["value"] > 70
    assert result["state"] == "overbought"
