from __future__ import annotations

"""Ledger analytics for PS Scanner.

The recommendation ledger is the source of truth. Active pages query only their current
period; this module is the explicit route for historical evidence, learning diagnostics
and performance statistics. VOID/data-integrity rows are counted but never mixed into
trading P/L metrics.
"""

import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .constants import IST
from .db import db, now_iso

VALID_TRADING_RESULTS = {"WIN", "LOSS", "MISS"}
NON_TRADING_RESULTS = {"VOID"}


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


def _strategy_family_map() -> Dict[str, str]:
    try:
        with db() as con:
            return {str(r[0]): str(r[1] or "UNKNOWN") for r in con.execute("SELECT strategy_id,family FROM strategies").fetchall()}
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


def _group_stats(key: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    wins = losses = misses = voids = other = 0
    returns: List[float] = []
    rvals: List[float] = []
    chronological: List[Tuple[datetime, float]] = []
    for r in rows:
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


def performance(book: Optional[str] = None, group_by: str = "book", limit: int = 10000) -> Dict[str, Any]:
    limit = max(100, min(int(limit or 10000), 50000))
    where = ["state='CLOSED'"]
    args: List[Any] = []
    if book:
        where.append("book=?")
        args.append(str(book).upper())
    sql = (
        "SELECT * FROM recommendations WHERE " + " AND ".join(where) +
        " ORDER BY COALESCE(closed_at,updated_at,created_at) ASC LIMIT ?"
    )
    args.append(limit)
    with db() as con:
        rows = [decode_recommendation(dict(r)) for r in con.execute(sql, tuple(args)).fetchall()]
    family_map = _strategy_family_map() if str(group_by).lower() == "family" else {}
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for key in _group_keys(row, group_by, family_map):
            grouped[key].append(row)
    groups = [_group_stats(key, values) for key, values in grouped.items()]
    groups.sort(key=lambda x: (x.get("trading_count") or 0, x.get("group") or ""), reverse=True)
    total = _group_stats("ALL", rows)
    return {
        "generated_at": now_iso(),
        "book": str(book).upper() if book else None,
        "group_by": str(group_by).lower(),
        "rows_scanned": len(rows),
        "total": total,
        "groups": groups,
        "outcome_policy": {
            "trading_results": sorted(VALID_TRADING_RESULTS),
            "voids": "counted separately and excluded from P/L, expectancy, profit factor and win-rate denominator",
            "confidence": "Wilson 95% interval on WIN / (WIN+LOSS+MISS)",
            "max_drawdown": "cumulative directional-return percentage points in close-time order; descriptive, not portfolio NAV",
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
