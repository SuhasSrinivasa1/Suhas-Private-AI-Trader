from __future__ import annotations

from typing import Any, Iterable


def exchange_trading_symbols(symbols: Iterable[str], exchange: str = "NSE") -> tuple[str, ...]:
    exchange = exchange.upper().strip()
    return tuple(f"{exchange}_{str(symbol).upper().strip()}" for symbol in symbols if str(symbol).strip())


def normalize_batch_symbol(key: Any) -> str:
    raw = str(key).upper().strip()
    for separator in (":", "_"):
        if separator in raw:
            prefix, symbol = raw.split(separator, 1)
            if prefix in {"NSE", "BSE", "MCX"} and symbol:
                return symbol
    return raw


def _payload_source(payload: Any, nested_key: str) -> dict[Any, Any]:
    if not isinstance(payload, dict):
        return {}
    nested = payload.get(nested_key)
    return nested if isinstance(nested, dict) else payload


def parse_ltp_payload(payload: Any) -> dict[str, float]:
    source = _payload_source(payload, "ltp")
    parsed: dict[str, float] = {}
    for key, value in source.items():
        raw_value = value.get("ltp") if isinstance(value, dict) else value
        try:
            price = float(raw_value)
        except (TypeError, ValueError):
            continue
        if price > 0:
            parsed[normalize_batch_symbol(key)] = price
    return parsed


def parse_ohlc_payload(payload: Any) -> dict[str, dict[str, Any]]:
    source = _payload_source(payload, "ohlc")
    parsed: dict[str, dict[str, Any]] = {}
    for key, value in source.items():
        if isinstance(value, dict):
            parsed[normalize_batch_symbol(key)] = value
    return parsed


def get_ltp_batch_sync(groww: Any, symbols: list[str], exchange: str = "NSE") -> dict[str, float]:
    if not symbols:
        return {}
    exchange = exchange.upper().strip()
    exchange_symbols = exchange_trading_symbols(symbols, exchange)
    try:
        payload = groww.get_ltp(
            segment=groww.SEGMENT_CASH,
            exchange_trading_symbols=exchange_symbols,
        )
    except TypeError:
        payload = groww.get_ltp(
            segment=groww.SEGMENT_CASH,
            exchange=getattr(groww, f"EXCHANGE_{exchange}"),
            trading_symbols=symbols,
        )
    return parse_ltp_payload(payload)


def get_ohlc_batch_sync(groww: Any, symbols: list[str], exchange: str = "NSE") -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    exchange = exchange.upper().strip()
    exchange_symbols = exchange_trading_symbols(symbols, exchange)
    try:
        payload = groww.get_ohlc(
            segment=groww.SEGMENT_CASH,
            exchange_trading_symbols=exchange_symbols,
        )
    except TypeError:
        payload = groww.get_ohlc(
            segment=groww.SEGMENT_CASH,
            exchange=getattr(groww, f"EXCHANGE_{exchange}"),
            trading_symbols=symbols,
        )
    return parse_ohlc_payload(payload)
