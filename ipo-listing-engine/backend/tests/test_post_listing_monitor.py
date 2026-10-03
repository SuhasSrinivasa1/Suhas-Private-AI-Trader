from datetime import date

from app.post_listing_monitor import (
    OpportunityType,
    PostListingOpportunityEngine,
    PostListingSnapshot,
    trading_day_number,
)
from app.services import ExchangeCalendar


def test_trading_day_number_skips_weekends_and_holidays():
    calendar = ExchangeCalendar(holidays={date(2026, 10, 2)}, source_ready=True)
    assert trading_day_number(calendar, date(2026, 10, 1), date(2026, 10, 5)) == 2


def test_monitor_expires_after_30_exchange_days():
    calendar = ExchangeCalendar(source_ready=True)
    snapshot = PostListingSnapshot(
        symbol="TEST",
        as_of=date(2026, 11, 20),
        listing_date=date(2026, 10, 1),
        last_price=120,
        issue_price=100,
        listing_price=110,
        anchored_vwap=115,
        rolling_high_20=125,
        rolling_low_20=105,
        ema9=118,
        ema20=116,
        relative_volume=1.2,
        relative_strength_pct=0.5,
        close_position=0.6,
    )
    result = PostListingOpportunityEngine().evaluate(calendar, snapshot)
    assert result.active is False
    assert result.action == "EXPIRED"


def test_post_ipo_base_breakout_is_detected():
    calendar = ExchangeCalendar(source_ready=True)
    snapshot = PostListingSnapshot(
        symbol="TEST",
        as_of=date(2026, 10, 14),
        listing_date=date(2026, 10, 1),
        last_price=131,
        issue_price=100,
        listing_price=110,
        anchored_vwap=119,
        rolling_high_20=131,
        rolling_low_20=106,
        ema9=126,
        ema20=121,
        relative_volume=2.4,
        relative_strength_pct=2.2,
        close_position=0.84,
    )
    result = PostListingOpportunityEngine().evaluate(calendar, snapshot)
    assert result.action == "PROBE_LONG"
    assert result.opportunity is OpportunityType.POST_IPO_BASE_BREAKOUT


def test_bearish_signal_waits_when_short_not_eligible():
    calendar = ExchangeCalendar(source_ready=True)
    snapshot = PostListingSnapshot(
        symbol="TEST",
        as_of=date(2026, 10, 8),
        listing_date=date(2026, 10, 1),
        last_price=88,
        issue_price=100,
        listing_price=105,
        anchored_vwap=98,
        rolling_high_20=110,
        rolling_low_20=86,
        ema9=91,
        ema20=96,
        relative_volume=2.2,
        relative_strength_pct=-2.5,
        close_position=0.16,
        shortable=False,
    )
    result = PostListingOpportunityEngine().evaluate(calendar, snapshot)
    assert result.action == "WAIT"
    assert "SHORT_NOT_ELIGIBLE" in result.reasons


def test_monitor_waits_when_official_calendar_not_ready():
    calendar = ExchangeCalendar(source_ready=False)
    snapshot = PostListingSnapshot(
        symbol="TEST",
        as_of=date(2026, 10, 5),
        listing_date=date(2026, 10, 5),
        last_price=110,
        issue_price=100,
        listing_price=105,
        anchored_vwap=107,
        rolling_high_20=110,
        rolling_low_20=104,
        ema9=109,
        ema20=108,
        relative_volume=2.0,
        relative_strength_pct=1.0,
        close_position=0.8,
    )
    result = PostListingOpportunityEngine().evaluate(calendar, snapshot)
    assert result.action == "WAIT"
    assert result.reasons == ("OFFICIAL_CALENDAR_NOT_READY",)
