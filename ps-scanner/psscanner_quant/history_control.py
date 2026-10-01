from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional

from .config import load_settings
from .constants import IST
from .db import health, now_iso
from .paths import DATA

_STATE_PATH = DATA / "history_control.json"
_LOCK = RLock()
_LAST_REQUEST_MONO = 0.0
_GLOBAL_COOLDOWN_UNTIL = 0.0
_CONSECUTIVE_429 = 0


def _empty_state() -> Dict[str, Any]:
    return {
        "quarantine": {},
        "rate_limit_events": 0,
        "invalid_request_events": 0,
        "successful_requests": 0,
        "legacy_false_quarantines_cleared": 0,
        "last_rate_limit_at": None,
        "last_success_at": None,
        "updated_at": None,
    }


def _load_state() -> Dict[str, Any]:
    try:
        if _STATE_PATH.exists():
            d = json.loads(_STATE_PATH.read_text())
            if isinstance(d, dict):
                base = _empty_state(); base.update(d)
                if not isinstance(base.get("quarantine"), dict):
                    base["quarantine"] = {}
                # v6.2.3 migration: v6.2.1-v6.2.2 used 365/1080-day requests
                # against Groww's new backtesting endpoint, whose 1-day candles are
                # capped at 180 calendar days per request. Those false HTTP-400
                # quarantines are safe to remove; other quarantines are preserved.
                q = dict(base.get("quarantine") or {})
                removed = 0
                for key, item in list(q.items()):
                    if not isinstance(item, dict):
                        continue
                    if (str(key).lower().endswith("|1day")
                        and int(item.get("status_code") or 0) == 400
                        and str(item.get("reason") or "") == "HTTP 400 historical request rejected"):
                        q.pop(key, None); removed += 1
                if removed:
                    base["quarantine"] = q
                    base["legacy_false_quarantines_cleared"] = int(base.get("legacy_false_quarantines_cleared") or 0) + removed
                    _save_state(base)
                return base
    except Exception:
        pass
    return _empty_state()


def _save_state(d: Dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    d = dict(d); d["updated_at"] = now_iso()
    tmp = _STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, sort_keys=True, default=str))
    os.replace(tmp, _STATE_PATH)


def _parse_iso(s: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(s))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except Exception:
        return None


def quarantine_key(groww_symbol: str, interval: str) -> str:
    return f"{str(groww_symbol).upper()}|{str(interval).lower()}"


def quarantine_status(groww_symbol: str, interval: str) -> Dict[str, Any]:
    key = quarantine_key(groww_symbol, interval)
    with _LOCK:
        state = _load_state(); q = dict(state.get("quarantine") or {})
        item = q.get(key)
        if not isinstance(item, dict):
            return {"quarantined": False, "key": key}
        until = _parse_iso(item.get("until"))
        if until is None or until <= datetime.now(IST):
            q.pop(key, None); state["quarantine"] = q; _save_state(state)
            return {"quarantined": False, "key": key}
        return {"quarantined": True, "key": key, **item}


def quarantine(groww_symbol: str, interval: str, reason: str, *, hours: Optional[float] = None, status_code: Optional[int] = None) -> Dict[str, Any]:
    settings = load_settings()
    h = float(hours if hours is not None else settings.get("history_invalid_symbol_quarantine_hours", 12.0))
    key = quarantine_key(groww_symbol, interval)
    now = datetime.now(IST); until = now + timedelta(hours=max(0.25, h))
    with _LOCK:
        state = _load_state(); q = dict(state.get("quarantine") or {})
        prev = q.get(key) if isinstance(q.get(key), dict) else {}
        item = {
            "reason": str(reason)[:240],
            "status_code": status_code,
            "first_seen_at": prev.get("first_seen_at") or now.isoformat(timespec="seconds"),
            "last_seen_at": now.isoformat(timespec="seconds"),
            "until": until.isoformat(timespec="seconds"),
            "failures": int(prev.get("failures") or 0) + 1,
        }
        q[key] = item; state["quarantine"] = q
        state["invalid_request_events"] = int(state.get("invalid_request_events") or 0) + 1
        _save_state(state)
    health("history_quarantine", "WARN", f"{groww_symbol} {interval} quarantined until {until.isoformat(timespec='seconds')}: {reason}")
    return {"quarantined": True, "key": key, **item}


def clear_quarantine(groww_symbol: str, interval: str) -> None:
    key = quarantine_key(groww_symbol, interval)
    with _LOCK:
        state = _load_state(); q = dict(state.get("quarantine") or {})
        if key in q:
            q.pop(key, None); state["quarantine"] = q; _save_state(state)


def wait_for_slot() -> float:
    """Serialize Groww historical requests and enforce global adaptive cooldown.

    This gate is intentionally specific to historical candles so live quote/order traffic is
    not delayed by background cache warming. Holding the lock while sleeping guarantees that
    concurrent research jobs cannot burst through the broker rate limit together.
    """
    global _LAST_REQUEST_MONO
    settings = load_settings()
    min_gap = max(0.25, float(settings.get("history_min_request_interval_seconds", 1.25)))
    with _LOCK:
        now_wall = time.time(); now_mono = time.monotonic()
        wait = max(0.0, _GLOBAL_COOLDOWN_UNTIL - now_wall, min_gap - (now_mono - _LAST_REQUEST_MONO))
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST_MONO = time.monotonic()
        return wait


