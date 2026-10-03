from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from .services import ExchangeCalendar


class OpportunityType(StrEnum):
    NONE = "NONE"
    EARLY_CONTINUATION = "EARLY_CONTINUATION"
    HEALTHY_PULLBACK = "HEALTHY_PULLBACK"
    ANCHORED_VWAP_RECLAIM = "ANCHORED_VWAP_RECLAIM"
    POST_IPO_BASE_BREAKOUT = "POST_IPO_BASE_BREAKOUT"
    FAILED_BREAKDOWN_RECLAIM = "FAILED_BREAKDOWN_RECLAIM"
    VOLUME_REVIVAL = "VOLUME_REVIVAL"
    INTRADAY_FADE_SHORT = "INTRADAY_FADE_SHORT"


@dataclass(frozen=True)
class PostListingSnapshot:
    symbol: str
    as_of: date
    listing_date: date
    last_price: float
    issue_price: float
    listing_price: float
    anchored_vwap: float
    rolling_high_20: float
    rolling_low_20: float
    ema9: float
    ema20: float
    relative_volume: float
    relative_strength_pct: float
    close_position: float
    shortable: bool = False
    data_fresh: bool = True


@dataclass(frozen=True)
class PostListingDecision:
    symbol: str
    trading_day: int
    active: bool
    action: str
    opportunity: OpportunityType
    score: float
    reasons: tuple[str, ...]


def trading_day_number(calendar: ExchangeCalendar, listing_date: date, as_of: date) -> int:
    """Listing day is D1. Non-trading as_of dates return the last elapsed trading-day number."""
    if as_of < listing_date:
        return 0

    current = listing_date
    count = 0
    while current <= as_of:
        if calendar.is_trading_day(current):
            count += 1
        current += timedelta(days=1)
    return count


