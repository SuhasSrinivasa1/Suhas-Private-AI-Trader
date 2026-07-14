from __future__ import annotations

import asyncio
import json
import time as time_module
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from technical_indicators import analyze_indicator_bundle

MODE_PROFILES: dict[str, dict[str, Any]] = {
    "intraday": {
        "label": "Intraday",
        "broker_product": "MIS",
        "holding_period": "same trading day",
        "primary_timeframes": ["5minute", "15minute"],
        "history_days": 15,
        "macd_required": True,
        "description": "Fast event-driven scan using 5-minute and 15-minute MACD alignment, live order flow, liquidity and same-day risk controls.",
        "weights": {
            "macd": 0.17,
            "rsi_momentum": 0.08,
            "trend_ema": 0.09,
            "volume_confirmation": 0.08,
            "volatility_atr": 0.06,
            "liquidity": 0.11,
            "order_flow": 0.11,
            "market_regime": 0.08,
            "news": 0.06,
            "six_month_pattern": 0.06,
            "portfolio_exposure": 0.04,
            "risk_veto": 0.06,
        },
    },
    "delivery": {
        "label": "Delivery",
        "broker_product": "CNC",
        "holding_period": "multi-day delivery position",
        "primary_timeframes": ["1day", "1week context"],
        "history_days": 180,
        "macd_required": True,
        "description": "Delivery analysis using daily MACD, six-month trend, news, volatility, portfolio exposure and wider holding-period risk controls.",
        "weights": {
            "macd": 0.15,
            "rsi_momentum": 0.08,
            "trend_ema": 0.14,
            "volume_confirmation": 0.07,
            "volatility_atr": 0.07,
            "liquidity": 0.07,
            "order_flow": 0.04,
            "market_regime": 0.08,
            "news": 0.12,
            "six_month_pattern": 0.13,
            "portfolio_exposure": 0.03,
            "risk_veto": 0.02,
        },
    },
}

AGENT_CATALOG = [
    {"id": "macd", "name": "MACD Agent", "purpose": "Checks MACD line, signal line, histogram direction and bullish/bearish crossovers."},
    {"id": "rsi_momentum", "name": "RSI Momentum Agent", "purpose": "Detects constructive momentum, weakness, oversold conditions and overbought risk."},
    {"id": "trend_ema", "name": "Trend / EMA Agent", "purpose": "Checks price versus EMA20/EMA50 and moving-average direction."},
    {"id": "volume_confirmation", "name": "Volume Confirmation Agent", "purpose": "Requires price moves to be supported by recent volume."},
    {"id": "volatility_atr", "name": "Volatility / ATR Agent", "purpose": "Measures true-range risk and rejects unstable setups."},
    {"id": "liquidity", "name": "Liquidity Agent", "purpose": "Checks spreads, live volume and execution quality."},
    {"id": "order_flow", "name": "Order Flow Agent", "purpose": "Measures live buy-versus-sell pressure for intraday timing."},
    {"id": "market_regime", "name": "Market Regime Agent", "purpose": "Checks whether the broad NSE environment supports the proposed trade."},
    {"id": "news", "name": "News Agent", "purpose": "Uses current lawful public news and blocks strong negative or unavailable required news."},
    {"id": "six_month_pattern", "name": "Six-Month Pattern Agent", "purpose": "Evaluates 180-day trend, drawdown, consistency and historical structure."},
    {"id": "portfolio_exposure", "name": "Portfolio Exposure Agent", "purpose": "Prevents concentration and capital over-allocation."},
    {"id": "risk_veto", "name": "Independent Risk Veto Agent", "purpose": "Can block any BUY regardless of the ensemble score."},
]


