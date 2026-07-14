from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass

KEYCHAIN_SERVICE = "SuhasPrivateAITrader"
KEYCHAIN_API_KEY_ACCOUNT = "groww-api-key"
KEYCHAIN_API_SECRET_ACCOUNT = "groww-api-secret"


@dataclass(frozen=True)
class GrowwCredentials:
    api_key: str
    api_secret: str
    source: str


def _read_keychain(account: str) -> str:
    if platform.system() != "Darwin":
        return ""
    try:
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-a",
                account,
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def resolve_groww_credentials() -> GrowwCredentials | None:
    env_key = os.getenv("GROWW_API_KEY", "").strip()
    env_secret = os.getenv("GROWW_API_SECRET", "").strip()
    if env_key and env_secret:
        return GrowwCredentials(env_key, env_secret, "environment")

    keychain_key = _read_keychain(KEYCHAIN_API_KEY_ACCOUNT)
    keychain_secret = _read_keychain(KEYCHAIN_API_SECRET_ACCOUNT)
    if keychain_key and keychain_secret:
        return GrowwCredentials(keychain_key, keychain_secret, "macos_keychain")
    return None


def groww_credentials_configured() -> bool:
    return resolve_groww_credentials() is not None
