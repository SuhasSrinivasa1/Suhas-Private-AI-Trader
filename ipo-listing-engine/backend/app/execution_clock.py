from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class IntradayClockPolicy:
    """
    IPO Sentinel uses its own earlier force-flat deadline.

    Groww's current published stock MIS auto square-off begins at 15:20 IST.
    IPO Sentinel deliberately starts its forced-exit workflow at 15:05 IST,
    leaving a 15-minute execution/retry buffer for volatile or illiquid new listings.
    """
    force_flat_time: time = time(15, 5)
    broker_auto_squareoff_time: time = time(15, 20)

    def status(self, now: datetime) -> str:
        local = now.astimezone(IST)
        if local.time() >= self.broker_auto_squareoff_time:
            return "BROKER_AUTO_SQUAREOFF_WINDOW"
        if local.time() >= self.force_flat_time:
            return "IPO_SENTINEL_FORCE_FLAT"
        return "TRADING_ALLOWED"

    def must_force_flat(self, now: datetime) -> bool:
        return self.status(now) in {"IPO_SENTINEL_FORCE_FLAT", "BROKER_AUTO_SQUAREOFF_WINDOW"}
