from __future__ import annotations

import json
import math
import threading
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

from .broker import broker
from .config import load_settings
from .constants import (IST, VERSION, MARKET_OPEN, MARKET_CLOSE, INTRADAY_ENTRY_CUTOFF, SHORT_HARD_EXIT,
    HORIZON_RESEARCH_START, HORIZON_FREEZE_START, HORIZON_FREEZE_END, HORIZON_RECOVERY_END,
    HORIZON_PUBLISH_START, HORIZON_PUBLISH_END)
from .data import (bootstrap_history, warm_intraday_history, warm_daily_history, cached_history_coverage, history, liquidity_rank, live_prices, refresh_live_price_cache, refresh_instruments, refresh_universe, universe, full_nse_symbols, full_breadth_discovery_snapshot, universe_status, _history_path, _load_raw_candles)
from .db import db, get_state, health, now_iso, set_state
from .features import latest_features
from .candle_patterns import detect_patterns
from .global_context import snapshot as global_snapshot
from .news_context import context as news_context
from .portfolio_risk import recommendation_cluster
from .trade_intelligence import evaluate as evaluate_trade_intelligence
from .fundamentals import get as fundamentals_get, quality_score
from .regime import classify
from .strategy_library import active_strategies, score_strategy, seed_library
from .trading_calendar import (period_end_date as exchange_period_end_date, remaining_sessions as exchange_remaining_sessions,
    is_regular_trading_day, next_trading_day, first_trading_day_of_week, first_trading_day_of_month)
from .sector_context import context as sector_context, context_cached as sector_context_cached
from .event_calendar import risk_context as event_risk_context, refresh_symbol_event, seed_official_calendar
from .evidence_fabric import publish as fabric_publish, priority_symbols as fabric_priority_symbols, symbol_context as fabric_symbol_context
from .institutional_intelligence import refresh as institutional_refresh
from .production_integrity import (
    common_audit_context, make_audit_envelope, record_scan_run, seed_release_experiment, maybe_daily_backup,
)


HORIZON_EXECUTABLE_SIDES = {"WEEKLY": ("LONG",), "MONTHLY": ("LONG",), "ETF": ("LONG",)}
FREEZE_CONTRACT_MIN = {"WEEKLY": 5, "MONTHLY": 5, "ETF": 5, "INTERNATIONAL": 5}


def _freeze_contract_min(book: str) -> int:
    return int(FREEZE_CONTRACT_MIN.get(str(book).upper(), 0))


def _freeze_contract_count(book: str, pk: Optional[str] = None) -> int:
    b=str(book).upper(); pk=pk or period_key(b)
    with db() as con:
        if b in HORIZON_EXECUTABLE_SIDES or b == "INTERNATIONAL":
            # Contract books are LONG-only executable slates. Legacy/VOID rows must not
            # make an empty period look frozen.
            return int(con.execute(
                "SELECT COUNT(*) FROM recommendations WHERE book=? AND period_key=? "
                "AND side='LONG' AND COALESCE(result,'')<>'VOID'",
                (b,pk),
            ).fetchone()[0])
        return int(con.execute(
            "SELECT COUNT(*) FROM recommendations WHERE book=? AND period_key=? "
            "AND COALESCE(result,'')<>'VOID'",
            (b,pk),
        ).fetchone()[0])


