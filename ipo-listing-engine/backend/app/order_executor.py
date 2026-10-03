from __future__ import annotations

from threading import RLock
from uuid import uuid4

from .groww_session import GrowwSession
from .order_events import order_events

TERMINAL_EXECUTED = {"EXECUTED", "COMPLETED", "DELIVERY_AWAITED"}
TERMINAL_FAILED = {"REJECTED", "FAILED"}
TERMINAL_CANCELLED = {"CANCELLED"}


def _payload(response: dict) -> dict:
    payload = response.get("payload")
    return payload if isinstance(payload, dict) else response


class GrowwOrderExecutor:
    """
    Broker adapter that emits auditable order lifecycle events.

    The strategy and immutable risk layers must approve an order before this class
    is invoked. It never decides direction or position size.
    """

    def __init__(self, session: GrowwSession) -> None:
        self.session = session
        self._lock = RLock()
        self._last_status: dict[str, tuple[str, int]] = {}

    def submit(
        self,
        *,
        trading_symbol: str,
        quantity: int,
        transaction_type: str,
        product: str,
        order_type: str,
        price: float | None = None,
        trigger_price: float | None = None,
        purpose: str = "ENTRY",
    ) -> dict:
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        symbol = trading_symbol.upper().strip()
        side = transaction_type.upper().strip()
        is_exit = purpose.upper().strip() == "EXIT"

        order_events.publish(
            "EXIT_PLACING" if is_exit else "ORDER_PLACING",
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            message="Submitting order to Groww",
            metadata={"purpose": purpose.upper().strip()},
        )

        reference = "IS" + uuid4().hex[:16]
        try:
            response = self.session.api.place_order(
                trading_symbol=symbol,
                quantity=quantity,
                validity=self.session.api.VALIDITY_DAY,
                exchange=self.session.api.EXCHANGE_NSE,
                segment=self.session.api.SEGMENT_CASH,
                product=product,
                order_type=order_type,
                transaction_type=transaction_type,
                price=price,
                trigger_price=trigger_price,
                order_reference_id=reference,
            )
        except Exception as exc:
            order_events.publish(
                "ORDER_REJECTED",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                message=str(exc),
                metadata={
                    "purpose": purpose.upper().strip(),
                    "stage": "submission",
                },
            )
            raise

        data = _payload(response)
        order_id = str(data.get("groww_order_id") or "").strip() or None
        status = str(data.get("order_status") or "NEW").upper().strip()

        order_events.publish(
            "ORDER_ACCEPTED",
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_id=order_id,
            message=f"Groww status: {status}",
            metadata={
                "purpose": purpose.upper().strip(),
                "order_reference_id": reference,
            },
        )

        if order_id:
            with self._lock:
                self._last_status[order_id] = (status, 0)
        return response

    def refresh_status(
        self,
        *,
        groww_order_id: str,
        symbol: str,
        side: str,
        quantity: int,
        purpose: str = "ENTRY",
    ) -> dict:
        response = self.session.api.get_order_status(
            groww_order_id=groww_order_id,
            segment=self.session.api.SEGMENT_CASH,
        )
        data = _payload(response)
        status = str(data.get("order_status") or "").upper().strip()
        filled = int(data.get("filled_quantity") or 0)
        is_exit = purpose.upper().strip() == "EXIT"

        with self._lock:
            previous_status, previous_filled = self._last_status.get(
                groww_order_id,
                ("", 0),
            )
            self._last_status[groww_order_id] = (status, filled)

        if status == previous_status and filled == previous_filled:
            return response

        average_fill = float(
            data.get("average_fill_price") or 0
        ) or None

        if status in TERMINAL_EXECUTED:
            event_type = "POSITION_CLOSED" if is_exit else "ORDER_FILLED"
        elif status in TERMINAL_FAILED:
            event_type = "ORDER_REJECTED"
        elif status in TERMINAL_CANCELLED:
            event_type = "ORDER_CANCELLED"
        elif filled > previous_filled:
            event_type = "ORDER_PARTIAL"
        else:
            return response

        order_events.publish(
            event_type,
            symbol=symbol,
            side=side,
            quantity=filled if filled > 0 else quantity,
            price=average_fill,
            order_id=groww_order_id,
            message=f"Groww status: {status}",
            metadata={"purpose": purpose.upper().strip()},
        )
        return response
