from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from .audit import audit_log


ORDER_EVENT_TYPES = {
    "LIVE_ENABLED",
    "LIVE_DISABLED",
    "ORDER_PLACING",
    "ORDER_ACCEPTED",
    "ORDER_PARTIAL",
    "ORDER_FILLED",
    "EXIT_PLACING",
    "POSITION_CLOSED",
    "ORDER_REJECTED",
    "ORDER_CANCELLED",
    "RISK_HALT",
    "FORCE_FLAT_STARTED",
}


@dataclass(frozen=True)
class OrderEvent:
    id: int
    timestamp: str
    event_type: str
    symbol: str | None = None
    side: str | None = None
    quantity: int | None = None
    price: float | None = None
    order_id: str | None = None
    message: str | None = None
    metadata: dict[str, Any] | None = None


class OrderEventStore:
    """Append-only event journal used by the Android live-notification service."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._path = Path(os.getenv("IPO_SENTINEL_ORDER_EVENT_FILE", ".runtime/order-events.jsonl"))
        self._next_id = self._discover_next_id()

    def _discover_next_id(self) -> int:
        if not self._path.exists():
            return 1
        last_id = 0
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    last_id = max(last_id, int(json.loads(line).get("id", 0)))
        except Exception:
            return 1
        return last_id + 1

    def publish(
        self,
        event_type: str,
        *,
        symbol: str | None = None,
        side: str | None = None,
        quantity: int | None = None,
        price: float | None = None,
        order_id: str | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> OrderEvent:
        normalized = event_type.upper().strip()
        if normalized not in ORDER_EVENT_TYPES:
            raise ValueError(f"Unsupported order event: {event_type}")

        with self._lock:
            event = OrderEvent(
                id=self._next_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type=normalized,
                symbol=symbol.upper().strip() if symbol else None,
                side=side.upper().strip() if side else None,
                quantity=quantity,
                price=price,
                order_id=order_id,
                message=message,
                metadata=metadata or {},
            )
            self._next_id += 1
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(event), separators=(",", ":"), ensure_ascii=False) + "\n")

        audit_log.append(
            "ORDER_LIFECYCLE",
            order_event_id=event.id,
            order_event_type=event.event_type,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            price=event.price,
            order_id=event.order_id,
            message=event.message,
        )
        return event

    def after(self, event_id: int, limit: int = 100) -> list[OrderEvent]:
        if not self._path.exists():
            return []
        limit = max(1, min(500, int(limit)))
        out: list[OrderEvent] = []
        with self._lock:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    if int(raw.get("id", 0)) <= event_id:
                        continue
                    out.append(OrderEvent(**raw))
                    if len(out) >= limit:
                        break
                except Exception:
                    continue
        return out


order_events = OrderEventStore()
