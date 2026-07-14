from groww_feed_engine import GrowwFeedEngine


class FakeGroww:
    EXCHANGE_NSE = "NSE"

    def get_instrument_by_exchange_and_trading_symbol(self, *, exchange, trading_symbol):
        if trading_symbol == "BAD":
            raise RuntimeError("not found")
        return {"exchange_token": {"AAA": 101, "BBB": 202}[trading_symbol]}


def test_feed_engine_resolves_exchange_tokens_without_network():
    engine = GrowwFeedEngine(FakeGroww(), ["AAA", "BBB", "BAD"], lambda event: None)
    instruments = engine._resolve_instruments()
    assert instruments == [
        {"exchange": "NSE", "segment": "CASH", "exchange_token": "101"},
        {"exchange": "NSE", "segment": "CASH", "exchange_token": "202"},
    ]
    assert engine._token_to_symbol == {"101": "AAA", "202": "BBB"}
