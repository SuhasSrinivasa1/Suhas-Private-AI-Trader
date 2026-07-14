from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from call_results import CallResultsEngine
from memory_store import MemoryStore


class FakeCore:
    latest_prices = {}

    @staticmethod
    def _broker_configured():
        return False

    @staticmethod
    async def broadcast(_message):
        return None


class FakeOverlay:
    mode = "intraday"


def make_engine(tmp_path):
    store = MemoryStore(tmp_path / "trader.db")
    runtime = SimpleNamespace(store=store)
    return CallResultsEngine(FakeCore(), runtime, FakeOverlay())


def prediction(symbol: str, recommendation_id: str, confidence: float = 82.0):
    return {
        "recommendation_id": recommendation_id,
        "symbol": symbol,
        "exchange": "NSE",
        "state": "BUY",
        "action": "BUY",
        "trading_mode": "intraday",
        "entry_price": 100.0,
        "target_price": 103.0,
        "stop_loss": 98.0,
        "confidence": confidence,
        "agent_consensus_score": 80.0,
        "decision_model": "test",
        "specialist_agents": {"macd": {"score": 80}, "risk_veto": {"score": 100}},
    }


def test_paper_call_target_before_stop_is_correct(tmp_path):
    engine = make_engine(tmp_path)
    item = engine.record_prediction(prediction("AAA", "rec-a"))
    assert item and item["status"] == "OPEN"
    resolved = engine.observe_price(item["id"], 103.1)
    assert resolved and resolved["status"] == "CORRECT"
    summary = engine.summary()
    assert summary["correct_calls"] == 1
    assert summary["wrong_calls"] == 0
    assert summary["accuracy_pct"] == 100.0


def test_paper_call_stop_before_target_is_wrong(tmp_path):
    engine = make_engine(tmp_path)
    item = engine.record_prediction(prediction("BBB", "rec-b"))
    resolved = engine.observe_price(item["id"], 97.9)
    assert resolved and resolved["status"] == "WRONG"
    assert "stop_reached" in resolved["result_reason"]


def test_expired_unresolved_call_is_wrong_not_silently_correct(tmp_path):
    engine = make_engine(tmp_path)
    item = engine.record_prediction(prediction("CCC", "rec-c"))
    with engine.store._lock, engine.store.connect() as connection:
        connection.execute(
            "UPDATE paper_calls SET evaluation_deadline=? WHERE id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), item["id"]),
        )
    resolved = engine.observe_price(item["id"], 101.0)
    assert resolved and resolved["status"] == "WRONG"
    assert "expired" in resolved["result_reason"]


def test_first_week_is_paper_only_and_99_is_not_guaranteed(tmp_path):
    engine = make_engine(tmp_path)
    observation = engine.observation_status()
    learning = engine.learning_profile()
    assert observation["paper_calls_only"] is True
    assert observation["live_orders_blocked"] is True
    assert learning["target_precision_pct"] == 99.0
    assert learning["target_is_guaranteed"] is False
    assert learning["recommended_min_confidence"] >= 72
