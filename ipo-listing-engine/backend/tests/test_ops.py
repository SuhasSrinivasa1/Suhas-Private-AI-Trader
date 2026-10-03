from pathlib import Path

from app.audit import AuditLog
from app.live_state import LiveStateStore
from app.order_events import OrderEventStore


def test_live_state_defaults_off(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("IPO_SENTINEL_LIVE_STATE_FILE", str(tmp_path / "state.json"))
    store = LiveStateStore()
    assert store.load().enabled is False


def test_live_state_budget_is_bounded(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("IPO_SENTINEL_LIVE_STATE_FILE", str(tmp_path / "state.json"))
    store = LiveStateStore()
    assert store.save(True, 999_999).budget_rupees == 100_000
    assert store.save(True, 1).budget_rupees == 10_000


def test_order_events_are_monotonic(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("IPO_SENTINEL_ORDER_EVENT_FILE", str(tmp_path / "events.jsonl"))
    store = OrderEventStore()
    first = store.publish("ORDER_PLACING", symbol="ABC", side="BUY", quantity=10)
    second = store.publish("ORDER_FILLED", symbol="ABC", side="BUY", quantity=10, price=100)
    assert second.id == first.id + 1
    assert [e.event_type for e in store.after(first.id)] == ["ORDER_FILLED"]


def test_audit_export(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("IPO_SENTINEL_AUDIT_DIR", str(tmp_path / "audit"))
    log = AuditLog()
    log.append("TEST_EVENT", value=1)
    exported = log.export(7)
    assert "TEST_EVENT" in exported
    assert "value" in exported
