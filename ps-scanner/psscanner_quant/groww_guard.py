from __future__ import annotations

"""PS Scanner v6.4.5 Groww Budget Guard v2.

HTTP-layer guard for Groww API traffic. It intentionally does not require the
``growwapi`` package. The app's existing requests-based Groww flow is guarded at
``requests.Session.request`` so authentication retry storms are stopped even when
SDK packaging changes.
"""

import base64
import copy
import hashlib
import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from requests.structures import CaseInsensitiveDict

PATCH_VERSION = "6.4.6-groww-budget-guard-telemetry"
IST = ZoneInfo("Asia/Kolkata")
APP_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = APP_ROOT / ".runtime"
STATE_FILE = STATE_DIR / "groww_budget_guard_state.json"

# Groww published category ceilings used by the local pacer.
OFFICIAL_LIMITS = {
    "AUTHENTICATION": {"per_second": 5, "per_minute": 30, "per_24h": 150},
    "ORDERS": {"per_second": 10, "per_minute": 250},
    "LIVE_DATA": {"per_second": 10, "per_minute": 300},
    "NON_TRADING": {"per_second": 20, "per_minute": 500},
}

# The user explicitly wants off-hours protection but no market-hours suppression.
# Off hours preserve a large recovery reserve. During market hours, the guard may
# use almost the full documented allowance but still never crosses it.
OFF_HOURS_AUTH_24H_GUARD = 100
MARKET_AUTH_24H_GUARD = 149
TOKEN_EXPIRY_BUFFER_SECONDS = 300
MARKET_START = dtime(9, 0)
MARKET_END = dtime(15, 35)

_INSTALL_LOCK = threading.RLock()
_AUTH_LOCK = threading.RLock()
_STATE_LOCK = threading.RLock()
_INSTALLED = False
_INSTALL_ERROR: Optional[str] = None
_ORIGINAL_REQUEST = None
_TOKEN_HTTP_CACHE: Dict[str, Dict[str, Any]] = {}


class GrowwAuthGuardCooldown(requests.exceptions.RetryError):
    """Local deferral protecting Groww's finite authentication allowance."""


def _now_epoch() -> float:
    return time.time()


