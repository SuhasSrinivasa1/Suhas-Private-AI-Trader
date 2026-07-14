from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query

import production23_main as base
from research_engine import ResearchEngine

core, runtime, app, calls = base.core, base.runtime, base.app, base.calls
research = ResearchEngine(core, runtime, calls)
app.title = "Suhas Private AI Trader — Production 2.4"
app.version = "2.4.0"


def _remove_legacy_health_route() -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == "/health"
            and "GET" in (getattr(route, "methods", set()) or set())
        )
    ]


_remove_legacy_health_route()


@app.get("/health")
def health24() -> dict[str, Any]:
    health = core.health()
    health.update(
        {
            "release": "2.4.0",
            "rules_contract_version": "2.4.0",
            "intraday_only": False,
            "trading_modes": ["intraday", "delivery"],
            "research_lab": True,
            "research_data_provider": "Groww Trading API",
            "mock_market_data": False,
        }
    )
    return health


@app.get("/api/production24/status")
def status24() -> dict[str, Any]:
    return {
        "release": "2.4.0",
        "groww_only_research_data": True,
        "mock_market_data": False,
        "research_lab": True,
        "backtesting": True,
        "walk_forward": True,
        "monte_carlo": True,
        "strategy_approval_gate": True,
        "rules_contract_version": "2.4.0",
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
