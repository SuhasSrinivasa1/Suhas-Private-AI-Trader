from app.execution_gateway import ExecutionOrder, GrowwExecutionGateway


class FakeGroww:
    EXCHANGE_NSE = "NSE"
    EXCHANGE_BSE = "BSE"
    SEGMENT_CASH = "CASH"
    PRODUCT_CNC = "CNC"
    PRODUCT_MIS = "MIS"
    ORDER_TYPE_LIMIT = "LIMIT"
    ORDER_TYPE_MARKET = "MARKET"
    ORDER_TYPE_STOP_LOSS = "SL"
    ORDER_TYPE_STOP_LOSS_MARKET = "SL_M"
    TRANSACTION_TYPE_BUY = "BUY"
    TRANSACTION_TYPE_SELL = "SELL"
    VALIDITY_DAY = "DAY"

    def __init__(self):
        self.placed = None
        self.status = "OPEN"

    def place_order(self, **kwargs):
        self.placed = kwargs
        return {
            "groww_order_id": "G123",
            "order_status": "OPEN",
            "remark": "Order placed successfully",
        }

    def get_order_status(self, **kwargs):
        return {
            "groww_order_id": kwargs["groww_order_id"],
            "order_status": self.status,
            "filled_quantity": 1 if self.status == "EXECUTED" else 0,
        }


def test_gateway_uses_official_cash_order_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("IPO_SENTINEL_ORDER_EVENT_FILE", str(tmp_path / "events.jsonl"))
    api = FakeGroww()
    gateway = GrowwExecutionGateway(api)
    response = gateway.place(
        ExecutionOrder(
            trading_symbol="ABC",
            quantity=2,
            transaction_type="BUY",
            product="CNC",
            order_type="LIMIT",
            order_reference_id="IPOSENT-ABC-01",
            price=100.0,
        )
    )
    assert response["groww_order_id"] == "G123"
    assert api.placed["segment"] == "CASH"
    assert api.placed["product"] == "CNC"
    assert api.placed["transaction_type"] == "BUY"
    assert api.placed["price"] == 100.0


def test_gateway_refresh_accepts_fill_transition():
    api = FakeGroww()
    gateway = GrowwExecutionGateway(api)
    gateway._last_status["G123"] = "OPEN"
    api.status = "EXECUTED"
    result = gateway.refresh(
        groww_order_id="G123",
        symbol="ABC",
        side="BUY",
        quantity=2,
    )
    assert result["order_status"] == "EXECUTED"
