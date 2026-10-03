from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .audit import audit_log

from .connection_api import router as connection_router
from .domain import LiveFeatures
from .post_listing_monitor import PostListingOpportunityEngine, PostListingSnapshot
from .live_state import live_state_store
from .ops_api import router as ops_router
from .services import ExchangeCalendar, OwnedPositionRegistry, ShadowLedger
from .strategy import ListingDecisionEngine
from .strategy_api import router as strategy_router

app = FastAPI(title="IPO Sentinel", version="1.0.0")
app.include_router(connection_router)
app.include_router(strategy_router)
app.include_router(ops_router)

calendar = ExchangeCalendar()
registry = OwnedPositionRegistry()
shadow = ShadowLedger(100_000)
engine = ListingDecisionEngine()
post_listing_engine = PostListingOpportunityEngine()


class DecisionRequest(BaseModel):
    symbol: str
    ltp: float
    vwap: float
    rvol: float = 1.0
    spread_bps: float = 0.0
    buy_qty: float = 0.0
    sell_qty: float = 0.0
    first_5m_high: float | None = None
    first_5m_low: float | None = None
    listing_price: float | None = None
    issue_price: float | None = None
    nifty_return_pct: float = 0.0
    sector_return_pct: float = 0.0
    circuit_distance_pct: float | None = None
    shortable: bool = False
    data_fresh: bool = True
    budget_rupees: int = Field(default=100_000, ge=10_000, le=100_000)


class PostListingRequest(BaseModel):
    symbol: str
    as_of: date
    listing_date: date
    last_price: float
    issue_price: float
    listing_price: float
    anchored_vwap: float
    rolling_high_20: float
    rolling_low_20: float
    ema9: float
    ema20: float
    relative_volume: float
    relative_strength_pct: float
    close_position: float = Field(ge=0.0, le=1.0)
    shortable: bool = False
    data_fresh: bool = True


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "ipo-sentinel",
        "version": "1.0.0",
        "shadow_capital": shadow.starting_capital,
        "live_execution": live_state_store.load().enabled,
        "calendar_ready": calendar.source_ready,
        "post_listing_monitor_days": 30,
        "trade_event_notifications": True,
    }


@app.get("/calendar/next-trading-day")
def next_trading_day(after: date) -> dict:
    nxt = calendar.next_trading_day(after)
    return {
        "after": after.isoformat(),
        "next_trading_day": nxt.isoformat(),
        "official_calendar_ready": calendar.source_ready,
    }


@app.post("/decision")
def decision(payload: DecisionRequest) -> dict:
    features = LiveFeatures(
        symbol=payload.symbol.upper(),
        at=datetime.now(timezone.utc),
        ltp=payload.ltp,
        vwap=payload.vwap,
        rvol=payload.rvol,
        spread_bps=payload.spread_bps,
        buy_qty=payload.buy_qty,
        sell_qty=payload.sell_qty,
        first_5m_high=payload.first_5m_high,
        first_5m_low=payload.first_5m_low,
        listing_price=payload.listing_price,
        issue_price=payload.issue_price,
        nifty_return_pct=payload.nifty_return_pct,
        sector_return_pct=payload.sector_return_pct,
        circuit_distance_pct=payload.circuit_distance_pct,
        shortable=payload.shortable,
        data_fresh=payload.data_fresh,
    )
    result = engine.decide(features, payload.budget_rupees)
    audit_log.append(
        "DECISION_EVALUATED",
        symbol=features.symbol,
        action=str(result.action),
        score=result.score,
        confidence=result.confidence,
        budget_rupees=result.budget_rupees,
        reason_codes=list(result.reason_codes),
    )
    return {
        "symbol": features.symbol,
        "action": result.action,
        "score": result.score,
        "confidence": result.confidence,
        "budget_rupees": result.budget_rupees,
        "reason_codes": result.reason_codes,
        "position_isolation_ok": registry.may_mutate(features.symbol),
    }


@app.post("/post-listing/evaluate")
def post_listing_evaluate(payload: PostListingRequest) -> dict:
    snapshot = PostListingSnapshot(
        symbol=payload.symbol.upper(),
        as_of=payload.as_of,
        listing_date=payload.listing_date,
        last_price=payload.last_price,
        issue_price=payload.issue_price,
        listing_price=payload.listing_price,
        anchored_vwap=payload.anchored_vwap,
        rolling_high_20=payload.rolling_high_20,
        rolling_low_20=payload.rolling_low_20,
        ema9=payload.ema9,
        ema20=payload.ema20,
        relative_volume=payload.relative_volume,
        relative_strength_pct=payload.relative_strength_pct,
        close_position=payload.close_position,
        shortable=payload.shortable,
        data_fresh=payload.data_fresh,
    )
    result = post_listing_engine.evaluate(calendar, snapshot)
    audit_log.append(
        "POST_LISTING_EVALUATED",
        symbol=result.symbol,
        trading_day=result.trading_day,
        action=result.action,
        opportunity=str(result.opportunity),
        score=result.score,
        reasons=list(result.reasons),
    )
    return {
        "symbol": result.symbol,
        "trading_day": result.trading_day,
        "active": result.active,
        "action": result.action,
        "opportunity": result.opportunity,
        "score": result.score,
        "reasons": result.reasons,
    }


@app.get("/shadow")
def shadow_status() -> dict:
    return shadow.mark_to_market({})
