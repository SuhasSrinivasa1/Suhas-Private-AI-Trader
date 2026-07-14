from __future__ import annotations

import csv
import os
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

INSTRUMENT_MASTER_URL = "https://growwapi-assets.groww.in/instruments/instrument.csv"
EQUITY_INSTRUMENT_TYPES = {"EQ", "EQUITY", "STOCK"}
EQUITY_SERIES = {"EQ", "BE", "BZ", "SM", "ST", "MT", "Z", "ZP"}
TRUE_VALUES = {"1", "true", "yes", "y"}


@dataclass(frozen=True)
class NSEEquityInstrument:
    trading_symbol: str
    exchange_token: str
    name: str
    series: str
    instrument_type: str
    buy_allowed: bool
    sell_allowed: bool


def _application_support_dir() -> Path:
    configured = os.getenv("TRADER_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SuhasPrivateAITrader"
    return Path(__file__).resolve().parents[1] / ".runtime"


def instrument_cache_path() -> Path:
    configured = os.getenv("GROWW_INSTRUMENT_CACHE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return _application_support_dir() / "instrument.csv"


def refresh_instrument_master(*, force: bool = False, max_age_seconds: int = 86_400, timeout_seconds: int = 20) -> Path:
    """Download Groww's public instrument master once per day and keep a local fallback cache."""
    path = instrument_cache_path()
    if not force and path.exists() and (time.time() - path.stat().st_mtime) < max_age_seconds:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(INSTRUMENT_MASTER_URL, headers={"User-Agent": "SuhasPrivateAITrader/2.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read()
        if not payload:
            raise RuntimeError("Groww instrument master download returned no data")
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            handle.write(payload)
            temp_path = Path(handle.name)
        temp_path.replace(path)
        return path
    except Exception:
        if path.exists():
            return path
        raise


def _is_true(value: object) -> bool:
    return str(value or "").strip().lower() in TRUE_VALUES


def _is_nse_cash_equity(row: dict[str, str]) -> bool:
    if str(row.get("exchange") or "").strip().upper() != "NSE":
        return False
    if str(row.get("segment") or "").strip().upper() != "CASH":
        return False
    symbol = str(row.get("trading_symbol") or "").strip().upper()
    token = str(row.get("exchange_token") or "").strip()
    if not symbol or not token or not _is_true(row.get("buy_allowed")):
        return False
    instrument_type = str(row.get("instrument_type") or "").strip().upper()
    series = str(row.get("series") or "").strip().upper()
    return instrument_type in EQUITY_INSTRUMENT_TYPES or series in EQUITY_SERIES


def load_nse_cash_equities(path: Path | None = None) -> list[NSEEquityInstrument]:
    csv_path = path or refresh_instrument_master()
    instruments: list[NSEEquityInstrument] = []
    seen: set[str] = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not _is_nse_cash_equity(row):
                continue
            symbol = str(row.get("trading_symbol") or "").strip().upper()
            if symbol in seen:
                continue
            seen.add(symbol)
            instruments.append(
                NSEEquityInstrument(
                    trading_symbol=symbol,
                    exchange_token=str(row.get("exchange_token") or "").strip(),
                    name=str(row.get("name") or "").strip(),
                    series=str(row.get("series") or "").strip().upper(),
                    instrument_type=str(row.get("instrument_type") or "").strip().upper(),
                    buy_allowed=_is_true(row.get("buy_allowed")),
                    sell_allowed=_is_true(row.get("sell_allowed")),
                )
            )
    return instruments


def build_full_nse_universe(seed_symbols: Iterable[str]) -> list[str]:
    """Return seed/liquid symbols first, followed by every tradable NSE cash equity from the instrument master."""
    seeds = [str(symbol).strip().upper() for symbol in seed_symbols if str(symbol).strip()]
    try:
        all_symbols = [item.trading_symbol for item in load_nse_cash_equities()]
    except Exception:
        return list(dict.fromkeys(seeds))
    return list(dict.fromkeys(seeds + all_symbols))


def cached_exchange_token_map() -> dict[str, str]:
    """Resolve exchange tokens from the local instrument-master cache without broker API calls."""
    path = instrument_cache_path()
    if not path.exists():
        return {}
    try:
        return {item.trading_symbol: item.exchange_token for item in load_nse_cash_equities(path)}
    except Exception:
        return {}
