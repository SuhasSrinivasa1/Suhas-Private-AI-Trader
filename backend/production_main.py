from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import HTTPException

import main as core
from production_runtime import ProductionRuntime
from secure_store import groww_credentials_configured, resolve_groww_credentials


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
        runtime.daily_task = asyncio.create_task(runtime.daily_loop())
        try:
            yield
        finally:
            if runtime.daily_task:
                runtime.daily_task.cancel()
                try:
                    await runtime.daily_task
                except asyncio.CancelledError:
                    pass


core.app.router.lifespan_context = _production_lifespan
app = core.app
app.title = "Suhas Private AI Trader — Production"
app.version = "1.0.0"


@app.get("/api/production/status")
def production_status() -> dict[str, Any]:
    credentials = resolve_groww_credentials()
    return {
        "release": "1.0.0",
        "production_mode": True,
        "sample_data_enabled": False,
        "local_only": True,
        "broker": "groww",
        "broker_configured": credentials is not None,
        "credential_source": credentials.source if credentials else None,
        "live_execution_enabled": core.GROWW_LIVE_EXECUTION_ENABLED,
        "six_month_pattern_agent": True,
        "daily_recommendation_engine": True,
        "free_news_risk_check": True,
        "local_llm": "ollama",
        "daily_status": runtime.daily_snapshot.get("status", "not_generated"),
        "rules_contract_version": "1.0.0",
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
        return {
            "configured": True,
            "connected": True,
            "credential_source": credentials.source,
            "holdings_count": len(holdings),
            "positions_count": len(positions),
            "message": "Groww read-only connection verified.",
        }
    except Exception as exc:
        return {
            "configured": True,
            "connected": False,
            "credential_source": credentials.source,
            "holdings_count": 0,
            "positions_count": 0,
            "message": f"{exc.__class__.__name__}: Groww authentication or read-only verification failed. Check daily API approval and local credentials.",
        }


@app.post("/api/groww/reconnect")
async def groww_reconnect() -> dict[str, Any]:
    core._groww = None
    core._groww_error = None
    return await groww_status()


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


@app.get("/api/daily-recommendations")
def daily_recommendations() -> dict[str, Any]:
    if runtime.daily_snapshot:
        return runtime.daily_snapshot
    return {
        "status": "not_generated",
        "generated_for": None,
        "generated_at": None,
        "items": [],
        "message": "Run the first daily six-month analysis after Groww is connected.",
    }


@app.post("/api/daily-recommendations/refresh")
async def refresh_daily_recommendations() -> dict[str, Any]:
    if not core._broker_configured():
        raise HTTPException(status_code=503, detail="Configure Groww credentials before running six-month analysis.")
    return await runtime.build_daily_watchlist(force=True)
