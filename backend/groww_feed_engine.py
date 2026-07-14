from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from nse_universe import cached_exchange_token_map


@dataclass(frozen=True)
class FeedEvent:
    symbol: str
    exchange: str
    price: float
    ts_ms: int
    source: str = "groww_feed"


class GrowwFeedEngine:
    """Bridges Groww's blocking callback feed into the asyncio production runtime."""

    def __init__(self, groww: Any, symbols: list[str], event_callback: Callable[[FeedEvent], None]) -> None:
        self.groww = groww
        self.symbols = list(dict.fromkeys(symbol.upper() for symbol in symbols if symbol))
        self.event_callback = event_callback
        self._feed: Any | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._token_to_symbol: dict[str, str] = {}
        self.last_event_at: str | None = None
        self.last_error: str | None = None
        self.subscribed_count = 0
        self._instruments: list[dict[str, str]] = []

    def _resolve_instruments(self) -> list[dict[str, str]]:
        instruments: list[dict[str, str]] = []
        local_tokens = cached_exchange_token_map()
        for symbol in self.symbols[:1000]:
            token = str(local_tokens.get(symbol) or "").strip()
            if not token:
                try:
                    item = self.groww.get_instrument_by_exchange_and_trading_symbol(
                        exchange=self.groww.EXCHANGE_NSE,
                        trading_symbol=symbol,
                    )
                    token = str(item.get("exchange_token") or "").strip() if isinstance(item, dict) else ""
                except Exception:
                    token = ""
            if not token:
                continue
            self._token_to_symbol[token] = symbol
            instruments.append({"exchange": "NSE", "segment": "CASH", "exchange_token": token})
        return instruments

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        try:
            from growwapi import GrowwFeed
        except Exception as exc:
            self.last_error = f"{exc.__class__.__name__}: GrowwFeed unavailable"
            return False
        instruments = self._resolve_instruments()
        if not instruments:
            self.last_error = "No Groww exchange tokens could be resolved for the configured universe."
            return False
        self._feed = GrowwFeed(self.groww)

        def on_data_received(meta: dict[str, Any]) -> None:
            _ = meta
            if self._stop.is_set() or self._feed is None:
                return
            try:
                payload = self._feed.get_ltp() or {}
                nse_cash = (((payload.get("ltp") or {}).get("NSE") or {}).get("CASH") or {})
                for token, data in nse_cash.items():
                    if not isinstance(data, dict):
                        continue
                    symbol = self._token_to_symbol.get(str(token))
                    price = float(data.get("ltp") or 0.0)
                    ts_ms = int(float(data.get("tsInMillis") or time.time() * 1000))
                    if symbol and price > 0:
                        self.last_event_at = datetime.now(timezone.utc).isoformat()
                        self.event_callback(FeedEvent(symbol=symbol, exchange="NSE", price=price, ts_ms=ts_ms))
            except Exception as exc:
                self.last_error = f"{exc.__class__.__name__}: feed callback failed"

        try:
            self._feed.subscribe_ltp(instruments, on_data_received=on_data_received)
            self._instruments = instruments
            self.subscribed_count = len(instruments)
        except Exception as exc:
            self.last_error = f"{exc.__class__.__name__}: feed subscribe failed"
            return False

        def consume() -> None:
            try:
                self._feed.consume()
            except Exception as exc:
                self.last_error = f"{exc.__class__.__name__}: feed consume stopped"

        self._thread = threading.Thread(target=consume, name="groww-live-feed", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._feed is not None and self._instruments:
            try:
                self._feed.unsubscribe_ltp(self._instruments)
            except Exception:
                pass
        close = getattr(self._feed, "close", None) if self._feed is not None else None
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "subscribed_count": self.subscribed_count,
            "last_event_at": self.last_event_at,
            "last_error": self.last_error,
        }
