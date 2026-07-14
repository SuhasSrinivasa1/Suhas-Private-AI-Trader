from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import HTTPException

import production22_main as base
from call_results import CallResultsEngine

core = base.core
runtime = base.runtime
app = base.app
overlay = base.overlay

calls = CallResultsEngine(core, runtime, overlay)
_original_mode_scan = overlay.enriched_deep_scan


async def tracked_mode_scan(candidate: dict[str, Any]) -> dict[str, Any]:
    """Mode-specific scan plus paper-call logging and precision calibration."""
    result = await _original_mode_scan(candidate)
    learning = calls.learning_profile()
    observation = learning["observation"]
    result["calls_results_learning"] = {
        "state": learning["state"],
        "recommended_min_confidence": learning["recommended_min_confidence"],
        "target_precision_pct": learning["target_precision_pct"],
        "target_is_guaranteed": False,
        "paper_observation_complete": observation["complete"],
    }
    if (
        observation["complete"]
        and result.get("state") == "BUY"
        and float(result.get("confidence") or 0) < float(learning["recommended_min_confidence"])
    ):
        result["state"] = "WATCHING"
        result["action"] = "WATCH"
        result.setdefault("reasons", []).append(
            f"Automatic call calibration requires confidence >= {learning['recommended_min_confidence']:.1f} after the paper-observation phase."
        )
        result.setdefault("risk_vetoes", []).append("call_precision_calibration_threshold")
        result["recommendation_id"] = core._signal_identity(result)
        core.recommendation_cache[result["recommendation_id"]] = result
    if result.get("state") == "BUY":
        item = calls.record_prediction(result)
        if item:
            await core.broadcast({
                "type": "paper_call_created",
                "item": item,
                "summary": calls.summary(),
                "ts": core._now().isoformat(),
            })
    return result


runtime.enriched_deep_scan = tracked_mode_scan
core._deep_scan = tracked_mode_scan

app.title = "Suhas Private AI Trader — Production 2.3"
app.version = "2.3.0"

_original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _production23_lifespan(application):
    async with _original_lifespan(application):
        task = asyncio.create_task(calls.run_loop(), name="production23-calls-results")
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app.router.lifespan_context = _production23_lifespan


def _remove_legacy_production_status() -> None:
    app.router.routes[:] = [
        route for route in app.router.routes
        if not (getattr(route, "path", None) == "/api/production/status" and "GET" in (getattr(route, "methods", set()) or set()))
    ]


_remove_legacy_production_status()


@app.get("/api/production/status")
def production_status() -> dict[str, Any]:
    status = base.base.base.production_status()
    status.update({
        "release": "2.3.0",
        "rules_contract_version": "2.3.0",
        "calls_and_results": True,
        "paper_observation": calls.observation_status(),
        "call_learning": calls.learning_profile(),
        "trading_mode": overlay.status(),
    })
    return status


@app.get("/api/production23/status")
def production23_status() -> dict[str, Any]:
    return {
        "release": "2.3.0",
        "calls_and_results": True,
        "paper_observation_days": calls.observation_status()["observation_days"],
        "predictions_are_not_trades": True,
        "automatic_result_resolution": True,
        "visual_accuracy_dashboard": True,
        "automatic_precision_calibration": True,
        "target_precision_pct": calls.learning_profile()["target_precision_pct"],
        "target_precision_is_guaranteed": False,
        "live_orders_blocked_during_observation": calls.observation_status()["live_orders_blocked"],
        "rules_contract_version": "2.3.0",
    }


@app.get("/api/calls-results")
def calls_results(limit: int = 250, mode: str | None = None, status: str | None = None) -> dict[str, Any]:
    return {
        "items": calls.list_calls(limit=limit, mode=mode, status=status),
        "summary": calls.summary(),
    }


@app.get("/api/calls-results/summary")
def calls_results_summary() -> dict[str, Any]:
    return calls.summary()


@app.get("/api/calls-results/learning")
def calls_results_learning() -> dict[str, Any]:
    return calls.learning_profile()


@app.post("/api/calls-results/refresh")
async def refresh_calls_results() -> dict[str, Any]:
    resolved = await calls.resolve_once()
    return {"resolved": resolved, "summary": calls.summary()}


def _remove_mode_buy_route() -> None:
    app.router.routes[:] = [
        route for route in app.router.routes
        if not (getattr(route, "path", None) == "/api/orders/buy-recommendation" and "POST" in (getattr(route, "methods", set()) or set()))
    ]


_remove_mode_buy_route()


@app.post("/api/orders/buy-recommendation")
async def observation_gated_buy_recommendation(request: core.BuyRecommendationRequest) -> dict[str, Any]:
    observation = calls.observation_status()
    if not observation["complete"]:
        raise HTTPException(
            status_code=409,
            detail=(
                "The mandatory seven-day paper-call observation phase is active. "
                "Predictions are being logged and evaluated, but live BUY submission is blocked until the phase completes."
            ),
        )
    return await base.mode_aware_buy_recommendation(request)
