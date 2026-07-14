from __future__ import annotations

from math import isfinite
from statistics import mean
from typing import Any


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def ema_series(values: list[float], period: int) -> list[float]:
    clean = []
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(parsed):
            clean.append(parsed)
    if not clean or period <= 0:
        return []
    multiplier = 2.0 / (period + 1.0)
    result = [clean[0]]
    for value in clean[1:]:
        result.append((value - result[-1]) * multiplier + result[-1])
    return result


def calculate_macd(
    closes: list[float],
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> dict[str, Any]:
    values = [_f(value) for value in closes if _f(value) > 0]
    minimum = slow_period + signal_period
    if len(values) < minimum:
        return {
            "available": False,
            "fast_period": fast_period,
            "slow_period": slow_period,
            "signal_period": signal_period,
            "sample_size": len(values),
            "reason": f"MACD requires at least {minimum} valid closes.",
        }

    fast = ema_series(values, fast_period)
    slow = ema_series(values, slow_period)
    macd_line = [fast[index] - slow[index] for index in range(len(values))]
    signal_line = ema_series(macd_line, signal_period)
    histogram = [macd_line[index] - signal_line[index] for index in range(len(values))]

    current_macd = macd_line[-1]
    current_signal = signal_line[-1]
    current_histogram = histogram[-1]
    previous_histogram = histogram[-2]
    previous_macd = macd_line[-2]
    previous_signal = signal_line[-2]

    if previous_macd <= previous_signal and current_macd > current_signal:
        crossover = "bullish"
    elif previous_macd >= previous_signal and current_macd < current_signal:
        crossover = "bearish"
    else:
        crossover = "none"

    histogram_rising = current_histogram > previous_histogram
    above_zero = current_macd > 0
    bullish = current_macd > current_signal and current_histogram > 0
    bearish = current_macd < current_signal and current_histogram < 0

    score = 50.0
    score += 22 if bullish else -22 if bearish else 0
    score += 10 if above_zero else -8
    score += 9 if histogram_rising else -7
    score += 12 if crossover == "bullish" else -12 if crossover == "bearish" else 0
    score = _clamp(score)

    state = "bullish" if bullish else "bearish" if bearish else "mixed"
    return {
        "available": True,
        "fast_period": fast_period,
        "slow_period": slow_period,
        "signal_period": signal_period,
        "sample_size": len(values),
        "macd_line": round(current_macd, 6),
        "signal_line": round(current_signal, 6),
        "histogram": round(current_histogram, 6),
        "previous_histogram": round(previous_histogram, 6),
        "histogram_rising": histogram_rising,
        "above_zero": above_zero,
        "crossover": crossover,
        "state": state,
        "score": round(score, 2),
    }


def calculate_rsi(closes: list[float], period: int = 14) -> dict[str, Any]:
    values = [_f(value) for value in closes if _f(value) > 0]
    if len(values) < period + 1:
        return {"available": False, "period": period, "sample_size": len(values)}
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = mean(gains[:period])
    avg_loss = mean(losses[:period])
    for index in range(period, len(changes)):
        avg_gain = ((avg_gain * (period - 1)) + gains[index]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[index]) / period
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

    if 52 <= rsi <= 68:
        score = 78.0
        state = "constructive"
    elif 45 <= rsi < 52:
        score = 58.0
        state = "neutral"
    elif 32 <= rsi < 45:
        score = 38.0
        state = "weak"
    elif rsi < 32:
        score = 48.0
        state = "oversold"
    elif rsi <= 75:
        score = 68.0
        state = "strong"
    else:
        score = 42.0
        state = "overbought"
    return {"available": True, "period": period, "value": round(rsi, 3), "state": state, "score": score}


def calculate_atr(rows: list[dict[str, Any]], period: int = 14) -> dict[str, Any]:
    if len(rows) < period + 1:
        return {"available": False, "period": period, "sample_size": len(rows)}
    true_ranges: list[float] = []
    for index in range(1, len(rows)):
        high = _f(rows[index].get("high"))
        low = _f(rows[index].get("low"))
        previous_close = _f(rows[index - 1].get("close"))
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    atr = mean(true_ranges[-period:])
    latest_close = _f(rows[-1].get("close"))
    atr_pct = atr / latest_close * 100 if latest_close else 0.0
    score = _clamp(100 - abs(atr_pct - 1.8) * 20)
    return {
        "available": True,
        "period": period,
        "value": round(atr, 6),
        "pct": round(atr_pct, 3),
        "score": round(score, 2),
    }


def analyze_indicator_bundle(candles: list[Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in candles:
        if isinstance(row, dict):
            parsed = {
                "open": _f(row.get("open")),
                "high": _f(row.get("high")),
                "low": _f(row.get("low")),
                "close": _f(row.get("close")),
                "volume": max(0.0, _f(row.get("volume"))),
            }
        elif isinstance(row, (list, tuple)) and len(row) >= 5:
            parsed = {
                "open": _f(row[1]),
                "high": _f(row[2]),
                "low": _f(row[3]),
                "close": _f(row[4]),
                "volume": max(0.0, _f(row[5])) if len(row) > 5 else 0.0,
            }
        else:
            continue
        if min(parsed["open"], parsed["high"], parsed["low"], parsed["close"]) > 0:
            rows.append(parsed)

    closes = [row["close"] for row in rows]
    volumes = [row["volume"] for row in rows]
    macd = calculate_macd(closes)
    rsi = calculate_rsi(closes)
    atr = calculate_atr(rows)
    ema20_values = ema_series(closes, 20)
    ema50_values = ema_series(closes, 50)
    latest = closes[-1] if closes else 0.0
    ema20 = ema20_values[-1] if ema20_values else 0.0
    ema50 = ema50_values[-1] if ema50_values else 0.0
    trend_score = 50.0
    trend_score += 20 if latest > ema20 else -20
    trend_score += 18 if ema20 > ema50 else -18
    trend_score += 8 if len(ema20_values) > 1 and ema20_values[-1] > ema20_values[-2] else -6
    trend_score = _clamp(trend_score)
    trend_state = "bullish" if latest > ema20 > ema50 else "bearish" if latest < ema20 < ema50 else "mixed"

    recent_volume = mean(volumes[-10:]) if volumes and any(volumes[-10:]) else 0.0
    baseline_volume = mean(volumes[-30:]) if volumes and any(volumes[-30:]) else 0.0
    volume_ratio = recent_volume / baseline_volume if baseline_volume > 0 else 1.0
    volume_score = _clamp(50 + (volume_ratio - 1.0) * 45)

    available = bool(closes) and bool(macd.get("available"))
    return {
        "available": available,
        "sample_size": len(rows),
        "latest_close": round(latest, 6) if latest else 0.0,
        "macd": macd,
        "rsi": rsi,
        "atr": atr,
        "trend": {
            "ema20": round(ema20, 6),
            "ema50": round(ema50, 6),
            "state": trend_state,
            "score": round(trend_score, 2),
        },
        "volume": {
            "ratio_10_vs_30": round(volume_ratio, 4),
            "score": round(volume_score, 2),
            "state": "confirming" if volume_ratio >= 1.1 else "weak" if volume_ratio < 0.75 else "normal",
        },
    }
