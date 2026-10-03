from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class Action(StrEnum):
    WAIT = "WAIT"
    PROBE_LONG = "PROBE_LONG"
    BUILD_LONG = "BUILD_LONG"
    HOLD_LONG = "HOLD_LONG"
    REDUCE_LONG = "REDUCE_LONG"
    FLAT = "FLAT"
    PROBE_SHORT = "PROBE_SHORT"
    BUILD_SHORT = "BUILD_SHORT"
    HOLD_SHORT = "HOLD_SHORT"
    COVER_SHORT = "COVER_SHORT"
    HALTED = "HALTED"


class Ownership(StrEnum):
    IPO_SENTINEL = "IPO_SENTINEL"
    EXTERNAL = "EXTERNAL"


@dataclass(frozen=True)
class ListingCandidate:
    symbol: str
    company_name: str
    listing_date: date
    issue_price: float
    exchange: str = "NSE"
    is_sme: bool = False


@dataclass(frozen=True)
class LiveFeatures:
    symbol: str
    at: datetime
    ltp: float
    vwap: float
    rvol: float
    spread_bps: float
    buy_qty: float
    sell_qty: float
    first_5m_high: float | None = None
    first_5m_low: float | None = None
    listing_price: float | None = None
    issue_price: float | None = None
    nifty_return_pct: float = 0.0
    sector_return_pct: float = 0.0
    circuit_distance_pct: float | None = None
    shortable: bool = False
    data_fresh: bool = True

    @property
    def depth_imbalance(self) -> float:
        total = max(self.buy_qty + self.sell_qty, 0.0)
        return 0.0 if total == 0 else (self.buy_qty - self.sell_qty) / total


@dataclass(frozen=True)
class Decision:
    action: Action
    score: float
    confidence: float
    budget_rupees: int
    reason_codes: tuple[str, ...]
