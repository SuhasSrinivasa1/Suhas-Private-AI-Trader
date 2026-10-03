from datetime import datetime

from app.scheduler import IST, ResearchScheduler


def test_research_scheduler_covers_weekends_and_listing_transition():
    calls = []

    def job(**kwargs):
        calls.append(kwargs)

    scheduler = ResearchScheduler(job).build()
    jobs = {item.id: item for item in scheduler.get_jobs()}

    assert "ipo_research_after_market" in jobs
    assert "ipo_research_pre_market" in jobs
    for minute in (0, 35, 46, 58):
        assert f"ipo_listing_recheck_09{minute:02d}" in jobs
    for minute in (0, 1, 2, 3, 5, 10, 15):
        assert f"ipo_listing_recheck_10{minute:02d}" in jobs

    # The after-market trigger intentionally has no weekday restriction,
    # so Saturday/Sunday refreshes still build the next-week plan.
    after = str(jobs["ipo_research_after_market"].trigger)
    pre = str(jobs["ipo_research_pre_market"].trigger)
    assert "hour='16'" in after and "minute='5'" in after
    assert "day_of_week='mon-fri'" not in after
    assert "day_of_week='mon-fri'" in pre
    assert "hour='8'" in pre and "minute='30'" in pre
