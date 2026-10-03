import pytest

from app.services import ShadowFill, ShadowLedger


def test_shadow_long_net_pnl_includes_entry_and_exit_charges():
    ledger = ShadowLedger(100_000)
    ledger.apply(ShadowFill("ABC", "BUY", 100, 100.0, charges=10.0))

    open_snapshot = ledger.mark_to_market({"ABC": 105.0})
    assert open_snapshot["unrealized_pnl"] == 490.0
    assert open_snapshot["net_pnl"] == 490.0

    ledger.apply(ShadowFill("ABC", "SELL", 100, 105.0, charges=12.0))
    closed = ledger.mark_to_market({})
    assert closed["realized_gross_pnl"] == 500.0
    assert closed["realized_pnl"] == 478.0
    assert closed["net_pnl"] == 478.0
    assert closed["charges_paid"] == 22.0


def test_shadow_short_marks_correctly_and_covers():
    ledger = ShadowLedger(100_000)
    ledger.apply(ShadowFill("XYZ", "SELL", 50, 200.0, charges=8.0))
    open_snapshot = ledger.mark_to_market({"XYZ": 190.0})
    assert open_snapshot["net_pnl"] == 492.0

    ledger.apply(ShadowFill("XYZ", "BUY", 50, 190.0, charges=9.0))
    closed = ledger.mark_to_market({})
    assert closed["net_pnl"] == 483.0


def test_shadow_cannot_cross_through_flat():
    ledger = ShadowLedger(100_000)
    ledger.apply(ShadowFill("ABC", "BUY", 10, 100.0))
    with pytest.raises(ValueError):
        ledger.apply(ShadowFill("ABC", "SELL", 11, 99.0))
