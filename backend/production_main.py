from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

import main as core
from production2_runtime import ProductionRuntime
from secure_store import groww_credentials_configured, resolve_groww_credentials


class SellPositionRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    quantity: int = Field(gt=0)


def _production_broker_configured() -> bool:
    return groww_credentials_configured()


def _production_get_groww() -> Any:
    if core._groww is not None:
        return core._groww
    credentials = resolve_groww_credentials()
    if credentials is None:
        raise RuntimeError("Groww API credentials are not configured in macOS Keychain or backend environment.")
    try:
        from growwapi import GrowwAPI

        access_token = GrowwAPI.get_access_token(api_key=credentials.api_key, secret=credentials.api_secret)
        core._groww = GrowwAPI(access_token)
        core._groww_error = None
        return core._groww
    except Exception as exc:
        core._groww_error = f"{exc.__class__.__name__}: Groww authentication or API request failed."
        raise


core._broker_configured = _production_broker_configured
core.get_groww = _production_get_groww
runtime = ProductionRuntime(core)
core._deep_scan = runtime.enriched_deep_scan

_original_lifespan = core.app.router.lifespan_context


@asynccontextmanager
async def _production_lifespan(app):
    async with _original_lifespan(app):
        runtime.daily_task = asyncio.create_task(runtime.daily_loop(), name="production-daily-watchlist")
        await runtime.start_background_services()
        try:
            yield
        finally:
            if runtime.daily_task:
                runtime.daily_task.cancel()
                try:
                    await runtime.daily_task
                except asyncio.CancelledError:
                    pass
            await runtime.stop_background_services()


core.app.router.lifespan_context = _production_lifespan
app = core.app
app.title = "Suhas Private AI Trader — Production 2.0"
app.version = "2.0.0"


@app.get("/api/production/status")
def production_status() -> dict[str, Any]:
    credentials = resolve_groww_credentials()
    engine = runtime.status()
    return {
        "release": "2.0.0",
        "production_mode": True,
        "sample_data_enabled": False,
        "local_only": True,
        "broker": "groww",
        "broker_configured": credentials is not None,
        "credential_source": credentials.source if credentials else None,
        "live_execution_enabled": core.GROWW_LIVE_EXECUTION_ENABLED,
        "six_month_pattern_agent": True,
        "daily_recommendation_engine": True,
        "continuous_news_engine": True,
        "groww_event_feed": True,
        "local_sqlite_memory": True,
        "local_semantic_memory": True,
        "automatic_local_llm": True,
        "outcome_tracking": True,
        "adaptive_agent_weights": True,
        "sell_exit_agent": True,
        "provider_health_monitoring": True,
        "local_llm": "ollama",
        "daily_status": runtime.daily_snapshot.get("status", "not_generated"),
        "rules_contract_version": "2.0.0",
        "engine": engine,
    }


@app.get("/api/groww/status")
async def groww_status() -> dict[str, Any]:
    credentials = resolve_groww_credentials()
    if credentials is None:
        return {
            "configured": False,
            "connected": False,
            "credential_source": None,
            "holdings_count": 0,
            "positions_count": 0,
            "feed": runtime.feed_engine.status() if runtime.feed_engine else {"running": False},
            "message": "Groww credentials are not configured in macOS Keychain.",
        }
    try:
        groww = core.get_groww()
        holdings_payload, positions_payload = await asyncio.gather(
            asyncio.to_thread(groww.get_holdings_for_user, timeout=5),
            asyncio.to_thread(groww.get_positions_for_user, segment=groww.SEGMENT_CASH),
        )
        holdings = core._extract_list(holdings_payload, "holdings")
        positions = core._extract_list(positions_payload, "positions")
        core.latest_holdings = holdings
        core.latest_positions = positions
        asyncio.create_task(runtime.ensure_feed_started())
        runtime.store.update_provider_health("groww_rest", ok=True, message="Read-only holdings and positions verification passed.")
        return {
            "configured": True,
            "connected": True,
            "credential_source": credentials.source,
            "holdings_count": len(holdings),
            "positions_count": len(positions),
            "feed": runtime.feed_engine.status() if runtime.feed_engine else {"running": False},
            "message": "Groww read-only connection verified.",
        }
    except Exception as exc:
        runtime.store.update_provider_health("groww_rest", ok=False, message=f"{exc.__class__.__name__}: read-only verification failed")
        return {
            "configured": True,
            "connected": False,
            "credential_source": credentials.source,
            "holdings_count": 0,
            "positions_count": 0,
            "feed": runtime.feed_engine.status() if runtime.feed_engine else {"running": False},
            "message": f"{exc.__class__.__name__}: Groww authentication or read-only verification failed. Check daily API approval and local credentials.",
        }


