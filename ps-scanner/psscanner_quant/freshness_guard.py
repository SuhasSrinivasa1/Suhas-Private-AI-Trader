from __future__ import annotations

"""PS Scanner v6.4.6 intraday market-data freshness integrity guard.

This guard does not throttle normal market-hours Groww traffic.  It protects the
semantic meaning of an INTRADAY LIVE recommendation: a new call must have a
same-session, recent feature snapshot and recent successful Groww live-data
transport.  Stale candidates are preserved in an audit ledger instead of being
published as LIVE or counted as CLOSED learning evidence.
"""

import ast
import functools
import hashlib
import importlib
import inspect
import json
import sys
import threading
import time
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

PATCH_VERSION = "6.4.6-freshness-integrity"
IST = ZoneInfo("Asia/Kolkata")
SESSION_START = dtime(9, 15)
SESSION_END = dtime(15, 30)
MAX_FEATURE_AGE_SECONDS = int(__import__("os").environ.get("PS_SCANNER_INTRADAY_FRESHNESS_SECONDS", "900"))
LIVE_TRANSPORT_MAX_AGE_SECONDS = int(__import__("os").environ.get("PS_SCANNER_LIVE_TRANSPORT_FRESHNESS_SECONDS", "180"))

_INSTALL_LOCK = threading.RLock()
_INSTALLED = False
_INSTALL_ERROR: Optional[str] = None
_WRAPPED_MODULES: List[str] = []
_SWEEPER_THREAD: Optional[threading.Thread] = None
_STOP = threading.Event()
_LAST_SWEEP: Dict[str, Any] = {}


def _now() -> datetime:
    return datetime.now(IST)


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except Exception:
        return None


def _regular_trading_day(day) -> bool:
    try:
        from .trading_calendar import is_regular_trading_day
        return bool(is_regular_trading_day(day))
    except Exception:
        return day.weekday() < 5


def _market_hours(now: Optional[datetime] = None) -> bool:
    now = now or _now()
    t = now.time().replace(tzinfo=None)
    return _regular_trading_day(now.date()) and SESSION_START <= t <= SESSION_END


def assess_feature_freshness(features: Any, at: Optional[datetime] = None) -> Dict[str, Any]:
    at = (at or _now()).astimezone(IST)
    f = features if isinstance(features, dict) else {}
    asof = _parse_dt(f.get("asof"))
    if asof is None:
        return {"fresh": False, "reason": "FEATURE_ASOF_MISSING", "feature_asof": None, "age_seconds": None}
    age = (at - asof).total_seconds()
    if asof.date() != at.date():
        return {"fresh": False, "reason": "FEATURE_FROM_DIFFERENT_SESSION", "feature_asof": asof.isoformat(), "age_seconds": round(age, 2)}
    if age < -300:
        return {"fresh": False, "reason": "FEATURE_TIMESTAMP_IN_FUTURE", "feature_asof": asof.isoformat(), "age_seconds": round(age, 2)}
    if age > MAX_FEATURE_AGE_SECONDS:
        return {"fresh": False, "reason": "FEATURE_TOO_OLD_FOR_NEW_INTRADAY_CALL", "feature_asof": asof.isoformat(), "age_seconds": round(age, 2)}
    return {"fresh": True, "reason": "FRESH", "feature_asof": asof.isoformat(), "age_seconds": round(max(0.0, age), 2)}


def _live_transport() -> Dict[str, Any]:
    try:
        from . import groww_guard
        g = groww_guard.status()
        live = ((g.get("request_pacing") or {}).get("LIVE_DATA") or {})
        last = _parse_dt(live.get("last_success_at"))
        age = (_now() - last).total_seconds() if last else None
        return {
            "recent": bool(last and age is not None and age <= LIVE_TRANSPORT_MAX_AGE_SECONDS),
            "last_success_at": live.get("last_success_at"),
            "age_seconds": round(age, 2) if age is not None else None,
            "successful_responses": int(live.get("successful_responses", 0) or 0),
            "failed_responses": int(live.get("failed_responses", 0) or 0),
            "last_status_code": live.get("last_status_code"),
        }
    except Exception as exc:
        return {"recent": False, "last_success_at": None, "age_seconds": None, "error": str(exc)[:240]}


