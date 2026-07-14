from memory_store import MemoryStore


def test_news_deduplication_and_semantic_similarity(tmp_path):
    store = MemoryStore(tmp_path / "trader.db")
    result = {
        "symbol": "TEST",
        "headlines": [
            {"title": "Company wins major contract", "url": "https://example.com/a", "source": "example.com", "published": "now"},
            {"title": "Company wins major contract", "url": "https://example.com/a", "source": "example.com", "published": "now"},
        ],
    }
    sentiment = lambda title: 1.0 if "wins" in title else 0.0
    new_items = store.store_news_result(result, sentiment)
    assert len(new_items) == 1
    assert store.store_news_result(result, sentiment) == []
    store.store_embedding(new_items[0]["article_id"], "test-embed", [1.0, 0.0, 0.0])
    similar = store.similar_news([0.9, 0.1, 0.0], symbol="TEST")
    assert similar[0]["title"] == "Company wins major contract"
    assert similar[0]["similarity"] > 0.9


def test_outcomes_create_bounded_adaptive_weights(tmp_path):
    store = MemoryStore(tmp_path / "trader.db")
    for index in range(12):
        signal = {
            "recommendation_id": f"signal-{index:03d}",
            "symbol": "TEST",
            "exchange": "NSE",
            "state": "BUY",
            "action": "BUY",
            "generated_at": "2026-07-14T00:00:00+00:00",
            "entry_price": 100,
            "target_price": 105,
            "stop_loss": 98,
            "last_price": 100,
            "confidence": 80,
            "agent_scores": {"momentum": 80, "news": 20},
        }
        assert store.record_signal(signal)
        row = store.due_signals(0)[0]
        store.record_outcome(row, index + 1, 102)
    multipliers = store.agent_weight_multipliers()
    assert 0.75 <= multipliers["momentum"] <= 1.25
    assert 0.75 <= multipliers["news"] <= 1.25
    assert multipliers["momentum"] > multipliers["news"]
