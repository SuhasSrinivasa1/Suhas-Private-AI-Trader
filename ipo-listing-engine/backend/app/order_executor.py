from __future__ import annotations

from threading import RLock
from uuid import uuid4

from .groww_session import GrowwSession
from .trade_events import TradeEventStore

TERMINAL_EXECUTED = {"EXECUTED", "COMPLETED", "DELIVERY_AWAITED"}
TERMINAL_FAILED = {"REJECTED", "FAILED"}
TERMINAL_CANCELLED = {"CANCELLED"}


def _payload(response: dict) -> dict:
    payload = response.get("payload")
    return payload if isinstance(payload, dict) else response


class GrowwOrderExecutor:
    """
    Execution adapter that emits an auditable event before and after every broker action.
    Strategy/risk approval must happen before calling this class.
    """

    def __init__(self, session: GrowwSession, events: TradeEventStore) -> None:
        self.session = session
        self.events = events
        self._lock = RLock()
        self._last_status: dict[str, str] = {}

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
        placing_type = "EXIT_PLACING" if is_exit else "ORDER_PLACING"
        submitted_type = "EXIT_SUBMITTED" if is_exit else "ORDER_SUBMITTED"

        self.events.publish(
            event_type=placing_type,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            message="Submitting order to Groww",
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
            self.events.publish(
                event_type="EXIT_FAILED" if is_exit else "ORDER_FAILED",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                message=str(exc),
            )
            raise

        data = _payload(response)
        order_id = str(data.get("groww_order_id") or "").strip() or None
        status = str(data.get("order_status") or "NEW").upper().strip()

        self.events.publish(
            event_type=submitted_type,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_id=order_id,
            message=f"Groww status: {status}",
        )

        if order_id:
            with self._lock:
                self._last_status[order_id] = status
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
            previous = self._last_status.get(groww_order_id)
            self._last_status[groww_order_id] = status

        if status == previous and filled <= 0:
            return response

        if status in TERMINAL_EXECUTED:
            event_type = "EXIT_EXECUTED" if is_exit else "ORDER_EXECUTED"
        elif status in TERMINAL_FAILED:
            event_type = "EXIT_REJECTED" if is_exit else "ORDER_REJECTED"
        elif status in TERMINAL_CANCELLED:
            event_type = "EXIT_CANCELLED" if is_exit else "ORDER_CANCELLED"
        elif filled > 0:
            event_type = "EXIT_PARTIAL_FILL" if is_exit else "ORDER_PARTIAL_FILL"
        else:
            return response

        average_fill = float(data.get("average_fill_price") or 0) or None
        self.events.publish(
            event_type=event_type,
            symbol=symbol,
            side=side,
            quantity=filled if filled > 0 else quantity,
            price=average_fill,
            order_id=groww_order_id,
            message=f"Groww status: {status}",
        )
        return response
