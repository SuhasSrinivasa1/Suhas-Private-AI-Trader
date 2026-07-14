from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import HTTPException, Query

import production23_main as base
from always_on_duty import AlwaysOnDutyEngine
from research_engine import ResearchEngine

core, runtime, app, calls = base.core, base.runtime, base.app, base.calls
research = ResearchEngine(core, runtime, calls)
duty = AlwaysOnDutyEngine(core, runtime, base._original_mode_scan)
app.title = "Suhas Private AI Trader — Production 2.4.1"
app.version = "2.4.1"

_original_scanner_status = core._scanner_status


def _always_on_scanner_status() -> str:
    status = _original_scanner_status()
    if status == "market_closed":
        return "off_hours_research"
    return status


core._scanner_status = _always_on_scanner_status


def _remove_legacy_health_route() -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == "/health"
            and "GET" in (getattr(route, "methods", set()) or set())
        )
    ]


def _remove_legacy_scan_route() -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == "/api/opportunities/scan-now"
            and "POST" in (getattr(route, "methods", set()) or set())
        )
    ]


_remove_legacy_health_route()
_remove_legacy_scan_route()


@app.get("/health")
def health24() -> dict[str, Any]:
    health = core.health()
    health.update(
        {
            "release": "2.4.1",
            "rules_contract_version": "2.4.0",
            "intraday_only": False,
            "trading_modes": ["intraday", "delivery"],
            "research_lab": True,
            "research_data_provider": "Groww Trading API",
            "mock_market_data": False,
            "always_on_duty": True,
            "duty_mode": duty.status()["mode"],
            "off_hours_research_enabled": True,
            "off_hours_execution_eligible": False,
        }
    )
    return health


@app.get("/api/production24/status")
def status24() -> dict[str, Any]:
    return {
        "release": "2.4.1",
        "groww_only_research_data": True,
        "mock_market_data": False,
        "research_lab": True,
        "backtesting": True,
        "walk_forward": True,
        "monte_carlo": True,
        "strategy_approval_gate": True,
        "always_on_duty": True,
        "off_hours_research": True,
        "off_hours_candidates_require_live_revalidation": True,
        "off_hours_paper_calls_created": False,
        "live_buy_sell_enabled": bool(core.GROWW_LIVE_EXECUTION_ENABLED),
        "rules_contract_version": "2.4.0",
        "duty": duty.status(),
    }


@app.get("/api/duty/status")
def duty_status() -> dict[str, Any]:
    return duty.status()


@app.get("/api/duty/snapshot")
def duty_snapshot() -> dict[str, Any]:
    return duty.status()


@app.post("/api/duty/run")
async def run_duty_now() -> dict[str, Any]:
    if not core._broker_configured():
        raise HTTPException(
            status_code=503,
            detail="Groww credentials are required for always-on research.",
        )
    if core._market_open_now():
        return {
            "status": "live_market_scan",
            "market_open": True,
            "message": "NSE is open; the live scanner is already active.",
            "items": list(core.latest_opportunities.values()),
        }
    return await duty.run_once(force=True, reason="manual_duty_run")


@app.post("/api/opportunities/scan-now")
async def scan_or_research_now() -> dict[str, Any]:
    if not core._broker_configured():
        raise HTTPException(
            status_code=503,
            detail="Groww credentials are required before scanning.",
        )

    if core._market_open_now():
        items = await core.scan_market_once()
        return {
            "items": items,
            "prices": core.latest_prices,
            "market_regime": core.latest_market_regime,
            "scan_at": core.last_scan_at,
            "scanner_status": "active",
            "scan_mode": "live_market_scan",
            "market_open": True,
            "execution_eligible": bool(core.GROWW_LIVE_EXECUTION_ENABLED),
            "message": "Live Groww market scan completed.",
        }

    snapshot = await duty.run_once(force=True, reason="manual_scan_button")
    return {
        "items": snapshot.get("items", []),
        "prices": core.latest_prices,
        "market_regime": core.latest_market_regime,
        "scan_at": snapshot.get("last_run_at"),
        "scanner_status": "off_hours_research",
        "scan_mode": "off_hours_research",
        "market_open": False,
        "execution_eligible": False,
        "message": (
            "NSE is closed. Groww-backed off-hours research completed; "
            "all candidates require live revalidation after the market opens."
        ),
        "duty": snapshot,
    }


@app.get("/api/research/strategies")
def strategies() -> dict[str, Any]:
    return {
        "items": research.catalog(),
        "data_policy": "All market tests require real Groww candles; no mock/synthetic prices.",
    }


async def _guard(coro):
    try:
        return await coro
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{exc.__class__.__name__}: Groww research request failed",
        ) from exc


@app.get("/api/research/regime/{symbol}")
async def regime(symbol: str, years: int = Query(5, ge=1, le=10)):
    async def run():
        rows, source = await research.candles(symbol, years)
        return {
            "symbol": symbol.upper(),
            "source": source,
            "regime": research.regime(rows),
        }

    return await _guard(run())


@app.get("/api/research/backtest/{symbol}/{strategy_id}")
async def backtest(
    symbol: str,
    strategy_id: str,
    years: int = Query(5, ge=1, le=10),
):
    return await _guard(research.backtest(symbol, strategy_id, years))


@app.get("/api/research/walk-forward/{symbol}/{strategy_id}")
async def walk_forward(
    symbol: str,
    strategy_id: str,
    years: int = Query(5, ge=3, le=10),
):
    return await _guard(research.walk_forward(symbol, strategy_id, years))


@app.get("/api/research/monte-carlo/{symbol}/{strategy_id}")
async def monte(
    symbol: str,
    strategy_id: str,
    years: int = Query(5, ge=1, le=10),
    simulations: int = Query(2000, ge=250, le=10000),
):
    return await _guard(
        research.monte_carlo(symbol, strategy_id, years, simulations)
    )


@app.get("/api/research/full-report/{symbol}/{strategy_id}")
async def report(
    symbol: str,
    strategy_id: str,
    years: int = Query(5, ge=3, le=10),
):
    return await _guard(research.full_report(symbol, strategy_id, years))


@app.get("/api/research/edge-monitor")
def edge_monitor():
    return research.calls_edge()


_original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _production241_lifespan(application):
    async with _original_lifespan(application):
        task = asyncio.create_task(
            duty.run_loop(), name="production241-always-on-duty"
        )
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app.router.lifespan_context = _production241_lifespan
