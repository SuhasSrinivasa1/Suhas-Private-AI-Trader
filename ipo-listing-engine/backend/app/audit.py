from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any


class AuditLog:
    """Append-only daily JSONL audit log. Secrets must never be passed in payloads."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._dir = Path(os.getenv("IPO_SENTINEL_AUDIT_DIR", ".runtime/audit"))

    def _path_for(self, day: date) -> Path:
        return self._dir / f"{day.isoformat()}.jsonl"

    def append(self, event_type: str, *, severity: str = "INFO", **payload: Any) -> None:
        now = datetime.now(timezone.utc)
        record = {
            "timestamp": now.isoformat(),
            "event_type": event_type,
            "severity": severity,
            "payload": payload,
        }
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._path_for(now.date())
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def export(self, days: int = 7) -> str:
        days = max(1, min(31, int(days)))
        today = datetime.now(timezone.utc).date()
        rows: list[str] = []
        with self._lock:
            for offset in range(days - 1, -1, -1):
                path = self._path_for(today - timedelta(days=offset))
                if not path.exists():
                    continue
                rows.extend(line.rstrip("\n") for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        return "\n".join(rows) + ("\n" if rows else "")


audit_log = AuditLog()
