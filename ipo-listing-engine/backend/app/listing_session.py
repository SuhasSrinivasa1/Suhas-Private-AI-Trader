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
    market_depth_available: bool = False,
    liquidity_sufficient: bool = False,
    spread_bps: float | None = None,
    max_spread_bps: float = 85.0,
    estimated_impact_bps: float | None = None,
    max_impact_bps: float = 75.0,
    circuit_state_acceptable: bool = False,
    position_reconciled: bool = False,
    order_state_known: bool = False,
    position_isolation_ok: bool = False,
    side: str = "BUY",
    buy_allowed: bool = True,
    sell_allowed: bool = True,
    shortable: bool = False,
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
        return ListingSessionDecision("WAIT_LIVE_QUOTE", False, "Fresh live Groww quote is not available yet")
    if not market_depth_available:
        return ListingSessionDecision("WAIT_MARKET_DEPTH", False, "Usable live market depth is not available yet")
    if not liquidity_sufficient:
        return ListingSessionDecision("WAIT_LIQUIDITY", False, "Listing liquidity is not sufficient for execution")
    if spread_bps is None or spread_bps < 0:
        return ListingSessionDecision("WAIT_SPREAD_UNKNOWN", False, "Spread must be measured before execution")
    if spread_bps > max_spread_bps:
        return ListingSessionDecision("WAIT_SPREAD_TOO_WIDE", False, "Spread exceeds the immutable execution threshold")
    if estimated_impact_bps is None or estimated_impact_bps < 0:
        return ListingSessionDecision("WAIT_IMPACT_UNKNOWN", False, "Estimated market impact must be measured")
    if estimated_impact_bps > max_impact_bps:
        return ListingSessionDecision("WAIT_IMPACT_TOO_HIGH", False, "Estimated market impact exceeds the threshold")
    if not circuit_state_acceptable:
        return ListingSessionDecision("WAIT_CIRCUIT_STATE", False, "Circuit state is not confirmed safe")
    if not position_reconciled:
        return ListingSessionDecision("WAIT_POSITION_RECONCILIATION", False, "Broker position reconciliation is not current")
    if not order_state_known:
        return ListingSessionDecision("WAIT_ORDER_STATE", False, "Outstanding order state is uncertain")
    if not position_isolation_ok:
        return ListingSessionDecision("WAIT_POSITION_ISOLATION", False, "IPO Sentinel position isolation is not confirmed")

    normalized_side = side.upper().strip()
    if normalized_side == "BUY" and not buy_allowed:
        return ListingSessionDecision("WAIT_BUY_NOT_ALLOWED", False, "Groww instrument master does not currently allow buying")
    if normalized_side in {"SELL", "SELL_SHORT"} and not sell_allowed:
        return ListingSessionDecision("WAIT_SELL_NOT_ALLOWED", False, "Groww instrument master does not currently allow selling")
    if normalized_side == "SELL_SHORT" and not shortable:
        return ListingSessionDecision("WAIT_SHORT_NOT_ELIGIBLE", False, "Fresh intraday short eligibility is not confirmed")
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
        "CONTINUOUS_TRADING_ELIGIBLE",
        True,
        "Continuous market and all identity, data, liquidity, risk and isolation gates passed",
    )