@app.post("/api/groww/reconnect")
async def groww_reconnect() -> dict[str, Any]:
    if runtime.feed_engine:
        runtime.feed_engine.stop()
    runtime.feed_engine = None
    runtime._feed_start_attempted = False
    core._groww = None
    core._groww_error = None
    return await groww_status()


@app.get("/api/feed/status")
def feed_status() -> dict[str, Any]:
    return runtime.feed_engine.status() if runtime.feed_engine else {"running": False, "subscribed_count": 0, "last_event_at": None, "last_error": None}


@app.get("/api/pattern/{symbol}")
async def six_month_pattern(symbol: str) -> dict[str, Any]:
    if not core._broker_configured():
        raise HTTPException(status_code=503, detail="Groww credentials are required for six-month historical analysis.")
    try:
        return await runtime.get_pattern(symbol.upper().strip(), "NSE")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{exc.__class__.__name__}: historical pattern analysis failed.") from exc


@app.get("/api/news/{symbol}")
async def free_news(symbol: str) -> dict[str, Any]:
    return await runtime.get_news(symbol.upper().strip())


@app.get("/api/news-memory/{symbol}")
def news_memory(symbol: str, limit: int = 50) -> dict[str, Any]:
    return {"symbol": symbol.upper(), "items": runtime.store.recent_news(symbol, limit=limit)}


@app.get("/api/daily-recommendations")
def daily_recommendations() -> dict[str, Any]:
    if runtime.daily_snapshot:
        return runtime.daily_snapshot
    return {
        "status": "not_generated",
        "generated_for": None,
        "generated_at": None,
        "items": [],
        "message": "The automatic daily engine will generate the first six-month analysis after Groww is connected.",
    }


@app.post("/api/daily-recommendations/refresh")
async def refresh_daily_recommendations() -> dict[str, Any]:
    if not core._broker_configured():
        raise HTTPException(status_code=503, detail="Configure Groww credentials before running six-month analysis.")
    return await runtime.build_daily_watchlist(force=True)


@app.get("/api/memory/status")
def memory_status() -> dict[str, Any]:
    return runtime.store.stats()


@app.get("/api/provider-health")
def provider_health() -> dict[str, Any]:
    return {"items": runtime.store.provider_health()}


@app.get("/api/agent-performance")
def agent_performance() -> dict[str, Any]:
    return {"items": runtime.store.agent_stats(), "adaptive": True}


@app.get("/api/llm-analyses")
def llm_analyses(limit: int = 25) -> dict[str, Any]:
    return {"items": runtime.store.recent_llm_analyses(limit=limit)}


@app.get("/api/exit-signals")
def exit_signals() -> dict[str, Any]:
    return {"items": runtime.latest_exit_signals(), "execution": "human_confirmation_required"}


