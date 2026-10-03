from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock


@dataclass(frozen=True)
class TradeEvent:
    id: int
    event_type: str
    symbol: str | None
    side: str | None
    quantity: int | None
    price: float | None
    order_id: str | None
    message: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


class TradeEventStore:
    """Durable append-only event stream consumed by the Android live monitor."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._lock = RLock()
        configured = path or os.getenv(
            "IPO_SENTINEL_TRADE_EVENT_DB",
            ".runtime/trade-events.sqlite3",
        )
        self._path = Path(configured)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_event (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    symbol TEXT,
                    side TEXT,
                    quantity INTEGER,
                    price REAL,
                    order_id TEXT,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_trade_event_created ON trade_event(created_at)"
            )

    def publish(
        self,
        *,
        event_type: str,
        symbol: str | None = None,
        side: str | None = None,
        quantity: int | None = None,
        price: float | None = None,
        order_id: str | None = None,
        message: str = "",
    ) -> TradeEvent:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO trade_event(
                    event_type, symbol, side, quantity, price, order_id, message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type.upper().strip(),
                    symbol.upper().strip() if symbol else None,
                    side.upper().strip() if side else None,
                    quantity,
                    price,
                    order_id,
                    message,
                    created_at,
                ),
            )
            event_id = int(cursor.lastrowid)
        return TradeEvent(
            id=event_id,
            event_type=event_type.upper().strip(),
            symbol=symbol.upper().strip() if symbol else None,
            side=side.upper().strip() if side else None,
            quantity=quantity,
            price=price,
            order_id=order_id,
            message=message,
            created_at=created_at,
        )

    def after(self, event_id: int, limit: int = 100) -> tuple[TradeEvent, ...]:
        safe_limit = max(1, min(100, int(limit)))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, event_type, symbol, side, quantity, price, order_id, message, created_at
                FROM trade_event
                WHERE id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (max(0, int(event_id)), safe_limit),
            ).fetchall()
        return tuple(TradeEvent(**dict(row)) for row in rows)
