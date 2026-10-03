from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.listing_session import listing_session_gate
from app.research_service import GrowwInstrumentMaster, _extract_forthcoming_records

IST = ZoneInfo("Asia/Kolkata")


def test_groww_instrument_resolution_prefers_exact_isin():
    rows = [
        {
            "exchange": "NSE",
            "segment": "CASH",
            "trading_symbol": "NEWIPO",
            "groww_symbol": "NSE-NEWIPO",
            "isin": "INE123456789",
            "series": "EQ",
            "exchange_token": "123",
            "buy_allowed": "1",
            "sell_allowed": "1",
        },
        {
            "exchange": "BSE",
            "segment": "CASH",
            "trading_symbol": "NEWIPO",
            "groww_symbol": "BSE-NEWIPO",
            "isin": "INE123456789",
            "series": "A",
            "exchange_token": "999",
            "buy_allowed": "1",
            "sell_allowed": "1",
        },
    ]
    resolved = GrowwInstrumentMaster.resolve(
        rows,
        official_symbol="NEWIPO",
        isin="INE123456789",
    )
    assert resolved is not None
    assert resolved["exchange"] == "NSE"
    assert resolved["trading_symbol"] == "NEWIPO"


def test_symbol_mismatch_fails_closed_even_if_isin_matches():
    rows = [
        {
            "exchange": "NSE",
            "segment": "CASH",
            "trading_symbol": "WRONG",
            "groww_symbol": "NSE-WRONG",
            "isin": "INE123456789",
        }
    ]
    assert GrowwInstrumentMaster.resolve(
        rows,
        official_symbol="NEWIPO",
        isin="INE123456789",
    ) is None


def test_listing_session_does_not_allow_continuous_order_before_10():
    result = listing_session_gate(
        now=datetime(2026, 10, 5, 9, 50, tzinfo=IST),
        listing_date=date(2026, 10, 5),
        nse_symbol_confirmed=True,
        groww_instrument_resolved=True,
        live_quote_available=True,
    )
    assert result.can_submit_continuous_order is False
    assert result.state == "SPECIAL_PREOPEN_MATCHING"


def test_listing_session_allows_after_10_when_all_checks_pass():
    result = listing_session_gate(
        now=datetime(2026, 10, 5, 10, 1, tzinfo=IST),
        listing_date=date(2026, 10, 5),
        nse_symbol_confirmed=True,
        groww_instrument_resolved=True,
        live_quote_available=True,
        buy_allowed=True,
        lot_size=1,
        live_price=100.0,
        budget_rupees=100_000,
    )
    assert result.can_submit_continuous_order is True
    assert result.state == "CONTINUOUS_TRADING"


def test_listing_session_blocks_sme_lot_above_budget():
    result = listing_session_gate(
        now=datetime(2026, 10, 5, 10, 1, tzinfo=IST),
        listing_date=date(2026, 10, 5),
        nse_symbol_confirmed=True,
        groww_instrument_resolved=True,
        live_quote_available=True,
        buy_allowed=True,
        lot_size=1200,
        live_price=110.0,
        budget_rupees=100_000,
    )
    assert result.can_submit_continuous_order is False
    assert result.state == "WAIT_MIN_LOT_ABOVE_BUDGET"


def test_listing_session_blocks_when_groww_buy_not_allowed():
    result = listing_session_gate(
        now=datetime(2026, 10, 5, 10, 1, tzinfo=IST),
        listing_date=date(2026, 10, 5),
        nse_symbol_confirmed=True,
        groww_instrument_resolved=True,
        live_quote_available=True,
        buy_allowed=False,
        lot_size=1,
        live_price=100.0,
        budget_rupees=100_000,
    )
    assert result.can_submit_continuous_order is False
    assert result.state == "WAIT_BUY_NOT_ALLOWED"


def test_forthcoming_listing_parser_extracts_official_identity():
    payload = {
        "data": [
            {
                "symbol": "NEWIPO",
                "companyName": "New IPO Limited",
                "dateOfListing": "05-Oct-2026",
                "isin": "INE123456789",
                "series": "EQ",
            }
        ]
    }
    rows = _extract_forthcoming_records(payload)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "NEWIPO"
