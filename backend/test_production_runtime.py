import asyncio
from types import SimpleNamespace

from memory_store import MemoryStore
from production2_runtime import ProductionRuntime


class FakeCore:
    SCANNER_UNIVERSE = ["TEST"]
    policy = SimpleNamespace(min_buy_confidence=72, min_watch_confidence=58)
    recommendation_cache = {}
    latest_opportunities = {}
    latest_holdings = []
    latest_positions = []
    latest_prices = {}
    latest_market_regime = {"score": 50}

    def __init__(self):
        self._deep_scan = self.base_scan

    async def base_scan(self, candidate):
        scores = {
            "momentum": 82,
            "technical": 80,
            "liquidity": 84,
            "order_flow": 78,
            "market_regime": 75,
            "news": 50,
        }
        return {
            "symbol": candidate["symbol"],
            "exchange": "NSE",
            "state": "BUY",
            "action": "BUY",
            "confidence": 80,
            "rank_score": 80,
            "risk_vetoes": [],
            "reasons": ["base"],
            "agent_scores": scores,
            "entry_price": 100,
            "target_price": 104,
            "stop_loss": 98,
            "last_price": 100,
            "generated_at": "2026-07-14T00:00:00+00:00",
            "recommendation_id": "oldid1234",
        }

    def _signal_identity(self, result):
        return "newid1234"

    def _broker_configured(self):
        return False

    def _holding_symbol(self, item):
        return str(item.get("symbol") or "")

    async def broadcast(self, message):
        return None


def test_enrichment_blends_pattern_and_news(tmp_path):
    core = FakeCore()
    runtime = ProductionRuntime(core, store=MemoryStore(tmp_path / "trader.db"))

    async def pattern(symbol, exchange="NSE"):
        return {"available": True, "score": 80, "label": "strong_uptrend", "risk_flags": []}

    async def news(symbol):
        return {"available": True, "status": "ok", "sentiment": 0.2, "article_count": 2, "headlines": []}

    runtime.get_pattern = pattern
    runtime.get_news = news
    result = asyncio.run(runtime.enriched_deep_scan({"symbol": "TEST", "exchange": "NSE"}))
    assert result["state"] == "BUY"
    assert result["agent_scores"]["six_month_pattern"] == 80
    assert result["decision_model"] == "agentic-ensemble-v3-event-driven-local-memory"
    assert result["confirmation_layers"][-1] == "adaptive_outcome_learning"
