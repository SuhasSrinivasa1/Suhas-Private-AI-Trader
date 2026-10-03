from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class ResearchScheduler:
    research_job: Callable[..., None]

    def build(self) -> BackgroundScheduler:
        scheduler = BackgroundScheduler(timezone=IST)

        # Full refresh after the cash session on every calendar day, including weekends.
        # Weekend runs build the next-week plan from the latest official NSE issue feed.
        scheduler.add_job(
            lambda: self.research_job(trigger="after_market"),
            trigger="cron",
            hour=16,
            minute=5,
            id="ipo_research_after_market",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Revalidate the queue before the market on weekdays because listing dates,
        # exchange symbols or broker instrument availability can change overnight.
        scheduler.add_job(
            lambda: self.research_job(trigger="pre_market"),
            trigger="cron",
            day_of_week="mon-fri",
            hour=8,
            minute=30,
            id="ipo_research_pre_market",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Re-check instrument availability around special pre-open/listing transition.
        for minute in (0, 35, 46, 58):
            scheduler.add_job(
                lambda: self.research_job(trigger="listing_day_recheck"),
                trigger="cron",
                day_of_week="mon-fri",
                hour=9,
                minute=minute,
                id=f"ipo_listing_recheck_09{minute:02d}",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
        scheduler.add_job(
            lambda: self.research_job(trigger="continuous_open_recheck"),
            trigger="cron",
            day_of_week="mon-fri",
            hour=10,
            minute=0,
            id="ipo_listing_recheck_1000",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        return scheduler


def ist_now() -> datetime:
    return datetime.now(IST)