def _position_snapshot(symbol: str) -> tuple[int, str, float]:
    symbol = symbol.upper()
    intraday_qty = 0
    intraday_cost = 0.0
    for item in core.latest_positions:
        if core._holding_symbol(item) == symbol:
            qty = int(float(item.get("quantity") or item.get("qty") or item.get("net_quantity") or 0))
            avg = float(item.get("average_price") or item.get("avg_price") or item.get("net_price") or 0.0)
            if qty > 0:
                intraday_qty += qty
                intraday_cost += qty * avg
    if intraday_qty > 0:
        return intraday_qty, "MIS", intraday_cost / intraday_qty if intraday_qty else 0.0
    holding_qty = 0
    holding_cost = 0.0
    for item in core.latest_holdings:
        if core._holding_symbol(item) == symbol:
            qty = int(float(item.get("quantity") or item.get("qty") or 0))
            avg = float(item.get("average_price") or item.get("averagePrice") or item.get("avg_price") or 0.0)
            if qty > 0:
                holding_qty += qty
                holding_cost += qty * avg
    return holding_qty, "CNC", holding_cost / holding_qty if holding_qty else 0.0


@app.post("/api/orders/sell-position")
async def sell_position(request: SellPositionRequest) -> dict[str, Any]:
    """Human-confirmed controlled SELL. Never called automatically by an agent or LLM."""
    if not core.GROWW_LIVE_EXECUTION_ENABLED:
        raise HTTPException(status_code=403, detail="Live execution is disabled in backend/.env.")
    if not core._market_open_now():
        raise HTTPException(status_code=409, detail="SELL is blocked outside the configured NSE session window.")
    symbol = request.symbol.upper().strip()
    available, product_name, average_price = _position_snapshot(symbol)
    if available < request.quantity:
        raise HTTPException(status_code=409, detail=f"Requested quantity {request.quantity} exceeds available quantity {available}.")
    if available <= 0 or average_price <= 0:
        raise HTTPException(status_code=409, detail="No positive Groww position/holding is available for this symbol.")

    quote = await core._quote(symbol, "NSE")
    price = core._f(quote.get("bid_price") or quote.get("last_price"))
    if price <= 0:
        raise HTTPException(status_code=409, detail="Fresh executable SELL price is unavailable.")

    pattern, news = await asyncio.gather(runtime.get_pattern(symbol, "NSE"), runtime.get_news(symbol, force=True))
    from exit_engine import evaluate_exit_signal
    fresh_exit = evaluate_exit_signal(
        symbol=symbol,
        quantity=available,
        average_price=average_price,
        current_price=price,
        pattern=pattern,
        news=news,
    )
    if fresh_exit.get("action") == "HOLD":
        raise HTTPException(status_code=409, detail="Fresh exit revalidation no longer supports a SELL/trim action.")
    if fresh_exit.get("action") == "BOOK_PARTIAL_REVIEW":
        raise HTTPException(
            status_code=409,
            detail="The 3% profit-booking rule is advisory only because no automatic partial-exit quantity is defined. Review the position manually.",
        )
    if fresh_exit.get("action") == "TRIM_15":
        max_trim = max(1, round(available * 0.15))
        if request.quantity > max_trim:
            raise HTTPException(status_code=409, detail=f"Current rule allows a maximum trim of {max_trim} share(s) for this 5% profit trigger.")

    try:
        groww = core.get_groww()
        product = groww.PRODUCT_MIS if product_name == "MIS" else groww.PRODUCT_CNC
        reference_id = f"EXIT-{uuid.uuid4().hex[:12]}"
        result = await asyncio.to_thread(
            groww.place_order,
            trading_symbol=symbol,
            quantity=request.quantity,
            validity=groww.VALIDITY_DAY,
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            product=product,
            order_type=groww.ORDER_TYPE_LIMIT,
            transaction_type=groww.TRANSACTION_TYPE_SELL,
            price=price,
            order_reference_id=reference_id,
        )
        await core.broadcast({"type": "order", "data": result, "exit_signal": fresh_exit, "ts": core._now().isoformat()})
        return {"submitted": True, "broker": "groww", "side": "SELL", "symbol": symbol, "quantity": request.quantity, "price": price, "order": result}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{exc.__class__.__name__}: Groww SELL submission failed.") from exc
