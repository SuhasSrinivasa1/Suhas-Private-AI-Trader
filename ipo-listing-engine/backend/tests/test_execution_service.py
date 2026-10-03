from types import SimpleNamespace

import pytest

from app.execution_service import ExecutionRequest, GrowwExecutionService
from app.live_state import LiveState


class FakeGroww:
    VALIDITY_DAY = "DAY"
    EXCHANGE_NSE = "NSE"
    SEGMENT_CASH = "CASH"
    PRODUCT_MIS = "MIS"
    PRODUCT_CNC = "CNC"
    ORDER_TYPE_MARKET = "MARKET"
    ORDER_TYPE_LIMIT = "LIMIT"
    ORDER_TYPE_STOP_LOSS = "SL"
    ORDER_TYPE_STOP_LOSS_MARKET = "SL_M"
    TRANSACTION_TYPE_BUY = "BUY"
    TRANSACTION_TYPE_SELL = "SELL"

    def __init__(self):
        self.placed = []

    def get_instrument_by_exchange_and_trading_symbol(self, **kwargs):
        return {
            "exchange": "NSE",
            "segment": "CASH",
            "trading_symbol": kwargs["trading_symbol"],
            "lot_size": 1,
            "buy_allowed": 1,
            "sell_allowed": 1,
        }

    def get_quote(self, **kwargs):
        return {"last_price": 100.0}

    def place_order(self, **kwargs):
        self.placed.append(kwargs)
        return {"groww_order_id": "G123", "order_status": "OPEN"}

    def get_order_status(self, **kwargs):
        return {
            "groww_order_id": "G123",
            "order_status": "EXECUTED",
            "filled_quantity": 10,
            "average_fill_price": 101.5,
        }


def test_submit_requires_live_enabled(monkeypatch):
    monkeypatch.setattr("app.execution_service.live_state_store.load", lambda: LiveState(enabled=False))
    service = GrowwExecutionService()
    with pytest.raises(RuntimeError):
        service.submit(ExecutionRequest("ABC", "BUY", 1, "CNC", "MARKET"))


def test_submit_routes_order_when_live_enabled(monkeypatch):
    fake = FakeGroww()
    monkeypatch.setattr(
        "app.execution_service.live_state_store.load",
        lambda: LiveState(enabled=True, budget_rupees=100000),
    )
    monkeypatch.setattr(
        GrowwExecutionService,
        "_session",
        lambda self: SimpleNamespace(api=fake),
    )
    monkeypatch.setattr("app.execution_service.order_events.publish", lambda *args, **kwargs: None)

    service = GrowwExecutionService()
    result = service.submit(ExecutionRequest("ABC", "BUY", 10, "CNC", "LIMIT", price=100.0))
    assert result["groww_order_id"] == "G123"
    assert fake.placed[0]["trading_symbol"] == "ABC"
    assert fake.placed[0]["quantity"] == 10


def test_reconcile_emits_fill(monkeypatch):
    fake = FakeGroww()
    published = []
    monkeypatch.setattr(
        GrowwExecutionService,
        "_session",
        lambda self: SimpleNamespace(api=fake),
    )
    monkeypatch.setattr(
        "app.execution_service.order_events.publish",
        lambda event_type, **kwargs: published.append((event_type, kwargs)),
    )

    service = GrowwExecutionService()
    service.reconcile_order(
        groww_order_id="G123",
        symbol="ABC",
        side="BUY",
        quantity=10,
    )
    assert published[-1][0] == "ORDER_FILLED"
    assert published[-1][1]["price"] == 101.5


def test_submit_blocks_order_above_budget(monkeypatch):
    fake = FakeGroww()
    monkeypatch.setattr(
        "app.execution_service.live_state_store.load",
        lambda: LiveState(enabled=True, budget_rupees=10_000),
    )
    monkeypatch.setattr(
        GrowwExecutionService,
        "_session",
        lambda self: SimpleNamespace(api=fake),
    )
    service = GrowwExecutionService()
    with pytest.raises(RuntimeError, match="exceeds live budget"):
        service.submit(ExecutionRequest("ABC", "BUY", 101, "CNC", "MARKET"))


def test_submit_blocks_fresh_short_without_shortability(monkeypatch):
    fake = FakeGroww()
    monkeypatch.setattr(
        "app.execution_service.live_state_store.load",
        lambda: LiveState(enabled=True, budget_rupees=100_000),
    )
    monkeypatch.setattr(
        GrowwExecutionService,
        "_session",
        lambda self: SimpleNamespace(api=fake),
    )
    service = GrowwExecutionService()
    with pytest.raises(RuntimeError, match="short is not confirmed eligible"):
        service.submit(ExecutionRequest("ABC", "SELL", 10, "MIS", "MARKET", shortable=False))