class PostListingOpportunityEngine:
    """
    Tracks newly listed equities for 30 exchange trading days.

    Multi-day opportunities are long/delivery candidates. Bearish opportunities may only
    become executable intraday shorts after the live broker/exchange shortability gate passes.
    """

    max_trading_days = 30

    def evaluate(self, calendar: ExchangeCalendar, s: PostListingSnapshot) -> PostListingDecision:
        if not calendar.source_ready:
            return PostListingDecision(
                s.symbol,
                0,
                False,
                "WAIT",
                OpportunityType.NONE,
                0.0,
                ("OFFICIAL_CALENDAR_NOT_READY",),
            )
        d = trading_day_number(calendar, s.listing_date, s.as_of)
        if d <= 0:
            return PostListingDecision(s.symbol, d, False, "WAIT", OpportunityType.NONE, 0.0, ("NOT_LISTED_YET",))
        if d > self.max_trading_days:
            return PostListingDecision(s.symbol, d, False, "EXPIRED", OpportunityType.NONE, 0.0, ("30D_WINDOW_COMPLETE",))
        if not s.data_fresh:
            return PostListingDecision(s.symbol, d, True, "WAIT", OpportunityType.NONE, 0.0, ("STALE_DATA",))

        if min(
            s.last_price,
            s.issue_price,
            s.listing_price,
            s.anchored_vwap,
            s.ema9,
            s.ema20,
        ) <= 0:
            return PostListingDecision(s.symbol, d, True, "WAIT", OpportunityType.NONE, 0.0, ("MISSING_REQUIRED_PRICE",))

        reasons: list[str] = []
        long_score = 0.0
        short_score = 0.0
        long_type = OpportunityType.NONE
        short_type = OpportunityType.NONE

        above_avwap = s.last_price > s.anchored_vwap
        ema_bull = s.ema9 > s.ema20
        ema_bear = s.ema9 < s.ema20
        strong_close = s.close_position >= 0.70
        weak_close = s.close_position <= 0.30
        volume_confirmed = s.relative_volume >= 1.5
        outperforming = s.relative_strength_pct >= 1.0
        underperforming = s.relative_strength_pct <= -1.0

        # D1-D5: continuation after the chaotic listing session only if participation persists.
        if d <= 5 and above_avwap and ema_bull and volume_confirmed and strong_close:
            long_score += 72
            if outperforming:
                long_score += 10
            long_type = OpportunityType.EARLY_CONTINUATION
            reasons += ["D1_D5_CONTINUATION", "ABOVE_LISTING_AVWAP", "EMA_BULL", "RVOL_CONFIRMED"]

        # D2-D10: first controlled retracement that still holds the listing anchored VWAP.
        pullback_distance_pct = abs(s.last_price / s.ema20 - 1.0) * 100.0
        if 2 <= d <= 10 and above_avwap and ema_bull and pullback_distance_pct <= 2.0:
            candidate = 66 + (8 if volume_confirmed else 0) + (7 if outperforming else 0)
            if candidate > long_score:
                long_score = candidate
                long_type = OpportunityType.HEALTHY_PULLBACK
                reasons += ["CONTROLLED_PULLBACK", "LISTING_AVWAP_HELD"]

        # D2-D20: reclaim of listing anchored VWAP after an early shakeout.
        if 2 <= d <= 20 and above_avwap and strong_close and volume_confirmed:
            candidate = 68 + (8 if ema_bull else 0) + (6 if outperforming else 0)
            if candidate > long_score:
                long_score = candidate
                long_type = OpportunityType.ANCHORED_VWAP_RECLAIM
                reasons += ["AVWAP_RECLAIM", "STRONG_CLOSE", "VOLUME_EXPANSION"]

        # D5-D30: a post-IPO base can become more tradable than the listing day itself.
        breakout = s.rolling_high_20 > 0 and s.last_price >= s.rolling_high_20 * 0.997
        if 5 <= d <= 30 and breakout and volume_confirmed and ema_bull:
            candidate = 76 + (8 if outperforming else 0) + (5 if strong_close else 0)
            if candidate > long_score:
                long_score = candidate
                long_type = OpportunityType.POST_IPO_BASE_BREAKOUT
                reasons += ["POST_IPO_BASE_BREAKOUT", "RVOL_CONFIRMED", "EMA_BULL"]

        # Failed breakdown / reclaim from a rolling support area.
        near_low = s.rolling_low_20 > 0 and s.last_price <= s.rolling_low_20 * 1.03
        if 5 <= d <= 30 and near_low and above_avwap and strong_close:
            candidate = 67 + (8 if volume_confirmed else 0)
            if candidate > long_score:
                long_score = candidate
                long_type = OpportunityType.FAILED_BREAKDOWN_RECLAIM
                reasons += ["FAILED_BREAKDOWN", "RECLAIMED_AVWAP"]

        # Volume revival after quiet digestion.
        if 5 <= d <= 30 and volume_confirmed and ema_bull and above_avwap:
            candidate = 64 + min(12, max(0.0, (s.relative_volume - 1.5) * 8))
            if candidate > long_score:
                long_score = candidate
                long_type = OpportunityType.VOLUME_REVIVAL
                reasons += ["VOLUME_REVIVAL", "ABOVE_AVWAP"]

        # Bearish monitoring is allowed across the 30-day window, but is intraday-only in cash.
        if ema_bear and not above_avwap and weak_close and volume_confirmed:
            short_score = 70 + (8 if underperforming else 0)
            short_type = OpportunityType.INTRADAY_FADE_SHORT
            reasons += ["BELOW_LISTING_AVWAP", "EMA_BEAR", "WEAK_CLOSE", "SELL_VOLUME"]

        if short_score > long_score and short_score >= 72:
            if not s.shortable:
                return PostListingDecision(
                    s.symbol,
                    d,
                    True,
                    "WAIT",
                    short_type,
                    round(short_score, 2),
                    tuple(dict.fromkeys(reasons + ["SHORT_NOT_ELIGIBLE"])),
                )
            return PostListingDecision(
                s.symbol,
                d,
                True,
                "PROBE_SHORT",
                short_type,
                round(short_score, 2),
                tuple(dict.fromkeys(reasons)),
            )

        if long_score >= 72:
            return PostListingDecision(
                s.symbol,
                d,
                True,
                "PROBE_LONG",
                long_type,
                round(long_score, 2),
                tuple(dict.fromkeys(reasons)),
            )

        return PostListingDecision(
            s.symbol,
            d,
            True,
            "WAIT",
            OpportunityType.NONE,
            round(max(long_score, short_score), 2),
            tuple(dict.fromkeys(reasons + ["NO_CONFIRMED_30D_OPPORTUNITY"])),
        )
