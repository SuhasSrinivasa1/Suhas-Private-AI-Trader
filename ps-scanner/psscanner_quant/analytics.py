from __future__ import annotations

"""Ledger analytics for PS Scanner.

The recommendation ledger is the source of truth. Active pages query only their current
period; this module is the explicit route for historical evidence, learning diagnostics
and performance statistics. VOID/data-integrity rows are counted but never mixed into
trading P/L metrics.
"""

import json
import math
import sqlite3
import statistics
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .constants import IST
from .db import db, now_iso
from .config import load_settings

VALID_TRADING_RESULTS = {"WIN", "LOSS", "MISS"}
NON_TRADING_RESULTS = {"VOID"}

PERFORMANCE_API_QUERY_BUDGET_SECONDS = 2.5
PERFORMANCE_API_DB_TIMEOUT_SECONDS = 0.5
_PERFORMANCE_BASE_COLUMNS = (
    "book", "period_key", "symbol", "side", "regime", "horizon", "result", "close_reason",
    "entry_price", "current_price", "stop_price", "created_at", "updated_at", "closed_at",
)


def _performance_projection(group_by: str) -> List[str]:
    """Select only fields needed for the requested aggregation.

    Large audit/evidence JSON columns are deliberately excluded from passive performance
    reads unless a grouping actually needs the relevant strategy/behavior context.
    """
    g = str(group_by or "book").lower()
    cols = list(_PERFORMANCE_BASE_COLUMNS)
    if g in {"strategy", "family"}:
        cols.append("strategy_ids_json")
    if g == "behavior_cluster":
        cols.extend(("feature_snapshot_json", "rationale_json"))
    return cols


def _outcome_policy() -> Dict[str, Any]:
    return {
        "trading_results": sorted(VALID_TRADING_RESULTS),
        "voids": "counted separately and excluded from P/L, expectancy, profit factor and win-rate denominator",
        "confidence": "Wilson 95% interval on WIN / (WIN+LOSS+MISS)",
        "max_drawdown": "cumulative directional-return percentage points in close-time order; descriptive, not portfolio NAV",
    }


def _degraded_performance(book: Optional[str], group_by: str, limit: int, started: float,
                          budget_seconds: Optional[float], db_timeout_seconds: float,
                          reason: str, rows_loaded: int = 0) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "book": str(book).upper() if book else None,
        "group_by": str(group_by).lower(),
        "status": "DEGRADED_BOUNDED",
        "complete": False,
        "rows_scanned": 0,
        "rows_loaded_before_abort": int(rows_loaded),
        "requested_limit": int(limit),
        "total": _group_stats("ALL", []),
        "groups": [],
        "degraded_reason": str(reason)[:180],
        "outcome_policy": _outcome_policy(),
        "performance_contract": {
            "passive_bounded": True,
            "network_calls": False,
            "db_connections": 1,
            "db_timeout_seconds": float(db_timeout_seconds),
            "query_budget_seconds": float(budget_seconds or 0),
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 1),
            "narrow_projection": True,
            "partial_rows_published": False,
            "deep_learning_uses_passive_budget": False,
        },
    }


def _decode_json(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return default


def decode_recommendation(row: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(row)
    d["strategy_ids"] = _decode_json(d.pop("strategy_ids_json", None), [])
    d["rationale"] = _decode_json(d.pop("rationale_json", None), {})
    d["feature_snapshot"] = _decode_json(d.pop("feature_snapshot_json", None), {})
    d["audit_envelope"] = _decode_json(d.pop("audit_envelope_json", None), {})
    return d


def history_rows(book: Optional[str] = None, period_key: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 200), 2000))
    where = ["state='CLOSED'"]
    args: List[Any] = []
    if book:
        where.append("book=?")
        args.append(str(book).upper())
    if period_key:
        where.append("period_key=?")
        args.append(str(period_key))
    sql = (
        "SELECT * FROM recommendations WHERE " + " AND ".join(where) +
        " ORDER BY COALESCE(closed_at,updated_at,created_at) DESC LIMIT ?"
    )
    args.append(limit)
    with db() as con:
        rows = [dict(r) for r in con.execute(sql, tuple(args)).fetchall()]
    return [decode_recommendation(r) for r in rows]


def _directional_return_pct(r: Dict[str, Any]) -> Optional[float]:
    try:
        entry = float(r.get("entry_price") or 0)
        px = float(r.get("current_price") or 0)
        if entry <= 0 or px <= 0:
            return None
        sign = 1.0 if str(r.get("side") or "").upper() == "LONG" else -1.0
        return (px / entry - 1.0) * 100.0 * sign
    except Exception:
        return None