def record_rate_limit(retry_after: Optional[str] = None) -> float:
    global _GLOBAL_COOLDOWN_UNTIL, _CONSECUTIVE_429
    settings = load_settings()
    base = max(1.0, float(settings.get("history_429_backoff_base_seconds", 5.0)))
    cap = max(base, float(settings.get("history_429_backoff_max_seconds", 60.0)))
    with _LOCK:
        _CONSECUTIVE_429 += 1
        delay = min(cap, base * (2 ** min(4, _CONSECUTIVE_429 - 1)) + random.uniform(0.0, 1.0))
        try:
            if retry_after not in (None, ""):
                delay = max(delay, min(cap, float(retry_after)))
        except Exception:
            pass
        _GLOBAL_COOLDOWN_UNTIL = max(_GLOBAL_COOLDOWN_UNTIL, time.time() + delay)
        state = _load_state()
        state["rate_limit_events"] = int(state.get("rate_limit_events") or 0) + 1
        state["last_rate_limit_at"] = now_iso()
        _save_state(state)
        return delay


def record_success() -> None:
    global _CONSECUTIVE_429
    with _LOCK:
        _CONSECUTIVE_429 = max(0, _CONSECUTIVE_429 - 1)
        state = _load_state()
        state["successful_requests"] = int(state.get("successful_requests") or 0) + 1
        state["last_success_at"] = now_iso()
        _save_state(state)


def status_cached() -> Dict[str, Any]:
    """Return passive history-control telemetry without ever waiting for the pacer lock.

    The history request pacer intentionally owns _LOCK while sleeping through rate-limit
    cooldowns. Health/readiness endpoints must never queue behind that sleep. If another
    worker owns the pacer, expose a truthful BUSY snapshot from lock-free in-memory fields
    and let the next health poll collect the detailed persisted counters.
    """
    acquired=_LOCK.acquire(blocking=False)
    if not acquired:
        return {
            "mode":"CENTRAL_PACED_HISTORY_WITH_GROWW_WINDOW_CONTRACT_V2",
            "status":"PACER_BUSY_NONBLOCKING_SNAPSHOT",
            "pacer_busy":True,
            "global_cooldown_remaining_seconds":round(max(0.0,_GLOBAL_COOLDOWN_UNTIL-time.time()),2),
            "consecutive_429":int(_CONSECUTIVE_429),
            "nonblocking":True,
        }
    try:
        out=status()
        out=dict(out)
        out["status"]="READY"
        out["pacer_busy"]=False
        out["nonblocking"]=True
        return out
    finally:
        _LOCK.release()


def status() -> Dict[str, Any]:
    settings = load_settings()
    with _LOCK:
        state = _load_state(); q = dict(state.get("quarantine") or {})
        active = {}
        now = datetime.now(IST)
        changed = False
        for k, v in q.items():
            until = _parse_iso((v or {}).get("until") if isinstance(v, dict) else None)
            if until and until > now:
                active[k] = v
            else:
                changed = True
        if changed:
            state["quarantine"] = active; _save_state(state)
        cooldown = max(0.0, _GLOBAL_COOLDOWN_UNTIL - time.time())
        return {
            "mode": "CENTRAL_PACED_HISTORY_WITH_GROWW_WINDOW_CONTRACT_V2",
            "minimum_request_interval_seconds": float(settings.get("history_min_request_interval_seconds", 1.25)),
            "global_cooldown_remaining_seconds": round(cooldown, 2),
            "consecutive_429": int(_CONSECUTIVE_429),
            "active_quarantines": len(active),
            "rate_limit_events": int(state.get("rate_limit_events") or 0),
            "invalid_request_events": int(state.get("invalid_request_events") or 0),
            "successful_requests": int(state.get("successful_requests") or 0),
            "legacy_false_quarantines_cleared": int(state.get("legacy_false_quarantines_cleared") or 0),
            "api_window_contract": {
                "endpoint": "/v1/historical/candles",
                "daily_max_days_documented": 180,
                "daily_chunk_days": int(settings.get("history_daily_chunk_days", 175)),
                "daily_target_days": int(settings.get("history_daily_target_days", 350)),
                "five_minute_max_days_documented": 30,
            },
            "last_rate_limit_at": state.get("last_rate_limit_at"),
            "last_success_at": state.get("last_success_at"),
            "priority_policy": [
                "LIVE_AND_FROZEN_NSE_RECOMMENDATIONS",
                "NEW_LISTINGS_AND_MISSING_FULL_NSE_EQUITY_CACHE",
                "ROTATING_FULL_NSE_EQUITY_BACKGROUND_WARMUP",
                "ETF_BACKGROUND_WARMUP",
            ],
        }
