from __future__ import annotations

from fastapi import APIRouter, Depends

from .connection_settings import require_device_key
from .strategy_dashboard import StrategyEvidenceStore, strategy_summary

router = APIRouter(prefix="/strategies", tags=["strategies"])
store = StrategyEvidenceStore()


@router.get("/summary", dependencies=[Depends(require_device_key)])
def summary() -> dict:
    return strategy_summary(store)
