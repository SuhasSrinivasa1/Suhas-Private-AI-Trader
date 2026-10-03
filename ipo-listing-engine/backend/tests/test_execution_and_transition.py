from datetime import datetime
from zoneinfo import ZoneInfo

from app.execution_clock import IntradayClockPolicy
from app.position_transition import resolve_direction_transition


IST = ZoneInfo("Asia/Kolkata")


def test_force_flat_starts_at_1505():
    policy = IntradayClockPolicy()
    assert policy.must_force_flat(datetime(2026, 10, 5, 15, 4, tzinfo=IST)) is False
    assert policy.must_force_flat(datetime(2026, 10, 5, 15, 5, tzinfo=IST)) is True


def test_bearish_flip_exits_owned_long_before_shorting():
    result = resolve_direction_transition(
        desired_action="PROBE_SHORT",
        ipo_sentinel_long_quantity=100,
        ipo_sentinel_intraday_short_quantity=0,
    )
    assert result.action == "EXIT_OWNED_LONG"
    assert "REVALIDATE_BEFORE_SHORT" in result.reasons


def test_external_same_symbol_holding_is_not_sold():
    result = resolve_direction_transition(
        desired_action="PROBE_SHORT",
        ipo_sentinel_long_quantity=0,
        ipo_sentinel_intraday_short_quantity=0,
        external_same_symbol_quantity=500,
    )
    assert result.action == "PROBE_SHORT"
    assert "EXTERNAL_SAME_SYMBOL_HOLDING_READ_ONLY" in result.reasons