def _r_multiple(r: Dict[str, Any], ret_pct: Optional[float]) -> Optional[float]:
    if ret_pct is None:
        return None
    try:
        entry = float(r.get("entry_price") or 0)
        stop = float(r.get("stop_price") or 0)
        if entry <= 0 or stop <= 0:
            return None
        risk_pct = abs(entry - stop) / entry * 100.0
        if risk_pct <= 1e-9:
            return None
        return ret_pct / risk_pct
    except Exception:
        return None


def wilson_interval(wins: int, n: int, z: float = 1.959963984540054) -> Tuple[Optional[float], Optional[float]]:
    """Return a Wilson score interval as fractions, not percentages."""
    n = int(n)
    wins = int(wins)
    if n <= 0:
        return None, None
    p = wins / n
    z2 = z * z
    den = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / den
    half = z * math.sqrt((p * (1.0 - p) / n) + z2 / (4.0 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def _max_drawdown(values: Iterable[float]) -> float:
    equity = peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return drawdown


def _closed_dt(row: Dict[str, Any]) -> Optional[datetime]:
    for key in ("closed_at", "updated_at", "created_at"):
        raw = row.get(key)
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST)
            return dt.astimezone(IST)
        except Exception:
            continue
    return None


def _opened_dt(row: Dict[str, Any]) -> Optional[datetime]:
    raw=row.get("created_at")
    if not raw:return None
    try:
        dt=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
        if dt.tzinfo is None:dt=dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except Exception:return None


def _time_bucket(row: Dict[str, Any]) -> str:
    dt=_opened_dt(row)
    if not dt:return "UNKNOWN"
    m=dt.hour*60+dt.minute
    if 9*60+15<=m<10*60:return "OPENING_0915_1000"
    if 10*60<=m<14*60:return "MIDDAY_1000_1400"
    if 14*60<=m<=15*60+30:return "LATE_1400_1530"
    return "OUTSIDE_REGULAR_SESSION"


def _behavior_cluster(row: Dict[str, Any]) -> str:
    f=row.get("feature_snapshot") or {};r=row.get("rationale") or {}
    try:atr=float(f.get("atr_pct") or 0)
    except Exception:atr=0.0
    vol="VOL_UNKNOWN" if atr<=0 else ("VOL_LOW" if atr<0.8 else ("VOL_MEDIUM" if atr<1.8 else "VOL_HIGH"))
    sector=((r.get("sector_context") or {}).get("industry") if isinstance(r.get("sector_context"),dict) else None) or "SECTOR_UNKNOWN"
    regime=str(row.get("regime") or "REGIME_UNKNOWN")
    return f"{regime}|{vol}|{sector}"


def _strategy_family_map(con=None) -> Dict[str, str]:
    try:
        if con is not None:
            return {str(r[0]): str(r[1] or "UNKNOWN") for r in con.execute("SELECT strategy_id,family FROM strategies").fetchall()}
        with db() as own:
            return {str(r[0]): str(r[1] or "UNKNOWN") for r in own.execute("SELECT strategy_id,family FROM strategies").fetchall()}
    except Exception:
        return {}


def _group_keys(row: Dict[str, Any], group_by: str, family_map: Dict[str, str]) -> List[str]:
    g = str(group_by or "book").lower()
    if g == "strategy":
        ids = row.get("strategy_ids") or []
        return [str(x) for x in ids] or ["UNATTRIBUTED"]
    if g == "family":
        ids = row.get("strategy_ids") or []
        vals = []
        for sid in ids:
            fam = family_map.get(str(sid), "UNKNOWN")
            if fam not in vals:
                vals.append(fam)
        return vals or ["UNATTRIBUTED"]
    if g in {"book", "symbol", "side", "regime", "horizon", "period_key", "result", "close_reason"}:
        return [str(row.get(g) or "UNKNOWN")]
    if g=="time_bucket":
        return [_time_bucket(row)]
    if g=="behavior_cluster":
        return [_behavior_cluster(row)]
    dt = _closed_dt(row)
    if g == "day":
        return [dt.date().isoformat() if dt else "UNKNOWN"]
    if g == "week":
        if not dt:
            return ["UNKNOWN"]
        iso = dt.isocalendar()
        return [f"{iso.year}-W{iso.week:02d}"]
    if g == "month":
        return [dt.strftime("%Y-%m") if dt else "UNKNOWN"]
    return [str(row.get("book") or "UNKNOWN")]


def _group_stats(key: str, rows: List[Dict[str, Any]], deadline: Optional[float] = None) -> Dict[str, Any]:
    wins = losses = misses = voids = other = 0
    returns: List[float] = []
    rvals: List[float] = []
    chronological: List[Tuple[datetime, float]] = []
    for idx, r in enumerate(rows):
        if deadline is not None and idx % 128 == 0 and time.monotonic() > deadline:
            raise TimeoutError("performance statistics budget exceeded")
        result = str(r.get("result") or "").upper()
        if result == "VOID":
            voids += 1
            continue
        if result == "WIN":
            wins += 1
        elif result == "LOSS":
            losses += 1
        elif result == "MISS":
            misses += 1
        else:
            other += 1
            continue
        ret = _directional_return_pct(r)
        if ret is not None and math.isfinite(ret):
            returns.append(ret)
            dt = _closed_dt(r)
            if dt:
                chronological.append((dt, ret))
            rv = _r_multiple(r, ret)
            if rv is not None and math.isfinite(rv):
                rvals.append(rv)
    trading_n = wins + losses + misses
    ci_lo, ci_hi = wilson_interval(wins, trading_n)
    pos = sum(v for v in returns if v > 0)
    neg = abs(sum(v for v in returns if v < 0))
    # Undefined when no negative-return denominator exists; never manufacture a
    # large sentinel value that can masquerade as statistical evidence.
    profit_factor = (pos / neg) if neg > 1e-12 else None
    avg_win = statistics.fmean([v for v in returns if v > 0]) if any(v > 0 for v in returns) else None
    avg_loss = statistics.fmean([v for v in returns if v < 0]) if any(v < 0 for v in returns) else None
    chronological.sort(key=lambda x: x[0])
    ordered_returns = [x[1] for x in chronological]
    return {
        "group": key,
        "count": len(rows),
        "trading_count": trading_n,
        "wins": wins,
        "losses": losses,
        "misses": misses,
        "voids": voids,
        "other_closed": other,
        "win_rate": round(wins / trading_n, 4) if trading_n else None,
        "loss_rate": round(losses / trading_n, 4) if trading_n else None,
        "miss_rate": round(misses / trading_n, 4) if trading_n else None,
        "win_rate_wilson_95": {
            "low": round(ci_lo, 4) if ci_lo is not None else None,
            "high": round(ci_hi, 4) if ci_hi is not None else None,
        },
        "average_return_pct": round(statistics.fmean(returns), 4) if returns else None,
        "median_return_pct": round(statistics.median(returns), 4) if returns else None,
        "expectancy_pct": round(statistics.fmean(returns), 4) if returns else None,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "average_win_pct": round(avg_win, 4) if avg_win is not None else None,
        "average_loss_pct": round(avg_loss, 4) if avg_loss is not None else None,
        "average_r": round(statistics.fmean(rvals), 4) if rvals else None,
        "max_drawdown_pct_points": round(_max_drawdown(ordered_returns), 4) if ordered_returns else None,
        "sample_size": trading_n,
        "win_rate_wilson_width": round(ci_hi-ci_lo, 4) if ci_lo is not None and ci_hi is not None else None,
    }


def performance(book: Optional[str] = None, group_by: str = "book", limit: int = 10000,
                budget_seconds: Optional[float] = None, db_timeout_seconds: float = 10.0) -> Dict[str, Any]:
    """Aggregate immutable CLOSED recommendation evidence.

    Internal learning calls remain complete/unbounded by default. Passive API callers can
    pass a wall-clock budget; if SQLite or CPU work cannot finish inside it, the function
    returns explicit degraded telemetry and never publishes partial statistics.
    """
    started = time.monotonic()
    limit = max(100, min(int(limit or 10000), 50000))
    group_by = str(group_by or "book").lower()
    bounded = budget_seconds is not None
    budget = max(0.05, float(budget_seconds)) if bounded else None
    deadline = started + budget if budget is not None else None
    where = ["state='CLOSED'"]
    args: List[Any] = []
    if book:
        where.append("book=?")
        args.append(str(book).upper())
    columns = _performance_projection(group_by)
    sql = (
        "SELECT " + ",".join(columns) + " FROM recommendations WHERE " + " AND ".join(where) +
        " ORDER BY COALESCE(closed_at,updated_at,created_at) ASC LIMIT ?"
    )
    args.append(limit)
    rows: List[Dict[str, Any]] = []
    family_map: Dict[str, str] = {}
    try:
        with db(timeout_seconds=db_timeout_seconds) as con:
            if deadline is not None:
                con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
            cursor = con.execute(sql, tuple(args))
            for raw in cursor:
                if deadline is not None and time.monotonic() > deadline:
                    raise TimeoutError("performance CPU/decode budget exceeded")
                rows.append(decode_recommendation(dict(raw)))
            if group_by == "family":
                family_map = _strategy_family_map(con)
            if deadline is not None:
                con.set_progress_handler(None, 0)
    except (sqlite3.OperationalError, TimeoutError) as exc:
        if not bounded:
            raise
        return _degraded_performance(book, group_by, limit, started, budget, db_timeout_seconds,
                                     f"{type(exc).__name__}: {exc}", len(rows))

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for idx, row in enumerate(rows):
        if deadline is not None and idx % 64 == 0 and time.monotonic() > deadline:
            return _degraded_performance(book, group_by, limit, started, budget, db_timeout_seconds,
                                         "performance grouping budget exceeded", len(rows))
        for key in _group_keys(row, group_by, family_map):
            grouped[key].append(row)
    groups: List[Dict[str, Any]] = []
    try:
        for idx, (key, values) in enumerate(grouped.items()):
            if deadline is not None and idx % 32 == 0 and time.monotonic() > deadline:
                raise TimeoutError("performance statistics budget exceeded")
            groups.append(_group_stats(key, values, deadline))
    except TimeoutError as exc:
        if not bounded:
            raise
        return _degraded_performance(book, group_by, limit, started, budget, db_timeout_seconds,
                                     str(exc), len(rows))
    if group_by in {"time_bucket","behavior_cluster"}:
        settings=load_settings();min_n=int(settings.get("cohort_min_samples_for_live_use",50) or 50);max_width=float(settings.get("cohort_max_wilson_width_for_live_use",.30) or .30)
        for g in groups:
            width=g.get("win_rate_wilson_width");expectancy=g.get("expectancy_pct");pf=g.get("profit_factor")
            eligible=bool((g.get("trading_count") or 0)>=min_n and width is not None and width<=max_width and expectancy is not None and expectancy>0 and pf is not None and pf>1.0)
            g["live_use_eligible"]=eligible
            g["live_use_gate"]={"minimum_samples":min_n,"maximum_wilson_width":max_width,"positive_expectancy_required":True,"profit_factor_gt_1_required":True,"automatic_activation":False}
    groups.sort(key=lambda x: (x.get("trading_count") or 0, x.get("group") or ""), reverse=True)
    if deadline is not None and time.monotonic() > deadline:
        return _degraded_performance(book, group_by, limit, started, budget, db_timeout_seconds,
                                     "performance finalization budget exceeded", len(rows))
    try:
        total = _group_stats("ALL", rows, deadline)
    except TimeoutError as exc:
        if not bounded:
            raise
        return _degraded_performance(book, group_by, limit, started, budget, db_timeout_seconds,
                                     str(exc), len(rows))
    return {
        "generated_at": now_iso(),
        "book": str(book).upper() if book else None,
        "group_by": group_by,
        "status": "COMPLETE",
        "complete": True,
        "rows_scanned": len(rows),
        "total": total,
        "groups": groups,
        "outcome_policy": _outcome_policy(),
        "performance_contract": {
            "passive_bounded": bounded,
            "network_calls": False,
            "db_connections": 1,
            "db_timeout_seconds": float(db_timeout_seconds),
            "query_budget_seconds": budget,
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 1),
            "narrow_projection": True,
            "selected_columns": columns,
            "partial_rows_published": False,
            "deep_learning_uses_passive_budget": False,
        },
    }


def learning_evidence_snapshot(limit: int = 10000) -> Dict[str, Any]:
    """Summarize recommendation-ledger evidence available to daily learning/decay."""
    p = performance(group_by="book", limit=limit)
    return {
        "at": p["generated_at"],
        "books": {
            str(g["group"]): {
                "trading_count": g["trading_count"],
                "wins": g["wins"],
                "losses": g["losses"],
                "misses": g["misses"],
                "voids": g["voids"],
                "average_r": g["average_r"],
                "win_rate_wilson_95": g["win_rate_wilson_95"],
            }
            for g in p["groups"]
        },
        "policy": "VALID_CLOSED_RECOMMENDATIONS_ARE_LEARNING_EVIDENCE; VOID/DATA_ERROR_ROWS_ARE_AUDIT_ONLY",
    }
