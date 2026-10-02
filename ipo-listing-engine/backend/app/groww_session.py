from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pyotp
from growwapi import GrowwAPI


@dataclass(frozen=True)
class GrowwCredentials:
    totp_token: str
    totp_secret: str

    @classmethod
    def from_env(cls) -> "GrowwCredentials":
        token = os.environ.get("GROWW_TOTP_TOKEN", "").strip()
        secret = os.environ.get("GROWW_TOTP_SECRET", "").replace(" ", "").strip()
        if not token or not secret:
            raise RuntimeError("GROWW_TOTP_TOKEN and GROWW_TOTP_SECRET must be provided by server secret storage")
        return cls(token, secret)


class GrowwSession:
    """Server-side Groww session. Secrets never cross the API boundary to Android."""

    def __init__(self, api: GrowwAPI) -> None:
        self.api = api

    @classmethod
    def from_totp_env(cls) -> "GrowwSession":
        credentials = GrowwCredentials.from_env()
        current_totp = pyotp.TOTP(credentials.totp_secret).now()
        access_token = GrowwAPI.get_access_token(api_key=credentials.totp_token, totp=current_totp)
        return cls(GrowwAPI(access_token))

    def historical(
        self,
        *,
        symbol: str,
        start_time: str,
        end_time: str,
        interval: str,
        exchange: str = "NSE",
    ) -> dict[str, Any]:
        exchange_constant = self.api.EXCHANGE_NSE if exchange.upper() == "NSE" else self.api.EXCHANGE_BSE
        return self.api.get_historical_candles(
            exchange=exchange_constant,
            segment=self.api.SEGMENT_CASH,
            groww_symbol=f"{exchange.upper()}-{symbol.upper()}",
            start_time=start_time,
            end_time=end_time,
            candle_interval=interval,
        )
