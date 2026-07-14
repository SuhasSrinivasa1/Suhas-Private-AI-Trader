from __future__ import annotations

import asyncio
import json
import os
import time as time_module
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from exit_engine import evaluate_exit_signal
from groww_feed_engine import FeedEvent, GrowwFeedEngine
from memory_store import MemoryStore
from news_provider import _headline_sentiment, fetch_free_news_sync
from ollama_memory import OllamaMemoryClient
from pattern_engine import fetch_six_month_pattern_sync

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / ".runtime"
DAILY_FILE = RUNTIME_DIR / "daily_recommendations.json"
PATTERN_TTL = max(900, int(os.getenv("PATTERN_CACHE_TTL_SECONDS", "21600")))
NEWS_TTL = max(10, int(os.getenv("NEWS_CACHE_TTL_SECONDS", "1200")))
ENABLE_FEED = os.getenv("ENABLE_GROWW_FEED", "true").lower() in {"1", "true", "yes", "on"}
ENABLE_AUTO_LLM = os.getenv("ENABLE_AUTO_LLM", "true").lower() in {"1", "true", "yes", "on"}
ENABLE_SEMANTIC = os.getenv("ENABLE_SEMANTIC_MEMORY", "true").lower() in {"1", "true", "yes", "on"}
NEWS_PRIORITY_SECONDS = max(5, int(os.getenv("NEWS_PRIORITY_INTERVAL_SECONDS", "15")))
NEWS_BROAD_SECONDS = max(30, int(os.getenv("NEWS_BROAD_INTERVAL_SECONDS", "60")))
MATERIAL_MOVE_PCT = max(0.05, float(os.getenv("MATERIAL_PRICE_MOVE_PCT", "0.12")))
RESCAN_COOLDOWN = max(1.0, float(os.getenv("MATERIAL_RESCAN_COOLDOWN_SECONDS", "3")))
PRICE_PERSIST_SECONDS = max(1.0, float(os.getenv("PRICE_PERSIST_INTERVAL_SECONDS", "5")))
BROWSER_TICK_SECONDS = max(0.1, float(os.getenv("BROWSER_TICK_MIN_INTERVAL_SECONDS", "0.25")))
OUTCOME_HORIZONS = tuple(int(v) for v in os.getenv("OUTCOME_HORIZONS_MINUTES", "15,30,60").split(",") if v.strip().isdigit())
DAILY_TOP = max(5, min(20, int(os.getenv("DAILY_TOP_COUNT", "10"))))
DAILY_NEWS = max(5, min(30, int(os.getenv("DAILY_NEWS_CANDIDATES", "18"))))
NEWS_REQUIRED_FOR_BUY = os.getenv("NEWS_REQUIRED_FOR_BUY", "true").lower() in {"1", "true", "yes", "on"}

BASE_WEIGHTS = {
    "momentum": 0.18,
    "technical": 0.17,
    "liquidity": 0.13,
    "order_flow": 0.14,
    "market_regime": 0.12,
    "news": 0.10,
    "six_month_pattern": 0.16,
}


