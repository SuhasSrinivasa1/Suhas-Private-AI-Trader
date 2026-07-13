"""Groww broker adapter scaffold for the official Groww Trading API.

This module intentionally does not guess undocumented SDK method names. It provides
configuration validation and a single place to wire the official client once API access
has been enabled on the user's Groww account.

Secrets must be supplied only through local environment variables or a secret manager.
They must never be committed to source control or returned by API responses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class GrowwConfigurationError(RuntimeError):
    """Raised when Groww API credentials or account access are not configured."""


@dataclass(frozen=True)
class GrowwSettings:
    api_key: str
    api_secret: str
    live_execution_enabled: bool

    @classmethod
    def from_env(cls) -> "GrowwSettings":
        api_key = os.getenv("GROWW_API_KEY", "").strip()
        api_secret = os.getenv("GROWW_API_SECRET", "").strip()
        live_execution_enabled = (
            os.getenv("GROWW_LIVE_EXECUTION_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        return cls(
            api_key=api_key,
            api_secret=api_secret,
            live_execution_enabled=live_execution_enabled,
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def require_configured(self) -> None:
        if not self.configured:
            raise GrowwConfigurationError(
                "Groww API access is not configured. Enable the official Groww Trading API "
                "for the account, then set GROWW_API_KEY and GROWW_API_SECRET only in the "
                "local .env file or a secret manager."
            )


def connection_status() -> dict:
    """Return non-secret Groww connection status for the UI/backend."""
    settings = GrowwSettings.from_env()
    return {
        "broker": "groww",
        "configured": settings.configured,
        "live_execution_enabled": settings.live_execution_enabled,
        "secrets_exposed": False,
    }
