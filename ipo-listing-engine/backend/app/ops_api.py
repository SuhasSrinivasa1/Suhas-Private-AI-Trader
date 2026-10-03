from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .audit import audit_log
from .connection_api import validate_connection
from .connection_settings import require_device_key
from .live_state import live_state_store
from .order_events import order_events

router = APIRouter(tags=["operations"])


class LiveStateRequest(BaseModel):
    enabled: bool
    budget_rupees: int = Field(default=100_000, ge=10_000, le=100_000)


@router.get("/live/state", dependencies=[Depends(require_device_key)])
def get_live_state() -> dict:
    state = live_state_store.load()
    return {
        "enabled": state.enabled,
        "budget_rupees": state.budget_rupees,
        "updated_at": state.updated_at,
    }


@router.post("/live/state", dependencies=[Depends(require_device_key)])
async def set_live_state(payload: LiveStateRequest) -> dict:
    if payload.enabled:
        readiness = await validate_connection()
        if not readiness.get("live_execution_ready", False):
            audit_log.append(
                "LIVE_ENABLE_REJECTED",
                severity="WARN",
                groww_auth_ok=readiness.get("groww_auth_ok", False),
                static_ip_matches=readiness.get("static_ip_matches", False),
                static_ip_confirmed=readiness.get("static_ip_confirmed", False),
            )
            raise HTTPException(status_code=409, detail="Groww and static-IP validation must pass before live execution")

    state = live_state_store.save(payload.enabled, payload.budget_rupees)
    event_type = "LIVE_ENABLED" if state.enabled else "LIVE_DISABLED"
    event = order_events.publish(
        event_type,
        message=(
            f"Live auto-trading enabled with budget ₹{state.budget_rupees}"
            if state.enabled
            else "Live auto-trading disabled"
        ),
        metadata={"budget_rupees": state.budget_rupees},
    )
    audit_log.append(
        "LIVE_STATE_CHANGED",
        enabled=state.enabled,
        budget_rupees=state.budget_rupees,
        order_event_id=event.id,
    )
    return {
        "enabled": state.enabled,
        "budget_rupees": state.budget_rupees,
        "updated_at": state.updated_at,
    }


@router.get("/events/orders", dependencies=[Depends(require_device_key)])
def get_order_events(after_id: int = 0, limit: int = 100) -> dict:
    events = order_events.after(max(0, after_id), limit)
    return {
        "events": [event.__dict__ for event in events],
        "last_id": events[-1].id if events else max(0, after_id),
    }


@router.get(
    "/audit/export",
    dependencies=[Depends(require_device_key)],
    response_class=PlainTextResponse,
)
def export_audit(days: int = Query(default=7, ge=1, le=31)) -> str:
    audit_log.append("AUDIT_EXPORT_REQUESTED", days=days)
    return audit_log.export(days)
