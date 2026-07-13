"""Groww Trading API adapter using the official `growwapi` Python SDK.

Secrets are read only from environment variables. They are never returned by API
responses and must never be committed to GitHub.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from threading import Lock
from typing import Any

from growwapi import GrowwAPI


class GrowwConfigurationError(RuntimeError):
    """Raised when required