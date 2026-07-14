from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from news_provider import fetch_free_news_sync
from pattern_engine import fetch_six_month_pattern_sync

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / ".runtime"
DAILY_FILE = RUNTIME_DIR / "daily_recommendations.json"
PATTERN_TTL_SECONDS = max(900, int(os.getenv("PATTERN_CACHE_TTL_SECONDS", "21600")))
NEWS_TTL_SECONDS = max(300, int(os.getenv("NEWS_CACHE_TTL_SECONDS", "1200")))
NEWS_REQUIRED_FOR_BUY = os.getenv("NEWS_REQUIRED_FOR_BUY", "true").strip().lower() in {"1", "true", "yes", "on"}
DAILY_TOP_COUNT = max(5, min(20, int(os.getenv("DAILY_TOP_COUNT", "10"))))
DAILY_NEWS_CANDIDATES = max(5, min(30, int(os.getenv("DAILY_NEWS_CANDIDATES", "18"))))


class ProductionRuntime:
    def __init__(self, core: Any) -> None:
        self.core = core
        self.pattern_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.news_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.daily_snapshot: dict[str, Any] = self._load_daily_snapshot()
        self.daily_generation_lock = asyncio.Lock()
        self.pattern_semaphore = asyncio.Semaphore(3)
        self.news_semaphore = asyncio.Semaphore(4)
        self.daily_task: asyncio.Task | None = None
        self._original_deep_scan = core._deep_scan

    @staticmethod
    def _epoch() -> float:
        return datetime.now(timezone.utc).timestamp()

    def _load_daily_snapshot(self) -> dict[str, Any]:
        try:
            payload = json.loads(DAILY_FILE.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_daily_snapshot(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        temp = DAILY_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(self.daily_snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temp.replace(DAILY_FILE)

    async def get_pattern(self, symbol: str, exchange: str = "NSE") -> dict[str, Any]:
        key = f"{exchange.upper()}:{symbol.upper()}"
        cached = self.pattern_cache.get(key)
        now = self._epoch()
        if cached and now - cached[0] < PATTERN_TTL_SECONDS:
            return cached[1]
        groww = self.core.get_groww()
        async with self.pattern_semaphore:
            result = await asyncio.to_thread(fetch_six_month_pattern_sync, groww, symbol, exchange)
        self.pattern_cache[key] = (now, result)
        return result

    async def get_news(self, symbol: str) -> dict[str, Any]:
        key = symbol.upper()
        cached = self.news_cache.get(key)
        now = self._epoch()
        if cached and now - cached[0] < NEWS_TTL_SECONDS:
            return cached[1]
        async with self.news_semaphore:
            result = await asyncio.to_thread(fetch_free_news_sync, symbol)
        self.news_cache[key] = (now, result)
        return result

    async def enriched_deep_scan(self, candidate: dict[str, Any]) -> dict[str, Any]:
        result = await self._original_deep_scan(candidate)
        symbol = str(result.get("symbol") or candidate.get("symbol") or "").upper()
        exchange = str(result.get("exchange") or candidate.get("exchange") or "NSE").upper()
        old_recommendation_id = result.get("recommendation_id")

        pattern, news = await asyncio.gather(self.get_pattern(symbol, exchange), self.get_news(symbol))
        result["six_month_pattern"] = pattern
        result["news_check"] = news

        agent_scores = dict(result.get("agent_scores") or {})
        pattern_score = float(pattern.get("score") or 50.0)
        news_agent_score = 50.0 + float(news.get("sentiment") or 0.0) * 45.0
        agent_scores["six_month_pattern"] = round(pattern_score, 2)
        agent_scores["news"] = round(max(0.0, min(100.0, news_agent_score)), 2)
        result["agent_scores"] = agent_scores

        base_confidence = float(result.get("confidence") or 0.0)
        confidence = base_confidence * 0.72 + pattern_score * 0.20 + news_agent_score * 0.08
        confidence = round(max(0.0, min(100.0, confidence)), 2)
        result["confidence"] = confidence

        vetoes = list(result.get("risk_vetoes") or [])
        reasons = list(result.get("reasons") or [])

        if not pattern.get("available"):
            vetoes.append("Six-month historical pattern data is unavailable; a fresh BUY is blocked.")
        elif pattern_score < 40:
            vetoes.append(f"Six-month pattern score {pattern_score:.1f}/100 is too weak for a fresh long trade.")

        severe_pattern_flags = {
            "very_high_realized_volatility",
            "bearish_moving_average_structure",
            "sharp_one_month_decline",
        }
        active_flags = set(pattern.get("risk_flags") or [])
        if active_flags & severe_pattern_flags:
            vetoes.append("Six-month pattern risk flags: " + ", ".join(sorted(active_flags & severe_pattern_flags)) + ".")

        if NEWS_REQUIRED_FOR_BUY and not news.get("available"):
            vetoes.append("Free news-risk check is unavailable; a fresh BUY is blocked until the check completes.")
        if float(news.get("sentiment") or 0.0) <= -0.55:
            vetoes.append("Recent news-risk sentiment is strongly negative.")

        if pattern.get("available"):
            reasons.insert(0, f"Six-month pattern: {pattern.get('label', 'unknown').replace('_', ' ')} at {pattern_score:.1f}/100.")
        if news.get("available"):
            article_count = int(news.get("article_count") or 0)
            reasons.append(
                f"Free news-risk check completed with {article_count} recent headline(s)."
                if article_count
                else "Free news-risk check completed; no recent matching headlines were found."
            )

        result["risk_vetoes"] = list(dict.fromkeys(vetoes))
        result["reasons"] = list(dict.fromkeys(reasons))

        if result["risk_vetoes"]:
            state = "WAIT"
        elif confidence >= self.core.policy.min_buy_confidence:
            state = "BUY"
        elif confidence >= self.core.policy.min_watch_confidence:
            state = "WATCHING"
        else:
            state = "WAIT"
        result["state"] = state
        result["action"] = "BUY" if state == "BUY" else "WAIT"
        result["rank_score"] = round(confidence - len(result["risk_vetoes"]) * 12, 2)
        result["decision_model"] = "agentic-ensemble-v2-six-month-pattern-free-news"
        result["confirmation_layers"] = ["groww_live_market", "groww_180d_history", "free_news_risk_check"]

        if old_recommendation_id:
            self.core.recommendation_cache.pop(old_recommendation_id, None)
        result["recommendation_id"] = self.core._signal_identity(result)
        self.core.recommendation_cache[result["recommendation_id"]] = result
        return result

    async def build_daily_watchlist(self, *, force: bool = False) -> dict[str, Any]:
        async with self.daily_generation_lock:
            now_ist = datetime.now(IST)
            today = now_ist.date().isoformat()
            if not force and self.daily_snapshot.get("generated_for") == today and self.daily_snapshot.get("status") == "ready":
                return self.daily_snapshot

            if not self.core._broker_configured():
                self.daily_snapshot = {
                    "status": "broker_not_configured",
                    "generated_for": today,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "items": [],
                    "message": "Configure Groww credentials in macOS Keychain, then refresh the daily analysis.",
                }
                self._save_daily_snapshot()
                return self.daily_snapshot

            universe = list(dict.fromkeys(self.core.SCANNER_UNIVERSE))
            patterns: list[dict[str, Any]] = []
            for index, symbol in enumerate(universe):
                try:
                    pattern = await self.get_pattern(symbol, "NSE")
                    if pattern.get("available"):
                        patterns.append(pattern)
                except Exception as exc:
                    patterns.append(
                        {
                            "symbol": symbol,
                            "exchange": "NSE",
                            "available": False,
                            "score": 0.0,
                            "label": "error",
                            "risk_flags": [f"{exc.__class__.__name__}"],
                        }
                    )
                if index and index % 5 == 0:
                    await asyncio.sleep(0.2)

            ranked_patterns = sorted(patterns, key=lambda item: float(item.get("score") or 0.0), reverse=True)
            news_candidates = ranked_patterns[:DAILY_NEWS_CANDIDATES]
            items: list[dict[str, Any]] = []
            for pattern in news_candidates:
                symbol = str(pattern.get("symbol") or "")
                news = await self.get_news(symbol)
                news_score = 50.0 + float(news.get("sentiment") or 0.0) * 45.0
                combined = round(float(pattern.get("score") or 0.0) * 0.88 + news_score * 0.12, 2)
                flags = set(pattern.get("risk_flags") or [])
                severe = bool(flags & {"very_high_realized_volatility", "bearish_moving_average_structure", "sharp_one_month_decline"})
                if not news.get("available"):
                    state = "WAIT"
                elif float(news.get("sentiment") or 0.0) <= -0.55 or severe or combined < 45:
                    state = "AVOID"
                elif combined >= 65:
                    state = "WATCH_FOR_LIVE_CONFIRMATION"
                else:
                    state = "WAIT"
                items.append(
                    {
                        "symbol": symbol,
                        "exchange": pattern.get("exchange", "NSE"),
                        "state": state,
                        "daily_score": combined,
                        "six_month_pattern_score": pattern.get("score"),
                        "six_month_pattern_label": pattern.get("label"),
                        "return_20d_pct": pattern.get("return_20d_pct"),
                        "return_60d_pct": pattern.get("return_60d_pct"),
                        "return_120d_pct": pattern.get("return_120d_pct"),
                        "annualized_volatility_pct": pattern.get("annualized_volatility_pct"),
                        "max_drawdown_pct": pattern.get("max_drawdown_pct"),
                        "news_status": news.get("status"),
                        "news_sentiment": news.get("sentiment"),
                        "news_headlines": news.get("headlines", [])[:5],
                        "risk_flags": pattern.get("risk_flags", []),
                        "rule": "Premarket watch only. A live BUY requires current-market revalidation, fresh quote, live risk checks, and human confirmation.",
                    }
                )
                await asyncio.sleep(0.05)

            items.sort(key=lambda item: (item["state"] == "WATCH_FOR_LIVE_CONFIRMATION", item["daily_score"]), reverse=True)
            self.daily_snapshot = {
                "status": "ready",
                "generated_for": today,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "window_days": 180,
                "universe_size": len(universe),
                "items": items[:DAILY_TOP_COUNT],
                "method": "Groww 180-day daily candles + free news-risk check + deterministic multi-agent ranking",
                "disclaimer": "Decision support only. No profit is guaranteed. Premarket watchlist entries are not live BUY instructions.",
            }
            self._save_daily_snapshot()
            return self.daily_snapshot

    async def daily_loop(self) -> None:
        while True:
            try:
                now = datetime.now(IST)
                is_weekday = now.weekday() < 5
                after_generation_time = now.time() >= time(7, 50)
                generated_for = self.daily_snapshot.get("generated_for")
                if is_weekday and after_generation_time and generated_for != now.date().isoformat() and self.core._broker_configured():
                    await self.build_daily_watchlist(force=True)
            except Exception:
                pass
            await asyncio.sleep(60)