def _iso(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(float(ts), IST).isoformat(timespec="seconds")


def _market_hours(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(IST)
    if now.weekday() >= 5:
        return False
    t = now.time().replace(tzinfo=None)
    return MARKET_START <= t <= MARKET_END


def _default_state() -> Dict[str, Any]:
    return {
        "version": 2,
        "attempts": [],
        "consecutive_failures": 0,
        "next_allowed_at": 0.0,
        "last_attempt_at": 0.0,
        "last_success_at": 0.0,
        "last_failure_at": 0.0,
        "last_error_kind": None,
        "last_error": None,
        "last_provider_rate_limit_at": 0.0,
        "guard_deferrals": 0,
        "cache_hits": 0,
        "successful_authentications": 0,
    }


def _read_state() -> Dict[str, Any]:
    with _STATE_LOCK:
        state = _default_state()
        try:
            raw = json.loads(STATE_FILE.read_text())
            if isinstance(raw, dict):
                state.update(raw)
        except Exception:
            pass
        now = _now_epoch()
        state["attempts"] = [
            float(x) for x in state.get("attempts", [])
            if isinstance(x, (int, float)) and now - float(x) < 86400.0
        ]
        return state


def _write_state(state: Dict[str, Any]) -> None:
    with _STATE_LOCK:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = dict(state)
        payload["attempts"] = [float(x) for x in payload.get("attempts", [])][-300:]
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, STATE_FILE)
        try:
            os.chmod(STATE_FILE, 0o600)
        except OSError:
            pass


def _classify_error_text(status_code: Optional[int], text: str) -> str:
    s = (text or "").lower()
    if status_code == 429 or "too many requests" in s or "rate limit" in s:
        return "PROVIDER_RATE_LIMIT"
    if status_code in (401, 403) or any(x in s for x in (
        "ga005", "subscription", "not authorised", "not authorized", "auth_required"
    )):
        return "AUTH_OR_ENTITLEMENT"
    return "TRANSIENT"


def _backoff_seconds(kind: str, failures: int, market: bool) -> float:
    failures = max(1, int(failures))
    if kind == "PROVIDER_RATE_LIMIT":
        # Provider-side auth 429 may mean minute or 24h cap. Re-probe sparingly.
        return 1800.0 if market else 3600.0
    market_ladder = (30, 60, 120, 300, 600, 900)
    off_ladder = (300, 900, 1800, 3600, 7200, 10800)
    ladder = market_ladder if market else off_ladder
    delay = float(ladder[min(failures - 1, len(ladder) - 1)])
    if kind == "AUTH_OR_ENTITLEMENT":
        delay = max(delay, 300.0 if market else 3600.0)
    return delay


def _auth_guard_limit() -> int:
    return MARKET_AUTH_24H_GUARD if _market_hours() else OFF_HOURS_AUTH_24H_GUARD


def _quota_wait(state: Dict[str, Any], now: float) -> float:
    attempts = sorted(float(x) for x in state.get("attempts", []) if now - float(x) < 86400.0)
    state["attempts"] = attempts
    one = [x for x in attempts if now - x < 1.0]
    minute = [x for x in attempts if now - x < 60.0]
    delays = []
    if len(one) >= OFFICIAL_LIMITS["AUTHENTICATION"]["per_second"]:
        delays.append(one[0] + 1.05 - now)
    if len(minute) >= OFFICIAL_LIMITS["AUTHENTICATION"]["per_minute"]:
        delays.append(minute[0] + 60.10 - now)
    if len(attempts) >= _auth_guard_limit():
        delays.append(attempts[0] + 86400.10 - now)
    return max([0.0] + delays)


def _parse_expiry(value: Any) -> Optional[float]:
    if not value:
        return None
    try:
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.timestamp()
    except Exception:
        return None


def _decode_jwt_exp(token: str) -> Optional[float]:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        seg = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(seg.encode()).decode())
        exp = payload.get("exp")
        return float(exp) if isinstance(exp, (int, float)) else None
    except Exception:
        return None


def _response_expiry(resp: requests.Response) -> float:
    try:
        data = resp.json()
    except Exception:
        data = {}
    if isinstance(data, dict):
        explicit = _parse_expiry(data.get("expiry") or data.get("expires_at"))
        if explicit:
            return explicit
        token = data.get("token") or data.get("access_token")
        if isinstance(token, str):
            exp = _decode_jwt_exp(token)
            if exp:
                return exp
    now = datetime.now(IST)
    boundary = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now >= boundary:
        boundary += timedelta(days=1)
    return boundary.timestamp()


def _auth_fingerprint(kwargs: Dict[str, Any]) -> str:
    headers = kwargs.get("headers") or {}
    auth = ""
    try:
        auth = headers.get("Authorization") or headers.get("authorization") or ""
    except Exception:
        auth = ""
    if not auth:
        return "default"
    return hashlib.sha256(str(auth).encode("utf-8", "ignore")).hexdigest()[:12]


def _cache_response(resp: requests.Response, expiry: float) -> Dict[str, Any]:
    return {
        "status_code": int(resp.status_code),
        "content": bytes(resp.content or b""),
        "headers": dict(resp.headers or {}),
        "url": resp.url,
        "reason": resp.reason,
        "encoding": resp.encoding,
        "expiry": float(expiry),
    }


def _restore_response(item: Dict[str, Any]) -> requests.Response:
    resp = requests.Response()
    resp.status_code = int(item["status_code"])
    resp._content = bytes(item["content"])
    resp.headers = CaseInsensitiveDict(item.get("headers") or {})
    resp.url = item.get("url") or "https://api.groww.in/v1/token/api/access"
    resp.reason = item.get("reason")
    resp.encoding = item.get("encoding")
    return resp


