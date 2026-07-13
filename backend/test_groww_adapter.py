from groww_adapter import get_ltp_batch_sync, get_ohlc_batch_sync, normalize_batch_symbol


class CurrentGroww:
    SEGMENT_CASH = "CASH"

    def get_ltp(self, *, segment, exchange_trading_symbols):
        assert segment == "CASH"
        assert exchange_trading_symbols == ("NSE_RELIANCE", "NSE_TCS")
        return {"NSE_RELIANCE": 1500.5, "NSE_TCS": 3200}

    def get_ohlc(self, *, segment, exchange_trading_symbols):
        assert segment == "CASH"
        assert exchange_trading_symbols == ("NSE_RELIANCE",)
        return {"NSE_RELIANCE": {"open": 1490, "high": 1510, "low": 1480, "close": 1495}}


class LegacyGroww:
    SEGMENT_CASH = "CASH"
    EXCHANGE_NSE = "NSE"

    def get_ltp(self, *, segment, exchange=None, trading_symbols=None, exchange_trading_symbols=None):
        if exchange_trading_symbols is not None:
            raise TypeError("legacy SDK signature")
        assert segment == "CASH"
        assert exchange == "NSE"
        assert trading_symbols == ["RELIANCE"]
        return {"NSE:RELIANCE": {"ltp": 1501}}

    def get_ohlc(self, *, segment, exchange=None, trading_symbols=None, exchange_trading_symbols=None):
        if exchange_trading_symbols is not None:
            raise TypeError("legacy SDK signature")
        assert segment == "CASH"
        assert exchange == "NSE"
        assert trading_symbols == ["RELIANCE"]
        return {"ohlc": {"NSE:RELIANCE": {"open": 1490, "high": 1510, "low": 1480, "close": 1495}}}


def test_current_sdk_batch_contract():
    groww = CurrentGroww()
    assert get_ltp_batch_sync(groww, ["RELIANCE", "TCS"]) == {"RELIANCE": 1500.5, "TCS": 3200.0}
    assert "RELIANCE" in get_ohlc_batch_sync(groww, ["RELIANCE"])


def test_legacy_sdk_batch_contract_is_still_supported():
    groww = LegacyGroww()
    assert get_ltp_batch_sync(groww, ["RELIANCE"]) == {"RELIANCE": 1501.0}
    assert "RELIANCE" in get_ohlc_batch_sync(groww, ["RELIANCE"])


def test_batch_symbol_normalization():
    assert normalize_batch_symbol("NSE_RELIANCE") == "RELIANCE"
    assert normalize_batch_symbol("NSE:RELIANCE") == "RELIANCE"
