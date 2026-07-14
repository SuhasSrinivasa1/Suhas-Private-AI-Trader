from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

import production21_main as base
from mode_agent_overlay import AGENT_CATALOG, MODE_PROFILES, ModeAgentOverlay

core = base.core
runtime = base.runtime
app = base.app

overlay = ModeAgentOverlay(core, runtime)
runtime.enriched_deep_scan = overlay.enriched_deep_scan
core._deep_scan = overlay.enriched_deep_scan

app.title = "Suhas Private AI Trader — Production 2.2"
app.version = "2.2.0"


class TradingModeRequest(BaseModel):
    mode: str = Field(min_length=8, max_length=8)


@app.get("/api/production22/status")
def production22_status() -> dict[str, Any]:
    return {
        "release": "2.2.0",
        "macd_enabled": True,
        "macd_parameters": {"fast": 12, "slow": 26, "signal": 9},
        "trading_mode": overlay.status(),
        "specialist_agent_count": len(AGENT_CATALOG),
        "specialist_agents": AGENT_CATALOG,
        "intraday_product": "MIS",
        "delivery_product": "CNC",
        "full_nse_equity_universe": True,
        "rules_contract_version": "2.2.0",
    }


@app.get("/api/trading-mode")
def trading_mode() -> dict[str, Any]:
    return overlay.status()


@app.post("/api/trading-mode")
async def set_trading_mode(request: TradingModeRequest) -> dict[str, Any]:
    try:
        status = overlay.set_mode(request.mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await core.broadcast({"type": "trading_mode_changed", "mode": status["mode"], "profile": status["profile"], "ts": core._now().isoformat()})
    return status


@app.get("/api/specialist-agents")
def specialist_agents() -> dict[str, Any]:
    return {
        "mode": overlay.mode,
        "items": [agent | {"weight": MODE_PROFILES[overlay.mode]["weights"][agent["id"]]} for agent in AGENT_CATALOG],
        "macd": {"enabled": True, "fast": 12, "slow": 26, "signal": 9},
    }


@app.get("/api/indicators/{symbol}")
async def indicators(symbol: str, force: bool = False) -> dict[str, Any]:
    if not core._broker_configured():
        raise HTTPException(status_code=503, detail="Groww credentials are required for mode-specific MACD analysis.")
    try:
        return await overlay.indicator_snapshot(symbol.upper().strip(), force=force)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{exc.__class__.__name__}: indicator analysis failed") from exc


def _remove_legacy_buy_route() -> None:
    app.router.routes[:] = [
        route for route in app.router.routes
        if not (getattr(route, "path", None) == "/api/orders/buy-recommendation" and "POST" in (getattr(route, "methods", set()) or set()))
    ]


_remove_legacy_buy_route()


@app.post("/api/orders/buy-recommendation")
async def mode_aware_buy_recommendation(request: core.BuyRecommendationRequest) -> dict[str, Any]:
    """Human-confirmed BUY using MIS for Intraday and CNC for Delivery."""
    if not core.GROWW_LIVE_EXECUTION_ENABLED:
        raise HTTPException(status_code=403, detail="Live execution is disabled in backend/.env.")
    if not core._market_open_now():
        raise HTTPException(status_code=409, detail="BUY is blocked outside the configured NSE session window.")

    cached = core.recommendation_cache.get(request.recommendation_id)
    if not cached or cached.get("state") != "BUY":
        raise HTTPException(status_code=409, detail="Only an active, unexpired BUY opportunity can be executed.")

    fresh = await overlay.enriched_deep_scan({
        "symbol": cached["symbol"],
        "exchange": cached.get("exchange", "NSE"),
        "coarse_score": cached.get("coarse_score", 0),
    })
    if fresh.get("state") != "BUY" or float(fresh.get("confidence") or 0) < core.policy.min_buy_confidence:
        raise HTTPException(status_code=409, detail="Fresh mode-specific revalidation no longer supports BUY.")

    old_entry = core._f(cached.get("entry_price"))
    fresh_entry = core._f(fresh.get("entry_price"))
    if old_entry <= 0 or fresh_entry > old_entry * (1 + core.policy.max_chase_pct / 100):
        raise HTTPException(status_code=409, detail="Price moved beyond the anti-chase limit. Order blocked.")
    quantity = int(fresh.get("quantity") or 0)
    if quantity < 1:
        raise HTTPException(status_code=409, detail="Risk-sized quantity is below one share.")

    groww = core.get_groww()
    mode = overlay.mode
    product = groww.PRODUCT_CNC if mode == "delivery" else core._get_intraday_product(groww)
    reference_id = f"{'DELIV' if mode == 'delivery' else 'INTRA'}-{core.uuid.uuid4().hex[:12]}"
    try:
        result = await asyncio.to_thread(
            groww.place_order,
            trading_symbol=fresh["symbol"], quantity=quantity, validity=groww.VALIDITY_DAY,
            exchange=core._exchange_constant(groww, fresh.get("exchange", "NSE")),
            segment=groww.SEGMENT_CASH, product=product, order_type=groww.ORDER_TYPE_LIMIT,
            transaction_type=groww.TRANSACTION_TYPE_BUY, price=fresh_entry, order_reference_id=reference_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=core._mask_error(exc)) from exc
    await core.broadcast({"type": "order", "data": result, "recommendation": fresh, "ts": core._now().isoformat()})
    return {
        "submitted": True, "broker": "groww", "trading_mode": mode,
        "broker_product": "CNC" if mode == "delivery" else "MIS",
        "order": result, "executed_recommendation": fresh,
    }