def _db_columns(con, table: str) -> List[str]:
    return [str(r[1]) for r in con.execute("PRAGMA table_info(%s)" % table).fetchall()]


def _ensure_ledger(con) -> None:
    con.execute("""
    CREATE TABLE IF NOT EXISTS freshness_holds (
      hold_id TEXT PRIMARY KEY,
      patch_version TEXT NOT NULL,
      recommendation_id TEXT,
      book TEXT,
      symbol TEXT,
      side TEXT,
      period_key TEXT,
      previous_state TEXT,
      detected_at TEXT NOT NULL,
      reason TEXT NOT NULL,
      feature_asof TEXT,
      feature_age_seconds REAL,
      source TEXT NOT NULL,
      payload_json TEXT NOT NULL DEFAULT '{}'
    )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_freshness_holds_day ON freshness_holds(period_key,detected_at)")


def _feature_column(cols: List[str]) -> Optional[str]:
    for name in ("feature_snapshot_json", "features_json", "feature_json", "features"):
        if name in cols:
            return name
    return None


def _decode_features(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    try:
        x = json.loads(str(raw))
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}


def _safe_json(value: Any) -> str:
    def default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return repr(o)
    return json.dumps(value, default=default, separators=(",", ":"), ensure_ascii=False)


def _ledger_insert(con, *, recommendation_id=None, book="INTRADAY", symbol=None, side=None,
                   period_key=None, previous_state=None, reason="", feature_asof=None,
                   feature_age_seconds=None, source="", payload=None) -> str:
    detected = _now().isoformat(timespec="seconds")
    seed = "%s|%s|%s|%s|%s|%s" % (recommendation_id or "", symbol or "", side or "", detected, reason, source)
    hold_id = hashlib.sha256(seed.encode()).hexdigest()[:32]
    con.execute(
        "INSERT OR IGNORE INTO freshness_holds(hold_id,patch_version,recommendation_id,book,symbol,side,period_key,previous_state,detected_at,reason,feature_asof,feature_age_seconds,source,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (hold_id, PATCH_VERSION, recommendation_id, book, symbol, side, period_key, previous_state,
         detected, reason, feature_asof, feature_age_seconds, source, _safe_json(payload or {})),
    )
    return hold_id


def _quarantine_existing_current_day() -> Dict[str, Any]:
    out = {"at": _now().isoformat(timespec="seconds"), "examined": 0, "quarantined": 0, "errors": []}
    try:
        from .db import db
        day = _now().date().isoformat()
        with db() as con:
            cols = _db_columns(con, "recommendations")
            _ensure_ledger(con)
            fcol = _feature_column(cols)
            needed = {"book", "period_key", "state", "created_at", "recommendation_id", "symbol", "side"}
            if not needed.issubset(set(cols)) or not fcol:
                out["errors"].append("recommendations schema lacks freshness fields")
                return out
            rows = con.execute(
                "SELECT * FROM recommendations WHERE book='INTRADAY' AND period_key=? AND state IN ('LIVE','CLOSED')",
                (day,),
            ).fetchall()
            for row in rows:
                d = dict(row)
                out["examined"] += 1
                created = _parse_dt(d.get("created_at")) or _now()
                check = assess_feature_freshness(_decode_features(d.get(fcol)), at=created)
                if check["fresh"]:
                    continue
                _ledger_insert(
                    con, recommendation_id=d.get("recommendation_id"), symbol=d.get("symbol"), side=d.get("side"),
                    period_key=d.get("period_key"), previous_state=d.get("state"), reason=check["reason"],
                    feature_asof=check.get("feature_asof"), feature_age_seconds=check.get("age_seconds"),
                    source="EXISTING_RECOMMENDATION_QUARANTINE", payload=d,
                )
                assignments = ["state='STALE_DATA'"]
                if "data_confidence" in cols:
                    assignments.append("data_confidence=0.0")
                con.execute(
                    "UPDATE recommendations SET %s WHERE recommendation_id=? AND state IN ('LIVE','CLOSED')" % ",".join(assignments),
                    (d.get("recommendation_id"),),
                )
                out["quarantined"] += 1
    except Exception as exc:
        out["errors"].append("%s: %s" % (exc.__class__.__name__, exc))
    return out


def _extract_insert_call(fn, args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
        data.update(bound.arguments)
    except Exception:
        pass
    fallback = ("book", "symbol", "side", "score", "confidence", "price", "features", "source", "strategy_ids", "rationale")
    for i, name in enumerate(fallback):
        if name not in data and i < len(args):
            data[name] = args[i]
    data.update({k: v for k, v in kwargs.items() if k not in data})
    return data


def _record_intercept(call: Dict[str, Any], check: Dict[str, Any], reason: str) -> None:
    try:
        from .db import db
        with db() as con:
            _ensure_ledger(con)
            _ledger_insert(
                con, book=str(call.get("book") or "INTRADAY"), symbol=call.get("symbol"), side=call.get("side"),
                period_key=str(call.get("period_key_override") or _now().date().isoformat()), previous_state="PREINSERT",
                reason=reason, feature_asof=check.get("feature_asof"), feature_age_seconds=check.get("age_seconds"),
                source="PREINSERT_PUBLICATION_HOLD", payload=call,
            )
    except Exception:
        pass


def _make_insert_wrapper(fn, module_name: str):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        call = _extract_insert_call(fn, args, kwargs)
        if str(call.get("book") or "").upper() == "INTRADAY" and _market_hours():
            check = assess_feature_freshness(call.get("features"))
            transport = _live_transport()
            if not check["fresh"]:
                _record_intercept(call, check, check["reason"])
                return None
            if not transport.get("recent"):
                _record_intercept(call, check, "LIVE_TRANSPORT_NOT_RECENT")
                return None
            features = call.get("features")
            if isinstance(features, dict):
                features["market_data_integrity"] = {
                    "status": "FRESH_AT_PUBLICATION", "checked_at": _now().isoformat(timespec="seconds"),
                    "feature_asof": check.get("feature_asof"), "feature_age_seconds": check.get("age_seconds"),
                    "live_transport_last_success_at": transport.get("last_success_at"),
                }
            rationale = call.get("rationale")
            if isinstance(rationale, dict):
                rationale["market_data_integrity"] = "FRESH_AT_PUBLICATION"
        return fn(*args, **kwargs)
    wrapped._ps_v646_freshness_wrapped = True
    wrapped._ps_v646_module = module_name
    return wrapped


def _candidate_modules() -> List[str]:
    names = {"psscanner_quant.engine", "psscanner_quant.specialized", "psscanner_quant.cross_market"}
    pkg = Path(__file__).resolve().parent
    for path in pkg.glob("*.py"):
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
            if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_insert_rec" for n in tree.body):
                names.add("psscanner_quant." + path.stem)
        except Exception:
            pass
    return sorted(names)


def _wrap_insert_paths() -> List[str]:
    wrapped = []
    for name in _candidate_modules():
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        fn = getattr(mod, "_insert_rec", None)
        if callable(fn) and not getattr(fn, "_ps_v646_freshness_wrapped", False):
            setattr(mod, "_insert_rec", _make_insert_wrapper(fn, name))
            wrapped.append(name)
    # Also update already-loaded aliases imported with `from ... import _insert_rec`.
    for name, mod in list(sys.modules.items()):
        if not name.startswith("psscanner_quant.") or mod is None:
            continue
        fn = getattr(mod, "_insert_rec", None)
        if callable(fn) and not getattr(fn, "_ps_v646_freshness_wrapped", False):
            try:
                setattr(mod, "_insert_rec", _make_insert_wrapper(fn, name))
                wrapped.append(name)
            except Exception:
                pass
    return sorted(set(wrapped))


def _guard_shadow_cycle() -> None:
    try:
        lab = importlib.import_module("psscanner_quant.strategy_lab")
        fn = getattr(lab, "run_shadow_cycle", None)
        if not callable(fn) or getattr(fn, "_ps_v646_freshness_wrapped", False):
            return
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            if _market_hours() and not _live_transport().get("recent"):
                return {"status": "WAITING_FOR_FRESH_LIVE_DATA", "opened": 0, "at": _now().isoformat(timespec="seconds"),
                        "policy": "No new live-shadow evidence is opened while Groww live-data transport is not recent."}
            return fn(*args, **kwargs)
        wrapped._ps_v646_freshness_wrapped = True
        setattr(lab, "run_shadow_cycle", wrapped)
        # engine imports this function inside the worker each cycle, so future imports resolve the wrapper.
    except Exception:
        pass


def _sweeper() -> None:
    global _LAST_SWEEP
    while not _STOP.wait(30.0):
        _LAST_SWEEP = _quarantine_existing_current_day()


def install_runtime(app=None) -> Dict[str, Any]:
    global _INSTALLED, _INSTALL_ERROR, _WRAPPED_MODULES, _SWEEPER_THREAD, _LAST_SWEEP
    with _INSTALL_LOCK:
        if _INSTALLED:
            return status()
        try:
            _WRAPPED_MODULES = _wrap_insert_paths()
            _guard_shadow_cycle()
            _LAST_SWEEP = _quarantine_existing_current_day()
            _STOP.clear()
            _SWEEPER_THREAD = threading.Thread(target=_sweeper, name="psq-v646-freshness", daemon=True)
            _SWEEPER_THREAD.start()
            _INSTALLED = True
            _INSTALL_ERROR = None
        except Exception as exc:
            _INSTALL_ERROR = "%s: %s" % (exc.__class__.__name__, exc)
        return status()


def holds(limit: int = 50) -> Dict[str, Any]:
    limit = max(1, min(200, int(limit)))
    rows: List[Dict[str, Any]] = []
    try:
        from .db import db
        with db() as con:
            _ensure_ledger(con)
            q = con.execute(
                "SELECT hold_id,recommendation_id,book,symbol,side,period_key,previous_state,detected_at,reason,feature_asof,feature_age_seconds,source FROM freshness_holds ORDER BY detected_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            rows = [dict(r) for r in q]
    except Exception:
        pass
    return {"patch": PATCH_VERSION, "count": len(rows), "items": rows}


def _hold_counts() -> Dict[str, int]:
    try:
        from .db import db
        with db() as con:
            _ensure_ledger(con)
            total = int(con.execute("SELECT COUNT(*) FROM freshness_holds").fetchone()[0])
            day = _now().date().isoformat()
            today = int(con.execute("SELECT COUNT(*) FROM freshness_holds WHERE period_key=?", (day,)).fetchone()[0])
            return {"total": total, "today": today}
    except Exception:
        return {"total": 0, "today": 0}


def status() -> Dict[str, Any]:
    transport = _live_transport()
    counts = _hold_counts()
    return {
        "patch": PATCH_VERSION,
        "installed": _INSTALLED,
        "install_error": _INSTALL_ERROR,
        "policy": "NEW_INTRADAY_LIVE_REQUIRES_RECENT_SAME_SESSION_FEATURES_AND_RECENT_GROWW_LIVE_TRANSPORT",
        "normal_groww_market_requests_restricted": False,
        "stale_candidate_behavior": "AUDIT_HOLD_NOT_LIVE_NOT_CLOSED_NOT_LEARNING_EVIDENCE",
        "intraday_feature_max_age_seconds": MAX_FEATURE_AGE_SECONDS,
        "live_transport_max_age_seconds": LIVE_TRANSPORT_MAX_AGE_SECONDS,
        "market_hours_now": _market_hours(),
        "live_transport": transport,
        "holds": counts,
        "wrapped_insert_modules": list(_WRAPPED_MODULES),
        "shadow_policy": "NO_NEW_SHADOW_EVIDENCE_WHILE_LIVE_TRANSPORT_IS_NOT_RECENT",
        "last_sweep": dict(_LAST_SWEEP),
    }


def rollback_quarantine() -> Dict[str, Any]:
    out = {"restored": 0, "at": _now().isoformat(timespec="seconds")}
    try:
        from .db import db
        with db() as con:
            _ensure_ledger(con)
            rows = con.execute(
                "SELECT recommendation_id,previous_state FROM freshness_holds WHERE patch_version=? AND source='EXISTING_RECOMMENDATION_QUARANTINE' AND recommendation_id IS NOT NULL",
                (PATCH_VERSION,),
            ).fetchall()
            for rec_id, prev in rows:
                cur = con.execute("UPDATE recommendations SET state=? WHERE recommendation_id=? AND state='STALE_DATA'", (prev or "LIVE", rec_id))
                out["restored"] += max(0, int(cur.rowcount or 0))
    except Exception as exc:
        out["error"] = "%s: %s" % (exc.__class__.__name__, exc)
    return out
