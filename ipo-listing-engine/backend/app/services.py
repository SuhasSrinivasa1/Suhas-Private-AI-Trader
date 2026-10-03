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
        self._records: dict[str, list[PositionRecord]] = {}

    def reconcile(self, broker_positions: Iterable[dict]) -> None:
        rebuilt: dict[str, list[PositionRecord]] = {}
        for raw in broker_positions:
            symbol = str(raw.get("symbol") or raw.get("trading_symbol") or "").upper().strip()
            if not symbol:
                continue
            tag = str(raw.get("strategy_id") or raw.get("tag") or "")
            ownership = Ownership.IPO_SENTINEL if tag.startswith("IPO_SENTINEL") else Ownership.EXTERNAL
            rebuilt.setdefault(symbol, []).append(
                PositionRecord(
                    symbol=symbol,
                    quantity=int(raw.get("quantity") or 0),
                    product=str(raw.get("product") or ""),
                    ownership=ownership,
                    strategy_id=tag or None,
                    broker_order_ids=tuple(raw.get("broker_order_ids") or ()),
                )
            )
        with self._lock:
            self._records = rebuilt

    def owned(self, symbol: str) -> PositionRecord | None:
        records = [
            record
            for record in self._records.get(symbol.upper(), [])
            if record.ownership is Ownership.IPO_SENTINEL
        ]
        if not records:
            return None
        quantity = sum(record.quantity for record in records)
        order_ids = tuple(
            order_id
            for record in records
            for order_id in record.broker_order_ids
        )
        return PositionRecord(
            symbol=symbol.upper(),
            quantity=quantity,
            product=records[0].product,
            ownership=Ownership.IPO_SENTINEL,
            strategy_id="IPO_SENTINEL_AGGREGATE",
            broker_order_ids=order_ids,
        )

    def external_quantity(self, symbol: str) -> int:
        return sum(
            record.quantity
            for record in self._records.get(symbol.upper(), [])
            if record.ownership is Ownership.EXTERNAL
        )

    def may_mutate(self, symbol: str) -> bool:
        records = self._records.get(symbol.upper(), [])
        return not records or any(
            record.ownership is Ownership.IPO_SENTINEL
            for record in records
        )


@dataclass(frozen=True)
class ShadowFill:
    symbol: str
    side: str
    quantity: int
    price: float
    charges: float = 0.0


@dataclass
class ShadowPosition:
    quantity: int
    average_price: float
    entry_charges: float = 0.0


class ShadowLedger:
    """Long/short shadow ledger that reconciles net P&L to marked account equity."""

    def __init__(self, capital: float = 100_000.0) -> None:
        if capital <= 0:
            raise ValueError("capital must be positive")
        self.starting_capital = float(capital)
        self.cash = float(capital)
        self.positions: dict[str, ShadowPosition] = {}
        self.realized_gross_pnl = 0.0
        self.realized_pnl = 0.0
        self.charges_total = 0.0

    def apply(self, fill: ShadowFill) -> None:
        if fill.quantity <= 0:
            raise ValueError("fill quantity must be positive")
        if fill.price <= 0:
            raise ValueError("fill price must be positive")
        if fill.charges < 0:
            raise ValueError("charges cannot be negative")

        side = fill.side.upper().strip()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")

        symbol = fill.symbol.upper().strip()
        position = self.positions.get(symbol, ShadowPosition(0, 0.0, 0.0))
        qty = position.quantity
        signed = fill.quantity if side == "BUY" else -fill.quantity
        new_qty = qty + signed

        if qty and new_qty and (qty > 0) != (new_qty > 0):
            raise ValueError("Shadow ledger does not allow crossing through flat in one fill")

        self.cash -= signed * fill.price
        self.cash -= fill.charges
        self.charges_total += fill.charges

        opening_or_adding = (
            qty == 0
            or (qty > 0 and signed > 0)
            or (qty < 0 and signed < 0)
        )

        if opening_or_adding:
            old_abs = abs(qty)
            add_abs = abs(signed)
            total_abs = old_abs + add_abs
            average_price = (
                (old_abs * position.average_price)
                + (add_abs * fill.price)
            ) / total_abs
            self.positions[symbol] = ShadowPosition(
                quantity=new_qty,
                average_price=average_price,
                entry_charges=position.entry_charges + fill.charges,
            )
            return

        closed = min(abs(qty), abs(signed))
        entry_charge_alloc = (
            position.entry_charges * (closed / abs(qty))
            if qty
            else 0.0
        )
        gross = (
            closed * (fill.price - position.average_price)
            if qty > 0
            else closed * (position.average_price - fill.price)
        )
        self.realized_gross_pnl += gross
        self.realized_pnl += gross - entry_charge_alloc - fill.charges

        remaining_entry_charges = max(
            0.0,
            position.entry_charges - entry_charge_alloc,
        )
        if new_qty == 0:
            self.positions.pop(symbol, None)
        else:
            self.positions[symbol] = ShadowPosition(
                quantity=new_qty,
                average_price=position.average_price,
                entry_charges=remaining_entry_charges,
            )

    def mark_to_market(self, prices: dict[str, float]) -> dict:
        unrealized = 0.0
        market_value = 0.0
        deployed = 0.0
        open_positions = []

        for symbol, position in self.positions.items():
            mark = float(prices.get(symbol, position.average_price))
            if mark <= 0:
                mark = position.average_price

            qty = position.quantity
            market_value += qty * mark
            deployed += abs(qty) * mark
            position_unrealized = (
                qty * (mark - position.average_price)
                - position.entry_charges
            )
            unrealized += position_unrealized
            open_positions.append(
                {
                    "symbol": symbol,
                    "quantity": qty,
                    "average_price": round(position.average_price, 4),
                    "mark_price": round(mark, 4),
                    "unrealized_pnl": round(position_unrealized, 2),
                }
            )

        equity = self.cash + market_value
        net_pnl = equity - self.starting_capital

        return {
            "starting_capital": round(self.starting_capital, 2),
            "cash": round(self.cash, 2),
            "equity": round(equity, 2),
            "capital_deployed": round(deployed, 2),
            "realized_gross_pnl": round(self.realized_gross_pnl, 2),
            "charges": round(self.charges_total, 2),
            "charges_paid": round(self.charges_total, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "net_pnl": round(net_pnl, 2),
            "net_return_pct": round(
                net_pnl / self.starting_capital * 100,
                4,
            ),
            "open_positions": open_positions,
        }