def period_key(book: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(IST)
    if book in ("WEEKLY", "ETF"):
        monday = now.date() - timedelta(days=now.weekday())
        return monday.isoformat()
    if book == "MONTHLY":
        return now.strftime("%Y-%m")
    if book == "INTERNATIONAL":
        # v6.3.1: the U.S. book is frozen for the trading week, keyed by New York Monday.
        local_date = now.astimezone(ZoneInfo("America/New_York")).date()
        monday = local_date - timedelta(days=local_date.weekday())
        return monday.isoformat()
    if book == "CIRCUIT_NEXTDAY":
        t=now.time().replace(tzinfo=None)
        return (now.date() if is_regular_trading_day(now.date()) and t < SHORT_HARD_EXIT else next_trading_day(now.date())).isoformat()
    if book in ("GLOBAL_INDIA_LONG", "GLOBAL_INDIA_SHORT"):
        t=now.time().replace(tzinfo=None)
        return (now.date() if is_regular_trading_day(now.date()) and t < SHORT_HARD_EXIT else next_trading_day(now.date())).isoformat()
    return now.date().isoformat()



def _frozen_period_bounds(book: str, pk: str):
    """Return inclusive calendar bounds for frozen Weekly/Monthly identity periods."""
    b=str(book).upper();raw=str(pk)
    if b=="WEEKLY":
        start=datetime.fromisoformat(raw).date();return start,start+timedelta(days=6)
    if b=="MONTHLY":
        start=datetime.strptime(raw+"-01","%Y-%m-%d").date()
        nxt=start.replace(year=start.year+1,month=1) if start.month==12 else start.replace(month=start.month+1)
        return start,nxt-timedelta(days=1)
    raise ValueError(f"unsupported frozen identity book: {book}")


def _weekly_monthly_conflicts(exclude_book: Optional[str] = None, period_key_override: Optional[str] = None) -> set[str]:
    """Block opposite-book identities for every overlapping frozen calendar period.

    Early WIN/LOSS/MISS closure does not release a frozen identity. VOID is the only
    result that removes an invalid publication from this exclusivity invariant.
    """
    b=(exclude_book or "").upper()
    if b not in ("WEEKLY","MONTHLY"):return set()
    other="MONTHLY" if b=="WEEKLY" else "WEEKLY";pk=str(period_key_override or period_key(b))
    target_start,target_end=_frozen_period_bounds(b,pk)
    with db() as con:
        rs=con.execute("SELECT period_key,UPPER(symbol) symbol FROM recommendations WHERE book=? AND COALESCE(result,'')<>'VOID'",(other,)).fetchall()
    blocked=set()
    for row in rs:
        try:other_start,other_end=_frozen_period_bounds(other,str(row["period_key"]))
        except Exception:continue
        if target_start<=other_end and other_start<=target_end:blocked.add(str(row["symbol"]).upper())
    return blocked


def _repair_weekly_monthly_collisions(now: Optional[datetime] = None) -> List[Dict[str, str]]:
    """Repair current/future frozen-period Weekly/Monthly identity collisions."""
    now=now or datetime.now(IST);today=now.date()
    current={"WEEKLY":period_key("WEEKLY",now),"MONTHLY":period_key("MONTHLY",now)}
    with db() as con:
        rows=[dict(r) for r in con.execute(
            "SELECT recommendation_id,book,period_key,symbol,side,state,result,created_at FROM recommendations "
            "WHERE book IN ('WEEKLY','MONTHLY') AND COALESCE(result,'')<>'VOID' ORDER BY created_at"
        ).fetchall()]
    by_symbol={}
    for r in rows:
        try:start,end=_frozen_period_bounds(str(r["book"]),str(r["period_key"]))
        except Exception:continue
        if end<today:continue
        r["_start"]=start;r["_end"]=end;by_symbol.setdefault(str(r["symbol"]).upper(),[]).append(r)
    repairs=[];ts=now_iso()
    for symbol,items in by_symbol.items():
        n=len(items)
        if n<2:continue
        adjacency={i:set() for i in range(n)}
        for i in range(n):
            for j in range(i+1,n):
                if str(items[i]["book"]).upper()==str(items[j]["book"]).upper():continue
                if items[i]["_start"]<=items[j]["_end"] and items[j]["_start"]<=items[i]["_end"]:
                    adjacency[i].add(j);adjacency[j].add(i)
        seen=set()
        for root in range(n):
            if root in seen or not adjacency[root]:continue
            stack=[root];component=[]
            while stack:
                i=stack.pop()
                if i in seen:continue
                seen.add(i);component.append(i);stack.extend(adjacency[i]-seen)
            def priority(i):
                r=items[i];book=str(r["book"]).upper();pk=str(r["period_key"]);cur=str(current[book])
                relation=0 if pk==cur else (1 if pk>cur else 2)
                return (relation,str(r.get("created_at") or ""),book,str(r.get("recommendation_id") or ""))
            winner=items[min(component,key=priority)];winning_book=str(winner["book"]).upper()
            for i in component:
                loser=items[i]
                if str(loser["book"]).upper()==winning_book:continue
                repairs.append({"symbol":symbol,"kept_book":winning_book,"voided_book":str(loser["book"]).upper(),"voided_id":str(loser["recommendation_id"])})
    repairs=list({r["voided_id"]:r for r in repairs}.values())
    if repairs:
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                for r in repairs:
                    con.execute(
                        "UPDATE recommendations SET state='CLOSED',result='VOID',close_reason='HORIZON_IDENTITY_COLLISION_REPAIR_V661',"
                        "closed_at=COALESCE(closed_at,?),updated_at=? WHERE recommendation_id=? AND COALESCE(result,'')<>'VOID'",
                        (ts,ts,r["voided_id"]),
                    )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK");raise
        health("horizon_collision","WARN","Weekly/Monthly frozen-period identity collisions repaired",
               {"count":len(repairs),"repairs":repairs[:12],"policy":"V661_OVERLAPPING_PERIOD_IDENTITY_ISOLATION"})
    return repairs

def _pct_target(book: str, f: Dict[str, Any]) -> float:
    settings = load_settings()
    if book == "WEEKLY":
        return float(settings.get("weekly_target_pct", 10.0) or 10.0)
    if book == "MONTHLY":
        return float(settings.get("monthly_target_pct", 50.0) or 50.0)
    if book == "ETF":
        return float(settings.get("etf_target_pct", 5.0) or 5.0)
    if book == "CIRCUIT":
        return 4.0
    return max(0.75, min(4.0, float(f.get("atr_pct") or 1.0) * 1.5))


def _period_end_date(book: str, now: datetime):
    return exchange_period_end_date(book, now)


def _remaining_sessions(book: str, now: Optional[datetime] = None) -> float:
    return exchange_remaining_sessions(book, now or datetime.now(IST))


def _required_session_move(target_pct: float, side: str, sessions: float) -> float:
    sessions = max(0.10, float(sessions))
    if side == "LONG":
        return ((1.0 + target_pct / 100.0) ** (1.0 / sessions) - 1.0) * 100.0
    terminal = max(0.01, 1.0 - target_pct / 100.0)
    return (1.0 - terminal ** (1.0 / sessions)) * 100.0


def _target_feasibility(book: str, side: str, f: Dict[str, Any], score: float, confidence: float,
                        data_confidence: float, fundamental_quality: Optional[float],
                        now: Optional[datetime] = None) -> Dict[str, Any]:
    """Quantitative admission gate for official horizon books.

    This is deliberately conservative. It does not claim a target will occur; it prevents
    a recommendation from being published when the observed volatility/momentum capacity
    is insufficient for the stated period objective.
    """
    now = now or datetime.now(IST)
    target = _pct_target(book, f)
    sessions = _remaining_sessions(book, now)
    sign = 1.0 if side == "LONG" else -1.0
    atrp = max(0.05, float(f.get("atr_pct") or 0.0))
    ret5 = sign * float(f.get("ret5") or 0.0)
    ret20 = sign * float(f.get("ret20") or 0.0)
    ret60 = sign * float(f.get("ret60") or 0.0)
    vr = max(0.0, float(f.get("volume_ratio") or 0.0))
    adxv = max(0.0, float(f.get("adx14") or 0.0))

    # Diffusive volatility capacity plus directional momentum capacity. The multiplier is
    # intentionally not a probability forecast; it is a high-bar capacity screen.
    vol_capacity = atrp * math.sqrt(max(0.10, sessions)) * (1.80 if book in ("WEEKLY","ETF") else 2.05)
    daily_momentum = max(0.0, ret5 / 5.0, ret20 / 20.0, ret60 / 60.0)
    momentum_capacity = daily_momentum * sessions * (1.55 if book in ("WEEKLY","ETF") else 1.85)
    participation = min(1.25, max(0.75, 0.85 + min(2.5, vr) * 0.12 + min(45.0, adxv) / 450.0))
    estimated = min(95.0, max(vol_capacity, momentum_capacity) * participation)
    required = _required_session_move(target, side, sessions) if sessions > 0 else 999.0
    observed_capacity_per_session = max(atrp * 1.35, daily_momentum * 1.75)
    feasibility_ratio = estimated / target if target > 0 else 0.0

    settings = load_settings()
    min_score = float(76.0 if book == "ETF" else (settings.get("weekly_min_score", 80.0) if book == "WEEKLY" else settings.get("monthly_min_score", 84.0)))
    min_conf = float(settings.get("horizon_min_confidence", 0.50))
    min_data = float(settings.get("horizon_min_data_confidence", 0.72))
    fundamentals_present = fundamental_quality is not None and float(fundamental_quality) > 0
    if book == "ETF":
        fundamental_ok = True
    elif book == "WEEKLY":
        # Missing weekly fundamentals remain UNKNOWN rather than killing the whole Monday slate.
        # Compensate with stricter quantitative evidence instead of silently assuming quality.
        fundamental_ok = fundamentals_present or (score >= min_score + 4 and data_confidence >= min_data + 0.04)
    else:
        # Monthly remains fundamentals-sensitive because the horizon is longer.
        fundamental_ok = fundamentals_present

    feasible = bool(
        sessions > 0.05
        and score >= min_score
        and confidence >= min_conf
        and data_confidence >= min_data
        and fundamental_ok
        and estimated >= target
        and required <= max(0.25, observed_capacity_per_session)
    )
    reasons = []
    if sessions <= 0.05: reasons.append("NO_REMAINING_PERIOD_SESSION")
    if score < min_score: reasons.append("ENSEMBLE_SCORE_BELOW_TARGET_GATE")
    if confidence < min_conf: reasons.append("STRATEGY_CONSENSUS_TOO_THIN")
    if data_confidence < min_data: reasons.append("DATA_CONFIDENCE_TOO_LOW")
    if not fundamental_ok: reasons.append("FUNDAMENTALS_NOT_READY")
    if estimated < target: reasons.append("MODELLED_MOVE_CAPACITY_BELOW_TARGET")
    if required > max(0.25, observed_capacity_per_session): reasons.append("REQUIRED_PACE_EXCEEDS_OBSERVED_CAPACITY")

    return {
        "target_pct": round(target, 2),
        "remaining_sessions": round(sessions, 3),
        "required_session_move_pct": round(required, 3),
        "estimated_directional_move_pct": round(estimated, 2),
        "feasibility_ratio": round(feasibility_ratio, 3),
        "target_qualified": feasible,
        "fundamentals_present": fundamentals_present,
        "rejection_reasons": reasons,
        "model": "ATR_SQRT_TIME_PLUS_DIRECTIONAL_MOMENTUM_CAPACITY_V603",
        "disclaimer": "Target qualification is a statistical admission gate, not a guarantee of return.",
    }


def _risk_geometry(book: str, f: Dict[str, Any], target_pct: Optional[float]=None, stop_pct: Optional[float]=None) -> Dict[str,float]:
    """Return internally consistent target/stop percentages.

    v6.2.3 used a 0.75% target floor and a 0.70% stop floor. For ordinary low-ATR
    intraday names that mechanically produced R:R ~= 1.07, so the later hard R:R gate
    rejected almost every otherwise-eligible candidate. The geometry now enforces the
    same >=1.5 reward/risk contract that Trade Intelligence evaluates.
    """
    atr=max(.05,float(f.get("atr_pct") or 1.0))
    t=float(target_pct) if target_pct is not None else float(_pct_target(book,f))
    if book in ("INTRADAY","INTERNATIONAL"):
        st=float(stop_pct) if stop_pct is not None else max(.30,min(2.67,atr))
        t=max(.60,min(4.0,t))
        if t < st*1.5:t=min(4.0,st*1.5)
        # Leave a tiny numerical margin so rounded percentages still satisfy the hard >=1.5 gate.
        if st > t/1.5005:st=t/1.5005
        return {"target_pct":round(t,6),"stop_pct":round(max(.20,st),6)}
    st=float(stop_pct) if stop_pct is not None else max(.7,min(4.0,atr))
    return {"target_pct":round(t,6),"stop_pct":round(st,6)}


def _intraday_short_deadline_feasibility(f: Dict[str, Any], target_pct: float, now: Optional[datetime]=None) -> Dict[str, Any]:
    now=now or datetime.now(IST)
    t=now.time().replace(tzinfo=None);remaining=max(0,(SHORT_HARD_EXIT.hour*60+SHORT_HARD_EXIT.minute)-(t.hour*60+t.minute))
    atr=max(.05,float(f.get("atr_pct") or .25));bars=max(.25,remaining/5.0)
    momentum=max(0.0,-float(f.get("ret5") or 0)/5.0,-float(f.get("ret20") or 0)/20.0)
    capacity=atr*math.sqrt(bars)*.78+momentum*remaining/10.0
    feasible=bool(remaining>=15 and capacity>=float(target_pct)*1.05)
    return {"deadline":"15:00 IST","remaining_minutes":remaining,"modeled_capacity_pct":round(capacity,3),"target_pct":round(float(target_pct),3),"feasible":feasible,"reason":None if feasible else ("TOO_LATE_FOR_SHORT_TARGET" if remaining<15 else "MODELED_CAPACITY_BELOW_TARGET_BEFORE_1500"),"target_is_not_guaranteed":True}


def _insert_rec(book, symbol, side, score, confidence, price, f, regime, strategies, rationale, exchange="NSE", target_pct_override=None, stop_pct_override=None, period_key_override=None):
    b=str(book).upper();sym=str(symbol).upper()
    pk=str(period_key_override or period_key(b))
    geom=_risk_geometry(b,f,target_pct_override,stop_pct_override)
    target_pct=geom["target_pct"];stop_pct=geom["stop_pct"]
    sign=1 if side=="LONG" else -1
    target=price*(1+sign*target_pct/100);stop=price*(1-sign*stop_pct/100)
    rid=f"{b}-{pk}-{sym}-{side}-{uuid.uuid4().hex[:8]}";ts=now_iso()
    rationale=dict(rationale or {})
    audit=rationale.get("audit_envelope")
    if not isinstance(audit,dict) or not audit:
        audit=make_audit_envelope(b,pk,sym,side,f,rationale,strategies)
    audit=dict(audit);audit["regime"]=regime
    decision_id=rationale.get("decision_id") or audit.get("decision_id")
    config_hash=audit.get("settings_hash")
    audit_json=json.dumps(audit,default=str,separators=(",",":"))

    # Application-level frozen-period conflict gives a clean diagnostic; the SQLite trigger
    # remains the atomic race-safe authority.
    if b in ("WEEKLY","MONTHLY") and sym in _weekly_monthly_conflicts(b,pk):
        health("horizon_collision","WARN",
               f"{b} publication rejected because {sym} already belongs to an overlapping frozen opposite book",
               {"book":b,"symbol":sym,"period_key":pk,"policy":"V670_FROZEN_PERIOD_IDENTITY_APPLICATION_AND_DB"})
        return None

    sql=("INSERT INTO recommendations(recommendation_id,book,period_key,symbol,exchange,side,state,score,confidence,"
         "entry_price,current_price,target_price,stop_price,target_pct,horizon,regime,strategy_ids_json,rationale_json,"
         "feature_snapshot_json,data_confidence,software_version,config_hash,decision_id,audit_envelope_json,created_at,updated_at) "
         "VALUES(?,?,?,?,?,?,'LIVE',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    args=(rid,b,pk,sym,exchange,side,round(score,2),round(confidence,3),price,price,target,stop,target_pct,b,regime,
          json.dumps(strategies),json.dumps(rationale),json.dumps(f,default=str),rationale.get("data_confidence",0),
          VERSION,config_hash,decision_id,audit_json,ts,ts)
    if b in ("WEEKLY","MONTHLY"):
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute(sql,args);con.execute("COMMIT")
            except Exception as exc:
                con.execute("ROLLBACK")
                if "WEEKLY_MONTHLY_PERIOD_IDENTITY_COLLISION" in str(exc):
                    health("horizon_collision","WARN",str(exc)[:180],
                           {"book":b,"symbol":sym,"period_key":pk,"policy":"V670_DB_ATOMIC_FROZEN_IDENTITY"})
                    return None
                raise
        return rid
    with db() as con:con.execute(sql,args)
    return rid

def _observation_bucket(book: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(IST)
    settings = load_settings()
    minutes = int(settings.get("weekly_observation_bucket_minutes", 30) if book in ("WEEKLY", "ETF") else settings.get("monthly_observation_bucket_minutes", 60))
    minutes = max(5, minutes)
    minute = (now.minute // minutes) * minutes if minutes < 60 else 0
    hour = now.hour if minutes < 60 else (now.hour // max(1, minutes // 60)) * max(1, minutes // 60)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


def _observe(book: str, cands: List[Dict[str, Any]], period_key_override: Optional[str] = None):
    pk = str(period_key_override or period_key(book))
    ts = now_iso()
    bucket = _observation_bucket(book)
    with db() as con:
        for c in cands:
            payload = dict(c)
            payload["_observation_bucket"] = bucket
            old = con.execute(
                "SELECT observations,avg_score,max_score,payload_json FROM candidate_observations WHERE book=? AND period_key=? AND symbol=? AND side=?",
                (book, pk, c["symbol"], c["side"]),
            ).fetchone()
            if old:
                try:
                    old_payload = json.loads(old[3] or "{}")
                except Exception:
                    old_payload = {}
                # Multiple engine loops inside the same evidence bucket are refreshes, not
                # independent observations. This prevents fake persistence from a 5-minute loop.
                if old_payload.get("_observation_bucket") == bucket:
                    con.execute(
                        "UPDATE candidate_observations SET max_score=?,last_seen_at=?,payload_json=? WHERE book=? AND period_key=? AND symbol=? AND side=?",
                        (max(float(old[2]), c["score"]), ts, json.dumps(payload, default=str), book, pk, c["symbol"], c["side"]),
                    )
                    continue
                n = int(old[0]) + 1
                avg = (float(old[1]) * int(old[0]) + c["score"]) / n
                mx = max(float(old[2]), c["score"])
                con.execute(
                    "UPDATE candidate_observations SET observations=?,avg_score=?,max_score=?,last_seen_at=?,payload_json=? WHERE book=? AND period_key=? AND symbol=? AND side=?",
                    (n, avg, mx, ts, json.dumps(payload, default=str), book, pk, c["symbol"], c["side"]),
                )
            else:
                con.execute(
                    "INSERT INTO candidate_observations VALUES(?,?,?,?,1,?,?,?, ?,?)",
                    (book, pk, c["symbol"], c["side"], c["score"], c["score"], ts, ts, json.dumps(payload, default=str)),
                )


def _horizon_freeze_window(book: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Morning publication contract for Indian horizon books.

    Weekly/ETF are expected to freeze on the first actual NSE session of the week.
    Monthly freezes on the first actual NSE session of the month. If a book is still
    missing because the app was offline or an earlier build failed, a later-session
    morning recovery window is allowed; the original target feasibility gate is kept.
    """
    now = now or datetime.now(IST)
    b = str(book).upper()
    t = now.time().replace(tzinfo=None)
    if b not in ("WEEKLY", "MONTHLY", "ETF"):
        return {"open": False, "status": "NOT_HORIZON_BOOK"}
    if not is_regular_trading_day(now.date()):
        return {"open": False, "status": "NSE_CLOSED"}
    if t < HORIZON_FREEZE_START:
        return {"open": False, "status": "PREPARING_MORNING_FREEZE", "freeze_ist": HORIZON_FREEZE_START.strftime("%H:%M")}
    if t > HORIZON_RECOVERY_END:
        return {"open": False, "status": "MORNING_FREEZE_WINDOW_CLOSED", "freeze_ist": HORIZON_FREEZE_START.strftime("%H:%M")}
    first = first_trading_day_of_week(now.date()) if b in ("WEEKLY", "ETF") else first_trading_day_of_month(now.date())
    on_first = now.date() == first
    on_time = t <= HORIZON_FREEZE_END
    return {
        "open": True,
        "status": "ON_TIME_FREEZE" if on_first and on_time else ("FIRST_SESSION_RECOVERY" if on_first else "MISSING_BOOK_RECOVERY"),
        "first_period_session": first.isoformat(),
        "freeze_ist": HORIZON_FREEZE_START.strftime("%H:%M"),
        "normal_window_end_ist": HORIZON_FREEZE_END.strftime("%H:%M"),
        "recovery_window_end_ist": HORIZON_RECOVERY_END.strftime("%H:%M"),
    }


def _publication_window_open(now: Optional[datetime] = None, book: str = "WEEKLY") -> bool:
    return bool(_horizon_freeze_window(book, now).get("open"))


def _horizon_target_context(book: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Choose the period being repaired/prepared without ever shortening its risk gates.

    During the current period we recover the current key.  After the final session closes
    (and through the weekend) the worker switches to the next period so Weekly/ETF and
    Monthly can be frozen *before* the next period opens.
    """
    now = now or datetime.now(IST)
    b = str(book).upper()
    if b not in ("WEEKLY", "MONTHLY", "ETF"):
        return {"period_key": period_key(b, now), "target_now": now, "preperiod": False}
    t = now.time().replace(tzinfo=None)
    end = _period_end_date(b, now)
    preperiod = now.date() > end or (now.date() == end and t >= MARKET_CLOSE)
    if not preperiod:
        return {"period_key": period_key(b, now), "target_now": now, "preperiod": False,
                "period_end": end.isoformat()}
    if b in ("WEEKLY", "ETF"):
        probe = now.date() + timedelta(days=1)
        first = next_trading_day(probe, include_today=True)
        # If the next trading day is still in the same calendar week (e.g. a Thursday
        # holiday edge), advance until a new week begins.
        current_monday = now.date() - timedelta(days=now.weekday())
        while first - timedelta(days=first.weekday()) <= current_monday:
            first = next_trading_day(first)
        monday = first - timedelta(days=first.weekday())
        pk = monday.isoformat()
    else:
        if now.month == 12:
            probe = datetime(now.year + 1, 1, 1).date()
        else:
            probe = datetime(now.year, now.month + 1, 1).date()
        first = first_trading_day_of_month(probe)
        pk = first.strftime("%Y-%m")
    target_now = datetime.combine(first, HORIZON_FREEZE_START).replace(tzinfo=IST)
    return {"period_key": pk, "target_now": target_now, "preperiod": True,
            "first_period_session": first.isoformat(), "source_period_end": end.isoformat(),
            "status": "PREPERIOD_FREEZE_AFTER_PRIOR_CLOSE"}


def _recovery_symbol_batch(book: str, interval: str, pk: str, batch_size: int) -> Dict[str, Any]:
    """Return a rotating deterministic cached-data batch and explicit pass evidence."""
    metas=universe();all_syms=[str(x.get("symbol") or "").upper() for x in metas if x.get("symbol")]
    ranked=liquidity_rank(limit=max(1,len(all_syms)));seen=set();ordered=[]
    for sym in list(ranked)+all_syms:
        sym=str(sym or "").upper()
        if not sym or sym in seen or not _history_path(sym,interval).exists():continue
        seen.add(sym);ordered.append(sym)
    if not ordered:
        return {"symbols":[],"cursor":0,"next_cursor":0,"ready":0,"batch_size":0,"pass_started":0,"pass":0,"completed_pass":False}
    size=max(1,min(int(batch_size),len(ordered)));key=f"recovery_cursor_{str(book).upper()}_{pk}_{interval}"
    state=get_state(key,{}) or {}
    if isinstance(state,dict):cursor=int(state.get("cursor") or 0)%len(ordered);pass_no=int(state.get("pass") or 0)
    else:cursor=int(state or 0)%len(ordered);pass_no=0
    pass_started=pass_no;chosen=ordered[cursor:cursor+size];raw_next=cursor+len(chosen)
    completed_pass=bool(chosen and raw_next>=len(ordered));next_cursor=0 if completed_pass else raw_next
    if completed_pass:pass_no+=1
    set_state(key,{"cursor":next_cursor,"pass":pass_no,"ready":len(ordered),"last_batch":len(chosen),
                   "last_pass_started":pass_started,"completed_pass":completed_pass,"at":now_iso(),
                   "policy":"LIQUIDITY_ORDER_ONLY_ROTATING_FULL_CACHED_BREADTH"})
    return {"symbols":chosen,"cursor":cursor,"next_cursor":next_cursor,"ready":len(ordered),"batch_size":len(chosen),
            "pass_started":pass_started,"pass":pass_no,"completed_pass":completed_pass}


def _merge_intraday_bootstrap_pass(pk: str, batch: Dict[str, Any], detail: Dict[str, Any], published: int = 0) -> Dict[str, Any]:
    """Accumulate zero-live Intraday evidence until one cached-ready pass is actually exhaustive."""
    key=f"intraday_bootstrap_pass_{pk}";pass_started=int(batch.get("pass_started") or 0);previous=get_state(key,{}) or {}
    if int(previous.get("pass_started",-1))!=pass_started:
        previous={"period_key":pk,"pass_started":pass_started,"started_at":now_iso(),"scanned":0,"counters":{},"near_misses":[]}
    funnel=dict(detail.get("funnel") or {});counters=dict(previous.get("counters") or {})
    additive=("history_ready","history_reject","liquidity_reject","freshness_reject","strategy_evidence_reject",
              "strategy_diversity_advisory","score_reject","target_feasibility_reject","risk_reject",
              "trade_intelligence_reject","data_error","raw_eligible","publication_ready")
    for name in additive:counters[name]=int(counters.get(name) or 0)+int(funnel.get(name) or 0)
    counters["published"]=int(counters.get("published") or 0)+int(published or 0)
    scanned=int(previous.get("scanned") or 0)+int(detail.get("processed") or 0);ready=int(batch.get("ready") or 0)
    cursor_completed=bool(batch.get("completed_pass"));exhaustive=bool(cursor_completed and ready>0 and scanned>=ready)
    near=list(previous.get("near_misses") or [])+list(detail.get("near_misses") or [])
    near.sort(key=lambda x:(float(x.get("score") or 0),-abs(float(x.get("distance_to_threshold") or 999999))),reverse=True);near=near[:12]
    if counters["published"]>0:classification="OPPORTUNITY_PUBLISHED"
    elif not exhaustive:classification="SEARCH_INCOMPLETE"
    elif counters.get("history_ready",0)<=0:classification="DATA_NOT_READY"
    elif counters.get("publication_ready",0)<=0:classification="NO_QUALIFIED_OPPORTUNITY_IN_CACHED_READY_UNIVERSE"
    else:classification="QUALIFIED_CANDIDATE_NOT_PUBLISHED"
    out={"period_key":pk,"pass_started":pass_started,"ready_cached":ready,
         "full_universe_total":int(detail.get("full_nse_universe") or funnel.get("universe_total") or 0),
         "scanned":scanned,"coverage_pct":round(min(1.0,scanned/max(1,ready)),4) if ready else 0.0,
         "cursor_completed":cursor_completed,"exhaustive_cached_ready_pass":exhaustive,"classification":classification,
         "counters":counters,"near_misses":near,"updated_at":now_iso(),"started_at":previous.get("started_at") or now_iso()}
    set_state(key,out)
    if exhaustive:set_state(f"intraday_bootstrap_last_complete_{pk}",out)
    return out

def _period_has_valid_frozen_book(book: str, pk: Optional[str] = None) -> bool:
    """Return True only when the period's freeze contract is actually complete.

    For the four five-pick contract books, one accidental/legacy row (or a frozen
    marker with zero rows) must never suppress recovery. Other books keep the legacy
    "any non-VOID row" behavior.
    """
    b=str(book).upper(); pk=pk or period_key(b)
    minimum=_freeze_contract_min(b)
    n=_freeze_contract_count(b,pk)
    return n >= minimum if minimum else bool(n)


def _mark_scan_detail_idle(book: str, status: str, **extra) -> None:
    detail = get_state(f"scan_detail_{book}", {}) or {}
    if not isinstance(detail, dict):
        detail = {}
    previous_stage = detail.get("stage")
    try:
        current_universe=int((universe_status() or {}).get("n") or 0)
    except Exception:
        current_universe=0
    if detail.get("universe") is not None:
        detail["last_scan_universe"] = detail.get("universe")
    detail.update({"book": book, "running": False, "status": status, "at": now_iso(), "current_universe": current_universe})
    if previous_stage and previous_stage not in ("DONE", status):
        detail["previous_stage"] = previous_stage
    detail["stage"] = status
    detail.update(extra)
    set_state(f"scan_detail_{book}", detail)


def reset_transient_scan_states() -> int:
    """Clear persisted running flags from work interrupted by a process restart."""
    touched = 0
    for book in ("INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","CIRCUIT_NEXTDAY","INTERNATIONAL","GLOBAL_INDIA_LONG","GLOBAL_INDIA_SHORT"):
        for prefix in ("scan_status_", "scan_detail_"):
            key = prefix + book
            state = get_state(key, {}) or {}
            if not isinstance(state, dict) or not state.get("running"):
                continue
            prev = state.get("stage") or state.get("status") or "UNKNOWN"
            state["running"] = False
            state["status"] = "INTERRUPTED_BY_PROCESS_RESTART"
            state["previous_stage"] = prev
            state["interrupted_at"] = now_iso()
            if prefix == "scan_detail_":
                state["stage"] = "INTERRUPTED_BY_PROCESS_RESTART"
            set_state(key, state)
            touched += 1
    return touched


def _publish_frozen(book: str, min_obs: int = 3, per_side: int = 5, publication_anchor: Optional[datetime]=None,
                    period_key_override: Optional[str]=None, allow_preperiod: bool=False, allow_recovery: bool=False):
    """Publish/backfill a frozen slate up to its contract size without weakening gates.

    v6.4.9 preserves v6.4.8 reliability and adds pre-period/staged recovery:
      * a scan that starts before the freeze minute may publish when it completes inside
        the freeze/recovery window; and
      * 1-4 existing identities do not permanently block recovery to five.
    Existing identities are never replaced or re-ranked after publication.
    """
    b=str(book).upper(); pk=str(period_key_override or period_key(b)); now=datetime.now(IST)
    if b in ("WEEKLY","MONTHLY","ETF") and not allow_preperiod and not allow_recovery and not _publication_window_open(now,b):
        # A historical/test caller may explicitly supply an anchor already inside the
        # permitted window. Normal workers prefer completion time so a preparation scan
        # started before the freeze minute can still publish when it finishes after it.
        if publication_anchor is None or not _publication_window_open(publication_anchor,b):
            return 0
    allowed_sides=HORIZON_EXECUTABLE_SIDES.get(b,("LONG","SHORT"))
    with db() as con:
        existing_rows=con.execute(
            "SELECT symbol,side FROM recommendations WHERE book=? AND period_key=? "
            "AND COALESCE(result,'')<>'VOID'",
            (b,pk),
        ).fetchall()
        existing_by_side={}
        for row in existing_rows:
            existing_by_side.setdefault(str(row["side"]),set()).add(str(row["symbol"]).upper())
        rs=con.execute(
            "SELECT * FROM candidate_observations WHERE book=? AND period_key=? AND observations>=? "
            "ORDER BY side,avg_score DESC",
            (b,pk,min_obs),
        ).fetchall()

    made=0
    contract_min=_freeze_contract_min(b)
    horizon_blocked=_weekly_monthly_conflicts(b,pk) if b in ("WEEKLY","MONTHLY") else set()
    target_per_side=max(int(per_side),contract_min if contract_min and len(allowed_sides)==1 else int(per_side))
    for side in allowed_sides:
        already=existing_by_side.get(side,set())
        missing=max(0,target_per_side-len(already))
        if missing<=0:
            continue
        eligible=[]
        for raw in rs:
            sym=str(raw["symbol"]).upper()
            if raw["side"]!=side or sym in already or sym in horizon_blocked:
                continue
            try:
                c=json.loads(raw["payload_json"] or "{}")
            except Exception:
                continue
            feasibility=c.get("target_feasibility") or {}
            if b in ("WEEKLY","MONTHLY","ETF") and not feasibility.get("target_qualified"):
                continue
            eligible.append((float(raw["avg_score"]),c))
        eligible.sort(
            key=lambda x:(x[0],float((x[1].get("target_feasibility") or {}).get("feasibility_ratio") or 0),x[1].get("confidence",0)),
            reverse=True,
        )
        for avg_score,c in eligible[:missing]:
            rationale=dict(c.get("rationale") or {})
            rationale.update({
                "official_period_book":True,
                "identity_frozen_at_publication":True,
                "no_rank_replacement":True,
                "no_backfill_after_contract_complete":True,
                "freeze_contract_required":contract_min or target_per_side,
                "freeze_contract_recovery":bool(already),
                "scan_started_at":publication_anchor.isoformat() if publication_anchor else None,
                "publication_policy_version":"V649_STAGED_RECOVERY_PREPERIOD_FREEZE",
            })
            if b in HORIZON_EXECUTABLE_SIDES:
                rationale["horizon_execution_side_policy"]="LONG_ONLY"
                rationale["bearish_horizon_signals_are_research_only"]=True
            rid=_insert_rec(b,c["symbol"],side,avg_score,c["confidence"],c["price"],c["features"],c["regime"],c["strategies"],rationale,period_key_override=pk)
            if rid:
                already.add(str(c["symbol"]).upper()); made+=1
    return made


def _journal_decisions(book: str, candidates: List[Dict[str,Any]], period_key_override: Optional[str]=None) -> None:
    """Batch decision-journal writes with point-in-time audit envelopes."""
    if not candidates:return
    try:
        now=datetime.now(IST);bucket=now.replace(minute=(now.minute//5)*5,second=0,microsecond=0).isoformat()
        ts=now_iso();pk=str(period_key_override or period_key(book));rows=[]
        strategy_union=[]
        for c in candidates:
            for sid in c.get("strategies") or []:
                if sid not in strategy_union:strategy_union.append(sid)
        common=common_audit_context(strategy_union)
        for c in candidates:
            ti=c.get("trade_intelligence") or {}
            did=f"{book}|{pk}|{c.get('symbol')}|{c.get('side')}|{bucket}"
            envelope=c.get("audit_envelope")
            if not isinstance(envelope,dict) or not envelope:
                envelope=make_audit_envelope(book,pk,c.get("symbol"),c.get("side"),c.get("features") or {},
                                             c.get("rationale") or {},c.get("strategies") or [],common=common,decision_ts=ts)
            envelope=dict(envelope);envelope["decision_id"]=did;c["audit_envelope"]=envelope;c["decision_id"]=did
            if isinstance(c.get("rationale"),dict):
                c["rationale"]["audit_envelope"]=envelope;c["rationale"]["decision_id"]=did
            rows.append((
                did,ts,book,pk,c.get("symbol"),c.get("side"),
                ti.get("decision") or c.get("decision") or "WATCH",
                float(c.get("raw_ensemble_score") or c.get("score") or 0),
                float(ti.get("score") or 0),int(ti.get("hard_fail_count") or 0),
                json.dumps(c.get("strategies") or []),json.dumps(c,default=str,separators=(",",":")),
                json.dumps(envelope,default=str,separators=(",",":")),
                c.get("pipeline_verdict"),c.get("pipeline_stage"),
            ))
        with db() as con:
            con.executemany(
                "INSERT OR IGNORE INTO trade_decisions(decision_id,ts,book,period_key,symbol,side,decision,ensemble_score,"
                "intelligence_score,hard_fail_count,strategy_ids_json,payload_json,audit_envelope_json,pipeline_verdict,pipeline_stage) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",rows)
            con.execute("DELETE FROM trade_decisions WHERE id NOT IN (SELECT id FROM trade_decisions ORDER BY id DESC LIMIT 50000)")
    except Exception as exc:
        health("trade_journal","WARN",str(exc)[:180])

def _journal_decision(book: str, c: Dict[str, Any]) -> None:
    _journal_decisions(book,[c])


def scan_equities(book: str = "INTRADAY", symbols_override: Optional[List[str]] = None,
                  sides_override: Optional[tuple] = None, target_now: Optional[datetime] = None,
                  period_key_override: Optional[str] = None, scan_policy: Optional[str] = None) -> List[Dict[str, Any]]:
    """Cached-first deterministic scan.

    v6.2.8 rule: the scanner itself does not refresh global/sector/news/fundamental data.
    Slow network enrichment belongs to independent background workers. The only optional
    broker call is one bounded LTP refresh for the final short list after local scoring.
    """
    started=time.monotonic()
    horizon = "INTRADAY" if book == "INTRADAY" else ("MONTHLY" if book == "MONTHLY" else "WEEKLY")
    settings = load_settings()
    # v6.4.1: every Groww NSE CASH equity enters the discovery pass. Liquidity ranking is
    # used only as an enrichment priority elsewhere; it never truncates a research book.
    metas=universe();meta_map={str(x.get('symbol') or '').upper():x for x in metas}
    all_syms=[str(x.get('symbol') or '').upper() for x in metas if x.get('symbol')]
    if symbols_override is None:
        syms=all_syms
    else:
        allowed=set(all_syms); seen=set(); syms=[]
        for raw_sym in symbols_override:
            sym=str(raw_sym or '').upper()
            if sym in allowed and sym not in seen:
                syms.append(sym);seen.add(sym)
    sides=tuple(sides_override or ("LONG","SHORT"))
    interval="5minute" if book=="INTRADAY" else "1day"
    cov={"interval":interval,"symbols":len(syms),"files":None,"ready":0,"minimum_rows":30,
         "raw_rows":None,"parsed_rows":None,"parse_loss":None,"short_samples":[],
         "parser_policy":"V642_FULL_BREADTH_ON_THE_FLY","at":now_iso()}
    stats={"book":book,"started_at":now_iso(),"running":True,"stage":"PREP","universe":len(syms),
           "full_nse_universe":len(all_syms),"current_universe":len(all_syms),"breadth_evaluated":0,"processed":0,"history_ready":0,
           "history_missing":0,"limited_history_scanned":0,"limited_history_samples":[],"fundamentals_missing":0,
           "family_vote_reject":0,"family_vote_advisory":0,"strategy_evidence_reject":0,
           "ensemble_score_reject":0,"intelligence_no_trade":0,"intelligence_watch":0,
           "target_feasibility_reject":0,"liquidity_reject":0,"freshness_reject":0,"risk_reject":0,
           "data_error":0,"raw_eligible":0,"near_misses":[],"history_coverage":cov,
           "universe_policy":scan_policy or ("FULL_GROWW_NSE_EQUITY_SHARES_NO_TOP_N_CAP" if symbols_override is None else "DETERMINISTIC_RECOVERY_BATCH_NO_GATE_RELAXATION"),
           "target_period_key":str(period_key_override or period_key(book))}
    set_state(f"scan_detail_{book}",stats)

    # Cached-only context. Background workers keep these fresh; missing context remains UNKNOWN.
    # V627 compatibility/invariant: fabric_symbol_context delegates to sector_context_cached
    # and news_context(..., allow_refresh=False); scanners never synchronously refresh them.
    prices = live_prices(syms,allow_network=False,max_age_seconds=180)
    regime_state = get_state("last_regime",{}) or {"regime":"WARMING","breadth_up_pct":0.0,"breadth_down_pct":0.0,"trend_vote":0.0,"stale":True}
    regime=(regime_state.get("regime") or "WARMING")
    global_ctx=get_state("global_context",{}) or {"risk_state":"UNKNOWN","moves_pct":{},"stale":True,"source":"BACKGROUND_CONTEXT_NOT_READY"}
    specs_by_side={side:active_strategies(horizon,side,int(settings.get('strategy_champions_per_horizon',24))) for side in ("LONG","SHORT")}

    progress_step=max(25,min(100,max(1,len(syms)//50)))
    def progress(symbol=None, force=False):
        stats["elapsed_seconds"]=round(time.monotonic()-started,2)
        stats["last_progress_at"]=now_iso()
        if symbol is not None:stats["current_symbol"]=symbol
        stats["history_coverage"].update({"ready":stats["history_ready"],"files":stats["history_ready"]+stats["history_missing"],"scanned_on_the_fly":True})
        if force or stats["processed"]<=1 or stats["processed"]%progress_step==0 or stats["processed"]==len(syms):
            set_state(f"scan_detail_{book}",stats)

    def near(symbol,side,stage,score=None,detail=None,distance_to_threshold=None):
        item={"symbol":symbol,"side":side,"stage":stage,"rejection_stage":stage}
        if score is not None:item["score"]=round(float(score),2)
        if detail:
            item["detail"]=str(detail)[:180]
            item["rejection_reason"]=str(detail)[:180]
        if distance_to_threshold is not None:
            try:item["distance_to_threshold"]=round(float(distance_to_threshold),4)
            except Exception:item["distance_to_threshold"]=None
        arr=stats["near_misses"]
        arr.append(item)
        if len(arr)>12:
            arr.sort(key=lambda x:(float(x.get("score") or 0),-abs(float(x.get("distance_to_threshold") or 999999))),reverse=True)
            del arr[12:]

    raw=[];decision_buffer=[]
    def journal(candidate):
        decision_buffer.append(candidate)
        if len(decision_buffer)>=100:
            _journal_decisions(book,list(decision_buffer),period_key_override=period_key_override);decision_buffer.clear()
    def mark(candidate,verdict,stage,rejection_code=None):
        candidate["pipeline_verdict"]=verdict;candidate["pipeline_stage"]=stage
        if rejection_code:candidate["rejection_code"]=rejection_code
        return candidate
    stats["stage"]="SCORING";progress(force=True)
    for idx_symbol,sym in enumerate(syms,1):
        stats["processed"]=idx_symbol;stats["breadth_evaluated"]=idx_symbol;progress(sym)
        path=_history_path(sym,interval)
        if not path.exists():
            stats["history_missing"]+=1;stats["limited_history_scanned"]+=1
            if len(stats["limited_history_samples"])<12:
                stats["limited_history_samples"].append({"symbol":sym,"rows":0,"status":"NO_CACHE_YET"})
            continue
        raw_hist=_load_raw_candles(path)
        if len(raw_hist)<30:
            stats["history_missing"]+=1;stats["limited_history_scanned"]+=1
            if len(stats["limited_history_samples"])<12:
                stats["limited_history_samples"].append({"symbol":sym,"rows":len(raw_hist),"status":"LIMITED_HISTORY"})
            continue
        df = history(sym, interval, allow_network=False)
        if len(df) < 30:
            stats["history_missing"]+=1;stats["limited_history_scanned"]+=1
            if len(stats["limited_history_samples"])<12:
                stats["limited_history_samples"].append({"symbol":sym,"rows":len(df),"status":"PARSED_HISTORY_SHORT"})
            continue
        stats["history_ready"]+=1
        f = latest_features(df)
        if book == 'INTRADAY':
            daily=history(sym,'1day',allow_network=False)
            if len(daily)>=30:
                hf=latest_features(daily);f['higher_tf_trend']=hf.get('trend',0);f['higher_ret20']=hf.get('ret20',0)
        else:
            f['higher_tf_trend']=f.get('trend',0);f['higher_ret20']=f.get('ret20',0)
        px = float(prices.get(sym) or f.get("close") or 0);f['close']=px
        if px <= 0:
            near(sym,"-","PRICE_MISSING");continue
        fund = {} if book == "INTRADAY" else fundamentals_get(sym, allow_refresh=False)
        if book in ("WEEKLY", "MONTHLY") and not fund:
            stats["fundamentals_missing"] += 1
            near(sym, "-", "FUNDAMENTALS_NOT_CAPTURED", detail="continuing with UNKNOWN fundamentals; confidence/target gate remains conservative")
        meta=meta_map.get(sym) or {}
        data_conf=min(1.0,(len(df)/120)*.45+(.25 if px>0 else 0)+(.2 if fund else .05)+(.1 if meta else 0))
        fq=quality_score(fund) if fund else None
        candles=None
        for side in sides:
            # Recovery batches reject mathematically impossible horizon candidates before
            # expensive strategy/candle/intelligence work.  This is an optimization only:
            # the same target, data and fundamentals hard gates are used with optimistic
            # score/confidence, so no candidate that could pass the full gate is excluded.
            if symbols_override is not None and book in ("WEEKLY","MONTHLY"):
                optimistic=_target_feasibility(book,side,f,100.0,1.0,data_conf,fq,now=target_now)
                if not optimistic["target_qualified"]:
                    stats["target_feasibility_reject"]+=1
                    near(sym,side,"TARGET_CAPACITY_PREFILTER",100.0,f"ratio={optimistic.get('feasibility_ratio')}")
                    continue
            votes=[]
            for sp in specs_by_side.get(side) or []:
                sc,reasons=score_strategy(sp,f,regime,fund)
                if sc>=64:votes.append((sc,sp["strategy_id"],sp.get("family") or "UNKNOWN",reasons))
            best_by_family={}
            for vote in votes:
                fam=vote[2]
                if fam not in best_by_family or vote[0]>best_by_family[fam][0]:best_by_family[fam]=vote
            family_votes=sorted(best_by_family.values(),reverse=True)
            if not family_votes:
                stats["family_vote_reject"]+=1;stats["strategy_evidence_reject"]+=1
                near(sym,side,"STRATEGY_EVIDENCE",score=0,detail="no audited strategy produced score >=64",distance_to_threshold=64)
                continue
            # v6.6.0: distinct-family count is evidence, not a safety gate. Requiring two
            # families had never been validated out-of-sample and was eliminating otherwise
            # measurable candidates before liquidity/risk/intelligence gates could evaluate them.
            if len(family_votes)<2:
                stats["family_vote_advisory"]+=1
            top=family_votes[:5];ensemble_score=sum(x[0] for x in top)/len(top)
            # One authoritative score threshold per book. Earlier code scanned Intraday at
            # 72 and then silently discarded 72-75.99 at publication. Keep the effective
            # safety threshold unchanged at 76, but make every rejection visible in the funnel.
            base_min=76 if book=="INTRADAY" else 74
            # Joint evidence proxy: normalized signal score multiplied by independent data
            # completeness. Family count is intentionally absent until its incremental OOS
            # value has been statistically demonstrated.
            conf=max(0.0,min(1.0,data_conf*(ensemble_score/100.0)))
            if ensemble_score<base_min:
                stats["ensemble_score_reject"]+=1;near(sym,side,"ENSEMBLE_SCORE",ensemble_score,f"minimum={base_min}",distance_to_threshold=base_min-ensemble_score);continue
            if candles is None:candles=detect_patterns(df)
            geom=_risk_geometry(book,f);target_pct=geom["target_pct"];stop_pct=geom["stop_pct"]
            shared_ctx=fabric_symbol_context(sym,book=book,side=side,features=f,fundamentals=fund)
            cached_news=shared_ctx["news"];sctx=shared_ctx["sector"];ectx=shared_ctx["events"];ictx=shared_ctx["institutional"]
            ti=evaluate_trade_intelligence(book=book,symbol=sym,side=side,features=f,fundamentals=fund,regime_state=regime_state,candle_info=candles,news=cached_news,global_ctx=global_ctx,portfolio=None,sector_ctx=sctx,event_ctx=ectx,institutional_ctx=ictx,target_pct=target_pct,stop_pct=stop_pct,strategy_ids=[x[1] for x in top],data_confidence=data_conf)
            rationale={"reasons":sum([x[3][:2] for x in top],[]),"ensemble_families":[x[2] for x in top],
                "strategy_evidence":{"family_count":len(family_votes),"family_diversity_mode":"MULTI_FAMILY" if len(family_votes)>=2 else "ADVISORY_SHADOW","hard_gate":False,"policy":"V660_UNVALIDATED_FAMILY_VOTE_IS_ADVISORY"},
                "fundamental_quality":fq,"fundamentals_asof":fund.get("_asof") if fund else None,"fundamentals_source":fund.get("_source") if fund else None,"data_confidence":data_conf,"candlestick_context":candles,"global_context":global_ctx,"news_context":cached_news,"sector_context":sctx,"event_context":ectx,"institutional_context":ictx,"evidence_fabric_policy":shared_ctx.get("fabric_policy"),"trade_intelligence":ti}
            candidate={"symbol":sym,"side":side,"score":ensemble_score,"raw_ensemble_score":ensemble_score,"confidence":conf,"price":px,"features":f,"regime":regime,"strategies":[x[1] for x in top],"rationale":rationale,"trade_intelligence":ti,"candlestick_context":candles,"fundamentals":fund}
            if ti['decision']=='NO_TRADE':
                stats["intelligence_no_trade"]+=1
                failed={int(x.get("rank") or 0) for x in (ti.get("filters") or []) if x.get("hard_fail")}
                if 41 in failed:stats["liquidity_reject"]+=1
                if failed.intersection({44,45,46,47,48,50}):stats["risk_reject"]+=1
                near(sym,side,"INTELLIGENCE_NO_TRADE",ensemble_score,"; ".join((ti.get('hard_blockers') or [])[:3]));journal(mark(candidate,"REJECT","TRADE_INTELLIGENCE","INTELLIGENCE_NO_TRADE"));continue
            if ti['decision']!='ELIGIBLE':
                stats["intelligence_watch"]+=1;near(sym,side,"INTELLIGENCE_WATCH",ensemble_score);journal(mark(candidate,"WATCH","TRADE_INTELLIGENCE","INTELLIGENCE_WATCH"));continue
            candidate['score']=0.70*ensemble_score+0.30*float(ti['score'])
            if book in ("WEEKLY","MONTHLY"):
                tf=_target_feasibility(book,side,f,candidate['score'],conf,data_conf,fq,now=target_now);candidate["target_feasibility"]=tf;candidate["rationale"]["target_feasibility"]=tf
                if not tf["target_qualified"]:
                    stats["target_feasibility_reject"]+=1;near(sym,side,"TARGET_FEASIBILITY",candidate['score'],f"ratio={tf.get('feasibility_ratio')}");journal(mark(candidate,"REJECT","TARGET_FEASIBILITY","TARGET_NOT_QUALIFIED"));continue
                candidate["rationale"]["raw_ensemble_score"]=round(ensemble_score,3)
                capacity_score=min(100.0,70.0+30.0*min(1.0,max(0.0,tf["feasibility_ratio"]-1.0)));candidate["score"]=0.60*candidate['score']+0.40*capacity_score
            raw.append(candidate);stats["raw_eligible"]+=1
    raw.sort(key=lambda x:x['score'],reverse=True)

    # Finalists read the shared LTP cache maintained by market_snapshot. The scanner itself
    # performs no network request, so recommendation latency cannot be held hostage by APIs.
    stats["stage"]="FINALIST_REFRESH";progress(force=True)
    finalists=raw  # no arbitrary top-N finalist cap; every eligible candidate gets final gates
    fresh=live_prices([c['symbol'] for c in finalists],allow_network=False,max_age_seconds=90) if finalists else {}
    out=[]
    for c in finalists:
        if c['symbol'] in fresh:
            c['price']=float(fresh[c['symbol']]);c['features']['close']=c['price']
        shared_ctx=fabric_symbol_context(c['symbol'],book=book,side=c['side'],features=c['features'],fundamentals=c.get('fundamentals') or {})
        news=shared_ctx["news"];portfolio=recommendation_cluster(c['symbol'],c['side'])
        sctx=shared_ctx["sector"];ectx=shared_ctx["events"];ictx=shared_ctx["institutional"]
        ti=evaluate_trade_intelligence(book=book,symbol=c['symbol'],side=c['side'],features=c['features'],fundamentals=c.get('fundamentals') or {},regime_state=regime_state,candle_info=c.get('candlestick_context'),news=news,global_ctx=global_ctx,portfolio=portfolio,sector_ctx=sctx,event_ctx=ectx,institutional_ctx=ictx,target_pct=_risk_geometry(book,c['features'])['target_pct'],stop_pct=_risk_geometry(book,c['features'])['stop_pct'],strategy_ids=c['strategies'],data_confidence=float(c['rationale'].get('data_confidence') or 0))
        c['trade_intelligence']=ti;c['rationale']['trade_intelligence']=ti;c['rationale']['news_context']=news;c['rationale']['portfolio_fit']=portfolio;c['rationale']['sector_context']=sctx;c['rationale']['event_context']=ectx;c['rationale']['institutional_context']=ictx;c['rationale']['evidence_fabric_policy']=shared_ctx.get("fabric_policy")
        c['score']=0.70*float(c['raw_ensemble_score'])+0.30*float(ti['score'])
        if ti['decision']!='ELIGIBLE':
            stats["intelligence_no_trade"]+=1
            failed={int(x.get("rank") or 0) for x in (ti.get("filters") or []) if x.get("hard_fail")}
            if 41 in failed:stats["liquidity_reject"]+=1
            if failed.intersection({44,45,46,47,48,50}):stats["risk_reject"]+=1
            near(c['symbol'],c['side'],"FINAL_INTELLIGENCE",c['score'],"; ".join((ti.get('hard_blockers') or [])[:3]));journal(mark(c,"REJECT","FINAL_TRADE_INTELLIGENCE","FINAL_INTELLIGENCE"));continue
        if book in ('WEEKLY','MONTHLY'):
            tf=_target_feasibility(book,c['side'],c['features'],c['score'],c['confidence'],float(c['rationale'].get('data_confidence') or 0),c['rationale'].get('fundamental_quality'),now=target_now);c['target_feasibility']=tf;c['rationale']['target_feasibility']=tf
            if not tf['target_qualified']:
                stats["target_feasibility_reject"]+=1;near(c['symbol'],c['side'],"FINAL_TARGET_FEASIBILITY",c['score'],f"ratio={tf.get('feasibility_ratio')}");journal(mark(c,"REJECT","FINAL_TARGET_FEASIBILITY","FINAL_TARGET_NOT_QUALIFIED"));continue
        journal(mark(c,"PUBLICATION_READY","FINAL_GATES"));out.append(c)
    out.sort(key=lambda x:x['score'],reverse=True)
    if decision_buffer:
        _journal_decisions(book,list(decision_buffer),period_key_override=period_key_override);decision_buffer.clear()
    stats["history_coverage"].update({"ready":stats["history_ready"],"files":stats["history_ready"]+stats["history_missing"],"scanned_on_the_fly":True})
    stats["funnel"]={
        "universe_total":len(all_syms),"scan_scope_total":len(syms),"scan_scope_processed":stats["processed"],
        "full_universe_scan":bool(symbols_override is None and stats["processed"]>=len(all_syms)),
        "history_ready":stats["history_ready"],"history_reject":stats["history_missing"],
        "liquidity_reject":stats["liquidity_reject"],"freshness_reject":stats["freshness_reject"],
        "strategy_evidence_reject":stats["strategy_evidence_reject"],"strategy_diversity_advisory":stats["family_vote_advisory"],
        "score_reject":stats["ensemble_score_reject"],"target_feasibility_reject":stats["target_feasibility_reject"],
        "risk_reject":stats["risk_reject"],"trade_intelligence_reject":stats["intelligence_no_trade"]+stats["intelligence_watch"],
        "data_error":stats["data_error"],"raw_eligible":stats["raw_eligible"],"publication_ready":len(out),"published":0,
    }
    stats.update({"running":False,"stage":"DONE","output_candidates":len(out),"completed_at":now_iso(),"duration_seconds":round(time.monotonic()-started,2)})
    stats["scan_run_id"]=record_scan_run(book,stats)
    progress(force=True)
    return out

def _close_expired_period_books(now: Optional[datetime] = None) -> int:
    now = now or datetime.now(IST)
    current = {b: period_key(b, now) for b in ("WEEKLY", "MONTHLY", "ETF")}
    closed = 0
    with db() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM recommendations WHERE state='LIVE' AND book IN ('WEEKLY','MONTHLY','ETF')").fetchall()]
        for r in rows:
            book = r["book"]
            # Pre-period frozen rows have a future period_key and must remain LIVE.
            # Only rows from an actually older period are rollover-expired.
            rollover = str(r["period_key"]) < str(current[book])
            end_today = (str(r["period_key"]) == str(current[book])
                         and now.date() == _period_end_date(book, now)
                         and now.time().replace(tzinfo=None) >= MARKET_CLOSE)
            if not (rollover or end_today):
                continue
            entry = float(r["entry_price"] or 0)
            px = float(r["current_price"] or entry)
            sign = 1 if r["side"] == "LONG" else -1
            achieved = (px / entry - 1) * 100 * sign if entry > 0 else 0.0
            con.execute(
                "UPDATE recommendations SET state='CLOSED',closed_at=?,result='MISS',close_reason='PERIOD_END_TARGET_NOT_REACHED',updated_at=? WHERE recommendation_id=? AND state='LIVE'",
                (now_iso(), now_iso(), r["recommendation_id"]),
            )
            closed += 1
    return closed


def update_live_books():
    now = datetime.now(IST); t=now.time().replace(tzinfo=None); today=now.date().isoformat()
    _close_expired_period_books(now)
    # Price/outcome updates for every open Indian recommendation. Identities, entry,
    # target and original rationale remain immutable. User-specific deadline lanes are
    # resolved at 15:00 IST even though the exchange remains open until 15:30.
    with db() as con:
        rs = [dict(r) for r in con.execute("SELECT * FROM recommendations WHERE state='LIVE' AND exchange='NSE'").fetchall()]
    # Priority-quote producer refreshes these symbols at the same cadence. Lifecycle
    # consumers never initiate a second broker fetch for the same prices.
    prices = live_prices([r["symbol"] for r in rs],allow_network=False,max_age_seconds=90) if rs else {}
    with db() as con:
        for r in rs:
            px = float(prices.get(r["symbol"]) or r["current_price"]);entry = float(r["entry_price"]);side = r["side"];book=str(r.get('book') or '')
            d = (px / entry - 1) * 100 * (1 if side == "LONG" else -1);mfe = max(float(r["max_favourable_pct"]), d);mae = min(float(r["max_adverse_pct"]), d);close = None;result = None
            # Multi-session Indian books are delivery/holding books for this user. A cash
            # SHORT cannot be carried as a weekly/monthly/ETF position, so fail closed if a
            # legacy row somehow survives migration.
            if book in HORIZON_EXECUTABLE_SIDES and side == "SHORT":
                close = "HORIZON_SHORT_RESEARCH_ONLY_POLICY";result = "VOID"
            if close is None and d >= float(r["target_pct"] or 0): close = "TARGET_REACHED";result = "WIN"
            elif (side == "LONG" and px <= float(r["stop_price"] or 0)) or (side == "SHORT" and px >= float(r["stop_price"] or 1e99)): close = "THESIS_INVALIDATED";result = "LOSS"
            # Same-session user deadline contracts.
            if close is None and t>=SHORT_HARD_EXIT:
                if book=='INTRADAY' and side=='SHORT':close='USER_1500_SHORT_CUTOFF';result='MISS'
                elif book=='CIRCUIT' and r.get('period_key')==today:close='USER_1500_CIRCUIT_CUTOFF';result='MISS'
                elif book in ('CIRCUIT_NEXTDAY','GLOBAL_INDIA_LONG','GLOBAL_INDIA_SHORT') and str(r.get('period_key') or '')<=today:
                    close='SESSION_1500_FORECAST_CUTOFF';result='MISS'
            # Session/rollover safety if the laptop was asleep at the normal close.
            if close is None and book=='INTRADAY':
                if str(r.get('period_key') or '')<today:
                    close='INTRADAY_SESSION_ROLLOVER';result='MISS'
                elif str(r.get('period_key') or '')==today and t>=MARKET_CLOSE:
                    close='NSE_SESSION_END_TARGET_NOT_REACHED';result='MISS'
            if close is None and book=='CIRCUIT' and str(r.get('period_key') or '')<today:
                close='CIRCUIT_SESSION_ROLLOVER';result='MISS'
            # Rollover safety for forecast books if the laptop was asleep at the cutoff.
            if close is None and book in ('CIRCUIT_NEXTDAY','GLOBAL_INDIA_LONG','GLOBAL_INDIA_SHORT') and str(r.get('period_key') or '')<today:
                close='FORECAST_SESSION_ROLLOVER';result='MISS'
            if close:
                con.execute("UPDATE recommendations SET current_price=?,max_favourable_pct=?,max_adverse_pct=?,state='CLOSED',closed_at=?,result=?,close_reason=?,updated_at=? WHERE recommendation_id=?",(px,mfe,mae,now_iso(),result,close,now_iso(),r["recommendation_id"]))
            else:
                con.execute("UPDATE recommendations SET current_price=?,max_favourable_pct=?,max_adverse_pct=?,updated_at=? WHERE recommendation_id=?",(px,mfe,mae,now_iso(),r["recommendation_id"]))


def run_intraday_cycle():
    started=time.monotonic();now=datetime.now(IST);settings=load_settings()
    live_window=is_regular_trading_day(now.date()) and MARKET_OPEN <= now.time().replace(tzinfo=None) <= INTRADAY_ENTRY_CUTOFF
    status={"book":"INTRADAY","started_at":now_iso(),"running":True,"live_window":live_window}
    set_state("scan_status_INTRADAY",status)
    made=0;freshness_holds=0;cands=[];bootstrap_batch=None;pass_summary=None;pk=period_key("INTRADAY",now)
    with db() as con:
        live_count=int(con.execute("SELECT COUNT(*) FROM recommendations WHERE book='INTRADAY' AND period_key=? AND state='LIVE'",(pk,)).fetchone()[0])
    if live_window:
        if live_count==0:
            # Zero-output bootstrap scans cached-ready symbols in a deterministic rotating
            # liquidity order.  It does not relax any strategy, freshness, intelligence,
            # target, portfolio or execution gate; the next cycle returns to full breadth
            # as soon as one valid live recommendation exists.
            batch=_recovery_symbol_batch("INTRADAY","5minute",pk,int(settings.get("intraday_bootstrap_batch",100)));bootstrap_batch=batch
            status["bootstrap_recovery"]={"active":True,"batch_size":batch.get("batch_size",0),
                "ready_cached":batch.get("ready",0),"cursor":batch.get("cursor",0),
                "pass_started":batch.get("pass_started",0),"pass":batch.get("pass",0),
                "completed_pass":bool(batch.get("completed_pass")),
                "policy":"PRIORITY_BOOTSTRAP_THEN_FULL_BREADTH_NO_GATE_RELAXATION"}
            cands=scan_equities("INTRADAY",symbols_override=batch.get("symbols") or [],
                period_key_override=pk,scan_policy="PRIORITY_BOOTSTRAP_ZERO_LIVE_NO_GATE_RELAXATION")
        else:
            status["bootstrap_recovery"]={"active":False,"reason":"CURRENT_DAY_LIVE_RECOMMENDATION_EXISTS"}
            cands=scan_equities("INTRADAY")
        for c in cands:
            if c["side"]=="SHORT":
                geom=_risk_geometry("INTRADAY",c["features"]);deadline=_intraday_short_deadline_feasibility(c["features"],geom["target_pct"])
                c.setdefault("rationale",{})["deadline_feasibility"]=deadline
                if not deadline["feasible"]:continue
            if datetime.now(IST).time().replace(tzinfo=None)>INTRADAY_ENTRY_CUTOFF:break
            # STALE_DATA/VOID quarantine rows must not permanently poison a symbol identity.
            # LIVE/CLOSED rows still prevent same-day duplicate/re-entry behavior.
            with db() as con:
                exists=con.execute("SELECT 1 FROM recommendations WHERE book='INTRADAY' AND period_key=? AND symbol=? AND side=? AND state IN ('LIVE','CLOSED')",
                    (pk,c["symbol"],c["side"])).fetchone()
            if not exists:
                rid=_insert_rec("INTRADAY",c["symbol"],c["side"],c["score"],c["confidence"],c["price"],c["features"],c["regime"],c["strategies"],c["rationale"])
                if rid:made+=1
                else:freshness_holds+=1
    else:
        set_state("scan_detail_INTRADAY",{"book":"INTRADAY","running":False,"status":"OUTSIDE_LIVE_WINDOW","at":now_iso(),"processed":0,"universe":0})
    detail=get_state("scan_detail_INTRADAY",{}) or {}
    if isinstance(detail.get("funnel"),dict):
        detail["funnel"]["freshness_reject"]=int(detail["funnel"].get("freshness_reject") or 0)+freshness_holds
        detail["funnel"]["published"]=made
        detail["freshness_holds_at_publication"]=freshness_holds
        detail["published"]=made
        set_state("scan_detail_INTRADAY",detail)
    if bootstrap_batch is not None:
        pass_summary=_merge_intraday_bootstrap_pass(pk,bootstrap_batch,detail,made)
        status.setdefault("bootstrap_recovery",{})["pass_summary"]=pass_summary
        status["search_evidence"]=pass_summary
    if live_window and made==0:
        history_ready=int(detail.get("history_ready") or 0);processed=int(detail.get("processed") or 0)
        if pass_summary is not None:
            availability_class=str(pass_summary.get("classification") or "SEARCH_INCOMPLETE")
            if availability_class=="SEARCH_INCOMPLETE":availability_reason="DETERMINISTIC_CACHED_READY_UNIVERSE_PASS_INCOMPLETE"
            elif availability_class=="DATA_NOT_READY":availability_reason="NO_HISTORY_READY_SYMBOLS_AFTER_EXHAUSTIVE_CACHED_PASS"
            elif availability_class=="NO_QUALIFIED_OPPORTUNITY_IN_CACHED_READY_UNIVERSE":availability_reason="NO_QUALIFIED_OPPORTUNITY_AFTER_EXHAUSTIVE_CACHED_READY_PASS"
            elif availability_class=="QUALIFIED_CANDIDATE_NOT_PUBLISHED":availability_reason="QUALIFIED_CANDIDATE_BLOCKED_AT_PUBLICATION_OR_IDENTITY_GATE"
            else:availability_reason=availability_class
            status["availability_class"]=availability_class
        elif processed<=1 and history_ready==0:
            availability_reason="SCAN_INTERRUPTED_OR_NOT_PROGRESSING";status["availability_class"]="SOFTWARE_OR_DATA_BOTTLENECK"
        elif not cands:
            availability_reason="NO_DATA_VALID_CANDIDATES_AFTER_FULL_BREADTH_QUALITY_RISK_GATES";status["availability_class"]="NO_QUALIFIED_OPPORTUNITY"
        else:
            availability_reason="ELIGIBLE_CANDIDATES_ALREADY_EXIST_OR_ENTRY_GATE_REJECTED";status["availability_class"]="PUBLICATION_OR_IDENTITY_GATE"
        status["status"]="NO_RECOMMENDATIONS"
        status["availability_reason"]=availability_reason
    else:
        status["status"]="OK" if live_window else "OUTSIDE_LIVE_WINDOW"
        status["availability_reason"]=None
    status.update({"running":False,"candidates":len(cands),"inserted":made,"completed_at":now_iso(),"duration_seconds":round(time.monotonic()-started,2)})
    set_state("scan_status_INTRADAY",status)
    set_state("last_research_cycle",{"at":now_iso(),"ok":True,"live_window":live_window,"horizon_publication_window":_publication_window_open(now, "WEEKLY"),"worker":"INTRADAY"})
    return made


def run_single_horizon_cycle(book: str):
    book=str(book).upper()
    if book not in ("WEEKLY","MONTHLY"):
        raise ValueError(f"unsupported horizon book: {book}")
    _repair_weekly_monthly_collisions()
    now=datetime.now(IST); scan_anchor=now; t=now.time().replace(tzinfo=None);settings=load_settings()
    ctx=_horizon_target_context(book,now);pk=str(ctx["period_key"]);target_now=ctx.get("target_now") or now;preperiod=bool(ctx.get("preperiod"))
    required=_freeze_contract_min(book) or 5
    existing=_freeze_contract_count(book,pk)
    if existing>=required:
        state={"open":False,"status":"PERIOD_BOOK_ALREADY_FROZEN","period_key":pk,"required":required,"published_total":existing,"shortage":0,
               "preperiod":preperiod}
        set_state(f"scan_status_{book}",{"book":book,"running":False,"status":"PERIOD_BOOK_ALREADY_FROZEN","at":now_iso(),"freeze":state,"contract":state,"target_period":ctx})
        _mark_scan_detail_idle(book,"PERIOD_BOOK_ALREADY_FROZEN",period_key=pk,freeze_contract=state,target_period=ctx)
        return 0

    # On the final monthly session a missing current-month slate can no longer satisfy
    # the unchanged 50% monthly target without fabricating edge.  Do not burn hours on an
    # impossible recovery; switch automatically to the next month after today's close.
    if (book=="MONTHLY" and not preperiod and now.date()==_period_end_date(book,now)
            and t<MARKET_CLOSE and _remaining_sessions(book,now)<1.0):
        contract={"required":required,"published_total":existing,"shortage":max(0,required-existing),
                  "recovery_required":True,"reason":"CURRENT_MONTH_TARGET_WINDOW_EFFECTIVELY_EXPIRED"}
        status="CURRENT_MONTH_TOO_LATE_FOR_SAFE_RECOVERY_WAITING_NEXT_PERIOD_PREFREEZE"
        set_state(f"scan_status_{book}",{"book":book,"running":False,"status":status,"at":now_iso(),"contract":contract,
            "target_period":ctx,"next_action":"AFTER_MARKET_CLOSE_PREPARE_NEXT_MONTH"})
        _mark_scan_detail_idle(book,status,period_key=pk,freeze_contract=contract,target_period=ctx)
        return 0

    normal_research = is_regular_trading_day(now.date()) and HORIZON_RESEARCH_START<=t<=HORIZON_RECOVERY_END
    missed_freeze_recovery = bool(
        not preperiod and existing<required and is_regular_trading_day(now.date())
        and HORIZON_RECOVERY_END<t<=MARKET_CLOSE
    )
    research_window = preperiod or normal_research or missed_freeze_recovery
    publication_allowed = preperiod or _publication_window_open(now,book) or missed_freeze_recovery
    if not research_window:
        state=_horizon_freeze_window(book,now)
        status="FREEZE_CONTRACT_SHORTAGE_WINDOW_CLOSED" if existing<required and t>HORIZON_RECOVERY_END else (state.get("status") or "OUTSIDE_MORNING_RESEARCH_WINDOW")
        contract={"required":required,"published_total":existing,"shortage":max(0,required-existing),"recovery_required":existing<required}
        set_state(f"scan_status_{book}",{"book":book,"running":False,"status":status,"at":now_iso(),"freeze":state,"contract":contract,"target_period":ctx})
        _mark_scan_detail_idle(book,status,period_key=pk,freeze_contract=contract,target_period=ctx)
        return 0

    prepublished=0
    if publication_allowed:
        prepublished=_publish_frozen(book,1,required,publication_anchor=scan_anchor,
            period_key_override=pk,allow_preperiod=preperiod,allow_recovery=missed_freeze_recovery)
        existing=_freeze_contract_count(book,pk)
        if existing>=required:
            contract={"required":required,"published_total":existing,"shortage":0,"recovery_required":False}
            st={"book":book,"running":False,"status":"CONTRACT_FULFILLED_FROM_PREPARED_CANDIDATES","published":prepublished,
                "completed_at":now_iso(),"duration_seconds":0.0,"freeze":_horizon_freeze_window(book,now),"contract":contract,"target_period":ctx}
            set_state(f"scan_status_{book}",st)
            _mark_scan_detail_idle(book,"CONTRACT_FULFILLED",period_key=pk,freeze_contract=contract,target_period=ctx)
            return prepublished

    try:
        from .fundamentals import snapshot_status
        fund_status=snapshot_status()
    except Exception:
        fund_status={}
    obs=1;started=time.monotonic()
    batch=_recovery_symbol_batch(book,"1day",pk,int(settings.get("horizon_recovery_batch_size",120)))
    st={"book":book,"running":True,"started_at":now_iso(),"status":"MISSED_FREEZE_CACHED_RECOVERY" if missed_freeze_recovery else "STAGED_CONTRACT_RECOVERY",
        "fundamental_snapshots":fund_status.get("snapshots",0),
        "fundamental_symbols":fund_status.get("symbols",0),"contract":{"required":required,"published_total":existing,"shortage":max(0,required-existing)},
        "target_period":ctx,"recovery_policy":"CACHED_ONLY_NO_GATE_RELAXATION" if missed_freeze_recovery else "DETERMINISTIC_STAGED_RECOVERY_NO_GATE_RELAXATION",
        "recovery_batch":{"batch_size":batch.get("batch_size",0),"ready_cached":batch.get("ready",0),
            "cursor":batch.get("cursor",0),"pass":batch.get("pass",0)}}
    set_state(f"scan_status_{book}",st)
    try:
        c=scan_equities(book,symbols_override=batch.get("symbols") or [],sides_override=("LONG",),
            target_now=target_now,period_key_override=pk,scan_policy="STAGED_CONTRACT_RECOVERY_LONG_ONLY_NO_GATE_RELAXATION")
        _observe(book,c,period_key_override=pk)
        published=prepublished
        completion=datetime.now(IST)
        publication_at_completion = preperiod or _publication_window_open(completion,book) or missed_freeze_recovery
        if publication_at_completion:
            published+=_publish_frozen(book,obs,required,publication_anchor=completion,
                period_key_override=pk,allow_preperiod=preperiod,allow_recovery=missed_freeze_recovery)
        total=_freeze_contract_count(book,pk);shortage=max(0,required-total)
        with db() as con:
            obs_rows=con.execute("SELECT COUNT(*) FROM candidate_observations WHERE book=? AND period_key=?",(book,pk)).fetchone()[0]
            max_obs=con.execute("SELECT COALESCE(MAX(observations),0) FROM candidate_observations WHERE book=? AND period_key=?",(book,pk)).fetchone()[0]
        detail=get_state(f"scan_detail_{book}",{}) or {}
        if total>=required:
            status="CONTRACT_FULFILLED";reason=None
        elif not publication_at_completion:
            status="PREPARED_WAITING_FOR_FREEZE";reason="WAITING_FOR_FREEZE_WINDOW"
        else:
            status="FREEZE_SHORTAGE_EXPANDING_RECOVERY"
            out_candidates=int(detail.get("output_candidates") or len(c) or 0)
            reason="INSUFFICIENT_DATA_VALID_LONG_CANDIDATES_IN_CURRENT_BATCH" if out_candidates<required else "QUALIFIED_CANDIDATES_ACCUMULATING"
        contract={"required":required,"published_total":total,"shortage":shortage,"recovery_required":shortage>0,"reason":reason,
                  "staged_expansion":True,"no_gate_relaxation":True,"missed_freeze_recovery":missed_freeze_recovery}
        st.update({"running":False,"status":status,"eligible_candidates":len(c),"candidate_observation_rows":int(obs_rows),
                   "max_observations":int(max_obs),"required_observations":obs,"published":published,
                   "publication_window":publication_at_completion,"freeze":_horizon_freeze_window(book,completion),
                   "contract":contract,"completed_at":now_iso(),"duration_seconds":round(time.monotonic()-started,2)})
        _mark_scan_detail_idle(book,status,period_key=pk,freeze_contract=contract,target_period=ctx)
    except Exception as exc:
        total=_freeze_contract_count(book,pk)
        contract={"required":required,"published_total":total,"shortage":max(0,required-total),"recovery_required":total<required,"reason":"SCAN_ERROR"}
        st.update({"running":False,"status":"ERROR","error":str(exc)[:240],"contract":contract,"completed_at":now_iso(),"duration_seconds":round(time.monotonic()-started,2)})
        health(f"{book.lower()}_worker","ERROR",str(exc)[:240])
    set_state(f"scan_status_{book}",st)
    return int(st.get("published") or 0)


def run_horizon_cycle():
    """Compatibility/manual wrapper; runtime schedules Weekly and Monthly independently."""
    return run_single_horizon_cycle("WEEKLY") + run_single_horizon_cycle("MONTHLY")


def run_research_cycle():
    """Compatibility/manual full cycle. Runtime v6.2.4 uses independent workers."""
    update_live_books();n=run_intraday_cycle();n+=run_horizon_cycle()
    from .specialized import run_etf_cycle,run_circuit_cycle,run_international_cycle
    for name,fn in (("ETF",run_etf_cycle),("CIRCUIT",run_circuit_cycle),("INTERNATIONAL",run_international_cycle)):
        try:n+=int(fn() or 0)
        except Exception as exc:health(name.lower()+"_worker","WARN",str(exc)[:240])
    return n


def _ui_freshness(row_: Dict[str, Any], now: Optional[datetime]=None) -> Dict[str, Any]:
    """Label current-quote freshness without changing recommendation validity."""
    now=now or datetime.now(IST)
    raw=row_.get("updated_at")
    snapshot=row_.get("feature_snapshot") if isinstance(row_.get("feature_snapshot"),dict) else {}
    publication_asof=snapshot.get("asof")
    if not raw:
        return {"state":"INVALID","quote_asof":None,"age_seconds":None,"publication_data_asof":publication_asof}
    try:
        dt=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
        if dt.tzinfo is None:dt=dt.replace(tzinfo=IST)
        dt=dt.astimezone(IST);age=max(0.0,(now-dt).total_seconds())
    except Exception:
        return {"state":"INVALID","quote_asof":str(raw),"age_seconds":None,"publication_data_asof":publication_asof}
    state="FRESH" if age<=180 else ("AGING" if age<=900 else "STALE")
    return {"state":state,"quote_asof":dt.isoformat(timespec="seconds"),"age_seconds":round(age,1),
            "publication_data_asof":publication_asof}


def recommendations(book: str) -> Dict[str, Any]:
    target_ctx=_horizon_target_context(book) if book in ("WEEKLY","MONTHLY","ETF") else {"period_key":period_key(book),"target_now":datetime.now(IST),"preperiod":False}
    pk = str(target_ctx.get("period_key") or period_key(book))
    with db() as con:
        # International can be frozen for next week during the Friday-close/weekend window.
        # Prefer a live future/current frozen key instead of showing the just-finished week.
        if str(book).upper()=="INTERNATIONAL":
            rpk=con.execute("SELECT MAX(period_key) FROM recommendations WHERE book='INTERNATIONAL' AND state='LIVE'").fetchone()
            if rpk and rpk[0] and str(rpk[0])>=pk:pk=str(rpk[0])
        live = [dict(r) for r in con.execute("SELECT * FROM recommendations WHERE book=? AND period_key=? AND state='LIVE' ORDER BY side,score DESC", (book, pk)).fetchall()]
        # v6.6.0 lifecycle contract: every active page returns CLOSED rows only for
        # the same active period. Historical rows remain in the ledger and are exposed
        # explicitly through /api/history/recommendations and /api/performance.
        closed = [dict(r) for r in con.execute(
            "SELECT * FROM recommendations WHERE book=? AND period_key=? AND state='CLOSED' ORDER BY closed_at DESC LIMIT 100",
            (book,pk),
        ).fetchall()]

        # v6.5.1 defensive display guard. Publication itself is atomically protected,
        # but hide any legacy Weekly/Monthly collision until startup repair has run.
        if str(book).upper() in ("WEEKLY","MONTHLY"):
            other="MONTHLY" if str(book).upper()=="WEEKLY" else "WEEKLY"
            with db() as check_con:
                conflicts = check_con.execute(
                    "SELECT DISTINCT UPPER(symbol) FROM recommendations "
                    "WHERE book=? AND state='LIVE' AND COALESCE(result,'')<>'VOID'",
                    (other,),
                ).fetchall()
            if conflicts:
                bad={str(r[0]).upper() for r in conflicts}
                live=[x for x in live if str(x.get('symbol') or '').upper() not in bad]

    for arr in (live, closed):
        for d in arr:
            for k in ("strategy_ids_json", "rationale_json", "feature_snapshot_json"):
                try:
                    d[k[:-5]] = json.loads(d.pop(k) or ("[]" if "strategy" in k else "{}"))
                except Exception:
                    d[k[:-5]] = [] if "strategy" in k else {}
            if d.get("state")=="LIVE":
                d["freshness"]=_ui_freshness(d)
    frozen_books=("WEEKLY","MONTHLY","ETF","INTERNATIONAL","CIRCUIT_NEXTDAY","GLOBAL_INDIA_LONG","GLOBAL_INDIA_SHORT")
    dynamic_target_books=("INTERNATIONAL","CIRCUIT","CIRCUIT_NEXTDAY","GLOBAL_INDIA_LONG","GLOBAL_INDIA_SHORT")
    target_policy={
        "INTERNATIONAL":"FROZEN_US_WEEKLY_EXPECTED_NET_EDGE",
        "CIRCUIT":"VERIFIED_SAME_DAY_CIRCUIT_DISTANCE_BY_15_00_IST",
        "CIRCUIT_NEXTDAY":"PROJECTED_NEXT_SESSION_CIRCUIT_BAND_FROZEN_15_00_IST",
        "GLOBAL_INDIA_LONG":"GLOBAL_OVERNIGHT_TO_INDIA_DYNAMIC_TARGET",
        "GLOBAL_INDIA_SHORT":"GLOBAL_OVERNIGHT_TO_INDIA_DYNAMIC_TARGET",
    }.get(book)
    contract_required=_freeze_contract_min(book)
    contract_count=_freeze_contract_count(book,pk) if contract_required else None
    freeze_contract={
        "required":contract_required,
        "published_total":contract_count,
        "shortage":max(0,contract_required-contract_count) if contract_required else 0,
        "fulfilled":bool(contract_required and contract_count>=contract_required),
        "recovery_required":bool(contract_required and contract_count<contract_required),
        "policy":"FIVE_DATA_VALID_IDENTITIES_NO_STALE_OR_GATE_RELAXATION" if contract_required else None,
    } if contract_required else None
    policy = {
        "immutable_period_book": book in frozen_books,
        "no_rank_replacement": book in frozen_books,
        "no_backfill_after_close": True,
        "target_pct": None if book in dynamic_target_books else _pct_target(book, {}),
        "target_policy": target_policy,
        "target_is_admission_gate": book in ("WEEKLY", "MONTHLY", "ETF", "INTERNATIONAL", "CIRCUIT", "CIRCUIT_NEXTDAY", "GLOBAL_INDIA_LONG", "GLOBAL_INDIA_SHORT"),
        "target_is_not_guaranteed": True,
        "publication_window_ist": f"pre-period after prior close; first-session {HORIZON_FREEZE_START.strftime('%H:%M')}-{HORIZON_FREEZE_END.strftime('%H:%M')} (recovery until {HORIZON_RECOVERY_END.strftime('%H:%M')})" if book in ("WEEKLY", "MONTHLY", "ETF") else None,
        "remaining_sessions_estimate": _remaining_sessions(book,target_ctx.get("target_now")) if book in ("WEEKLY", "MONTHLY", "ETF") else None,
        "fewer_than_five_is_valid": True,
        "minimum_frozen_recommendations": contract_required or None,
        "forecast_lane": "3PM_NEXT_SESSION_UPPER_CIRCUIT_LONG_ONLY" if book=="CIRCUIT_NEXTDAY" else ("US_WEEKLY_FROZEN_LONG_ONLY" if book=="INTERNATIONAL" else ("GLOBAL_TO_INDIA_NEXT_SESSION" if book in ("GLOBAL_INDIA_LONG","GLOBAL_INDIA_SHORT") else None)),
        "policy_version": ("V649_STAGED_RECOVERY_PREPERIOD_FREEZE" if contract_required else ("V642_CIRCUIT_EVIDENCE_FAIL_CLOSED" if book in ("CIRCUIT","CIRCUIT_NEXTDAY") else "V632_MORNING_FREEZE_RECOVERY")),
        "recommendations_require_static_ip": False,
        "static_ip_scope": "ORDER_EXECUTION_ONLY",
        "international_session_policy": "US_WEEKLY_FROZEN_LONG_ONLY" if book == "INTERNATIONAL" else None,
        "international_side_policy": "LONG_ONLY" if book == "INTERNATIONAL" else None,
        "international_repriced_during_session": True if book == "INTERNATIONAL" else None,
        "international_session_end_closes_calls": False if book == "INTERNATIONAL" else None,
        "international_week_end_closes_calls": True if book == "INTERNATIONAL" else None,
        "international_no_replacement_after_close": True if book == "INTERNATIONAL" else None,
        "user_india_short_hard_exit_ist": "15:00" if book in ("INTRADAY","CIRCUIT","GLOBAL_INDIA_SHORT") else None,
        "india_horizon_side_policy": "LONG_ONLY_EXECUTABLE_BEARISH_RESEARCH_ONLY" if book in ("WEEKLY","MONTHLY","ETF") else None,
        "horizon_short_execution_supported": False if book in ("WEEKLY","MONTHLY","ETF") else None,
        "circuit_nextday_freeze_ist": "15:00" if book in ("CIRCUIT","CIRCUIT_NEXTDAY") else None,
    }
    scan_detail = get_state(f"scan_detail_{book}", {}) if book in ("INTRADAY","WEEKLY","MONTHLY","ETF") else {}
    preview = list((scan_detail or {}).get("near_misses") or [])[:12]
    if book in ("WEEKLY","MONTHLY","ETF"):
        try:
            with db() as con:
                bearish = con.execute(
                    "SELECT symbol,avg_score,payload_json FROM candidate_observations "
                    "WHERE book=? AND period_key=? AND side='SHORT' ORDER BY avg_score DESC LIMIT 12",
                    (book, pk),
                ).fetchall()
            seen={(str(x.get("symbol")),str(x.get("side")),str(x.get("stage"))) for x in preview if isinstance(x,dict)}
            for row in bearish:
                item={"symbol":row["symbol"],"side":"SHORT","stage":"BEARISH_RESEARCH_ONLY",
                      "score":round(float(row["avg_score"] or 0),2),
                      "detail":"Multi-session Indian SHORT is non-executable; use same-day short lanes only."}
                key=(item["symbol"],item["side"],item["stage"])
                if key not in seen:
                    preview.append(item);seen.add(key)
                if len(preview)>=12:break
        except Exception:
            pass
    return {
        "book": book,
        "period_key": pk,
        "live": {"long": [x for x in live if x["side"] == "LONG"], "short": [x for x in live if x["side"] == "SHORT"]},
        "closed": closed,
        "fixed_notional": 20000,
        "policy": policy,
        "freeze_contract": freeze_contract,
        "target_period": target_ctx if book in ("WEEKLY","MONTHLY","ETF") else None,
        "research_preview": preview,
        "scan_detail": scan_detail,
    }


class Engine:
    def __init__(self):
        self.stop_evt=threading.Event();self.thread=None;self.last_error="";self.workers={};self.worker_specs={}
        self.worker_runtime={};self.worker_restarts={}

    def start(self):
        if self.thread and self.thread.is_alive():return
        reset_transient_scan_states()
        try:
            _repair_weekly_monthly_collisions()
        except Exception as exc:
            health("horizon_collision","ERROR",f"startup repair failed: {str(exc)[:180]}")
        self.stop_evt.clear();self.thread=threading.Thread(target=self._supervise,name="psq-supervisor",daemon=True);self.thread.start()

    def stop(self):
        self.stop_evt.set()

    def _worker_timeout_seconds(self,name,interval):
        explicit={"international":120.0,"broker_probe":90.0,"live_update":180.0,"market_snapshot":240.0,
                  "intraday":900.0,"weekly":1200.0,"monthly":1200.0,"etf":900.0,
                  "circuit":600.0,"circuit_nextday":300.0,"global_india":600.0,
                  # Low-priority maintenance legitimately performs a paced multi-request
                  # history hydration batch; 360s was below its existing transport envelope.
                  "maintenance":900.0}
        return float(explicit.get(name,max(300.0,float(interval)*4.0)))

    def worker_status(self):
        now=datetime.now(IST);out={}
        # Read scan progress in one short WAL read. Failure is fail-soft so /api/health
        # cannot hang behind many independent state lookups.
        scan_cache={}
        worker_book={"intraday":"INTRADAY","weekly":"WEEKLY","monthly":"MONTHLY","etf":"ETF",
                     "circuit":"CIRCUIT","circuit_nextday":"CIRCUIT_NEXTDAY","international":"INTERNATIONAL"}
        keys=[f"scan_detail_{b}" for b in worker_book.values()]+[f"scan_status_{b}" for b in worker_book.values()]
        try:
            qs=",".join("?" for _ in keys)
            with db(timeout_seconds=.5) as con:
                for row_ in con.execute(f"SELECT key,value_json FROM system_state WHERE key IN ({qs})",tuple(keys)).fetchall():
                    try:scan_cache[str(row_[0])]=json.loads(row_[1] or "{}")
                    except Exception:pass
        except Exception:
            scan_cache={}
        for name,t in self.workers.items():
            spec=self.worker_specs.get(name,(300,None));interval=float(spec[0]);timeout=self._worker_timeout_seconds(name,interval)
            state=dict(self.worker_runtime.get(name) or {})
            started=state.get("started_at");elapsed=None
            if state.get("state")=="RUNNING" and started:
                try:
                    s=datetime.fromisoformat(str(started));s=s if s.tzinfo else s.replace(tzinfo=IST);elapsed=max(0.0,(now-s).total_seconds())
                except Exception:elapsed=None
            b=worker_book.get(name);detail=scan_cache.get(f"scan_detail_{b}",{}) if b else {};scan=scan_cache.get(f"scan_status_{b}",{}) if b else {}
            processed=detail.get("processed",scan.get("processed"));universe=detail.get("universe",scan.get("universe"))
            remaining=max(0,int(universe)-int(processed)) if isinstance(universe,(int,float)) and isinstance(processed,(int,float)) else None
            out[name]={**state,"alive":bool(t.is_alive()),"thread":t.name,"timeout_seconds":timeout,
                       "elapsed_seconds":round(elapsed,2) if elapsed is not None else state.get("duration_seconds"),
                       "hung":bool(t.is_alive() and state.get("state")=="RUNNING" and elapsed is not None and elapsed>timeout),
                       "current_stage":detail.get("stage") or scan.get("status") or state.get("state"),
                       "processed":processed,"remaining":remaining,
                       "rejection_counters":(detail.get("funnel") or {}),
                       "recovery_state":scan.get("contract") or scan.get("recovery_policy"),
                       "restart_count":int(self.worker_restarts.get(name,0))}
        return out

    def worker_status_cached(self):
        """Pure in-memory worker liveness for passive health/sanity endpoints.

        Detailed /api/workers telemetry may read scan state from SQLite. Passive health
        paths must not open that second connection or wait behind worker telemetry writes.
        """
        now=datetime.now(IST);out={}
        for name,t in self.workers.items():
            spec=self.worker_specs.get(name,(300,None));interval=float(spec[0]);timeout=self._worker_timeout_seconds(name,interval)
            state=dict(self.worker_runtime.get(name) or {})
            started=state.get("started_at");elapsed=None
            if state.get("state")=="RUNNING" and started:
                try:
                    s=datetime.fromisoformat(str(started));s=s if s.tzinfo else s.replace(tzinfo=IST)
                    elapsed=max(0.0,(now-s).total_seconds())
                except Exception:elapsed=None
            out[name]={**state,"alive":bool(t.is_alive()),"thread":t.name,"timeout_seconds":timeout,
                       "elapsed_seconds":round(elapsed,2) if elapsed is not None else state.get("duration_seconds"),
                       "hung":bool(t.is_alive() and state.get("state")=="RUNNING" and elapsed is not None and elapsed>timeout),
                       "current_stage":state.get("state"),"processed":None,"remaining":None,
                       "rejection_counters":{},"recovery_state":None,
                       "restart_count":int(self.worker_restarts.get(name,0)),"passive_cached":True}
        return out

    def _worker(self,name,interval,func,initial_delay=0):
        if self.stop_evt.wait(initial_delay):return
        while not self.stop_evt.is_set():
            started=time.monotonic();started_at=now_iso()
            previous=dict(self.worker_runtime.get(name) or {})
            running={"state":"RUNNING","started_at":started_at,"last_ok_at":previous.get("last_ok_at"),
                     "last_error":previous.get("last_error")}
            self.worker_runtime[name]=running
            set_state(f"worker_{name}",running)
            try:
                func()
                self.last_error=""
                state={"state":"IDLE","started_at":started_at,"last_ok_at":now_iso(),"duration_seconds":round(time.monotonic()-started,2),"last_error":None}
            except Exception as exc:
                self.last_error=f"{name}: {str(exc)[:260]}"
                health(name,"ERROR",str(exc)[:240])
                state={"state":"ERROR","started_at":started_at,"last_ok_at":previous.get("last_ok_at"),
                       "last_error":str(exc)[:240],"at":now_iso(),"duration_seconds":round(time.monotonic()-started,2)}
            self.worker_runtime[name]=state
            # set_state is fail-soft; telemetry contention cannot terminate this loop.
            set_state(f"worker_{name}",state)
            wait=max(1.0,float(interval)-(time.monotonic()-started))
            if self.stop_evt.wait(wait):return

    def _spawn_worker(self,name,interval,func,initial_delay=0):
        t=threading.Thread(target=self._worker,args=(name,interval,func,initial_delay),name=f"psq-{name}",daemon=True)
        self.workers[name]=t
        t.start()
        return t

    def _maintenance(self):
        settings=load_settings()
        # Low-priority universe rotation. Scanners never wait for this worker.
        bootstrap_history(int(settings.get("history_bootstrap_cycle_batch",4)))
        warm_intraday_history(int(settings.get("intraday_history_warm_batch",24)))

    def _daily_history(self):
        settings=load_settings()
        warm_daily_history(int(settings.get("daily_history_warm_batch",20)))

    def _market_snapshot(self):
        # Full-market batched LTP refresh. Groww supports 50 instruments per LTP request;
        # broker.ltp handles batching. No stock is removed for size/liquidity reasons.
        syms=full_nse_symbols();prices=refresh_live_price_cache(syms) if syms else {}
        breadth=full_breadth_discovery_snapshot(prices)
        state=classify(prices=prices,allow_network_prices=False)
        set_state("market_snapshot_status",{"at":now_iso(),"symbols":len(syms),"prices":len(prices),
            "breadth_evaluated":breadth.get("evaluated",0),"regime":state.get("regime"),
            "policy":"FULL_NSE_BATCHED_LTP_ALL_EQUITIES_SCANNERS_READ_CACHE"})
        fabric_publish("full_market_quotes",source="GROWW_BATCHED_LTP",consumers=("INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","GLOBAL_INDIA","LIVE_UPDATE"),payload={"prices":len(prices),"universe":len(syms)},network_fetch=True,symbols=len(prices))
        fabric_publish("market_regime",source="FULL_NSE_CACHED_BREADTH",consumers=("INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","GLOBAL_INDIA"),payload={"regime":state.get("regime"),"sample":state.get("sample")},network_fetch=False,symbols=state.get("sample"))

    def _universe_refresh(self):
        # Pick up same-day/new listings from Groww's authoritative instrument master.
        refresh_instruments(force=True);refresh_universe(force=True)

    def _global_context_refresh(self):
        out=global_snapshot(force=True)
        fabric_publish("global_context",source="BATCHED_GLOBAL_CROSS_ASSET",consumers=("INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","INTERNATIONAL","GLOBAL_INDIA"),payload={"coverage":out.get("coverage"),"risk_state":out.get("risk_state")},network_fetch=True,symbols=out.get("coverage"))

    def _fundamentals_refresh(self):
        from .fundamentals import refresh_batch
        settings=load_settings();syms=full_nse_symbols();u=get_state("universe_status",{}) or {};b=get_state("full_breadth_discovery",{}) or {}
        priority=[]
        for s in list(u.get("new_since_last_refresh") or [])+[x.get("symbol") for x in (b.get("top_absolute_movers") or [])]+syms:
            s=str(s or '').upper()
            if s and s in syms and s not in priority:priority.append(s)
        out=refresh_batch(priority,max(12,int(settings.get("fundamentals_refresh_batch",12))))
        fabric_publish("fundamentals",source="POINT_IN_TIME_FUNDAMENTAL_BATCH",consumers=("WEEKLY","MONTHLY","STRATEGY_LAB","ALGORITHM"),payload=out,network_fetch=True,symbols=out.get("attempted"))

    def _sector_context_refresh(self):
        from .sector_context import build_snapshot
        out=build_snapshot(ttl_seconds=600)
        fabric_publish("sector_context",source="CACHED_DAILY_INDUSTRY_BREADTH",consumers=("INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","ALGORITHM"),payload={"industries_ready":len(out)},network_fetch=False)

    def _priority_quote_refresh(self):
        syms=fabric_priority_symbols(160)
        prices=refresh_live_price_cache(syms) if syms else {}
        fabric_publish("priority_quotes",source="GROWW_PRIORITY_LTP",consumers=("LIVE_UPDATE","INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","ORDER_PREVIEW"),payload={"prices":len(prices),"requested":len(syms)},network_fetch=bool(syms),symbols=len(prices))

    def _news_refresh(self):
        from .news_context import refresh_batch
        syms=fabric_priority_symbols(24)
        out=refresh_batch(syms,limit=12)
        fabric_publish("news",source="YFINANCE_AGGREGATED_NEWS_PRIORITY_BATCH",consumers=("INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","ALGORITHM"),payload=out,network_fetch=bool(out.get("attempted")),symbols=out.get("attempted"))

    def _event_refresh(self):
        syms=fabric_priority_symbols(12)
        attempted=events=0
        for sym in syms[:4]:
            attempted+=1
            r=refresh_symbol_event(sym)
            events+=int(r.get("events") or 0)
        out={"attempted":attempted,"events":events,"at":now_iso()}
        fabric_publish("events",source="POINT_IN_TIME_EARNINGS_AND_OFFICIAL_CALENDAR",consumers=("INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","ALGORITHM"),payload=out,network_fetch=bool(attempted),symbols=attempted)

    def _institutional_refresh(self):
        out=institutional_refresh(force=True)
        fabric_publish("institutional",source="NSE_FII_DII_LARGE_DEALS_PLUS_LOCAL_ACCUMULATION",consumers=("INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","GLOBAL_INDIA","ALGORITHM","STRATEGY_LAB"),payload={"status":out.get("status"),"large_deal_count":out.get("large_deal_count"),"errors":out.get("errors")},network_fetch=True,symbols=out.get("large_deal_count"))

    def _algorithm_refresh(self):
        from .trading_algorithm import refresh as refresh_algorithm
        out=refresh_algorithm()
        fabric_publish("algorithm",source="VALIDATED_CHAMPION_MANIFEST_PLUS_LIVE_BOOKS",consumers=("ALGORITHM_UI","AUDIT"),payload={"algorithm_version":out.get("algorithm_version"),"active_strategy_count":out.get("active_strategy_count"),"accuracy":(out.get("accuracy") or {}).get("overall")},network_fetch=False)

    def _broker_probe(self):
        # Populate the cached broker status without coupling research to execution readiness.
        # This is a read-only Groww profile/authentication probe.
        broker.status()
        broker.static_ip_status()

    def _live_update(self):
        update_live_books()
        try:
            from .specialized import update_international_books
            update_international_books()
        except Exception as exc:health("international_update","WARN",str(exc)[:220])

    def _etf(self):
        from .specialized import run_etf_cycle
        run_etf_cycle()

    def _circuit(self):
        from .specialized import run_circuit_cycle
        run_circuit_cycle()

    def _circuit_nextday(self):
        from .specialized import run_circuit_nextday_cycle
        run_circuit_nextday_cycle()

    def _global_india(self):
        from .cross_market import run_global_india_cycle
        run_global_india_cycle()

    def _international(self):
        from .specialized import run_international_cycle
        run_international_cycle()

    def _execution_integrity(self):
        from .orders import reconcile_orders
        from .execution_integrity import reconcile_positions
        status=broker.status_cached()
        if not status.get("connected"):
            set_state("execution_integrity_worker",{"at":now_iso(),"status":"WAITING_FOR_GROWW_CONNECTION"})
            return
        orders=reconcile_orders();positions=reconcile_positions()
        set_state("execution_integrity_worker",{"at":now_iso(),"status":"OK" if positions.get("verified") and not positions.get("hard_block") else "HALT",
            "orders":orders,"positions":positions})

    def _backup_integrity(self):
        maybe_daily_backup()

    def _strategy(self):
        try:
            from .strategy_lab import maybe_weekly_jobs,run_shadow_cycle,resolve_shadow_signals
            resolve_shadow_signals();run_shadow_cycle();maybe_weekly_jobs()
            self._algorithm_refresh()
        except Exception as exc:health("strategy_lab","WARN",str(exc)[:220])

    def _supervise(self):
        try:
            refresh_instruments();refresh_universe();seed_library();seed_official_calendar();seed_release_experiment()
        except Exception as exc:
            self.last_error=str(exc)[:300];health("bootstrap","ERROR",self.last_error)
        settings=load_settings()
        specs=[
            ("broker_probe",float(settings.get("broker_probe_interval_seconds",300)),self._broker_probe,1),
            ("execution_integrity",float(settings.get("execution_integrity_worker_interval_seconds",120)),self._execution_integrity,6),
            ("backup_integrity",float(settings.get("backup_worker_interval_seconds",3600)),self._backup_integrity,120),
            ("universe_refresh",float(settings.get("universe_refresh_interval_seconds",1800)),self._universe_refresh,2),
            ("market_snapshot",float(settings.get("full_breadth_ltp_interval_seconds",180)),self._market_snapshot,3),
            ("priority_quotes",float(settings.get("live_update_interval_seconds",60)),self._priority_quote_refresh,3),
            ("live_update",float(settings.get("live_update_interval_seconds",60)),self._live_update,4),
            ("intraday",float(settings.get("intraday_worker_interval_seconds",120)),run_intraday_cycle,5),
            ("maintenance",float(settings.get("maintenance_worker_interval_seconds",90)),self._maintenance,8),
            ("daily_history",float(settings.get("daily_history_worker_interval_seconds",90)),self._daily_history,9),
            ("weekly",float(settings.get("horizon_worker_interval_seconds",300)),lambda:run_single_horizon_cycle("WEEKLY"),10),
            ("monthly",float(settings.get("horizon_worker_interval_seconds",300)),lambda:run_single_horizon_cycle("MONTHLY"),12),
            ("circuit",float(settings.get("circuit_worker_interval_seconds",120)),self._circuit,14),
            ("circuit_nextday",float(settings.get("circuit_nextday_worker_interval_seconds",60)),self._circuit_nextday,15),
            ("international",float(settings.get("international_worker_interval_seconds",120)),self._international,16),
            ("global_india",float(settings.get("global_india_worker_interval_seconds",300)),self._global_india,17),
            ("etf",float(settings.get("etf_worker_interval_seconds",600)),self._etf,18),
            ("fundamentals",float(settings.get("fundamentals_worker_interval_seconds",60)),self._fundamentals_refresh,20),
            ("news",float(settings.get("news_worker_interval_seconds",120)),self._news_refresh,21),
            ("events",float(settings.get("event_worker_interval_seconds",300)),self._event_refresh,22),
            ("institutional",float(settings.get("institutional_worker_interval_seconds",300)),self._institutional_refresh,23),
            ("sector_context",float(settings.get("sector_context_interval_seconds",900)),self._sector_context_refresh,24),
            ("global_context",float(settings.get("global_context_interval_seconds",900)),self._global_context_refresh,28),
            ("algorithm",float(settings.get("algorithm_worker_interval_seconds",300)),self._algorithm_refresh,35),
            ("strategy",float(settings.get("strategy_worker_interval_seconds",600)),self._strategy,90),
        ]
        self.worker_specs={name:(interval,fn) for name,interval,fn,delay in specs}
        for name,interval,fn,delay in specs:
            self._spawn_worker(name,interval,fn,delay)
        set_state("scheduler_v624",{"mode":"SHARED_EVIDENCE_PRODUCERS_PLUS_INDEPENDENT_SCANNER_CONSUMERS_WITH_WATCHDOG","workers":[x[0] for x in specs],"started_at":now_iso(),"watchdog":"RESPAWN_DEAD_DOMAIN_WORKERS"})
        while not self.stop_evt.wait(5):
            # A domain thread can still die because of interpreter/library failures that
            # occur outside normal cycle handling. Never leave an entire scanner lane
            # dead for the rest of the trading day.
            for name,(interval,fn) in list(self.worker_specs.items()):
                t=self.workers.get(name)
                if t is not None and t.is_alive():
                    continue
                self.worker_restarts[name]=int(self.worker_restarts.get(name,0))+1
                health("worker_watchdog","WARN",f"respawning dead worker {name}",
                       {"restart_count":self.worker_restarts[name],"persistent_failure":self.worker_restarts[name]>=3})
                restart={"state":"RESTARTING","at":now_iso(),"reason":"THREAD_NOT_ALIVE","restart_count":self.worker_restarts[name]}
                self.worker_runtime[name]=restart;set_state(f"worker_{name}",restart)
                self._spawn_worker(name,interval,fn,1)


engine = Engine()
