from pathlib import Path

from cryptography.fernet import Fernet

from app.connection_settings import EncryptedGrowwSettingsStore, StoredGrowwSettings


def test_encrypted_store_round_trip(monkeypatch, tmp_path: Path):
    key = Fernet.generate_key().decode("ascii")
    path = tmp_path / "settings.enc"
    monkeypatch.setenv("IPO_SENTINEL_MASTER_KEY", key)
    monkeypatch.setenv("IPO_SENTINEL_SETTINGS_FILE", str(path))

    store = EncryptedGrowwSettingsStore()
    store.save(
        StoredGrowwSettings(
            totp_token="token-value",
            totp_secret="ABCDEF123456",
            expected_static_ip="203.0.113.10",
            static_ip_confirmed=True,
        )
    )

    raw = path.read_bytes()
    assert b"token-value" not in raw
    assert b"ABCDEF123456" not in raw

    loaded = store.load()
    assert loaded is not None
    assert loaded.totp_token == "token-value"
    assert loaded.totp_secret == "ABCDEF123456"
    assert loaded.expected_static_ip == "203.0.113.10"
    assert loaded.static_ip_confirmed is True
