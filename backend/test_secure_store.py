from secure_store import resolve_groww_credentials


def test_environment_credentials_are_supported_for_ci(monkeypatch):
    monkeypatch.setenv("GROWW_API_KEY", "key")
    monkeypatch.setenv("GROWW_API_SECRET", "secret")
    credentials = resolve_groww_credentials()
    assert credentials is not None
    assert credentials.source == "environment"
    assert credentials.api_key == "key"
