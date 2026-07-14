from pathlib import Path

from nse_universe import build_full_nse_universe, load_nse_cash_equities


def test_loads_tradable_nse_cash_equities_and_keeps_penny_sme_series(tmp_path: Path):
    path = tmp_path / "instrument.csv"
    path.write_text(
        "exchange,exchange_token,trading_symbol,name,instrument_type,segment,series,buy_allowed,sell_allowed\n"
        "NSE,1,RELIANCE,Reliance,EQ,CASH,EQ,1,1\n"
        "NSE,2,PENNYSME,Penny SME,EQ,CASH,SM,1,1\n"
        "NSE,3,NOBUY,No Buy,EQ,CASH,EQ,0,1\n"
        "NSE,4,NIFTY,Nifty,INDEX,CASH,,1,1\n"
        "BSE,5,OTHER,Other,EQ,CASH,EQ,1,1\n",
        encoding="utf-8",
    )
    result = load_nse_cash_equities(path)
    assert [item.trading_symbol for item in result] == ["RELIANCE", "PENNYSME"]
    assert result[1].series == "SM"


def test_full_universe_keeps_seed_order_when_download_unavailable(monkeypatch):
    monkeypatch.setattr("nse_universe.load_nse_cash_equities", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    assert build_full_nse_universe(["TCS", "RELIANCE", "TCS"]) == ["TCS", "RELIANCE"]
