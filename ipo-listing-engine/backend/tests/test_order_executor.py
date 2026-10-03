from pathlib import Path

import app.order_executor as order_executor_module
from app.order_events import OrderEventStore
from app.order_executor import GrowwOrderExecutor


class FakeApi:
    VALIDITY_DAY = "DAY"
    EXCHANGE_NSE = "NSE"
    SEGMENT_CASH = "CASH"

    def __init__(self):
        self.status = "OPEN"

    def place_order(self, **kwargs):
        return {
            "groww_order_id": "G123",
            "order_status": "OPEN",
            "order_reference_id": kwargs["order_reference_id"],
        }

    def get_order_status(self, **kwargs):
        return {
            "groww_order_id": kwargs["groww_order_id"],
            "order_status": self.status,
            "filled_quantity": 10 if self.status == "EXECUTED" else 0,
        }


class FakeSession:
    def __init__(self):
        self.api = FakeApi()


def test_executor_emits_place_accept_and_fill(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("IPO_SENTINEL_ORDER_EVENT_FILE", str(tmp_path / "orders.jsonl"))
    store = OrderEventStore()
    monkeypatch.setattr(order_executor_module, "order_events", store)

    session = FakeSession()
    executor = GrowwOrderExecutor(session)

    executor.submit(
        trading_symbol="ABC",
        quantity=10,
        transaction_type="BUY",
        product="CNC",
        order_type="MARKET",
    )
    session.api.status = "EXECUTED"
    executor.refresh_status(
        groww_order_id="G123",
        symbol="ABC",
        side="BUY",
        quantity=10,
    )

    assert [event.event_type for event in store.after(0)] == [
        "ORDER_PLACING",
        "ORDER_ACCEPTED",
        "ORDER_FILLED",
    ]
