from __future__ import annotations

import asyncio
from time import monotonic

from fastapi import APIRouter, Depends, Query

from .connection_settings import require_device_key
from .trade_events import TradeEventStore

router = APIRouter(prefix="/events", tags=["trade-events"])
store = TradeEventStore()


@router.get("", dependencies=[Depends(require_device_key)])
async def trade_events(
    after_id: int = Query(default=0, ge=0),
    timeout: int = Query(default=20, ge=1, le=25),
) -> dict:
    deadline = monotonic() + timeout

    while True:
        events = store.after(after_id)
        if events or monotonic() >= deadline:
            return {
                "events": [event.to_dict() for event in events],
                "last_id": events[-1].id if events else after_id,
            }
        await asyncio.sleep(0.5)