class ProductionRuntime:
    def __init__(self, core: Any, *, store: MemoryStore | None = None) -> None:
        self.core = core
        self.store = store or MemoryStore()
        self.ollama = OllamaMemoryClient()
        self._original_deep_scan = core._deep_scan
        self.pattern_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.news_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.daily_snapshot = self._load_daily()
        self.daily_generation_lock = asyncio.Lock()
        self.feed_engine: GrowwFeedEngine | None = None
        self.feed_queue: asyncio.Queue[FeedEvent] = asyncio.Queue(maxsize=5000)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: list[asyncio.Task] = []
        self._last_tick: dict[str, float] = {}
        self._last_persist: dict[str, float] = {}
        self._last_browser_tick: dict[str, float] = {}
        self._last_rescan: dict[str, float] = {}
        self._last_signal_state: dict[str, str] = {}
        self._last_feed_attempt = 0.0
        self._feed_start_attempted = False
        self._news_rotation = 0
        self._last_broad_news = 0.0
        self._latest_exits: list[dict[str, Any]] = []
        self.daily_task: asyncio.Task | None = None

    @staticmethod
    def _epoch() -> float:
        return datetime.now(timezone.utc).timestamp()

    def _load_daily(self) -> dict[str, Any]:
        try:
            data = json.loads(DAILY_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_daily(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        temp = DAILY_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(self.daily_snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temp.replace(DAILY_FILE)

    async def start_background_services(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._tasks = [
            asyncio.create_task(self.feed_event_loop(), name="prod2-feed-events"),
            asyncio.create_task(self.news_loop(), name="prod2-news"),
            asyncio.create_task(self.outcome_loop(), name="prod2-outcomes"),
            asyncio.create_task(self.exit_loop(), name="prod2-exits"),
            asyncio.create_task(self.health_loop(), name="prod2-health"),
        ]
        asyncio.create_task(self.ensure_feed_started(), name="prod2-feed-start")

    async def stop_background_services(self) -> None:
        if self.feed_engine:
            self.feed_engine.stop()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    async def ensure_feed_started(self) -> bool:
        if not ENABLE_FEED or not self.core._broker_configured():
            return False
        if self.feed_engine and self.feed_engine.status().get("running"):
            return True
        now = time_module.monotonic()
        if self._feed_start_attempted and now - self._last_feed_attempt < 60:
            return False
        self._feed_start_attempted = True
        self._last_feed_attempt = now
        try:
            self.feed_engine = GrowwFeedEngine(self.core.get_groww(), list(self.core.SCANNER_UNIVERSE)[:1000], self._feed_callback)
            started = await asyncio.to_thread(self.feed_engine.start)
            self.store.update_provider_health("groww_feed", ok=started, message="Live Groww Feed subscribed." if started else (self.feed_engine.last_error or "Feed did not start."))
            return started
        except Exception as exc:
            self.store.update_provider_health("groww_feed", ok=False, message=f"{exc.__class__.__name__}: feed startup failed")
            return False

    def _feed_callback(self, event: FeedEvent) -> None:
        if self._loop is None:
            return

        def enqueue() -> None:
            try:
                self.feed_queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    self.feed_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self.feed_queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

        self._loop.call_soon_threadsafe(enqueue)

    async def feed_event_loop(self) -> None:
        while True:
            event = await self.feed_queue.get()
            try:
                await self._handle_feed_event(event)
            finally:
                self.feed_queue.task_done()

    async def _handle_feed_event(self, event: FeedEvent) -> None:
        now = time_module.monotonic()
        key = f"{event.exchange}:{event.symbol}"
        previous = self._last_tick.get(key)
        self._last_tick[key] = event.price
        ts = datetime.fromtimestamp(event.ts_ms / 1000, tz=timezone.utc).isoformat()
        self.core.latest_prices[key] = {"ltp": event.price, "last_price": event.price, "ts": ts, "source": event.source}
        self.store.update_provider_health("groww_feed", ok=True, message="Receiving callback market events.")
        if now - self._last_persist.get(key, 0) >= PRICE_PERSIST_SECONDS:
            self.store.store_price(event.symbol, event.exchange, event.price, event.source, ts)
            self._last_persist[key] = now
        if now - self._last_browser_tick.get(key, 0) >= BROWSER_TICK_SECONDS:
            await self.core.broadcast({"type": "market_tick", "symbol": event.symbol, "exchange": event.exchange, "price": event.price, "ts": ts})
            self._last_browser_tick[key] = now
        move_pct = abs((event.price - previous) / previous * 100) if previous else 0.0
        if previous and move_pct >= MATERIAL_MOVE_PCT and now - self._last_rescan.get(key, 0) >= RESCAN_COOLDOWN:
            self._last_rescan[key] = now
            asyncio.create_task(self.rescan_symbol(event.symbol, reason=f"material_price_move_{move_pct:.3f}pct"))

    def active_symbols(self) -> list[str]:
        symbols: list[str] = []
        for item in self.core.latest_opportunities.values():
            if item.get("state") in {"BUY", "WATCHING"} and item.get("symbol"):
                symbols.append(str(item["symbol"]).upper())
        for item in self.daily_snapshot.get("items") or []:
            if item.get("state") == "WATCH_FOR_LIVE_CONFIRMATION" and item.get("symbol"):
                symbols.append(str(item["symbol"]).upper())
        for item in self.core.latest_holdings + self.core.latest_positions:
            symbol = self.core._holding_symbol(item)
            if symbol:
                symbols.append(symbol.upper())
        return list(dict.fromkeys(symbols))

    async def rescan_symbol(self, symbol: str, *, reason: str) -> None:
        try:
            result = await self.enriched_deep_scan({"symbol": symbol.upper(), "exchange": "NSE", "coarse_score": 0})
            self.core.latest_opportunities[f"NSE:{symbol.upper()}"] = result
            await self.core.broadcast({"type": "opportunities", "items": list(self.core.latest_opportunities.values()), "prices": self.core.latest_prices, "market_regime": self.core.latest_market_regime, "scan_at": self.core._now().isoformat()})
            previous = self._last_signal_state.get(symbol.upper())
            current = str(result.get("state") or "WAIT")
            self._last_signal_state[symbol.upper()] = current
            if previous and previous != current:
                event_key = f"signal:{symbol.upper()}:{previous}:{current}:{result.get('recommendation_id')}"
                await self.core.broadcast({"type": "signal_change", "symbol": symbol.upper(), "previous": previous, "current": current, "reason": reason, "ts": self.core._now().isoformat()})
                asyncio.create_task(self.trigger_llm_analysis(symbol=symbol, event_type="signal_change", event_key=event_key, payload={"reason": reason, "opportunity": result}))
        except Exception as exc:
            self.store.update_provider_health("event_rescan", ok=False, message=f"{exc.__class__.__name__}: {symbol} rescan failed")

    async def get_pattern(self, symbol: str, exchange: str = "NSE", *, force: bool = False) -> dict[str, Any]:
        key = f"{exchange.upper()}:{symbol.upper()}"
        now = self._epoch()
        cached = self.pattern_cache.get(key)
        if not force and cached and now - cached[0] < PATTERN_TTL:
            return cached[1]
        if not force:
            stored = self.store.latest_pattern(symbol, exchange)
            if stored and str(stored.get("as_of_date") or "") == datetime.now(timezone.utc).date().isoformat():
                self.pattern_cache[key] = (now, stored)
                return stored
        started = time_module.monotonic()
        try:
            result = await asyncio.to_thread(fetch_six_month_pattern_sync, self.core.get_groww(), symbol, exchange)
            self.pattern_cache[key] = (now, result)
            self.store.store_pattern(result)
            self.store.update_provider_health("groww_history", ok=True, latency_ms=(time_module.monotonic() - started) * 1000, message="180-day candle analysis available.")
            return result
        except Exception as exc:
            self.store.update_provider_health("groww_history", ok=False, latency_ms=(time_module.monotonic() - started) * 1000, message=f"{exc.__class__.__name__}: historical analysis unavailable")
            raise

    async def get_news(self, symbol: str, *, force: bool = False) -> dict[str, Any]:
        symbol = symbol.upper()
        now = self._epoch()
        cached = self.news_cache.get(symbol)
        if not force and cached and now - cached[0] < NEWS_TTL:
            return cached[1]
        started = time_module.monotonic()
        result = await asyncio.to_thread(fetch_free_news_sync, symbol)
        self.news_cache[symbol] = (now, result)
        self.store.update_provider_health("free_news", ok=bool(result.get("available")), latency_ms=(time_module.monotonic() - started) * 1000, message=str(result.get("status") or result.get("error") or "news check completed"))
        new_items = self.store.store_news_result(result, _headline_sentiment)
        for item in new_items:
            if ENABLE_SEMANTIC:
                asyncio.create_task(self._embed_article(item))
        if new_items:
            await self.core.broadcast({"type": "news_event", "symbol": symbol, "new_count": len(new_items), "headlines": new_items[:5], "sentiment": result.get("sentiment", 0), "ts": self.core._now().isoformat()})
        return result | {"new_articles": new_items}

    async def _embed_article(self, item: dict[str, Any]) -> None:
        try:
            vector = await asyncio.to_thread(self.ollama.embed, f"{item.get('title','')}\n{item.get('source','')}")
            self.store.store_embedding(str(item["article_id"]), self.ollama.embedding_model, vector)
            self.store.update_provider_health("ollama_embeddings", ok=True, message="Local semantic news memory active.")
        except Exception as exc:
            self.store.update_provider_health("ollama_embeddings", ok=False, message=f"{exc.__class__.__name__}: embedding unavailable")

    async def trigger_llm_analysis(self, *, symbol: str, event_type: str, event_key: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not ENABLE_AUTO_LLM or self.store.has_llm_event(event_key):
            return None
        similar: list[dict[str, Any]] = []
        try:
            if ENABLE_SEMANTIC and symbol != "MARKET":
                seed = json.dumps(payload, ensure_ascii=False, default=str)[:5000]
                vector = await asyncio.to_thread(self.ollama.embed, seed)
                similar = self.store.similar_news(vector, symbol=symbol, limit=5)
            system = (
                "You are the private local advisory analyst for Suhas Private AI Trader. "
                "Use only supplied evidence. Never invent live prices or news. Never ask for or expose broker secrets. "
                "Never override deterministic risk vetoes or execute orders. State the strongest evidence, contradictions, risks, and invalidation conditions."
            )
            analysis = await asyncio.to_thread(self.ollama.analyze, system=system, payload={"event_type": event_type, "symbol": symbol, "snapshot": payload, "similar_local_news": similar})
            item = self.store.store_llm_analysis(symbol=None if symbol == "MARKET" else symbol, event_type=event_type, event_key=event_key, model=self.ollama.chat_model, analysis=analysis, payload=payload)
            self.store.update_provider_health("ollama_chat", ok=True, message="Automatic local material-event analysis active.")
            await self.core.broadcast({"type": "llm_analysis", "item": item, "ts": item["created_at"]})
            return item
        except Exception as exc:
            self.store.update_provider_health("ollama_chat", ok=False, message=f"{exc.__class__.__name__}: local analysis unavailable")
            return None

    def _adaptive_confidence(self, scores: dict[str, Any]) -> float:
        multipliers = self.store.agent_weight_multipliers()
        weighted = 0.0
        total = 0.0
        for agent, base_weight in BASE_WEIGHTS.items():
            if agent not in scores:
                continue
            multiplier = max(0.75, min(1.25, float(multipliers.get(agent, 1.0))))
            weight = base_weight * multiplier
            weighted += float(scores.get(agent) or 50) * weight
            total += weight
        return weighted / total if total else 50.0

    async def enriched_deep_scan(self, candidate: dict[str, Any]) -> dict[str, Any]:
        result = await self._original_deep_scan(candidate)
        symbol = str(result.get("symbol") or candidate.get("symbol") or "").upper()
        pattern, news = await asyncio.gather(self.get_pattern(symbol), self.get_news(symbol))
        scores = dict(result.get("agent_scores") or {})
        scores["six_month_pattern"] = float(pattern.get("score") or 50)
        scores["news"] = max(0.0, min(100.0, 50.0 + float(news.get("sentiment") or 0) * 35.0)) if news.get("available") else 50.0
        result["agent_scores"] = scores
        confidence = round(self._adaptive_confidence(scores), 2)
        result["confidence"] = confidence
        result["rank_score"] = confidence
        result["six_month_pattern"] = pattern
        result["news_context"] = news
        result["decision_model"] = "agentic-ensemble-v3-event-driven-local-memory"
        result["confirmation_layers"] = ["groww_live_or_feed", "groww_180_day_history", "continuous_free_news_memory", "adaptive_outcome_learning"]
        vetoes = list(result.get("risk_vetoes") or [])
        if not pattern.get("available") or float(pattern.get("score") or 0) < 45:
            vetoes.append("six_month_pattern_not_supportive")
        if NEWS_REQUIRED_FOR_BUY and not news.get("available"):
            vetoes.append("current_news_check_unavailable")
        if news.get("available") and float(news.get("sentiment") or 0) <= -0.65:
            vetoes.append("strong_negative_news")
        result["risk_vetoes"] = list(dict.fromkeys(vetoes))
        if result["risk_vetoes"] or confidence < self.core.policy.min_watch_confidence:
            result["state"] = "WAIT"
            result["action"] = "WAIT"
        elif confidence >= self.core.policy.min_buy_confidence:
            result["state"] = "BUY"
            result["action"] = "BUY"
        else:
            result["state"] = "WATCHING"
            result["action"] = "WATCH"
        result["recommendation_id"] = self.core._signal_identity(result)
        self.core.recommendation_cache[result["recommendation_id"]] = result
        is_new = self.store.record_signal(result)
        previous = self._last_signal_state.get(symbol)
        self._last_signal_state[symbol] = str(result.get("state") or "WAIT")
        if is_new and result.get("state") == "BUY" and previous != "BUY":
            asyncio.create_task(self.trigger_llm_analysis(symbol=symbol, event_type="buy_candidate", event_key=f"buy:{result['recommendation_id']}", payload={"opportunity": result}))
        return result

    async def news_loop(self) -> None:
        while True:
            try:
                priority = self.active_symbols()[:8]
                for symbol in priority:
                    result = await self.get_news(symbol, force=True)
                    if result.get("new_articles"):
                        asyncio.create_task(self.rescan_symbol(symbol, reason="new_material_news"))
                        asyncio.create_task(self.trigger_llm_analysis(symbol=symbol, event_type="news_event", event_key=f"news:{symbol}:{result['new_articles'][0]['article_id']}", payload={"news": result}))
                    await asyncio.sleep(0)
                now = time_module.monotonic()
                if now - self._last_broad_news >= NEWS_BROAD_SECONDS:
                    universe = list(self.core.SCANNER_UNIVERSE)
                    batch = universe[self._news_rotation:self._news_rotation + 5]
                    if not batch:
                        self._news_rotation = 0
                        batch = universe[:5]
                    self._news_rotation = (self._news_rotation + len(batch)) % max(1, len(universe))
                    self._last_broad_news = now
                    for symbol in batch:
                        await self.get_news(symbol, force=True)
            except Exception as exc:
                self.store.update_provider_health("news_loop", ok=False, message=f"{exc.__class__.__name__}: news loop iteration failed")
            await asyncio.sleep(NEWS_PRIORITY_SECONDS)

    async def outcome_loop(self) -> None:
        while True:
            try:
                for horizon in OUTCOME_HORIZONS:
                    for signal in self.store.due_signals(horizon):
                        symbol = str(signal.get("symbol") or "")
                        price = float((self.core.latest_prices.get(f"NSE:{symbol}") or {}).get("last_price") or 0)
                        if price <= 0 and self.core._broker_configured():
                            quote = await self.core._quote(symbol, "NSE")
                            price = self.core._f(quote.get("last_price"))
                        if price > 0:
                            outcome = self.store.record_outcome(signal, horizon, price)
                            if outcome:
                                await self.core.broadcast({"type": "outcome_update", "item": outcome, "ts": self.core._now().isoformat()})
            except Exception:
                pass
            await asyncio.sleep(60)

    async def exit_loop(self) -> None:
        while True:
            signals: list[dict[str, Any]] = []
            try:
                merged: dict[str, dict[str, Any]] = {}
                for item in self.core.latest_holdings + self.core.latest_positions:
                    symbol = self.core._holding_symbol(item)
                    if not symbol:
                        continue
                    qty = float(item.get("quantity") or item.get("qty") or item.get("net_quantity") or 0)
                    avg = float(item.get("average_price") or item.get("averagePrice") or item.get("avg_price") or item.get("net_price") or 0)
                    if qty <= 0 or avg <= 0:
                        continue
                    current = merged.setdefault(symbol, {"quantity": 0.0, "cost": 0.0})
                    current["quantity"] += qty
                    current["cost"] += qty * avg
                for symbol, position in merged.items():
                    price = float((self.core.latest_prices.get(f"NSE:{symbol}") or {}).get("last_price") or 0)
                    if price <= 0:
                        continue
                    average = position["cost"] / position["quantity"]
                    pattern = await self.get_pattern(symbol)
                    news = await self.get_news(symbol)
                    signal = evaluate_exit_signal(symbol=symbol, quantity=position["quantity"], average_price=average, current_price=price, pattern=pattern, news=news)
                    signals.append(signal)
                    if signal["action"] != "HOLD":
                        self.store.store_exit_signal(signal)
                self._latest_exits = signals
                await self.core.broadcast({"type": "exit_signals", "items": signals, "ts": self.core._now().isoformat()})
            except Exception:
                pass
            await asyncio.sleep(30)

    def latest_exit_signals(self) -> list[dict[str, Any]]:
        return list(self._latest_exits)

    async def build_daily_watchlist(self, *, force: bool = False) -> dict[str, Any]:
        async with self.daily_generation_lock:
            today = datetime.now(IST).date().isoformat()
            if not force and self.daily_snapshot.get("generated_for") == today:
                return self.daily_snapshot
            universe = list(self.core.SCANNER_UNIVERSE)
            patterns: list[dict[str, Any]] = []
            for symbol in universe:
                try:
                    pattern = await self.get_pattern(symbol, force=force)
                    if pattern.get("available"):
                        patterns.append(pattern)
                except Exception:
                    continue
            patterns.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
            items: list[dict[str, Any]] = []
            for pattern in patterns[:DAILY_NEWS]:
                symbol = str(pattern.get("symbol") or "")
                news = await self.get_news(symbol, force=force)
                score = float(pattern.get("score") or 0) + float(news.get("sentiment") or 0) * 10
                state = "WATCH_FOR_LIVE_CONFIRMATION" if score >= 65 and news.get("available") and float(news.get("sentiment") or 0) > -0.65 else "WAIT"
                items.append({
                    "symbol": symbol,
                    "state": state,
                    "daily_score": round(score, 2),
                    "pattern_score": pattern.get("score"),
                    "pattern_label": pattern.get("label"),
                    "news_sentiment": news.get("sentiment"),
                    "news_headlines": news.get("headlines", [])[:5],
                    "risk_flags": pattern.get("risk_flags", []),
                    "rule": "Watch only. A live BUY requires event-driven current-market revalidation and human confirmation.",
                })
            items.sort(key=lambda item: (item["state"] == "WATCH_FOR_LIVE_CONFIRMATION", item["daily_score"]), reverse=True)
            self.daily_snapshot = {
                "status": "ready",
                "generated_for": today,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "window_days": 180,
                "universe_size": len(universe),
                "items": items[:DAILY_TOP],
                "method": "Groww 180-day candles + local SQLite cache + continuous free news memory + deterministic multi-agent ranking",
                "disclaimer": "Decision support only. No profit is guaranteed. Premarket watchlist entries are not live BUY instructions.",
            }
            self._save_daily()
            await self.core.broadcast({"type": "daily_watchlist", "snapshot": self.daily_snapshot, "ts": self.daily_snapshot["generated_at"]})
            asyncio.create_task(self.trigger_llm_analysis(symbol="MARKET", event_type="daily_watchlist", event_key=f"daily:{today}", payload={"daily_watchlist": self.daily_snapshot}))
            return self.daily_snapshot

    async def daily_loop(self) -> None:
        while True:
            try:
                now = datetime.now(IST)
                if now.weekday() < 5 and now.time() >= time(7, 50) and self.daily_snapshot.get("generated_for") != now.date().isoformat() and self.core._broker_configured():
                    await self.build_daily_watchlist(force=False)
            except Exception:
                pass
            await asyncio.sleep(60)

    async def health_loop(self) -> None:
        last_prune: str | None = None
        last_backup: str | None = None
        while True:
            try:
                if self.core._broker_configured() and not (self.feed_engine and self.feed_engine.status().get("running")):
                    await self.ensure_feed_started()
                today = datetime.now(IST).date().isoformat()
                if today != last_prune:
                    self.store.prune(
                        price_retention_days=max(1, int(os.getenv("PRICE_RETENTION_DAYS", "30"))),
                        news_retention_days=max(30, int(os.getenv("NEWS_RETENTION_DAYS", "365"))),
                        llm_retention_days=max(30, int(os.getenv("LLM_RETENTION_DAYS", "180"))),
                    )
                    last_prune = today
                if datetime.now(IST).time() >= time(16, 0) and today != last_backup:
                    backup_path = await asyncio.to_thread(self.store.backup)
                    self.store.update_provider_health("local_memory_backup", ok=True, message=f"Daily SQLite backup: {backup_path}")
                    last_backup = today
                await self.core.broadcast({"type": "provider_health", "items": self.store.provider_health(), "feed": self.feed_engine.status() if self.feed_engine else {"running": False}, "ts": datetime.now(timezone.utc).isoformat()})
            except Exception:
                pass
            await asyncio.sleep(30)

    def status(self) -> dict[str, Any]:
        return {
            "feed": self.feed_engine.status() if self.feed_engine else {"running": False, "subscribed_count": 0, "last_event_at": None, "last_error": None},
            "memory": self.store.stats(),
            "provider_health": self.store.provider_health(),
            "agent_stats": self.store.agent_stats(),
            "auto_llm_enabled": ENABLE_AUTO_LLM,
            "semantic_memory_enabled": ENABLE_SEMANTIC,
            "continuous_news_enabled": True,
            "news_priority_interval_seconds": NEWS_PRIORITY_SECONDS,
            "news_broad_interval_seconds": NEWS_BROAD_SECONDS,
            "material_price_move_pct": MATERIAL_MOVE_PCT,
        }
