from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .connection_api import store as groww_settings_store
from .groww_session import GrowwCredentials, GrowwSession
from .live_state import live_state_store
from .order_events import order_events


@dataclass(frozen=True)
class ExecutionRequest:
    symbol: str
    side: str
    quantity: int
    product: str
    order_type: str
    price: float | None = None
    trigger_price: float | None = None
    is_exit: bool = False
    shortable: bool = False


class GrowwExecutionService:
    """
    Internal order-routing service.

    This is intentionally not exposed as a public API endpoint. Strategy/risk code must
    call it only after all decision, ownership, liquidity and immutable risk gates pass.
    """

    TERMINAL_SUCCESS = {"EXECUTED", "COMPLETED", "DELIVERY_AWAITED"}
    TERMINAL_FAILURE = {"REJECTED", "FAILED", "CANCELLED"}

    def _session(self) -> GrowwSession:
        saved = groww_settings_store.load()
        if not saved:
            raise RuntimeError("Groww credentials are not configured")
        return GrowwSession.from_credentials(
            GrowwCredentials(totp_token=saved.totp_token, totp_secret=saved.totp_secret)
        )

    @staticmethod
    def _reference(symbol: str) -> str:
        # Groww accepts 8-20 chars, alphanumeric with at most two hyphens.
        stamp = str(int(time.time() * 1000))[-10:]
        clean = "".join(ch for ch in symbol.upper() if ch.isalnum())[:5]
        return f"IPO-{clean}-{stamp}"[:20]

    @staticmethod
    def _extract_ltp(quote: Any) -> float:
        if not isinstance(quote, dict):
            return 0.0
        source = quote.get("payload") if isinstance(quote.get("payload"), dict) else quote
        for key in ("last_price", "ltp", "close", "average_price"):
            try:
                value = float(source.get(key) or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0

    def _instrument_and_price(self, groww: Any, symbol: str) -> tuple[dict[str, Any], float]:
        instrument = groww.get_instrument_by_exchange_and_trading_symbol(
            exchange=groww.EXCHANGE_NSE,
            trading_symbol=symbol,
        )
        if not isinstance(instrument, dict):
            raise RuntimeError("Groww instrument could not be resolved")
        if str(instrument.get("exchange") or "").upper() != "NSE":
            raise RuntimeError("Resolved instrument is not NSE")
        if str(instrument.get("segment") or "").upper() != "CASH":
            raise RuntimeError("Resolved instrument is not CASH")
        if str(instrument.get("trading_symbol") or "").upper().strip() != symbol:
            raise RuntimeError("Resolved Groww trading symbol does not exactly match NSE symbol")

        quote = groww.get_quote(
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            trading_symbol=symbol,
        )
        ltp = self._extract_ltp(quote)
        if ltp <= 0:
            raise RuntimeError("Positive live Groww price is unavailable")
        return instrument, ltp

    def submit(self, request: ExecutionRequest) -> dict[str, Any]:
        state = live_state_store.load()
        if not state.enabled:
            raise RuntimeError("Live execution is disabled")
        if request.quantity <= 0:
            raise ValueError("Quantity must be positive")

        symbol = request.symbol.upper().strip()
        side = request.side.upper().strip()
        if side not in {"BUY", "SELL"}:
            raise ValueError("Side must be BUY or SELL")

        groww = self._session().api
        instrument, live_price = self._instrument_and_price(groww, symbol)

        lot_size = max(1, int(float(instrument.get("lot_size") or 1)))
        if request.quantity % lot_size != 0:
            raise RuntimeError(
                f"Order quantity {request.quantity} is not a multiple of Groww market lot {lot_size}"
            )

        buy_allowed = str(instrument.get("buy_allowed") or "").strip().lower() in {"1", "true", "yes"}
        sell_allowed = str(instrument.get("sell_allowed") or "").strip().lower() in {"1", "true", "yes"}
        if side == "BUY" and not buy_allowed:
            raise RuntimeError("Groww currently marks buying as unavailable for this instrument")
        if side == "SELL" and not sell_allowed:
            raise RuntimeError("Groww currently marks selling as unavailable for this instrument")
        if side == "SELL" and request.product.upper() == "MIS" and not request.is_exit and not request.shortable:
            raise RuntimeError("Fresh intraday short is not confirmed eligible")

        reference_price = float(request.price) if request.price and request.price > 0 else live_price
        estimated_notional = request.quantity * reference_price
        if estimated_notional > state.budget_rupees:
            raise RuntimeError(
                f"Order notional ₹{estimated_notional:.2f} exceeds live budget ₹{state.budget_rupees}"
            )

        event_type = "EXIT_PLACING" if request.is_exit else "ORDER_PLACING"
        order_events.publish(
            event_type,
            symbol=symbol,
            side=side,
            quantity=request.quantity,
            price=request.price,
            message="Submitting order to Groww",
        )

        product = (
            groww.PRODUCT_MIS if request.product.upper() == "MIS"
            else groww.PRODUCT_CNC
        )
        order_type = {
            "MARKET": groww.ORDER_TYPE_MARKET,
            "LIMIT": groww.ORDER_TYPE_LIMIT,
            "SL": groww.ORDER_TYPE_STOP_LOSS,
            "SL_M": groww.ORDER_TYPE_STOP_LOSS_MARKET,
        }.get(request.order_type.upper())
        if order_type is None:
            raise ValueError("Unsupported order type")

        transaction_type = (
            groww.TRANSACTION_TYPE_BUY if side == "BUY"
            else groww.TRANSACTION_TYPE_SELL
        )

        try:
            response = groww.place_order(
                trading_symbol=symbol,
                quantity=request.quantity,
                validity=groww.VALIDITY_DAY,
                exchange=groww.EXCHANGE_NSE,
                segment=groww.SEGMENT_CASH,
                product=product,
                order_type=order_type,
                transaction_type=transaction_type,
                price=request.price,
                trigger_price=request.trigger_price,
                order_reference_id=self._reference(symbol),
            )
        except Exception as exc:
            order_events.publish(
                "ORDER_REJECTED",
                symbol=symbol,
                side=side,
                quantity=request.quantity,
                price=request.price,
                message=f"Groww order submission failed: {exc}",
            )
            raise

        order_id = str(response.get("groww_order_id") or "").strip() or None
        status = str(response.get("order_status") or "NEW").upper()
        order_events.publish(
            "ORDER_ACCEPTED",
            symbol=symbol,
            side=side,
            quantity=request.quantity,
            price=request.price,
            order_id=order_id,
            message=f"Groww accepted order ({status})",
        )
        return response

    def reconcile_order(
        self,
        *,
        groww_order_id: str,
        symbol: str,
        side: str,
        quantity: int,
        is_exit: bool = False,
    ) -> dict[str, Any]:
        groww = self._session().api
        response = groww.get_order_status(
            groww_order_id=groww_order_id,
            segment=groww.SEGMENT_CASH,
        )
        status = str(response.get("order_status") or "").upper()
        filled = int(response.get("filled_quantity") or 0)
        average = response.get("average_fill_price")
        price = float(average) if average not in (None, "") else None

        if status in self.TERMINAL_SUCCESS:
            order_events.publish(
                "POSITION_CLOSED" if is_exit else "ORDER_FILLED",
                symbol=symbol,
                side=side,
                quantity=filled or quantity,
                price=price,
                order_id=groww_order_id,
                message=f"Groww order {status.lower()}",
            )
        elif status in self.TERMINAL_FAILURE:
            order_events.publish(
                "ORDER_REJECTED" if status in {"REJECTED", "FAILED"} else "ORDER_CANCELLED",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                order_id=groww_order_id,
                message=f"Groww order {status.lower()}",
            )
        elif 0 < filled < quantity:
            order_events.publish(
                "ORDER_PARTIAL",
                symbol=symbol,
                side=side,
                quantity=filled,
                price=price,
                order_id=groww_order_id,
                message=f"Partial fill {filled}/{quantity}",
            )
        return response