class ModeAgentOverlay:
    def __init__(self, core: Any, runtime: Any) -> None:
        self.core = core
        self.runtime = runtime
        self._base_scan = runtime.enriched_deep_scan
        self._mode_path = Path(core.ROOT if hasattr(core, "ROOT") else Path(__file__).resolve().parents[1]) / ".runtime" / "trading_mode.json"
        self._mode = self._load_mode()
        self._indicator_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    def _load_mode(self) -> str:
        try:
            payload = json.loads(self._mode_path.read_text(encoding="utf-8"))
            mode = str(payload.get("mode") or "intraday").lower()
            return mode if mode in MODE_PROFILES else "intraday"
        except (OSError, json.JSONDecodeError):
            return "intraday"

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> dict[str, Any]:
        normalized = mode.strip().lower()
        if normalized not in MODE_PROFILES:
            raise ValueError("Trading mode must be intraday or delivery.")
        self._mode = normalized
        self._mode_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._mode_path.with_suffix(".tmp")
        temp.write_text(json.dumps({"mode": normalized, "updated_at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n", encoding="utf-8")
        temp.replace(self._mode_path)
        return self.status()

    def status(self) -> dict[str, Any]:
        profile = MODE_PROFILES[self._mode]
        return {
            "mode": self._mode,
            "profile": profile,
            "available_modes": {key: value | {"mode": key} for key, value in MODE_PROFILES.items()},
            "agent_count": len(AGENT_CATALOG),
            "macd_enabled": True,
            "macd_parameters": {"fast": 12, "slow": 26, "signal": 9},
        }

    @staticmethod
    def _score(value: Any, default: float = 50.0) -> float:
        try:
            return max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            return default

    def _historical_candles_sync(self, symbol: str, interval_name: str) -> list[Any]:
        groww = self.core.get_groww()
        current = datetime.now(timezone.utc)
        days = 15
        interval = groww.CANDLE_INTERVAL_MIN_5 if interval_name == "5minute" else groww.CANDLE_INTERVAL_MIN_15
        payload = groww.get_historical_candles(
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            groww_symbol=f"NSE-{symbol.upper()}",
            start_time=(current - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S"),
            end_time=current.strftime("%Y-%m-%d %H:%M:%S"),
            candle_interval=interval,
        )
        return payload.get("candles", []) if isinstance(payload, dict) else []

    async def indicator_snapshot(self, symbol: str, *, force: bool = False) -> dict[str, Any]:
        symbol = symbol.upper().strip()
        cache_key = (self._mode, symbol)
        cached = self._indicator_cache.get(cache_key)
        ttl = 45 if self._mode == "intraday" else 900
        if not force and cached and time_module.monotonic() - cached[0] < ttl:
            return cached[1]

        if self._mode == "delivery":
            pattern = await self.runtime.get_pattern(symbol, "NSE", force=force)
            bundle = pattern.get("technical_indicators") or {}
            result = {
                "mode": "delivery",
                "symbol": symbol,
                "timeframes": {"1day": bundle},
                "macd": bundle.get("macd") or pattern.get("macd") or {},
                "available": bool(bundle.get("available")),
                "source": "Groww 180-day daily candles",
            }
        else:
            candles_5m, candles_15m = await asyncio.gather(
                asyncio.to_thread(self._historical_candles_sync, symbol, "5minute"),
                asyncio.to_thread(self._historical_candles_sync, symbol, "15minute"),
            )
            bundle_5m = analyze_indicator_bundle(candles_5m)
            bundle_15m = analyze_indicator_bundle(candles_15m)
            macd_5m = bundle_5m.get("macd") or {}
            macd_15m = bundle_15m.get("macd") or {}
            macd_score = (self._score(macd_5m.get("score")) * 0.58) + (self._score(macd_15m.get("score")) * 0.42)
            alignment = (
                "bullish"
                if macd_5m.get("state") == "bullish" and macd_15m.get("state") == "bullish"
                else "bearish"
                if macd_5m.get("state") == "bearish" and macd_15m.get("state") == "bearish"
                else "mixed"
            )
            result = {
                "mode": "intraday",
                "symbol": symbol,
                "timeframes": {"5minute": bundle_5m, "15minute": bundle_15m},
                "macd": {
                    "available": bool(macd_5m.get("available") and macd_15m.get("available")),
                    "state": alignment,
                    "score": round(macd_score, 2),
                    "five_minute": macd_5m,
                    "fifteen_minute": macd_15m,
                },
                "available": bool(bundle_5m.get("available") and bundle_15m.get("available")),
                "source": "Groww 5-minute and 15-minute candles",
            }
        self._indicator_cache[cache_key] = (time_module.monotonic(), result)
        return result

    def _agent_results(self, result: dict[str, Any], indicators: dict[str, Any]) -> dict[str, dict[str, Any]]:
        existing = result.get("agent_scores") or {}
        pattern = result.get("six_month_pattern") or {}
        news = result.get("news_context") or {}
        exposure = float(result.get("portfolio_exposure_pct") or 0)
        macd = indicators.get("macd") or {}

        if self._mode == "intraday":
            bundle_5m = (indicators.get("timeframes") or {}).get("5minute") or {}
            bundle_15m = (indicators.get("timeframes") or {}).get("15minute") or {}
            rsi_score = self._score((bundle_5m.get("rsi") or {}).get("score")) * 0.6 + self._score((bundle_15m.get("rsi") or {}).get("score")) * 0.4
            trend_score = self._score((bundle_5m.get("trend") or {}).get("score")) * 0.55 + self._score((bundle_15m.get("trend") or {}).get("score")) * 0.45
            volume_score = self._score((bundle_5m.get("volume") or {}).get("score"))
            atr_score = self._score((bundle_5m.get("atr") or {}).get("score"))
        else:
            bundle = (indicators.get("timeframes") or {}).get("1day") or {}
            rsi_score = self._score((bundle.get("rsi") or {}).get("score"))
            trend_score = self._score((bundle.get("trend") or {}).get("score"))
            volume_score = self._score((bundle.get("volume") or {}).get("score"))
            atr_score = self._score((bundle.get("atr") or {}).get("score"))

        veto_count = len(result.get("risk_vetoes") or [])
        raw = {
            "macd": self._score(macd.get("score")),
            "rsi_momentum": self._score(rsi_score),
            "trend_ema": self._score(trend_score),
            "volume_confirmation": self._score(volume_score),
            "volatility_atr": self._score(atr_score),
            "liquidity": self._score(existing.get("liquidity")),
            "order_flow": self._score(existing.get("order_flow")),
            "market_regime": self._score(existing.get("market_regime")),
            "news": self._score(existing.get("news"), 50.0 if news.get("available") else 35.0),
            "six_month_pattern": self._score(pattern.get("score")),
            "portfolio_exposure": self._score(100 - min(100, exposure * 4.0)),
            "risk_veto": 100.0 if veto_count == 0 else 0.0,
        }
        return {
            agent["id"]: {
                "name": agent["name"],
                "score": round(raw[agent["id"]], 2),
                "purpose": agent["purpose"],
            }
            for agent in AGENT_CATALOG
        }

    async def enriched_deep_scan(self, candidate: dict[str, Any]) -> dict[str, Any]:
        result = await self._base_scan(candidate)
        symbol = str(result.get("symbol") or candidate.get("symbol") or "").upper()
        if not symbol:
            return result
        try:
            indicators = await self.indicator_snapshot(symbol)
        except Exception as exc:
            indicators = {"mode": self._mode, "symbol": symbol, "available": False, "error": f"{exc.__class__.__name__}: indicator data unavailable", "macd": {"available": False, "score": 0}}

        agent_results = self._agent_results(result, indicators)
        profile = MODE_PROFILES[self._mode]
        consensus = sum(agent_results[key]["score"] * weight for key, weight in profile["weights"].items())
        vetoes = list(result.get("risk_vetoes") or [])
        macd = indicators.get("macd") or {}

        if not macd.get("available"):
            vetoes.append("macd_data_unavailable")
        elif self._mode == "intraday" and macd.get("state") == "bearish":
            vetoes.append("macd_5m_15m_bearish_alignment")
        elif self._mode == "delivery" and macd.get("state") == "bearish" and float((result.get("six_month_pattern") or {}).get("score") or 0) < 60:
            vetoes.append("daily_macd_and_six_month_trend_bearish")

        result["trading_mode"] = self._mode
        result["broker_product"] = profile["broker_product"]
        result["holding_period"] = profile["holding_period"]
        result["indicator_snapshot"] = indicators
        result["macd"] = macd
        result["specialist_agents"] = agent_results
        result["agent_consensus_score"] = round(consensus, 2)
        result["risk_vetoes"] = list(dict.fromkeys(vetoes))
        result["decision_model"] = "agentic-ensemble-v4-macd-mode-specialists"
        result["confirmation_layers"] = list(dict.fromkeys(list(result.get("confirmation_layers") or []) + ["mode_specific_macd", "specialist_agent_consensus"]))

        combined_confidence = round(float(result.get("confidence") or 0) * 0.55 + consensus * 0.45, 2)
        result["confidence"] = combined_confidence
        result["rank_score"] = combined_confidence - len(result["risk_vetoes"]) * 12
        reasons = list(result.get("reasons") or [])
        reasons.append(f"{profile['label']} mode uses {profile['broker_product']} and {', '.join(profile['primary_timeframes'])} analysis.")
        if macd.get("available"):
            reasons.append(f"MACD specialist is {macd.get('state', 'mixed')} with score {float(macd.get('score') or 0):.1f}/100.")
        result["reasons"] = reasons

        if result["risk_vetoes"] or combined_confidence < self.core.policy.min_watch_confidence:
            result["state"] = "WAIT"
            result["action"] = "WAIT"
        elif combined_confidence >= self.core.policy.min_buy_confidence:
            result["state"] = "BUY"
            result["action"] = "BUY"
        else:
            result["state"] = "WATCHING"
            result["action"] = "WATCH"
        result["recommendation_id"] = self.core._signal_identity(result)
        self.core.recommendation_cache[result["recommendation_id"]] = result
        return result
