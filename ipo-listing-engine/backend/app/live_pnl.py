from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from .audit import audit_log


@dataclass(frozen=True)
class LiveFill:
    timestamp: str
    order_id: str
    symbol: str
    side: str
    quantity: int
    price: float
    charges: float
    charges_estimated: bool = True


class AttributableLiveLedger:
    """
    Persistent P&L ledger containing only fills explicitly tied to IPO Sentinel orders.

    Broker portfolio positions are never imported into this ledger. Cumulative broker
    fill quantities are converted to deltas idempotently, so repeated reconciliation
    cannot double-count a fill.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._path = Path(os.getenv("IPO_SENTINEL_LIVE_LEDGER_FILE", ".runtime/live-ledger.json"))

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "orders": {},
            "positions": {},
            "realized_gross_pnl": 0.0,
            "charges": 0.0,
            "fills": [],
            "updated_at": None,
        }

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return self._empty()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else self._empty()
        except Exception:
            return self._empty()

    def _write(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    @staticmethod
    def _apply_position(
        state: dict[str, Any],
        *,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
    ) -> None:
        positions = state.setdefault("positions", {})
        current = positions.get(symbol) or {"quantity": 0, "avg_price": 0.0, "last_mark": price}
        old_qty = int(current.get("quantity") or 0)
        old_avg = float(current.get("avg_price") or 0.0)
        signed = quantity if side == "BUY" else -quantity
        new_qty = old_qty + signed

        # IPO Sentinel forbids crossing a broker-reconciled position through flat in a
        # single order. Treat such a fill as an accounting integrity violation.
        if old_qty and new_qty and (old_qty > 0) != (new_qty > 0):
            raise ValueError("Live fill would cross through flat; reconcile before reversing direction")

        realized = 0.0
        new_avg = old_avg
        if signed > 0:
            if old_qty >= 0:
                gross_qty = old_qty + signed
                new_avg = ((old_qty * old_avg) + (signed * price)) / gross_qty if gross_qty else 0.0
            else:
                covered = min(abs(old_qty), signed)
                realized = covered * (old_avg - price)
        else:
            sold = abs(signed)
            if old_qty > 0:
                closed = min(old_qty, sold)
                realized = closed * (price - old_avg)
            else:
                gross_qty = abs(old_qty) + sold
                new_avg = ((abs(old_qty) * old_avg) + (sold * price)) / gross_qty if gross_qty else 0.0

        if new_qty == 0:
            new_avg = 0.0
        positions[symbol] = {
            "quantity": new_qty,
            "avg_price": new_avg,
            "last_mark": price,
        }
        state["realized_gross_pnl"] = float(state.get("realized_gross_pnl") or 0.0) + realized

    def record_cumulative_fill(
        self,
        *,
        order_id: str,
        symbol: str,
        side: str,
        cumulative_quantity: int,
        average_price: float,
        estimated_charge_bps_per_fill: float = 12.5,
    ) -> LiveFill | None:
        oid = order_id.strip()
        ticker = symbol.upper().strip()
        direction = side.upper().strip()
        if not oid or not ticker:
            raise ValueError("IPO Sentinel order ID and symbol are required")
        if direction not in {"BUY", "SELL"}:
            raise ValueError("Live ledger side must be BUY or SELL")
        if cumulative_quantity <= 0 or average_price <= 0:
            return None

        with self._lock:
            state = self._read()
            orders = state.setdefault("orders", {})
            previous = orders.get(oid) or {}
            prior_qty = int(previous.get("cumulative_quantity") or 0)
            prior_avg = float(previous.get("average_price") or 0.0)
            if cumulative_quantity <= prior_qty:
                return None

            delta_qty = cumulative_quantity - prior_qty
            cumulative_notional = cumulative_quantity * average_price
            prior_notional = prior_qty * prior_avg
            delta_price = (cumulative_notional - prior_notional) / delta_qty
            if delta_price <= 0:
                raise ValueError("Broker cumulative fill produced a non-positive incremental price")

            charge_bps = max(0.0, float(estimated_charge_bps_per_fill))
            charges = delta_qty * delta_price * charge_bps / 10_000.0
            self._apply_position(
                state,
                symbol=ticker,
                side=direction,
                quantity=delta_qty,
                price=delta_price,
            )
            state["charges"] = float(state.get("charges") or 0.0) + charges
            timestamp = datetime.now(timezone.utc).isoformat()
            fill = LiveFill(
                timestamp=timestamp,
                order_id=oid,
                symbol=ticker,
                side=direction,
                quantity=delta_qty,
                price=round(delta_price, 6),
                charges=round(charges, 6),
                charges_estimated=True,
            )
            state.setdefault("fills", []).append(asdict(fill))
            orders[oid] = {
                "symbol": ticker,
                "side": direction,
                "cumulative_quantity": cumulative_quantity,
                "average_price": average_price,
                "updated_at": timestamp,
            }
            state["updated_at"] = timestamp
            self._write(state)

        audit_log.append(
            "LIVE_LEDGER_FILL",
            order_id=oid,
            symbol=ticker,
            side=direction,
            quantity=delta_qty,
            price=round(delta_price, 6),
            estimated_charges=round(charges, 6),
        )
        return fill

    def update_marks(self, prices: dict[str, float]) -> None:
        with self._lock:
            state = self._read()
            changed = False
            for symbol, raw_price in prices.items():
                ticker = symbol.upper().strip()
                price = float(raw_price)
                if price <= 0 or ticker not in state.get("positions", {}):
                    continue
                state["positions"][ticker]["last_mark"] = price
                changed = True
            if changed:
                state["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._write(state)

    def summary(self, *, capital_base: float = 100_000.0) -> dict[str, Any]:
        with self._lock:
            state = self._read()

        unrealized = 0.0
        deployed = 0.0
        open_positions = []
        for symbol, raw in (state.get("positions") or {}).items():
            quantity = int(raw.get("quantity") or 0)
            avg = float(raw.get("avg_price") or 0.0)
            mark = float(raw.get("last_mark") or avg)
            if quantity == 0:
                continue
            unrealized += quantity * (mark - avg)
            deployed += abs(quantity * mark)
            open_positions.append(
                {
                    "symbol": symbol,
                    "quantity": quantity,
                    "avg_price": round(avg, 4),
                    "mark": round(mark, 4),
                    "unrealized_pnl": round(quantity * (mark - avg), 2),
                }
            )

        gross = float(state.get("realized_gross_pnl") or 0.0)
        charges = float(state.get("charges") or 0.0)
        realized_net = gross - charges
        net = realized_net + unrealized
        capital = max(1.0, float(capital_base))
        return {
            "capital_base": round(capital, 2),
            "capital_deployed": round(deployed, 2),
            "realized_gross_pnl": round(gross, 2),
            "estimated_charges": round(charges, 2),
            "realized_pnl": round(realized_net, 2),
            "unrealized_pnl": round(unrealized, 2),
            "net_pnl": round(net, 2),
            "return_pct": round(net / capital * 100.0, 4),
            "open_positions": open_positions,
            "fill_count": len(state.get("fills") or []),
            "charges_are_estimated": True,
            "updated_at": state.get("updated_at"),
        }


live_ledger = AttributableLiveLedger()
