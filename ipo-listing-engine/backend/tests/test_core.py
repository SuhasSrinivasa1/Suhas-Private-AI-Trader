from datetime import date, datetime, timezone

from app.domain import Action, LiveFeatures, Ownership
from app.services import ExchangeCalendar, OwnedPositionRegistry, ShadowFill, ShadowLedger
from app.strategy import ListingDecisionEngine


def test_next_trading_day_skips_weekend_and_holiday():
    calendar = ExchangeCalendar(holidays={date(2026, 10, 2)}, source_ready=True)
    assert calendar.next_trading_day(date(2026, 10, 1)) == date(2026, 10, 5)


def test_external_position_is_read_only():
    registry = OwnedPositionRegistry()
    registry.reconcile([{"symbol": "ABC", "quantity": 10, "tag": "OTHER_APP"}])
    assert registry.owned("ABC") is None
    assert registry.may_mutate("ABC") is False


def test_owned_position_is_mutable():
    registry = OwnedPositionRegistry()
    registry.reconcile([{"symbol": "ABC", "quantity": 10, "tag": "IPO_SENTINEL:D0"}])
    assert registry.owned("ABC").ownership is Ownership.IPO_SENTINEL
    assert registry.may_mutate("ABC") is True


def test_strong_listing_flow_can_probe_long():
    f = LiveFeatures(
        symbol="TEST",
        at=datetime.now(timezone.utc),
        ltp=110,
        vwap=106,
        rvol=3.0,
        spread_bps=20,
        buy_qty=9000,
        sell_qty=1000,
        first_5m_high=108,
        first_5m_low=100,
        listing_price=103,
        issue_price=100,
        nifty_return_pct=0.3,
        sector_return_pct=0.4,
        circuit_distance_pct=8,
        shortable=False,
    )
    decision = ListingDecisionEngine().decide(f, 100_000)
    assert decision.action in {Action.PROBE_LONG, Action.BUILD_LONG}


def test_shadow_ledger_includes_all_charges_once():
    ledger = ShadowLedger(100_000)
    ledger.apply(ShadowFill(symbol="ABC", side="BUY", quantity=100, price=100, charges=10))
    ledger.apply(ShadowFill(symbol="ABC", side="SELL", quantity=100, price=110, charges=12))
    status = ledger.mark_to_market({})
    assert status["realized_gross_pnl"] == 1000.0
    assert status["charges"] == 22.0
    assert status["realized_pnl"] == 978.0
    assert status["net_pnl"] == 978.0
