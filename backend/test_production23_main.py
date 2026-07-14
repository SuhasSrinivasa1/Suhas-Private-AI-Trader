import asyncio

import pytest
from fastapi import HTTPException

import production23_main


def test_production23_routes_and_version():
    paths = {route.path for route in production23_main.app.routes}
    assert {
        "/api/production23/status",
        "/api/calls-results",
        "/api/calls-results/summary",
        "/api/calls-results/learning",
        "/api/calls-results/refresh",
    }.issubset(paths)
    assert production23_main.app.version == "2.3.0"


def test_production23_status_is_honest_about_99_percent():
    status = production23_main.production23_status()
    assert status["calls_and_results"] is True
    assert status["paper_observation_days"] == 7
    assert status["target_precision_pct"] == 99.0
    assert status["target_precision_is_guaranteed"] is False


def test_live_buy_is_blocked_during_first_week():
    request = production23_main.core.BuyRecommendationRequest(recommendation_id="paper-only")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(production23_main.observation_gated_buy_recommendation(request))
    assert exc.value.status_code == 409
    assert "paper-call observation phase" in exc.value.detail
