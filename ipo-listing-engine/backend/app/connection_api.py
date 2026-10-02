from __future__ import annotations

import ipaddress
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .connection_settings import (
    EncryptedGrowwSettingsStore,
    StoredGrowwSettings,
    detect_egress_ip,
    require_admin_key,
)
from .groww_session import GrowwCredentials, GrowwSession

router = APIRouter(prefix="/settings", tags=["connection-settings"])
store = EncryptedGrowwSettingsStore()


class GrowwSettingsRequest(BaseModel):
    totp_token: str = Field(min_length=4, max_length=512)
    totp_secret: str = Field(min_length=8, max_length=512)
    expected_static_ip: str = Field(min_length=3, max_length=64)
    static_ip_confirmed: bool = False


@router.get("/status", dependencies=[Depends(require_admin_key)])
async def connection_status() -> dict:
    saved = None
    error = None
    if store.ready:
        try:
            saved = store.load()
        except Exception as exc:
            error = str(exc)

    return {
        "secret_store_ready": store.ready,
        "groww_configured": saved is not None,
        "expected_static_ip": saved.expected_static_ip if saved else None,
        "static_ip_confirmed": saved.static_ip_confirmed if saved else False,
        "credential_values_returned": False,
        "error": error,
    }


@router.post("/groww", dependencies=[Depends(require_admin_key)])
def save_groww_settings(payload: GrowwSettingsRequest) -> dict:
    if not store.ready:
        raise HTTPException(status_code=503, detail="Backend encrypted secret store is not ready")

    try:
        ipaddress.ip_address(payload.expected_static_ip)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Expected static IP is invalid") from exc

    store.save(
        StoredGrowwSettings(
            totp_token=payload.totp_token.strip(),
            totp_secret=payload.totp_secret.replace(" ", "").strip(),
            expected_static_ip=payload.expected_static_ip.strip(),
            static_ip_confirmed=payload.static_ip_confirmed,
        )
    )
    return {
        "saved": True,
        "groww_configured": True,
        "expected_static_ip": payload.expected_static_ip.strip(),
        "static_ip_confirmed": payload.static_ip_confirmed,
        "credential_values_returned": False,
    }


@router.delete("/groww", dependencies=[Depends(require_admin_key)])
def clear_groww_settings() -> dict:
    store.clear()
    return {"cleared": True}


@router.post("/validate", dependencies=[Depends(require_admin_key)])
async def validate_connection() -> dict:
    if not store.ready:
        raise HTTPException(status_code=503, detail="Backend encrypted secret store is not ready")

    saved = store.load()
    if not saved:
        raise HTTPException(status_code=409, detail="Groww credentials have not been configured")

    detected_ip = None
    static_ip_matches = False
    egress_error = None
    try:
        detected_ip = await detect_egress_ip()
        static_ip_matches = detected_ip == saved.expected_static_ip
    except Exception as exc:
        egress_error = str(exc)

    groww_auth_ok = False
    groww_error = None
    try:
        GrowwSession.from_credentials(
            GrowwCredentials(totp_token=saved.totp_token, totp_secret=saved.totp_secret)
        )
        groww_auth_ok = True
    except Exception as exc:
        groww_error = str(exc)

    live_ready = bool(
        groww_auth_ok
        and detected_ip
        and static_ip_matches
        and saved.static_ip_confirmed
        and store.ready
    )

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "groww_auth_ok": groww_auth_ok,
        "detected_egress_ip": detected_ip,
        "expected_static_ip": saved.expected_static_ip,
        "static_ip_matches": static_ip_matches,
        "static_ip_confirmed": saved.static_ip_confirmed,
        "secret_store_ready": store.ready,
        "live_execution_ready": live_ready,
        "groww_error": groww_error,
        "egress_error": egress_error,
    }