class _SlidingWindowPacer:
    """Provider-limit pacer. It waits; it never rejects or drops normal calls."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events = {k: deque() for k in ("ORDERS", "LIVE_DATA", "NON_TRADING")}
        self._stats = {
            k: {
                "total_calls": 0, "delayed_calls": 0, "total_wait_seconds": 0.0, "last_call_at": None,
                "completed_responses": 0, "successful_responses": 0, "failed_responses": 0,
                "exceptions": 0, "provider_429_responses": 0, "last_status_code": None,
                "last_success_at": None, "last_failure_at": None,
            }
            for k in self._events
        }

    def before(self, category: str) -> None:
        limits = OFFICIAL_LIMITS[category]
        waited = 0.0
        delayed = False
        while True:
            now = time.monotonic()
            with self._lock:
                q = self._events[category]
                while q and now - q[0] >= 60.20:
                    q.popleft()
                one = [x for x in q if now - x < 1.0]
                minute = [x for x in q if now - x < 60.0]
                delay = 0.0
                if len(one) >= limits["per_second"]:
                    delay = max(delay, one[0] + 1.05 - now)
                if len(minute) >= limits["per_minute"]:
                    delay = max(delay, minute[0] + 60.10 - now)
                if delay <= 0:
                    q.append(now)
                    st = self._stats[category]
                    st["total_calls"] += 1
                    st["last_call_at"] = datetime.now(IST).isoformat(timespec="seconds")
                    if delayed:
                        st["delayed_calls"] += 1
                        st["total_wait_seconds"] = round(float(st["total_wait_seconds"]) + waited, 3)
                    return
            delayed = True
            sleep_for = max(0.01, delay)
            waited += sleep_for
            time.sleep(sleep_for)

    def after(self, category: str, response: Optional[requests.Response] = None, exc: Optional[BaseException] = None) -> None:
        with self._lock:
            st = self._stats[category]
            stamp = datetime.now(IST).isoformat(timespec="seconds")
            if exc is not None:
                st["exceptions"] += 1
                st["last_failure_at"] = stamp
                return
            code = int(getattr(response, "status_code", 0) or 0)
            st["completed_responses"] += 1
            st["last_status_code"] = code or None
            if 200 <= code < 300:
                st["successful_responses"] += 1
                st["last_success_at"] = stamp
            else:
                st["failed_responses"] += 1
                st["last_failure_at"] = stamp
                if code == 429:
                    st["provider_429_responses"] += 1

    def status(self) -> Dict[str, Any]:
        now = time.monotonic()
        out: Dict[str, Any] = {}
        with self._lock:
            for cat, q in self._events.items():
                recent = [x for x in q if now - x < 60.0]
                sec = [x for x in recent if now - x < 1.0]
                st = dict(self._stats[cat])
                st.update({
                    "requests_last_1s": len(sec),
                    "requests_last_60s": len(recent),
                    "limit_per_second": OFFICIAL_LIMITS[cat]["per_second"],
                    "limit_per_minute": OFFICIAL_LIMITS[cat]["per_minute"],
                    "behavior_at_limit": "WAIT_THEN_SEND_NEVER_DROP",
                })
                out[cat] = st
        return out


_PACER = _SlidingWindowPacer()


def _groww_category(url: str) -> Optional[str]:
    try:
        p = urlparse(str(url))
    except Exception:
        return None
    if p.hostname != "api.groww.in":
        return None
    path = p.path.lower()
    if path == "/v1/token/api/access":
        return "AUTHENTICATION"
    if "/historical/" in path:
        return None  # existing PS Scanner history controller owns this path
    if "/live-data/" in path or any(x in path for x in ("/quote", "/ltp", "/ohlc")):
        return "LIVE_DATA"
    if "/order" in path and any(x in path for x in ("create", "place", "modify", "cancel")):
        return "ORDERS"
    # Other REST calls to Groww are treated as non-trading for pacing purposes.
    return "NON_TRADING"


def _auth_request(session: requests.Session, method: str, url: str, args: tuple, kwargs: Dict[str, Any]):
    if _ORIGINAL_REQUEST is None:
        raise RuntimeError("Groww HTTP guard not initialised")
    fp = _auth_fingerprint(kwargs)
    with _AUTH_LOCK:
        now = _now_epoch()
        cached = _TOKEN_HTTP_CACHE.get(fp)
        if cached and now < float(cached.get("expiry", 0.0)) - TOKEN_EXPIRY_BUFFER_SECONDS:
            state = _read_state()
            state["cache_hits"] = int(state.get("cache_hits", 0)) + 1
            _write_state(state)
            return _restore_response(cached)
        if cached:
            _TOKEN_HTTP_CACHE.pop(fp, None)

        state = _read_state()
        next_allowed = float(state.get("next_allowed_at", 0.0) or 0.0)
        quota_wait = _quota_wait(state, now)
        if quota_wait > 0:
            next_allowed = max(next_allowed, now + quota_wait)
            state["next_allowed_at"] = next_allowed
        if now < next_allowed:
            state["guard_deferrals"] = int(state.get("guard_deferrals", 0)) + 1
            _write_state(state)
            raise GrowwAuthGuardCooldown(
                "Groww authentication deferred by PS Scanner budget guard until " + str(_iso(next_allowed))
            )

        state["attempts"].append(now)
        state["last_attempt_at"] = now
        _write_state(state)
        try:
            resp = _ORIGINAL_REQUEST(session, method, url, *args, **kwargs)
        except BaseException as exc:
            failed = _read_state()
            failed["consecutive_failures"] = int(failed.get("consecutive_failures", 0)) + 1
            failed["last_failure_at"] = _now_epoch()
            kind = _classify_error_text(None, str(exc))
            failed["last_error_kind"] = kind
            failed["last_error"] = str(exc)[:500]
            if kind == "PROVIDER_RATE_LIMIT":
                failed["last_provider_rate_limit_at"] = failed["last_failure_at"]
            failed["next_allowed_at"] = failed["last_failure_at"] + _backoff_seconds(
                kind, failed["consecutive_failures"], _market_hours()
            )
            _write_state(failed)
            raise

        if 200 <= int(resp.status_code) < 300:
            success_at = _now_epoch()
            expiry = _response_expiry(resp)
            _TOKEN_HTTP_CACHE[fp] = _cache_response(resp, expiry)
            ok = _read_state()
            ok["consecutive_failures"] = 0
            ok["next_allowed_at"] = 0.0
            ok["last_success_at"] = success_at
            ok["last_error_kind"] = None
            ok["last_error"] = None
            ok["successful_authentications"] = int(ok.get("successful_authentications", 0)) + 1
            _write_state(ok)
            return resp

        failed = _read_state()
        failed["consecutive_failures"] = int(failed.get("consecutive_failures", 0)) + 1
        failed["last_failure_at"] = _now_epoch()
        try:
            text = resp.text[:500]
        except Exception:
            text = ""
        kind = _classify_error_text(int(resp.status_code), text)
        failed["last_error_kind"] = kind
        failed["last_error"] = ("HTTP %s: %s" % (resp.status_code, text))[:500]
        if kind == "PROVIDER_RATE_LIMIT":
            failed["last_provider_rate_limit_at"] = failed["last_failure_at"]
        failed["next_allowed_at"] = failed["last_failure_at"] + _backoff_seconds(
            kind, failed["consecutive_failures"], _market_hours()
        )
        _write_state(failed)
        return resp


def _guarded_request(self: requests.Session, method: str, url: str, *args: Any, **kwargs: Any):
    category = _groww_category(url)
    if category is None:
        return _ORIGINAL_REQUEST(self, method, url, *args, **kwargs)
    if category == "AUTHENTICATION":
        return _auth_request(self, method, url, args, kwargs)
    _PACER.before(category)
    try:
        resp = _ORIGINAL_REQUEST(self, method, url, *args, **kwargs)
    except BaseException as exc:
        _PACER.after(category, exc=exc)
        raise
    _PACER.after(category, response=resp)
    return resp


def install() -> Dict[str, Any]:
    global _INSTALLED, _INSTALL_ERROR, _ORIGINAL_REQUEST
    with _INSTALL_LOCK:
        if _INSTALLED:
            return status()
        try:
            current = requests.sessions.Session.request
            if getattr(current, "_psscanner_v645_v2_wrapped", False):
                _INSTALLED = True
                _INSTALL_ERROR = None
                return status()
            _ORIGINAL_REQUEST = current
            setattr(_guarded_request, "_psscanner_v645_v2_wrapped", True)
            requests.sessions.Session.request = _guarded_request
            _INSTALLED = True
            _INSTALL_ERROR = None
        except Exception as exc:
            _INSTALL_ERROR = "%s: %s" % (exc.__class__.__name__, exc)
        return status()


def status() -> Dict[str, Any]:
    state = _read_state()
    now = _now_epoch()
    attempts = [float(x) for x in state.get("attempts", []) if now - float(x) < 86400.0]
    minute = [x for x in attempts if now - x < 60.0]
    second = [x for x in attempts if now - x < 1.0]
    next_allowed = float(state.get("next_allowed_at", 0.0) or 0.0)
    market = _market_hours()
    return {
        "patch": PATCH_VERSION,
        "installed": _INSTALLED,
        "install_error": _INSTALL_ERROR,
        "policy_mode": "MARKET_HOURS_PACE_ONLY" if market else "OFF_HOURS_AUTH_BUDGET_PROTECTION",
        "market_hours_policy": "PACE_TO_PUBLISHED_LIMITS; WAIT_IF_NEEDED; NEVER_DROP_NORMAL_GROWW_CALLS",
        "off_hours_policy": "PRESERVE_AUTH_BUDGET; CACHE_SUCCESSFUL_AUTH_RESPONSE; BACKOFF_ON_FAILURE",
        "history_policy": "UNCHANGED_EXISTING_PS_SCANNER_HISTORY_CONTROLLER",
        "http_guard": "requests.Session.request",
        "auth": {
            "attempts_last_1s": len(second),
            "attempts_last_60s": len(minute),
            "attempts_last_24h": len(attempts),
            "current_local_24h_guard": _auth_guard_limit(),
            "off_hours_local_24h_guard": OFF_HOURS_AUTH_24H_GUARD,
            "market_hours_local_24h_guard": MARKET_AUTH_24H_GUARD,
            "published_24h_limit": OFFICIAL_LIMITS["AUTHENTICATION"]["per_24h"],
            "consecutive_failures": int(state.get("consecutive_failures", 0)),
            "next_allowed_at": _iso(next_allowed),
            "cooldown_remaining_seconds": round(max(0.0, next_allowed - now), 2),
            "last_attempt_at": _iso(state.get("last_attempt_at")),
            "last_success_at": _iso(state.get("last_success_at")),
            "last_failure_at": _iso(state.get("last_failure_at")),
            "last_error_kind": state.get("last_error_kind"),
            "last_error": state.get("last_error"),
            "last_provider_rate_limit_at": _iso(state.get("last_provider_rate_limit_at")),
            "guard_deferrals": int(state.get("guard_deferrals", 0)),
            "cache_hits": int(state.get("cache_hits", 0)),
            "successful_authentications": int(state.get("successful_authentications", 0)),
            "token_http_cache_entries": len(_TOKEN_HTTP_CACHE),
            "token_persisted_to_disk": False,
        },
        "request_pacing": _PACER.status(),
        "official_limits": OFFICIAL_LIMITS,
    }


install()
