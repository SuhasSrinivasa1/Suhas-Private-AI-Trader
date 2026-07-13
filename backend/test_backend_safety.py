import asyncio

import pytest
from fastapi import HTTPException

import main


def test_unconfigured_broker_pauses_scanner_safely(monkeypatch):
    monkeypatch.delenv("GROWW_API_KEY", raising=False)
    monkeypatch.delenv("GROWW_API_SECRET", raising=False)

    assert main._broker_configured() is False
    assert main._scanner_status() == "broker_not_configured"

    health = main.health()
    assert health["status"] == "ok"
    assert health["configured"] is False
    assert health["scanner_status"] == "broker_not_configured"


def test_manual_live_scan_is_blocked_without_broker_credentials(monkeypatch):
    monkeypatch.delenv("GROWW_API_KEY", raising=False)
    monkeypatch.delenv("GROWW_API_SECRET", raising=False)

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.scan_now())

    assert error.value.status_code == 503
    assert "not configured" in str(error.value.detail).lower()


def test_live_state_never_exposes_broker_secrets(monkeypatch):
    monkeypatch.setenv("GROWW_API_KEY", "local-test-key")
    monkeypatch.setenv("GROWW_API_SECRET", "local-test-secret")

    state = main.live_state()
    serialized = repr(state)

    assert "local-test-key" not in serialized
    assert "local-test-secret" not in serialized
    assert "GROWW_API_KEY" not in serialized
    assert "GROWW_API_SECRET" not in serialized
