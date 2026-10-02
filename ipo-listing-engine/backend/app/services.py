from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from threading import RLock
from typing import Iterable

from .domain import Ownership


@dataclass
class ExchangeCalendar:
    holidays: set[date] = field(default_factory=set)
    source_ready: bool = False

    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.holidays

    def next_trading_day(self, after: date) -> date:
        day = after + timedelta(days=1)
        for _ in range(15):
            if self.is_trading_day(day):
                return day
            day += timedelta(days=1)
        raise RuntimeError("Unable to resolve next trading day")

    def require_live_ready(self) -> None:
        if not self.source_ready:
            raise RuntimeError("Official exchange holiday/session calendar has not been loaded")


@dataclass(frozen=True)
class PositionRecord:
    symbol: str
    quantity: int
    product: str
    ownership: Ownership
    strategy_id: str | None
    broker_order_ids: tuple[str, ...] = ()


class OwnedPositionRegistry:
    """Only IPO Sentinel-tagged exposure can be mutated by this application."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, PositionRecord] = {}

    def reconcile(self, broker_positions: Iterable[dict]) -> None:
        with self._lock:
            for raw in broker_positions:
                symbol = str(raw.get("symbol") or raw.get("trading_symbol") or "").upper().strip()
                if not symbol:
                    continue
                tag = str(raw.get("strategy_id") or raw.get("tag") or "")
                ownership = Ownership.IPO_SENTINEL if tag.startswith("IPO_SENTINEL") else Ownership.EXTERNAL
                self._records[symbol] = PositionRecord(
                    symbol=symbol,
                    quantity=int(raw.get("quantity") or 0),
                    product=str(raw.get("product") or ""),
                    ownership=ownership,
                    strategy_id=tag or None,
                    broker_order_ids=tuple(raw.get("broker_order_ids") or ()),
                )

    def owned(self, symbol: str) -> PositionRecord | None:
        record = self._records.get(symbol.upper())
        return record if record and record.ownership is Ownership.IPO_SENTINEL else None

    def may_mutate(self, symbol: str) -> bool:
        record = self._records.get(symbol.upper())
        return record is None or record.ownership is Ownership.IPO_SENTINEL


@dataclass
class ShadowFill:
    symbol: str
    side: str
    quantity: int
    price: float
    charges: float = 0.0


class ShadowLedger:
    def __init__(self, capital: float = 100_000.0) -> None:
        self.starting_capital = float(capital)
        self.cash = float(capital)
        self.positions: dict[str, tuple[int, float]] = {}
        self.realized_pnl = 0.0

    def apply(self, fill: ShadowFill) -> None:
        symbol = fill.symbol.upper()
        qty, avg = self.positions.get(symbol, (0, 0.0))
        signed = fill.quantity if fill.side.upper() == "BUY" else -fill.quantity
        new_qty = qty + signed

        self.cash -= signed * fill.price
        self.cash -= fill.charges

        if qty and (qty > 0) != (new_qty > 0) and new_qty != 0:
            raise ValueError("Shadow ledger does not allow crossing through flat in one fill")

        if signed > 0:
            if qty >= 0:
                gross_qty = qty + signed
                avg = ((qty * avg) + (signed * fill.price)) / gross_qty if gross_qty else 0.0
            else:
                covered = min(abs(qty), signed)
                self.realized_pnl += covered * (avg - fill.price) - fill.charges
        else:
            sold = abs(signed)
            if qty > 0:
                closed = min(qty, sold)
                self.realized_pnl += closed * (fill.price - avg) - fill.charges
            elif qty <= 0:
                gross_qty = abs(qty) + sold
                avg = ((abs(qty) * avg) + (sold * fill.price)) / gross_qty if gross_qty else 0.0

        if new_qty == 0:
            avg = 0.0
        self.positions[symbol] = (new_qty, avg)

    def mark_to_market(self, prices: dict[str, float]) -> dict:
        unrealized = 0.0
        for symbol, (qty, avg) in self.positions.items():
            if qty == 0:
                continue
            mark = float(prices.get(symbol, avg))
            unrealized += qty * (mark - avg)
        return {
            "starting_capital": round(self.starting_capital, 2),
            "cash": round(self.cash, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "net_pnl": round(self.realized_pnl + unrealized, 2),
            "net_return_pct": round((self.realized_pnl + unrealized) / self.starting_capital * 100, 4),
        }
