from __future__ import annotations

import ipaddress
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Header, HTTPException, status


@dataclass(frozen=True)
class StoredGrowwSettings:
    totp_token: str
    totp_secret: str
    expected_static_ip: str
    static_ip_confirmed: bool


class EncryptedGrowwSettingsStore:
    """Stores Groww credentials encrypted at rest on the trading service."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._path = Path(os.getenv("IPO_SENTINEL_SETTINGS_FILE", ".runtime/groww-settings.enc"))

    @property
    def ready(self) -> bool:
        return bool(os.getenv("IPO_SENTINEL_MASTER_KEY", "").strip())

    def _fernet(self) -> Fernet:
        raw = os.getenv("IPO_SENTINEL_MASTER_KEY", "").strip()
        if not raw:
            raise RuntimeError("IPO_SENTINEL_MASTER_KEY is not configured")
        try:
            return Fernet(raw.encode("ascii"))
        except Exception as exc:
            raise RuntimeError("IPO_SENTINEL_MASTER_KEY is not a valid Fernet key") from exc

    def save(self, settings: StoredGrowwSettings) -> None:
        ipaddress.ip_address(settings.expected_static_ip)
        payload = json.dumps(
            {
                "totp_token": settings.totp_token,
                "totp_secret": settings.totp_secret.replace(" ", ""),
                "expected_static_ip": settings.expected_static_ip,
                "static_ip_confirmed": settings.static_ip_confirmed,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            separators=(",", ":"),
        ).encode("utf-8")

        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_bytes(self._fernet().encrypt(payload))
            os.chmod(tmp, 0o600)
            tmp.replace(self._path)

    def load(self) -> StoredGrowwSettings | None:
        if not self._path.exists():
            return None
        with self._lock:
            try:
                decrypted = self._fernet().decrypt(self._path.read_bytes())
            except InvalidToken as exc:
                raise RuntimeError("Stored Groww settings cannot be decrypted with the current master key") from exc
            data = json.loads(decrypted.decode("utf-8"))
            return StoredGrowwSettings(
                totp_token=str(data["totp_token"]).strip(),
                totp_secret=str(data["totp_secret"]).replace(" ", "").strip(),
                expected_static_ip=str(data["expected_static_ip"]).strip(),
                static_ip_confirmed=bool(data.get("static_ip_confirmed", False)),
            )

    def clear(self) -> None:
        with self._lock:
            self._path.unlink(missing_ok=True)


def require_device_key(x_ipo_sentinel_device_key: str | None = Header(default=None)) -> None:
    configured = os.getenv("IPO_SENTINEL_DEVICE_KEY", "")
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trading service device key is not configured",
        )
    if not x_ipo_sentinel_device_key or not secrets.compare_digest(
        x_ipo_sentinel_device_key.encode("utf-8"),
        configured.encode("utf-8"),
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device key")


async def detect_egress_ip() -> str:
    async with httpx.AsyncClient(timeout=httpx.Timeout(7.0), follow_redirects=True) as client:
        response = await client.get("https://api.ipify.org?format=json")
        response.raise_for_status()
        value = str(response.json()["ip"]).strip()
        ipaddress.ip_address(value)
        return value
