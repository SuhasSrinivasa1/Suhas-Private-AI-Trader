from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

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
            "isin": "INE123456789",
            "exchange_token": "123",
            "lot_size": 1,
            "buy_allowed": 1,
            "sell_allowed": 1,
        }

    def get_quote(self, **kwargs):
        return {
            "last_price": 100.0,
            "depth": {
                "buy": [{"price": 99.9, "quantity": 1000}],
                "sell": [{"price": 100.1, "quantity": 1000}],
            },
        }

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


IST = ZoneInfo("Asia/Kolkata")


def arm_execution_safety(monkeypatch, service: GrowwExecutionService) -> None:
    fixed_now = datetime(2026, 10, 5, 10, 1, tzinfo=IST)
    monkeypatch.setattr(service, "_now", lambda: fixed_now)
    monkeypatch.setattr(service, "_require_current_static_ip", lambda: None)
    candidate = {
        "symbol": "ABC",
        "isin": "INE123456789",
        "listing_date": "2026-10-05",
        "nse_listing_confirmed": True,
        "symbol_resolved": True,
        "groww_resolution_status": "RESOLVED",
        "groww_exchange_token": "123",
    }
    plan = {"calendar_holidays": [], "calendar_ready": True}
    monkeypatch.setattr(service, "_authorized_candidate", lambda symbol, now: (candidate, plan))


def safe_request(*, side: str = "BUY", quantity: int = 10, budget_price: float | None = None, shortable: bool = False):
    return ExecutionRequest(
        "ABC",
        side,
        quantity,
        "MIS" if side == "SELL" else "CNC",
        "LIMIT" if budget_price else "MARKET",
        price=budget_price,
        shortable=shortable,
        liquidity_sufficient=True,
        spread_bps=20.0,
        estimated_impact_bps=15.0,
        circuit_state_acceptable=True,
        position_reconciled=True,
        order_state_known=True,
        position_isolation_ok=True,
    )


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
    arm_execution_safety(monkeypatch, service)
    result = service.submit(safe_request(quantity=10, budget_price=100.0))
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
    arm_execution_safety(monkeypatch, service)
    with pytest.raises(RuntimeError, match="exceeds live budget"):
        service.submit(safe_request(quantity=101))


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
    arm_execution_safety(monkeypatch, service)
    with pytest.raises(RuntimeError, match="short is not confirmed eligible"):
        service.submit(safe_request(side="SELL", quantity=10, shortable=False))


def test_submit_blocks_when_depth_is_missing(monkeypatch):
    fake = FakeGroww()
    fake.get_quote = lambda **kwargs: {"last_price": 100.0}
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
    arm_execution_safety(monkeypatch, service)
    with pytest.raises(RuntimeError, match="WAIT_MARKET_DEPTH"):
        service.submit(safe_request(quantity=10))


def test_submit_blocks_if_authoritative_isin_disagrees(monkeypatch):
    fake = FakeGroww()
    original = fake.get_instrument_by_exchange_and_trading_symbol
    def mismatched(**kwargs):
        row = original(**kwargs)
        row["isin"] = "INE000000001"
        return row
    fake.get_instrument_by_exchange_and_trading_symbol = mismatched
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
    arm_execution_safety(monkeypatch, service)
    with pytest.raises(RuntimeError, match="ISIN does not exactly match"):
        service.submit(safe_request(quantity=10))
