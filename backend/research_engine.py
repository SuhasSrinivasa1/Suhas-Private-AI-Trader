from __future__ import annotations

import asyncio
import math
import random
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from pattern_engine import normalize_candles
from technical_indicators import analyze_indicator_bundle


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    name: str
    mode: str
    description: str
    entry_rules: list[str]
    exit_rules: list[str]
    parameters: dict[str, Any]
    best_regimes: list[str]
    avoid_regimes: list[str]


STRATEGIES: tuple[StrategySpec, ...] = (
    StrategySpec(
        "trend_macd_volume", "MACD Trend + Volume", "delivery",
        "Daily trend-following strategy requiring MACD, EMA structure and volume confirmation.",
        ["close > EMA20 > EMA50", "MACD histogram > 0", "RSI between 50 and 72", "volume ratio >= 1.05"],
        ["ATR stop", "2R target", "MACD bearish crossover", "maximum 20 sessions"],
        {"ema_fast": 20, "ema_slow": 50, "macd": [12, 26, 9], "rsi": 14, "atr": 14, "stop_atr": 1.5, "target_r": 2.0, "max_holding_bars": 20},
        ["bullish", "recovering"], ["bearish", "extreme_volatility"],
    ),
    StrategySpec(
        "mean_reversion_rsi", "RSI Mean Reversion", "delivery",
        "Controlled rebound strategy for liquid stocks after a statistically stretched decline.",
        ["RSI < 35", "close above recent 5-day low", "long-term trend not strongly bearish", "volume ratio >= 0.8"],
        ["1.5R target", "ATR stop", "RSI >= 58", "maximum 10 sessions"],
        {"rsi": 14, "oversold": 35, "exit_rsi": 58, "atr": 14, "stop_atr": 1.25, "target_r": 1.5, "max_holding_bars": 10},
        ["sideways", "recovering"], ["strong_bearish", "event_shock"],
    ),
    StrategySpec(
        "breakout_volume", "Volume Breakout", "delivery",
        "Breakout above a 20-session range with strong volume and controlled volatility.",
        ["close > prior 20-bar high", "volume ratio >= 1.5", "ATR% <= 6", "RSI <= 78"],
        ["2R target", "ATR stop", "close below EMA20", "maximum 15 sessions"],
        {"breakout_lookback": 20, "volume_ratio": 1.5, "atr": 14, "stop_atr": 1.4, "target_r": 2.0, "max_holding_bars": 15},
        ["bullish", "high_momentum"], ["sideways_low_volume", "extreme_volatility"],
    ),
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def _rsi(values: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains, losses = [], []
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0)); losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / period; avg_loss = sum(losses) / period
    out[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0)) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def _atr(rows: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(rows)
    if len(rows) <= period:
        return out
    trs = []
    for i, row in enumerate(rows):
        prev = rows[i - 1]["close"] if i else row["close"]
        trs.append(max(row["high"] - row["low"], abs(row["high"] - prev), abs(row["low"] - prev)))
    current = sum(trs[1:period + 1]) / period
    out[period] = current
    for i in range(period + 1, len(rows)):
        current = (current * (period - 1) + trs[i]) / period
        out[i] = current
    return out


def _max_drawdown(equity: list[float]) -> float:
    peak = equity[0] if equity else 1.0
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak:
            worst = min(worst, (value - peak) / peak)
    return worst * 100


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    deviation = statistics.pstdev(returns)
    return statistics.mean(returns) / deviation * math.sqrt(252) if deviation else 0.0


def _sortino(returns: list[float]) -> float:
    downside = [r for r in returns if r < 0]
    if not downside:
        return 0.0 if not returns else 99.0
    deviation = math.sqrt(sum(r * r for r in downside) / len(downside))
    return statistics.mean(returns) / deviation * math.sqrt(252) if deviation else 0.0


class ResearchEngine:
    """Groww-only research, backtesting and strategy approval. No mock market data."""

    def __init__(self, core: Any, runtime: Any, calls: Any) -> None:
        self.core = core
        self.runtime = runtime
        self.calls = calls
        self._cache: dict[str, dict[str, Any]] = {}

    def catalog(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in STRATEGIES]

    def _fetch_candles_sync(self, symbol: str, years: int = 5) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        groww = self.core.get_groww()
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(365, years * 366))
        payload = groww.get_historical_candles(
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            groww_symbol=f"NSE-{symbol.upper()}",
            start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=end.strftime("%Y-%m-%d %H:%M:%S"),
            candle_interval=groww.CANDLE_INTERVAL_DAY,
        )
        raw = payload.get("candles", []) if isinstance(payload, dict) else []
        rows = normalize_candles(raw)
        return rows, {"provider": "Groww Trading API", "symbol": symbol.upper(), "requested_years": years, "valid_candles": len(rows), "fetched_at": end.isoformat()}

    async def candles(self, symbol: str, years: int = 5) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self.core._broker_configured():
            raise RuntimeError("Groww credentials are required. Research features never substitute mock data.")
        return await asyncio.to_thread(self._fetch_candles_sync, symbol, years)

    @staticmethod
    def regime(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if len(rows) < 60:
            return {"available": False, "state": "insufficient_data"}
        closes = [r["close"] for r in rows]
        ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
        returns = [(closes[i] / closes[i-1] - 1) for i in range(1, len(closes))]
        vol = statistics.pstdev(returns[-20:]) * math.sqrt(252) * 100 if len(returns) >= 20 else 0
        slope = (ema20[-1] / ema20[-20] - 1) * 100 if len(ema20) >= 20 else 0
        if ema20[-1] > ema50[-1] and slope > 1:
            state = "bullish"
        elif ema20[-1] < ema50[-1] and slope < -1:
            state = "bearish"
        else:
            state = "sideways"
        if vol >= 55:
            state = "extreme_volatility"
        return {"available": True, "state": state, "annualized_volatility_pct": round(vol, 2), "ema20": round(ema20[-1], 2), "ema50": round(ema50[-1], 2), "trend_slope_pct": round(slope, 2)}

    def _signals(self, strategy_id: str, rows: list[dict[str, Any]]) -> list[bool]:
        closes = [r["close"] for r in rows]; volumes = [r["volume"] for r in rows]
        ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
        rsi = _rsi(closes, 14); atr = _atr(rows, 14)
        macd_fast, macd_slow = _ema(closes, 12), _ema(closes, 26)
        macd = [a-b for a,b in zip(macd_fast, macd_slow)]; signal = _ema(macd, 9)
        output = [False] * len(rows)
        for i in range(55, len(rows)):
            avg_vol = statistics.mean(volumes[max(0, i-20):i]) if any(volumes[max(0, i-20):i]) else 0
            vol_ratio = volumes[i] / avg_vol if avg_vol else 1.0
            atr_pct = (atr[i] or 0) / closes[i] * 100 if closes[i] else 0
            if strategy_id == "trend_macd_volume":
                output[i] = closes[i] > ema20[i] > ema50[i] and macd[i] > signal[i] and (rsi[i] or 0) >= 50 and (rsi[i] or 100) <= 72 and vol_ratio >= 1.05
            elif strategy_id == "mean_reversion_rsi":
                output[i] = (rsi[i] or 100) < 35 and closes[i] > min(closes[i-4:i+1]) and closes[i] > ema50[i] * 0.85 and vol_ratio >= 0.8
            elif strategy_id == "breakout_volume":
                output[i] = closes[i] > max(closes[i-20:i]) and vol_ratio >= 1.5 and atr_pct <= 6 and (rsi[i] or 100) <= 78
        return output

    def backtest_rows(self, strategy_id: str, rows: list[dict[str, Any]], capital: float = 20000.0, costs_bps: float = 20.0) -> dict[str, Any]:
        spec = next((s for s in STRATEGIES if s.strategy_id == strategy_id), None)
        if spec is None:
            raise ValueError("Unknown strategy")
        if len(rows) < 120:
            raise ValueError("At least 120 valid Groww daily candles are required")
        signals = self._signals(strategy_id, rows)
        atr = _atr(rows, 14)
        trades, equity = [], [capital]
        i = 60
        while i < len(rows) - 1:
            if not signals[i]:
                i += 1; continue
            entry_i = i + 1; entry = rows[entry_i]["open"]
            risk = (atr[i] or entry * 0.02) * float(spec.parameters["stop_atr"])
            stop = max(0.01, entry - risk); target = entry + risk * float(spec.parameters["target_r"])
            exit_i = min(len(rows)-1, entry_i + int(spec.parameters["max_holding_bars"])); reason = "TIME"
            for j in range(entry_i, exit_i + 1):
                if rows[j]["low"] <= stop:
                    exit_i = j; exit_price = stop; reason = "STOP"; break
                if rows[j]["high"] >= target:
                    exit_i = j; exit_price = target; reason = "TARGET"; break
            else:
                exit_price = rows[exit_i]["close"]
            gross = exit_price / entry - 1
            net = gross - (costs_bps / 10000.0)
            pnl = equity[-1] * min(0.20, 0.01 / max((entry-stop)/entry, 0.0001)) * net
            equity.append(max(0.0, equity[-1] + pnl))
            trades.append({"entry_at": rows[entry_i]["timestamp"].isoformat() if rows[entry_i]["timestamp"] else None, "exit_at": rows[exit_i]["timestamp"].isoformat() if rows[exit_i]["timestamp"] else None, "entry": round(entry,2), "exit": round(exit_price,2), "return_pct": round(net*100,3), "reason": reason})
            i = exit_i + 1
        returns = [t["return_pct"] / 100 for t in trades]
        wins = [r for r in returns if r > 0]; losses = [r for r in returns if r <= 0]
        years = max(1/252, len(rows)/252)
        final = equity[-1]
        cagr = ((final / capital) ** (1/years) - 1) * 100 if final > 0 else -100
        gross_profit = sum(wins); gross_loss = abs(sum(losses))
        return {
            "strategy": asdict(spec), "data_source": "Groww Trading API", "candle_count": len(rows),
            "metrics": {"initial_capital": round(capital,2), "final_equity": round(final,2), "net_return_pct": round((final/capital-1)*100,2), "cagr_pct": round(cagr,2), "total_trades": len(trades), "win_rate_pct": round(len(wins)/len(trades)*100,2) if trades else 0.0, "profit_factor": round(gross_profit/gross_loss,2) if gross_loss else (99.0 if gross_profit else 0.0), "sharpe": round(_sharpe(returns),2), "sortino": round(_sortino(returns),2), "max_drawdown_pct": round(_max_drawdown(equity),2), "average_trade_pct": round(statistics.mean(returns)*100,3) if returns else 0.0, "largest_loss_pct": round(min(returns)*100,3) if returns else 0.0},
            "trades": trades[-250:], "equity_curve": [round(x,2) for x in equity], "costs_bps_round_trip": costs_bps,
        }

    async def backtest(self, symbol: str, strategy_id: str, years: int = 5) -> dict[str, Any]:
        rows, source = await self.candles(symbol, years)
        result = self.backtest_rows(strategy_id, rows)
        result["symbol"] = symbol.upper(); result["source_metadata"] = source; result["regime"] = self.regime(rows)
        return result

    async def walk_forward(self, symbol: str, strategy_id: str, years: int = 5) -> dict[str, Any]:
        rows, source = await self.candles(symbol, years)
        if len(rows) < 500:
            raise ValueError("Walk-forward validation requires at least 500 Groww daily candles")
        splits = []
        window, test = 378, 126
        start = 0
        while start + window + test <= len(rows):
            train_rows = rows[start:start+window]; test_rows = rows[start+window:start+window+test]
            train = self.backtest_rows(strategy_id, train_rows); out = self.backtest_rows(strategy_id, test_rows)
            splits.append({"train_start": train_rows[0]["timestamp"].date().isoformat(), "train_end": train_rows[-1]["timestamp"].date().isoformat(), "test_start": test_rows[0]["timestamp"].date().isoformat(), "test_end": test_rows[-1]["timestamp"].date().isoformat(), "train_metrics": train["metrics"], "test_metrics": out["metrics"]})
            start += test
        profitable = sum(1 for s in splits if s["test_metrics"]["net_return_pct"] > 0)
        return {"symbol": symbol.upper(), "strategy_id": strategy_id, "data_source": source, "splits": splits, "summary": {"windows": len(splits), "profitable_test_windows": profitable, "out_of_sample_consistency_pct": round(profitable/max(1,len(splits))*100,2), "approved": len(splits) >= 3 and profitable/max(1,len(splits)) >= 0.67}}

    async def monte_carlo(self, symbol: str, strategy_id: str, years: int = 5, simulations: int = 2000) -> dict[str, Any]:
        backtest = await self.backtest(symbol, strategy_id, years)
        returns = [t["return_pct"] / 100 for t in backtest["trades"]]
        if len(returns) < 20:
            raise ValueError("Monte Carlo requires at least 20 historical Groww-derived trades")
        simulations = max(250, min(int(simulations), 10000)); paths = []; drawdowns = []
        seed = f"{symbol}:{strategy_id}:{len(returns)}"; rng = random.Random(seed)
        for _ in range(simulations):
            equity = 20000.0; curve = [equity]
            for _n in range(min(60, max(20, len(returns)))):
                equity *= 1 + rng.choice(returns); curve.append(equity)
            paths.append(equity); drawdowns.append(_max_drawdown(curve))
        paths.sort(); drawdowns.sort()
        def pct(values, p): return values[min(len(values)-1, max(0, int((len(values)-1)*p)))]
        return {"symbol": symbol.upper(), "strategy_id": strategy_id, "simulations": simulations, "source": "resampled historical trades derived only from Groww candles", "probability_of_profit_pct": round(sum(v>20000 for v in paths)/simulations*100,2), "probability_of_10pct_loss_pct": round(sum(v<18000 for v in paths)/simulations*100,2), "probability_reach_1_lakh_pct": round(sum(v>=100000 for v in paths)/simulations*100,4), "ending_equity": {"p05": round(pct(paths,.05),2), "median": round(pct(paths,.5),2), "p95": round(pct(paths,.95),2)}, "max_drawdown_pct": {"median": round(pct(drawdowns,.5),2), "worst_95pct": round(pct(drawdowns,.05),2)}}

    def calls_edge(self) -> dict[str, Any]:
        summary = self.calls.summary(); learning = summary.get("learning") or {}
        resolved = int(summary.get("resolved_calls") or 0); accuracy = float(summary.get("accuracy_pct") or 0)
        state = "INSUFFICIENT_SAMPLE" if resolved < 50 else "ACTIVE" if accuracy >= 60 else "DETERIORATING"
        return {"state": state, "resolved_calls": resolved, "accuracy_pct": accuracy, "wilson_lower_bound_pct": round(float(learning.get("wilson_lower_bound") or 0)*100,2), "action": "COLLECT" if resolved < 50 else "KEEP" if accuracy >= 60 else "REDUCE_WEIGHT", "note": "This monitor never claims a permanent edge and never uses unresolved calls as wins."}

    async def full_report(self, symbol: str, strategy_id: str, years: int = 5) -> dict[str, Any]:
        backtest, walk, monte = await asyncio.gather(self.backtest(symbol, strategy_id, years), self.walk_forward(symbol, strategy_id, years), self.monte_carlo(symbol, strategy_id, years))
        m = backtest["metrics"]
        gates = {"minimum_trades": m["total_trades"] >= 30, "positive_profit_factor": m["profit_factor"] >= 1.2, "controlled_drawdown": m["max_drawdown_pct"] >= -25, "walk_forward": bool(walk["summary"]["approved"]), "monte_carlo_loss_risk": monte["probability_of_10pct_loss_pct"] <= 35}
        return {"symbol": symbol.upper(), "strategy_id": strategy_id, "backtest": backtest, "walk_forward": walk, "monte_carlo": monte, "approval": {"gates": gates, "approved_for_paper_observation": all(gates.values()), "approved_for_live_calls": False, "reason": "Research strategies must still complete live paper observation and risk review before influencing actionable calls."}, "edge_monitor": self.calls_edge()}
