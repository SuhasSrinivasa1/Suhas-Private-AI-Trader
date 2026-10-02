from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class ResearchScheduler:
    research_job: Callable[[], None]

    def build(self) -> BackgroundScheduler:
        scheduler = BackgroundScheduler(timezone=IST)
        # Run after the NSE cash session. The job itself resolves the next trading day
        # from the official exchange calendar and may do nothing on irrelevant days.
        scheduler.add_job(
            self.research_job,
            trigger="cron",
            hour=16,
            minute=0,
            id="next_listing_research",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        return scheduler


def ist_now() -> datetime:
    return datetime.now(IST)
