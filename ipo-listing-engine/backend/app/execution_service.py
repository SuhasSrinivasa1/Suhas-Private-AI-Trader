from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time
from typing import Any

import httpx

from .connection_api import store as groww_settings_store
from .groww_session import GrowwCredentials, GrowwSession
from .listing_session import IST, listing_session_gate
from .live_state import live_state_store
from .order_events import order_events
from .research_service import ResearchPlanStore


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
    liquidity_sufficient: bool = False
    spread_bps: float | None = None
    estimated_impact_bps: float | None = None
    circuit_state_acceptable: bool = False
    position_reconciled: bool = False
    order_state_known: bool = False
    position_isolation_ok: bool = False


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

    @staticmethod
    def _quote_has_depth(quote: Any) -> bool:
        if not isinstance(quote, dict):
            return False
        source = quote.get("payload") if isinstance(quote.get("payload"), dict) else quote
        if not isinstance(source, dict):
            return False
        depth = source.get("depth") or source.get("market_depth")
        if isinstance(depth, dict):
            bids = depth.get("buy") or depth.get("bids") or depth.get("buy_depth")
            asks = depth.get("sell") or depth.get("asks") or depth.get("sell_depth")
            if isinstance(bids, list) and bids and isinstance(asks, list) and asks:
                return True
        buy_total = source.get("total_buy_quantity") or source.get("buy_quantity")
        sell_total = source.get("total_sell_quantity") or source.get("sell_quantity")
        try:
            return float(buy_total or 0) > 0 and float(sell_total or 0) > 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _require_current_static_ip() -> None:
        saved = groww_settings_store.load()
        if not saved or not saved.static_ip_confirmed:
            raise RuntimeError("Static-IP whitelist confirmation is unavailable")
        try:
            response = httpx.get("https://api.ipify.org?format=json", timeout=7.0)
            response.raise_for_status()
            detected = str(response.json().get("ip") or "").strip()
        except Exception as exc:
            raise RuntimeError("Unable to validate current static egress IP") from exc
        if detected != saved.expected_static_ip:
            raise RuntimeError("Current backend egress IP does not match the Groww-whitelisted static IP")

    @staticmethod
    def _authorized_candidate(symbol: str, now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
        plan = ResearchPlanStore().load()
        if not plan:
            raise RuntimeError("Official IPO research plan is unavailable")
        if not plan.get("calendar_ready"):
            raise RuntimeError("Official NSE cash-market calendar is not ready")
        try:
            generated = datetime.fromisoformat(str(plan.get("generated_at")))
            generated = generated if generated.tzinfo else generated.replace(tzinfo=IST)
            age_seconds = (now - generated.astimezone(IST)).total_seconds()
        except Exception as exc:
            raise RuntimeError("Research plan timestamp is invalid") from exc
        if age_seconds < -300 or age_seconds > 18 * 60 * 60:
            raise RuntimeError("Research plan is stale; execution remains blocked")

        matches = [
            item
            for item in plan.get("all_known_candidates", [])
            if isinstance(item, dict)
            and str(item.get("symbol") or "").upper().strip() == symbol
            and bool(item.get("nse_listing_confirmed"))
        ]
        if len(matches) != 1:
            raise RuntimeError("Exactly one authoritative NSE listing identity is required")
        candidate = matches[0]
        if not candidate.get("symbol_resolved") or candidate.get("groww_resolution_status") != "RESOLVED":
            raise RuntimeError("Exact Groww NSE CASH instrument is not resolved")

        holidays = {
            str(value)
            for value in plan.get("calendar_holidays", [])
            if isinstance(value, str)
        }
        today = now.date()
        if today.weekday() >= 5 or today.isoformat() in holidays:
            raise RuntimeError("Today is not an official NSE cash trading day")
        return candidate, plan

    @staticmethod
    def _trading_day_number(listing_date: date, today: date, holidays: set[str]) -> int:
        if today < listing_date:
            return 0
        cursor = listing_date
        count = 0
        while cursor <= today:
            if cursor.weekday() < 5 and cursor.isoformat() not in holidays:
                count += 1
            cursor = date.fromordinal(cursor.toordinal() + 1)
        return count

    def _instrument_and_price(
        self,
        groww: Any,
        symbol: str,
        candidate: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], float]:
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

        official_isin = str(candidate.get("isin") or "").upper().strip()
        groww_isin = str(instrument.get("isin") or "").upper().strip()
        if official_isin and groww_isin != official_isin:
            raise RuntimeError("Groww ISIN does not exactly match the authoritative NSE identity")

        expected_token = str(candidate.get("groww_exchange_token") or "").strip()
        current_token = str(instrument.get("exchange_token") or "").strip()
        if expected_token and current_token and expected_token != current_token:
            raise RuntimeError("Groww exchange token changed since instrument resolution")

        quote = groww.get_quote(
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            trading_symbol=symbol,
        )
        if not isinstance(quote, dict):
            raise RuntimeError("Fresh Groww quote is unavailable")
        ltp = self._extract_ltp(quote)
        if ltp <= 0:
            raise RuntimeError("Positive live Groww price is unavailable")
        return instrument, quote, ltp

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

        now = datetime.now(IST)
        self._require_current_static_ip()
        candidate, plan = self._authorized_candidate(symbol, now)

        try:
            listing_date = date.fromisoformat(str(candidate.get("listing_date")))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Authoritative NSE listing date is unavailable") from exc
        if listing_date > now.date():
            raise RuntimeError("Security has not reached its official listing date")

        groww = self._session().api
        instrument, quote, live_price = self._instrument_and_price(groww, symbol, candidate)
        depth_available = self._quote_has_depth(quote)

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
        fresh_short = side == "SELL" and request.product.upper() == "MIS" and not request.is_exit
        if fresh_short and not request.shortable:
            raise RuntimeError("Fresh intraday short is not confirmed eligible")

        holidays = {str(value) for value in plan.get("calendar_holidays", []) if isinstance(value, str)}
        trading_day = self._trading_day_number(listing_date, now.date(), holidays)
        if trading_day <= 0 or trading_day > 30:
            raise RuntimeError("Candidate is outside the D1-D30 execution universe")

        if now.date() == listing_date:
            session = listing_session_gate(
                now=now,
                listing_date=listing_date,
                nse_symbol_confirmed=True,
                groww_instrument_resolved=True,
                live_quote_available=True,
                market_depth_available=depth_available,
                liquidity_sufficient=request.liquidity_sufficient,
                spread_bps=request.spread_bps,
                estimated_impact_bps=request.estimated_impact_bps,
                circuit_state_acceptable=request.circuit_state_acceptable,
                position_reconciled=request.position_reconciled,
                order_state_known=request.order_state_known,
                position_isolation_ok=request.position_isolation_ok,
                side="SELL_SHORT" if fresh_short else side,
                buy_allowed=buy_allowed,
                sell_allowed=sell_allowed,
                shortable=request.shortable,
                lot_size=lot_size,
                live_price=live_price,
                budget_rupees=state.budget_rupees,
            )
            if not session.can_submit_continuous_order:
                raise RuntimeError(f"{session.state}: {session.reason}")
        else:
            if now.time() < clock_time(9, 15) or now.time() >= clock_time(15, 30):
                raise RuntimeError("Regular NSE cash session is not open")
            if not depth_available:
                raise RuntimeError("WAIT_MARKET_DEPTH: usable live market depth is unavailable")
            if not request.liquidity_sufficient:
                raise RuntimeError("WAIT_LIQUIDITY: liquidity gate has not passed")
            if request.spread_bps is None or request.spread_bps < 0 or request.spread_bps > 85.0:
                raise RuntimeError("WAIT_SPREAD: measured spread is unavailable or too wide")
            if (
                request.estimated_impact_bps is None
                or request.estimated_impact_bps < 0
                or request.estimated_impact_bps > 75.0
            ):
                raise RuntimeError("WAIT_IMPACT: estimated market impact is unavailable or too high")
            if not request.circuit_state_acceptable:
                raise RuntimeError("WAIT_CIRCUIT_STATE: circuit state has not passed")
            if not request.position_reconciled:
                raise RuntimeError("WAIT_POSITION_RECONCILIATION: broker position state is stale")
            if not request.order_state_known:
                raise RuntimeError("WAIT_ORDER_STATE: outstanding order state is uncertain")
            if not request.position_isolation_ok:
                raise RuntimeError("WAIT_POSITION_ISOLATION: unrelated holdings may be affected")

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
