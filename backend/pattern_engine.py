from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import sqrt
from statistics import mean, pstdev
from typing import Any

from technical_indicators import analyze_indicator_bundle


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _pct_change(new: float, old: float) -> float:
    return ((new - old) / old * 100.0) if old else 0.0


def _sma(values: list[float], length: int) -> float:
    window = values[-length:] if len(values) >= length else values
    return mean(window) if window else 0.0


def _max_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak * 100.0)
    return worst


def _normalized_slope(values: list[float]) -> float:
    if len(values) < 3 or mean(values) == 0:
        return 0.0
    n = len(values)
    x_mean = (n - 1) / 2
    y_mean = mean(values)
    numerator = sum((i - x_mean) * (value - y_mean) for i, value in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    slope = numerator / denominator if denominator else 0.0
    return slope / y_mean * 100.0


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            seconds = float(value)
            if seconds > 10_000_000_000:
                seconds /= 1000.0
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T")):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def normalize_candles(candles: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        close = _f(row[4])
        high = _f(row[2])
        low = _f(row[3])
        open_price = _f(row[1])
        if min(close, high, low, open_price) <= 0:
            continue
        normalized.append(
            {
                "timestamp": _parse_timestamp(row[0]),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": max(0.0, _f(row[5])) if len(row) > 5 else 0.0,
            }
        )
    normalized.sort(key=lambda item: item["timestamp"] or datetime.min.replace(tzinfo=timezone.utc))
    return normalized


def analyze_six_month_pattern(candles: list[Any]) -> dict[str, Any]:
    rows = normalize_candles(candles)
    sample_size = len(rows)
    if sample_size < 60:
        return {
            "available": False,
            "score": 50.0,
            "label": "insufficient_history",
            "sample_size": sample_size,
            "reasons": [f"Only {sample_size} valid daily candles were available; at least 60 are required."],
            "risk_flags": ["insufficient_history"],
        }

    closes = [row["close"] for row in rows]
    highs = [row["high"] for row in rows]
    lows = [row["low"] for row in rows]
    volumes = [row["volume"] for row in rows]
    latest = closes[-1]

    def return_over(period: int) -> float:
        return _pct_change(latest, closes[-period - 1]) if len(closes) > period else 0.0

    ret_5 = return_over(5)
    ret_20 = return_over(20)
    ret_60 = return_over(60)
    ret_120 = return_over(120)

    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    sma100 = _sma(closes, 100)
    slope20 = _normalized_slope(closes[-20:])
    slope60 = _normalized_slope(closes[-60:])

    daily_returns = [_pct_change(closes[i], closes[i - 1]) for i in range(1, len(closes))]
    recent_returns = daily_returns[-60:]
    annualized_volatility = pstdev(recent_returns) * sqrt(252) if len(recent_returns) > 1 else 0.0
    win_rate_60 = sum(1 for value in recent_returns if value > 0) / len(recent_returns) * 100 if recent_returns else 50.0
    max_drawdown = _max_drawdown(closes)

    high_60 = max(highs[-60:])
    low_60 = min(lows[-60:])
    range_position_60 = (latest - low_60) / (high_60 - low_60) if high_60 > low_60 else 0.5

    avg_volume_20 = mean(volumes[-20:]) if any(volumes[-20:]) else 0.0
    avg_volume_60 = mean(volumes[-60:]) if any(volumes[-60:]) else 0.0
    volume_ratio = avg_volume_20 / avg_volume_60 if avg_volume_60 > 0 else 1.0

    weekday_returns: dict[int, list[float]] = {day: [] for day in range(5)}
    for index in range(1, len(rows)):
        timestamp = rows[index]["timestamp"]
        if timestamp and timestamp.weekday() < 5:
            weekday_returns[timestamp.weekday()].append(_pct_change(closes[index], closes[index - 1]))
    weekday_edges = {day: mean(values) if values else 0.0 for day, values in weekday_returns.items()}
    best_weekday = max(weekday_edges, key=weekday_edges.get)

    technical_indicators = analyze_indicator_bundle(rows)

    trend_score = _clamp(50 + ret_20 * 1.4 + ret_60 * 0.55 + ret_120 * 0.22 + slope60 * 35, 0, 100)
    structure_score = 50.0
    structure_score += 15 if latest > sma20 else -15
    structure_score += 15 if sma20 > sma50 else -15
    structure_score += 12 if sma50 > sma100 else -12
    structure_score += (range_position_60 - 0.5) * 35
    structure_score = _clamp(structure_score, 0, 100)
    momentum_score = _clamp(50 + ret_5 * 3.0 + ret_20 * 1.0 + slope20 * 55, 0, 100)
    consistency_score = _clamp(win_rate_60, 0, 100)
    risk_score = _clamp(100 - annualized_volatility * 0.85 - abs(min(max_drawdown, 0.0)) * 0.55, 0, 100)
    volume_score = _clamp(50 + (volume_ratio - 1.0) * 45, 0, 100)

    score = (
        trend_score * 0.28
        + structure_score * 0.22
        + momentum_score * 0.18
        + consistency_score * 0.12
        + risk_score * 0.12
        + volume_score * 0.08
    )
    score = round(_clamp(score, 0, 100), 2)

    if score >= 74:
        label = "strong_uptrend"
    elif score >= 62:
        label = "constructive"
    elif score >= 48:
        label = "neutral"
    elif score >= 38:
        label = "weak"
    else:
        label = "bearish"

    risk_flags: list[str] = []
    if max_drawdown <= -28:
        risk_flags.append("deep_six_month_drawdown")
    if annualized_volatility >= 65:
        risk_flags.append("very_high_realized_volatility")
    if latest < sma50 < sma100:
        risk_flags.append("bearish_moving_average_structure")
    if ret_20 <= -12:
        risk_flags.append("sharp_one_month_decline")

    reasons: list[str] = []
    reasons.append(f"Six-month pattern score {score:.1f}/100 ({label.replace('_', ' ')}).")
    reasons.append(f"20-day return {ret_20:.1f}% and 60-day return {ret_60:.1f}%.")
    reasons.append(
        "Price is above both the 20-day and 50-day averages."
        if latest > sma20 and latest > sma50
        else "Price is not above both the 20-day and 50-day averages."
    )
    reasons.append(f"60-day positive-session rate is {win_rate_60:.0f}% with {annualized_volatility:.1f}% annualized volatility.")
    if technical_indicators.get("macd", {}).get("available"):
        macd = technical_indicators["macd"]
        reasons.append(
            f"Daily MACD is {macd.get('state', 'mixed')} with histogram {float(macd.get('histogram') or 0):.4f}."
        )

    return {
        "available": True,
        "score": score,
        "label": label,
        "sample_size": sample_size,
        "latest_close": round(latest, 4),
        "return_5d_pct": round(ret_5, 3),
        "return_20d_pct": round(ret_20, 3),
        "return_60d_pct": round(ret_60, 3),
        "return_120d_pct": round(ret_120, 3),
        "sma20": round(sma20, 4),
        "sma50": round(sma50, 4),
        "sma100": round(sma100, 4),
        "slope20_pct_per_session": round(slope20, 4),
        "slope60_pct_per_session": round(slope60, 4),
        "annualized_volatility_pct": round(annualized_volatility, 3),
        "max_drawdown_pct": round(max_drawdown, 3),
        "win_rate_60d_pct": round(win_rate_60, 3),
        "range_position_60d": round(range_position_60, 4),
        "volume_ratio_20d_vs_60d": round(volume_ratio, 4),
        "best_weekday": best_weekday,
        "best_weekday_mean_return_pct": round(weekday_edges[best_weekday], 4),
        "technical_indicators": technical_indicators,
        "macd": technical_indicators.get("macd", {}),
        "rsi": technical_indicators.get("rsi", {}),
        "risk_flags": risk_flags,
        "reasons": reasons,
    }


def fetch_six_month_pattern_sync(
    groww: Any,
    symbol: str,
    exchange: str = "NSE",
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    end_time = current.strftime("%Y-%m-%d %H:%M:%S")
    start_time = (current - timedelta(days=180)).strftime("%Y-%m-%d %H:%M:%S")
    exchange_name = exchange.upper()
    exchange_constant = groww.EXCHANGE_NSE if exchange_name == "NSE" else groww.EXCHANGE_BSE
    payload = groww.get_historical_candles(
        exchange=exchange_constant,
        segment=groww.SEGMENT_CASH,
        groww_symbol=f"{exchange_name}-{symbol.upper()}",
        start_time=start_time,
        end_time=end_time,
        candle_interval=groww.CANDLE_INTERVAL_DAY,
    )
    candles = payload.get("candles", []) if isinstance(payload, dict) else []
    analysis = analyze_six_month_pattern(candles)
    analysis.update(
        {
            "symbol": symbol.upper(),
            "exchange": exchange_name,
            "window_days": 180,
            "source": "groww_historical_candles",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return analysis
