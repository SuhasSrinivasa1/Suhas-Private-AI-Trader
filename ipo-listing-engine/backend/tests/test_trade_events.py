from pathlib import Path

from app.trade_events import TradeEventStore


def test_trade_event_store_is_ordered_and_durable(tmp_path: Path):
    path = tmp_path / "events.sqlite3"
    store = TradeEventStore(path)
    first = store.publish(
        event_type="ORDER_PLACING",
        symbol="abc",
        side="buy",
        quantity=10,
        price=100.5,
        message="placing",
    )
    second = store.publish(
        event_type="ORDER_EXECUTED",
        symbol="ABC",
        side="BUY",
        quantity=10,
        price=101.0,
        order_id="G123",
        message="done",
    )

    assert second.id > first.id
    rows = TradeEventStore(path).after(first.id)
    assert len(rows) == 1
    assert rows[0].event_type == "ORDER_EXECUTED"
    assert rows[0].symbol == "ABC"
    assert rows[0].order_id == "G123"
