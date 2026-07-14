from __future__ import annotations

from typing import Any

import production_main as base
from full_universe_overlay import install_full_nse_universe

core = base.core
runtime = base.runtime
app = base.app

install_full_nse_universe(core)
app.title = "Suhas Private AI Trader — Production 2.1"
app.version = "2.1.0"


@app.get("/api/production21/status")
def production21_status() -> dict[str, Any]:
    return {
        "release": "2.1.0",
        "full_nse_equity_universe": True,
        "universe_size": len(core.SCANNER_UNIVERSE),
        "predictions_available": len(core.latest_universe_predictions),
        "starting_capital_inr": 20000,
        "stretch_target_inr": 100000,
        "target_horizon_calendar_days": 30,
        "target_is_guaranteed": False,
        "zero_loss_is_guaranteed": False,
        "capital_preservation_priority": True,
        "public_lawful_information_only": True,
        "insider_trading_prohibited": True,
        "rules_contract_version": "2.1.0",
    }


@app.get("/api/universe/predictions")
def universe_predictions(limit: int = 250) -> dict[str, Any]:
    """Latest rotating full-NSE discovery predictions. These are not actionable BUY instructions."""
    safe_limit = max(1, min(2000, int(limit)))
    items = sorted(
        core.latest_universe_predictions.values(),
        key=lambda item: core._f(item.get("coarse_score"), 0),
        reverse=True,
    )[:safe_limit]
    total = len(core.SCANNER_UNIVERSE)
    covered = len(core.latest_universe_predictions)
    return {
        "scope": "all tradable NSE CASH equities",
        "universe_size": total,
        "predictions_available": covered,
        "coverage_pct": round((covered / total) * 100, 2) if total else 0.0,
        "items": items,
        "actionable": False,
        "note": "Every symbol is scanned in rotating provider-safe batches. Only deep live revalidation can produce an actionable signal.",
    }


@app.get("/api/capital-objective")
def capital_objective() -> dict[str, Any]:
    return {
        "starting_capital_inr": 20000,
        "stretch_target_inr": 100000,
        "target_horizon_calendar_days": 30,
        "target_multiple": 5.0,
        "guaranteed": False,
        "zero_loss_guaranteed": False,
        "capital_preservation_priority": True,
        "risk_rules_may_not_be_relaxed_to_hit_target": True,
    }
