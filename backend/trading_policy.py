from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import floor
from typing import Any, Literal

Direction = Literal["long", "short"]
SUPPORTED_MARKETS = {"NSE", "BSE", "NYSE", "NASDAQ"}


@dataclass(frozen=True)
class TradingPolicy:
    enabled: bool = True
    allow_live_execution: bool = False
    max_risk_per_trade_pct: float =