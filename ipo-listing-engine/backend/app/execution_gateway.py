from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .order_events import order_events


TERMINAL_FILLED = {"EXECUTED", "COMPLETED", "DELIVERY_AWAITED"}
TERMINAL_REJECTED = {"REJECTED", "FAILED", "CANCELLED"}


@dataclass(frozen=True)
class ExecutionOrder:
    trading_symbol: str
    quantity: int
    transaction_type: str
    product: str
    order_type: str
    order_reference_id: str
    price: float | None = None
    trigger_price: float | None = None
    exchange: str = "NSE"


class GrowwExecutionGateway:
    """
    Thin, testable wrapper around the official Groww SDK.

    It emits lifecycle events before submission and after broker acknowledgement/status
    changes. Strategy code should never call the Groww SDK directly for live orders.
    """

    def __init__(self, groww_api: Any) -> None:
        self.groww = groww_api
        self._last_status: dict[str, str] = {}

    def _exchange(self, exchange: str) -> Any:
        if exchange.upper() == "NSE":
            return self.groww.EXCHANGE_NSE
        if exchange.upper() == "BSE":
            return self.groww.EXCHANGE_BSE
        raise ValueError(f"Unsupported cash exchange: {exchange}")

    def _product(self, product: str) -> Any:
        normalized = product.upper()
        if normalized == "CNC":
            return self.groww.PRODUCT_CNC
        if normalized == "MIS":
            return self.groww.PRODUCT_MIS
        raise ValueError(f"Unsupported cash product: {product}")

    def _order_type(self, order_type: str) -> Any:
        normalized = order_type.upper()
        mapping = {
            "LIMIT": self.groww.ORDER_TYPE_LIMIT,
            "MARKET": self.groww.ORDER_TYPE_MARKET,
            "SL": self.groww.ORDER_TYPE_STOP_LOSS,
            "SL_M": self.groww.ORDER_TYPE_STOP_LOSS_MARKET,
        }
        if normalized not in mapping:
            raise ValueError(f"Unsupported order type: {order_type}")
        return mapping[normalized]

    def _transaction(self, side: str) -> Any:
        normalized = side.upper()
        if normalized == "BUY":
            return self.groww.TRANSACTION_TYPE_BUY
        if normalized == "SELL":
            return self.groww.TRANSACTION_TYPE_SELL
        raise ValueError(f"Unsupported transaction type: {side}")

    def _validate_order(self, order: ExecutionOrder) -> None:
        if order.quantity <= 0:
            raise ValueError("Order quantity must be positive")
        ref = order.order_reference_id.strip()
        if not (8 <= len(ref) <= 20):
            raise ValueError("Groww order reference ID must be 8 to 20 characters")
        if ref.count("-") > 2 or any(not (ch.isalnum() or ch == "-") for ch in ref):
            raise ValueError("Groww order reference ID must be alphanumeric with at most two hyphens")
        if order.order_type.upper() == "LIMIT" and (order.price is None or order.price <= 0):
            raise ValueError("Limit order requires a positive price")
        if order.order_type.upper() in {"SL", "SL_M"} and (
            order.trigger_price is None or order.trigger_price <= 0
        ):
            raise ValueError("Stop order requires a positive trigger price")

    def place(self, order: ExecutionOrder, *, is_exit: bool = False) -> dict[str, Any]:
        self._validate_order(order)
        event_type = "EXIT_PLACING" if is_exit else "ORDER_PLACING"
        order_events.publish(
            event_type,
            symbol=order.trading_symbol,
            side=order.transaction_type,
            quantity=order.quantity,
            price=order.price,
            message="Submitting order to Groww",
            metadata={
                "product": order.product,
                "order_type": order.order_type,
                "reference_id": order.order_reference_id,
            },
        )

        kwargs: dict[str, Any] = {
            "trading_symbol": order.trading_symbol,
            "quantity": order.quantity,
            "validity": self.groww.VALIDITY_DAY,
            "exchange": self._exchange(order.exchange),
            "segment": self.groww.SEGMENT_CASH,
            "product": self._product(order.product),
            "order_type": self._order_type(order.order_type),
            "transaction_type": self._transaction(order.transaction_type),
            "order_reference_id": order.order_reference_id,
        }
        if order.price is not None:
            kwargs["price"] = order.price
        if order.trigger_price is not None:
            kwargs["trigger_price"] = order.trigger_price

        try:
            response = self.groww.place_order(**kwargs)
        except Exception as exc:
            order_events.publish(
                "ORDER_REJECTED",
                symbol=order.trading_symbol,
                side=order.transaction_type,
                quantity=order.quantity,
                price=order.price,
                message=f"Broker submission failed: {exc.__class__.__name__}",
                metadata={"reference_id": order.order_reference_id},
            )
            raise

        order_id = str(response.get("groww_order_id") or "").strip() or None
        status = str(response.get("order_status") or "ACKED").upper()
        self._emit_status(
            status=status,
            symbol=order.trading_symbol,
            side=order.transaction_type,
            quantity=order.quantity,
            price=order.price,
            order_id=order_id,
            is_exit=is_exit,
            message=str(response.get("remark") or "").strip() or None,
        )
        if order_id:
            self._last_status[order_id] = status
        return response

    def refresh(
        self,
        *,
        groww_order_id: str,
        symbol: str,
        side: str,
        quantity: int,
        is_exit: bool = False,
    ) -> dict[str, Any]:
        response = self.groww.get_order_status(
            groww_order_id=groww_order_id,
            segment=self.groww.SEGMENT_CASH,
        )
        status = str(response.get("order_status") or "UNKNOWN").upper()
        previous = self._last_status.get(groww_order_id)
        if status != previous:
            self._emit_status(
                status=status,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=None,
                order_id=groww_order_id,
                is_exit=is_exit,
                message=str(response.get("remark") or "").strip() or None,
            )
            self._last_status[groww_order_id] = status
        return response

    def _emit_status(
        self,
        *,
        status: str,
        symbol: str,
        side: str,
        quantity: int,
        price: float | None,
        order_id: str | None,
        is_exit: bool,
        message: str | None,
    ) -> None:
        normalized = status.upper()
        if normalized in TERMINAL_FILLED:
            event_type = "POSITION_CLOSED" if is_exit else "ORDER_FILLED"
        elif normalized in TERMINAL_REJECTED:
            event_type = "ORDER_REJECTED" if normalized in {"REJECTED", "FAILED"} else "ORDER_CANCELLED"
        else:
            event_type = "ORDER_ACCEPTED"

        order_events.publish(
            event_type,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_id=order_id,
            message=message or ("Broker status: " + normalized),
            metadata={"broker_status": normalized, "is_exit": is_exit},
        )
