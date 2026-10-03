from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class ListingSessionDecision:
    state: str
    can_submit_continuous_order: bool
    reason: str


def listing_session_gate(
    *,
    now: datetime,
    listing_date: date,
    nse_symbol_confirmed: bool,
    groww_instrument_resolved: bool,
    live_quote_available: bool,
    buy_allowed: bool = True,
    lot_size: int = 1,
    live_price: float | None = None,
    budget_rupees: int = 100_000,
) -> ListingSessionDecision:
    local = now.astimezone(IST)
    if local.date() != listing_date:
        return ListingSessionDecision("NOT_LISTING_DAY", False, "Candidate is not scheduled to list today")
    if not nse_symbol_confirmed:
        return ListingSessionDecision("WAIT_SYMBOL", False, "Official NSE symbol/date are not confirmed")
    if not groww_instrument_resolved:
        return ListingSessionDecision("WAIT_GROWW_INSTRUMENT", False, "Groww instrument master has not resolved the NSE symbol")
    if local.time() < time(9, 0):
        return ListingSessionDecision("PRE_MARKET", False, "Special pre-open has not started")
    if local.time() < time(9, 45):
        return ListingSessionDecision(
            "SPECIAL_PREOPEN_ORDER_ENTRY",
            False,
            "IPO Sentinel observes special pre-open; continuous-market auto execution is disabled",
        )
    if local.time() < time(9, 55):
        return ListingSessionDecision("SPECIAL_PREOPEN_MATCHING", False, "Exchange is determining the equilibrium open price")
    if local.time() < time(10, 0):
        return ListingSessionDecision("SPECIAL_PREOPEN_BUFFER", False, "Exchange is transitioning to continuous trading")
    if local.time() >= time(15, 30):
        return ListingSessionDecision("CLOSED", False, "Regular cash session is closed")
    if not live_quote_available:
        return ListingSessionDecision("WAIT_LIVE_QUOTE", False, "Live Groww quote/depth is not available yet")
    if not buy_allowed:
        return ListingSessionDecision("WAIT_BUY_NOT_ALLOWED", False, "Groww instrument master does not currently allow buying")
    if lot_size <= 0:
        return ListingSessionDecision("WAIT_INVALID_LOT", False, "Groww instrument lot size is invalid")
    if live_price is None or live_price <= 0:
        return ListingSessionDecision("WAIT_LIVE_PRICE", False, "Positive live price is required for budget/lot validation")
    minimum_live_notional = lot_size * live_price
    if minimum_live_notional > budget_rupees:
        return ListingSessionDecision(
            "WAIT_MIN_LOT_ABOVE_BUDGET",
            False,
            f"Minimum market lot requires about ₹{minimum_live_notional:.2f}, above live budget ₹{budget_rupees}",
        )
    return ListingSessionDecision(
        "CONTINUOUS_TRADING",
        True,
        "Continuous market is open and symbol/instrument/live-data checks passed",
    )
