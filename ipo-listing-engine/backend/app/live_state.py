from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock


@dataclass(frozen=True)
class LiveState:
    enabled: bool = False
    budget_rupees: int = 100_000
    updated_at: str | None = None


class LiveStateStore:
    """Server-authoritative live execution state. Defaults to disabled."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._path = Path(os.getenv("IPO_SENTINEL_LIVE_STATE_FILE", ".runtime/live-state.json"))

    def load(self) -> LiveState:
        if not self._path.exists():
            return LiveState()
        with self._lock:
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                return LiveState(
                    enabled=bool(raw.get("enabled", False)),
                    budget_rupees=max(10_000, min(100_000, int(raw.get("budget_rupees", 100_000)))),
                    updated_at=raw.get("updated_at"),
                )
            except Exception:
                return LiveState()

    def save(self, enabled: bool, budget_rupees: int) -> LiveState:
        state = LiveState(
            enabled=bool(enabled),
            budget_rupees=max(10_000, min(100_000, int(budget_rupees))),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(state), separators=(",", ":")), encoding="utf-8")
            tmp.replace(self._path)
        return state


live_state_store = LiveStateStore()
