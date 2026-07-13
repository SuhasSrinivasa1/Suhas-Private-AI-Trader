from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .base import BrokerAdapter, BrokerCapabilities, BrokerOrderRequest, BrokerOrderResult


@dataclass
class PaperPosition:
    symbol: str
    market: str
    quantity: float
    average_price: float


class PaperBroker(BrokerAdapter):
    """In-memory broker used only for safe local testing."""

    name = "paper"
    capabilities = BrokerCapabilities(
        read_account=True,
        read_positions=True,
        read_orders=True,
        place_orders=True,
        cancel_orders=True,
        withdrawals=False,
        paper=True,
    )

    def __init__(self) -> None:
        self._orders: list[dict] = []
        self._positions: list[dict] = []

    def connect(self) -> dict:
        return {
            "broker": self.name,
            "connected": True,
            "mode": "paper",
            "capabilities": self.capabilities.to_dict(),
        }

    def get_account(self) -> dict:
        return {
            "broker": self.name,
            "mode": "paper",
            "currency": "INR",
            "cash": 1_000_000.0,
            "equity": 1_000_000.0,
        }

    def get_positions(self) -> list[dict]:
        return list(self._positions)

    def get_orders(self) -> list[dict]:
        return list(self._orders)

    def place_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        order_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        order = {
            "order_id": order_id,
            "broker": self.name,
            "mode": "paper",
            "symbol": request.symbol,
            "market": request.market,
            "side": request.side,
            "quantity": request.quantity,
            "order_type": request.order_type,
            "price": request.price,
            "status": "accepted",
            "created_at": created_at,
        }
        self._orders.append(order)
        return BrokerOrderResult(
            broker=self.name,
            order_id=order_id,
            status="accepted",
            mode="paper",
            message="Paper order accepted. No real order was sent.",
        )

    def cancel_order(self, order_id: str) -> BrokerOrderResult:
        for order in self._orders:
            if order["order_id"] == order_id:
                order["status"] = "cancelled"
                return BrokerOrderResult(
                    broker=self.name,
                    order_id=order_id,
                    status="cancelled",
                    mode="paper",
                    message="Paper order cancelled.",
                )
        return BrokerOrderResult(
            broker=self.name,
            order_id=order_id,
            status="not_found",
            mode="paper",
            message="Paper order not found.",
        )
