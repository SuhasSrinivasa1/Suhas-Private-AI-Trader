from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.listing_session import listing_session_gate
from app.research_service import GrowwInstrumentMaster, _extract_forthcoming_records, _extract_records

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
        market_depth_available=True,
        liquidity_sufficient=True,
        spread_bps=20.0,
        estimated_impact_bps=15.0,
        circuit_state_acceptable=True,
        position_reconciled=True,
        order_state_known=True,
        position_isolation_ok=True,
        buy_allowed=True,
        lot_size=1,
        live_price=100.0,
        budget_rupees=100_000,
    )
    assert result.can_submit_continuous_order is True
    assert result.state == "CONTINUOUS_TRADING_ELIGIBLE"


def test_listing_session_blocks_sme_lot_above_budget():
    result = listing_session_gate(
        now=datetime(2026, 10, 5, 10, 1, tzinfo=IST),
        listing_date=date(2026, 10, 5),
        nse_symbol_confirmed=True,
        groww_instrument_resolved=True,
        live_quote_available=True,
        market_depth_available=True,
        liquidity_sufficient=True,
        spread_bps=20.0,
        estimated_impact_bps=15.0,
        circuit_state_acceptable=True,
        position_reconciled=True,
        order_state_known=True,
        position_isolation_ok=True,
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
        market_depth_available=True,
        liquidity_sufficient=True,
        spread_bps=20.0,
        estimated_impact_bps=15.0,
        circuit_state_acceptable=True,
        position_reconciled=True,
        order_state_known=True,
        position_isolation_ok=True,
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


def test_research_discovery_does_not_require_a_symbol():
    payload = {
        "data": [
            {
                "companyName": "Pre Symbol Limited",
                "issueStartDate": "05-Oct-2026",
                "issueEndDate": "07-Oct-2026",
                "status": "Forthcoming",
                "issuePrice": "Rs.100 to Rs.110",
            }
        ]
    }
    rows = _extract_records(payload)
    assert len(rows) == 1
    assert rows[0]["companyName"] == "Pre Symbol Limited"
    assert "symbol" not in rows[0]


def test_groww_resolution_waits_when_instrument_not_yet_present():
    result = GrowwInstrumentMaster.resolve_detailed(
        [],
        official_symbol="NEWIPO",
        isin="INE123456789",
    )
    assert result.status == "WAIT_GROWW_INSTRUMENT"
    assert result.row is None


def test_similar_company_name_never_authorizes_instrument():
    rows = [
        {
            "exchange": "NSE",
            "segment": "CASH",
            "trading_symbol": "OTHER",
            "groww_symbol": "NSE-OTHER",
            "name": "New IPO Limited",
            "isin": "INE000000001",
        }
    ]
    result = GrowwInstrumentMaster.resolve_detailed(
        rows,
        official_symbol="NEWIPO",
        isin="INE123456789",
    )
    assert result.status == "WAIT_GROWW_INSTRUMENT"
    assert result.row is None


def test_multiple_exact_groww_rows_fail_closed():
    row = {
        "exchange": "NSE",
        "segment": "CASH",
        "trading_symbol": "NEWIPO",
        "groww_symbol": "NSE-NEWIPO",
        "isin": "INE123456789",
    }
    result = GrowwInstrumentMaster.resolve_detailed(
        [dict(row), dict(row)],
        official_symbol="NEWIPO",
        isin="INE123456789",
    )
    assert result.status == "BLOCK_MULTIPLE_EXACT_ROWS"
    assert result.row is None


def test_live_quote_without_market_depth_still_waits():
    result = listing_session_gate(
        now=datetime(2026, 10, 5, 10, 1, tzinfo=IST),
        listing_date=date(2026, 10, 5),
        nse_symbol_confirmed=True,
        groww_instrument_resolved=True,
        live_quote_available=True,
        market_depth_available=False,
        liquidity_sufficient=True,
        spread_bps=20.0,
        estimated_impact_bps=15.0,
        circuit_state_acceptable=True,
        position_reconciled=True,
        order_state_known=True,
        position_isolation_ok=True,
        buy_allowed=True,
        lot_size=1,
        live_price=100.0,
        budget_rupees=100_000,
    )
    assert result.can_submit_continuous_order is False
    assert result.state == "WAIT_MARKET_DEPTH"
