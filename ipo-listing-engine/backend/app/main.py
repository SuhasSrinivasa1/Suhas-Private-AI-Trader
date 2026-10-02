from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .domain import LiveFeatures
from .services import ExchangeCalendar, OwnedPositionRegistry, ShadowLedger
from .strategy import ListingDecisionEngine

app = FastAPI(title="IPO Sentinel", version="0.1.0")

calendar = ExchangeCalendar()
registry = OwnedPositionRegistry()
shadow = ShadowLedger(100_000)
engine = ListingDecisionEngine()


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


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "ipo-sentinel",
        "shadow_capital": shadow.starting_capital,
        "live_execution": False,
        "calendar_ready": calendar.source_ready,
    }


@app.get("/calendar/next-trading-day")
def next_trading_day(after: date) -> dict:
    nxt = calendar.next_trading_day(after)
    return {"after": after.isoformat(), "next_trading_day": nxt.isoformat(), "official_calendar_ready": calendar.source_ready}


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
    return {
        "symbol": features.symbol,
        "action": result.action,
        "score": result.score,
        "confidence": result.confidence,
        "budget_rupees": result.budget_rupees,
        "reason_codes": result.reason_codes,
        "position_isolation_ok": registry.may_mutate(features.symbol),
    }


@app.get("/shadow")
def shadow_status() -> dict:
    return shadow.mark_to_market({})
