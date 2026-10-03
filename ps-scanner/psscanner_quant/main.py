from __future__ import annotations
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .broker import broker
from .config import load_settings, update_settings
from .constants import APP_NAME, VERSION, IST, MARKET_OPEN, MARKET_CLOSE, TRADE_NOTIONAL_RUPEES, MAX_RUPEE_RISK_PER_TRADE, BOOKS
from .db import db, get_state, init_db, now_iso
from .engine import engine, recommendations, period_key
from .analytics import history_rows as recommendation_history_rows, performance as performance_stats
from .lifecycle import lifecycle_payload
from .orders import create_preview, execute_preview, execution_readiness, execution_readiness_cached_snapshot, recent_orders, reconcile_orders, recent_fills
from .paths import STATIC
from .regime import classify
from .strategy_library import seed_library
from .strategy_lab import status as strategy_status, discover_new_strategies, validate_strategies, monitor_strategy_decay, run_shadow_cycle, resolve_shadow_signals
from .handbook import status as handbook_status, strategy_catalog, candlestick_catalog, filter_catalog
from .portfolio_risk import risk_summary
from .global_context import snapshot as global_snapshot
from .fundamentals import snapshot_status as fundamental_snapshot_status
from .trading_calendar import status as trading_calendar_status, is_regular_trading_day
from .sector_context import status as sector_status, status_cached as sector_status_cached
from .event_calendar import status as event_calendar_status
from .history_control import status as history_control_status, status_cached as history_control_status_cached
from .execution_integrity import execution_analytics, reconcile_positions, cached_position_reconciliation
from .production_integrity import (
    no_trade_diagnostics, replay_decisions, backup_status, backup_database,
    experiments as experiment_rows, register_experiment,
)
from .data import liquidity_rank, cached_history_coverage, full_nse_symbols, universe_status
from .cross_market import board_payload as global_india_board_payload
from .evidence_fabric import status as evidence_fabric_status
from .institutional_intelligence import cached_status as institutional_status, point_in_time_history as institutional_history
from .trading_algorithm import status as algorithm_status, history as algorithm_history

app=FastAPI(title=APP_NAME,version=VERSION)

@app.middleware("http")
async def _disable_runtime_cache(request, call_next):
    response=await call_next(request)
    if request.url.path.startswith("/api/") or request.url.path=="/":
        response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"]="no-cache"
    return response

class SettingsPatch(BaseModel):
    expected_static_ip: Optional[str]=None
    manual_execution_enabled: Optional[bool]=None
    execution_slippage_reserve_bps: Optional[float]=None
    execution_min_net_edge_rupees: Optional[float]=None

@app.on_event("startup")
def _startup():
    init_db();seed_library();engine.start()

@app.on_event("shutdown")
def _shutdown():engine.stop()

@app.get("/")
def index():return FileResponse(STATIC/"index.html")

@app.get("/api/ping")
def ping():
    return {"ok": True, "app": APP_NAME, "version": VERSION, "at": now_iso()}

def _cached_states(keys, timeout_seconds:float=.25):
    """Read several system_state keys in one bounded WAL snapshot."""
    out={}
    keys=list(dict.fromkeys(str(k) for k in keys if k))
    if not keys:return out
    try:
        marks=",".join("?" for _ in keys)
        with db(timeout_seconds=timeout_seconds) as con:
            rows=con.execute(f"SELECT key,value_json FROM system_state WHERE key IN ({marks})",tuple(keys)).fetchall()
        for r in rows:
            try:out[str(r[0])]=json.loads(r[1] or "{}")
            except Exception:out[str(r[0])]={}
    except Exception:
        return {}
    return out


def _bounded_evidence_db(timeout_seconds:float=.25):
    fundamentals={"status":"BOUNDED_SNAPSHOT_UNAVAILABLE","mode":"PROSPECTIVE_POINT_IN_TIME_CAPTURE"}
    events={"status":"BOUNDED_SNAPSHOT_UNAVAILABLE","policy":"Only persisted timestamped events are used. Missing macro data remains UNKNOWN rather than assumed safe."}
    try:
        with db(timeout_seconds=timeout_seconds) as con:
            f=con.execute("SELECT COUNT(*),COUNT(DISTINCT symbol),MIN(asof),MAX(asof) FROM fundamental_snapshots").fetchone()
            e=con.execute("SELECT COUNT(*),SUM(CASE WHEN starts_at>=? THEN 1 ELSE 0 END) FROM market_events",(now_iso(),)).fetchone()
        fundamentals={
            "snapshots":int(f[0] or 0),"symbols":int(f[1] or 0),"first_asof":f[2],"last_asof":f[3],
            "mode":"PROSPECTIVE_POINT_IN_TIME_CAPTURE","bounded":True,
            "historical_backtest_policy":"Only snapshots captured by the decision timestamp are eligible; current fundamentals are never backfilled into the past.",
        }
        events={
            "total_events":int(e[0] or 0),"future_events":int(e[1] or 0),"bounded":True,
            "policy":"Only persisted timestamped events are used. Missing macro data remains UNKNOWN rather than assumed safe.",
        }
    except Exception as exc:
        fundamentals["detail"]=str(exc)[:120];events["detail"]=str(exc)[:120]
    return fundamentals,events


def _cached_universe_health(state):
    u=dict(state.get("universe_status") or {})
    breadth=dict(state.get("full_breadth_discovery") or {})
    daily=dict(state.get("daily_history_warm_status") or {})
    intra=dict(state.get("last_intraday_history_warm") or {})
    ltp=dict(state.get("live_price_cache_status") or {})
    current_n=int(u.get("n") or 0);breadth_n=int(breadth.get("universe") or 0)
    current=bool(current_n and breadth_n==current_n and breadth.get("status")!="STALE_UNIVERSE")
    if current:
        daily_ready=breadth.get("daily_history_ready");intraday_ready=breadth.get("intraday_history_ready")
        live_ready=breadth.get("live_prices");evaluated=breadth.get("evaluated");limited=breadth.get("new_or_limited_history")
        breadth_at=breadth.get("at");breadth_status="CURRENT"
    else:
        daily_ready=((daily.get("coverage") or {}).get("ready"));intraday_ready=intra.get("ready")
        live_ready=None;evaluated=None;limited=None;breadth_at=None;breadth_status="AWAITING_CURRENT_UNIVERSE_PASS"
    return {**u,
        "daily_ready":daily_ready,"intraday_ready":intraday_ready,"live_prices_ready":live_ready,
        "breadth_evaluated":evaluated,"new_or_limited_history":limited,"last_breadth_scan_at":breadth_at,
        "breadth_status":breadth_status,"live_price_refresh":ltp,
        "scan_policy":"FULL_BREADTH_DISCOVERY_NO_TOP_N_UNIVERSE_CAP","cached":True,
    }


@app.get("/api/groww/status")
def groww_status(refresh: bool=False):
    """Read-only Groww connectivity status. refresh=true performs an explicit broker probe.

    This endpoint never checks or gates on Static IP; Static IP is an order-execution control.
    """
    return broker.status() if refresh else broker.status_cached()

@app.get("/api/health")
def health():
    started=time.monotonic();now=datetime.now(IST);today=now.date().isoformat()
    market=is_regular_trading_day(now.date()) and MARKET_OPEN<=now.time().replace(tzinfo=None)<=MARKET_CLOSE
    recent=[];recs=[];decisions=[];state={};order_count=None;db_error=None
    fundamentals={"status":"BOUNDED_SNAPSHOT_UNAVAILABLE","mode":"PROSPECTIVE_POINT_IN_TIME_CAPTURE"}
    events={"status":"BOUNDED_SNAPSHOT_UNAVAILABLE","policy":"Only persisted timestamped events are used. Missing macro data remains UNKNOWN rather than assumed safe."}
    state_keys=["last_regime","global_context","last_research_cycle","universe_status","full_breadth_discovery",
                "daily_history_warm_status","last_intraday_history_warm","live_price_cache_status",
                "position_reconciliation","last_verified_backup"]+["scan_status_"+b for b in BOOKS]
    try:
        with db(timeout_seconds=.20) as con:
            deadline=time.monotonic()+1.0
            con.set_progress_handler(lambda: 1 if time.monotonic()>deadline else 0,1000)
            # Execution-critical cached fields come first. If optional telemetry later
            # exhausts the passive budget, health still retains truthful fail-closed
            # order-count and position-reconciliation state.
            order_count=int(con.execute(
                "SELECT COUNT(*) FROM orders WHERE substr(created_at,1,10)=? AND state NOT IN ('FAILED','CANCELLED')",(today,)
            ).fetchone()[0])
            marks=",".join("?" for _ in state_keys)
            for row in con.execute(f"SELECT key,value_json FROM system_state WHERE key IN ({marks})",tuple(state_keys)).fetchall():
                try:state[str(row[0])]=json.loads(row[1] or "{}")
                except Exception:state[str(row[0])]={}
            recent=[dict(r) for r in con.execute("SELECT ts,component,level,message FROM health_events ORDER BY id DESC LIMIT 30").fetchall()]
            recs=con.execute("SELECT book,state,COUNT(*) n FROM recommendations GROUP BY book,state").fetchall()
            decisions=con.execute("SELECT decision,COUNT(*) FROM trade_decisions WHERE ts>=datetime('now','-1 day') GROUP BY decision").fetchall()
            f=con.execute("SELECT COUNT(*),COUNT(DISTINCT symbol),MIN(asof),MAX(asof) FROM fundamental_snapshots").fetchone()
            e=con.execute("SELECT COUNT(*),SUM(CASE WHEN starts_at>=? THEN 1 ELSE 0 END) FROM market_events",(now_iso(),)).fetchone()
            fundamentals={
                "snapshots":int(f[0] or 0),"symbols":int(f[1] or 0),"first_asof":f[2],"last_asof":f[3],
                "mode":"PROSPECTIVE_POINT_IN_TIME_CAPTURE","bounded":True,
                "historical_backtest_policy":"Only snapshots captured by the decision timestamp are eligible; current fundamentals are never backfilled into the past.",
            }
            events={
                "total_events":int(e[0] or 0),"future_events":int(e[1] or 0),"bounded":True,
                "policy":"Only persisted timestamped events are used. Missing macro data remains UNKNOWN rather than assumed safe.",
            }
    except Exception as exc:
        db_error=str(exc)[:160]
        if not recent:recent=[{"ts":now_iso(),"component":"health","level":"WARN","message":"bounded DB snapshot unavailable: "+db_error}]
    history_cached=history_control_status_cached()
    execution_cached=execution_readiness_cached_snapshot(order_count,state.get("position_reconciliation") or {})
    workers=engine.worker_status_cached()
    evidence={
        "fundamentals":fundamentals,
        "trading_calendar":trading_calendar_status(),
        "sector_breadth":sector_status_cached(),
        "event_calendar":events,
        "history_control":history_cached,
        "nse_universe":_cached_universe_health(state),
    }
    return {"app":APP_NAME,"version":VERSION,
        "architecture_patch":{"version":"6.8.0","name":"SHARED_EVIDENCE_FABRIC_AND_ADAPTIVE_TRADING_ALGORITHM",
            "current_period_ui":True,"history_performance_api":True,"family_diversity_advisory":True,
            "database_horizon_exclusivity_trigger":True,"late_horizon_recovery":True,"worker_hung_telemetry":True,
            "dynamic_mis_permission":True,"broker_position_reconciliation":True,"decision_to_fill_attribution":True,
            "point_in_time_audit_envelope":True,"production_contract_replay":True,"verified_database_backups":True,
            "experiment_governance":True,"evidence_gated_cohorts":True,"nonblocking_health":True,
            "shared_evidence_fabric":True,"institutional_intelligence":True,"adaptive_algorithm":True,
            "accuracy_target_is_evidence_gated_not_guaranteed":True},
        "reliability_patch":{"version":"6.4.9","name":"RECOVERY_EXECUTION_AND_PREPERIOD_FREEZE","five_pick_contract_books":["WEEKLY","MONTHLY","ETF","INTERNATIONAL"],
            "worker_watchdog":True,"staged_recovery":True,"preperiod_freeze":True,"intraday_bootstrap":True,"bounded_international_transport":True},
        "health_reliability_patch":{"version":"6.7.1","name":"NONBLOCKING_HEALTH_AND_VALIDATION","health_network_calls":False,
            "health_waits_for_history_pacer":False,"bounded_health_db_reads":True},
        "sanity_reliability_patch":{"version":"6.7.2","name":"BOUNDED_RUNTIME_SANITY_AND_BACKUP_RESTORE_DEEP_CHECK",
            "inline_quick_check":False,"runtime_query_budget_seconds":1.5,"deep_verification":"SQLITE_BACKUP_RESTORE_QUICK_CHECK"},
        "execution_cache_patch":{"version":"6.7.3","background_static_ip_probe":True,"public_ip_fallback":True,
            "health_single_db_snapshot":True,"position_mismatch_fail_closed":True},
        "performance_reliability_patch":{"version":"6.8.1","name":"BOUNDED_PERFORMANCE_ANALYTICS",
            "api_db_timeout_seconds":.5,"api_query_budget_seconds":2.5,"network_calls":False,
            "single_snapshot":True,"narrow_projection":True,"deep_learning_uses_passive_budget":False},
        "orchestration_patch":{"version":"6.8.0","policy":"V680_ONE_OBSERVATION_MANY_CONSUMERS",
            "scanner_frequency_reduced":False,"shared_priority_quotes":True,"shared_news":True,
            "shared_events":True,"shared_institutional":True,"shared_international_transport":True},
        "generated_at":now_iso(),"market_open":market,"engine_alive":bool(engine.thread and engine.thread.is_alive()),"engine_last_error":engine.last_error,
        "workers":workers,"groww":broker.status_cached(),"static_ip":broker.static_ip_status_cached(),
        "research":{"recommendations_require_static_ip":False,"static_ip_scope":"ORDER_EXECUTION_ONLY","status":"ACTIVE" if bool(engine.thread and engine.thread.is_alive()) else "ENGINE_STOPPED"},
        "execution":execution_cached,
        "execution_integrity":{"positions":state.get("position_reconciliation") or {},"backup":state.get("last_verified_backup") or {}},
        "regime":state.get("last_regime",{}),"global_context":state.get("global_context",{}),
        "last_research_cycle":state.get("last_research_cycle",{}),"scan_status":{b:state.get("scan_status_"+b,{}) for b in BOOKS},
        "evidence":evidence,
        "recommendation_counts":[{"book":r[0],"state":r[1],"n":r[2]} for r in recs],"decision_counts_24h":{r[0]:r[1] for r in decisions},
        "recent_health_events":recent,
        "health_contract":{"passive":True,"network_calls":False,"history_pacer_nonblocking":True,
            "db_connections":1,"db_snapshot_error":db_error,"db_wall_clock_budget_seconds":1.0,
            "execution_snapshot_available":order_count is not None,
            "elapsed_ms":round((time.monotonic()-started)*1000.0,1)}}


@app.get("/api/sanity")
def sanity():
    """Fast bounded runtime integrity check; deep SQLite verification is backup-based."""
    started=time.monotonic();now=datetime.now(IST);today=now.date().isoformat()
    collisions=[];counts=[];old_intraday=old_circuit=0;missing_levels=0;duplicates=[];stale_session_live=0
    runtime_db="ERROR";runtime_complete=False;runtime_error=None
    try:
        with db(timeout_seconds=.25) as con:
            deadline=time.monotonic()+1.5
            con.set_progress_handler(lambda: 1 if time.monotonic()>deadline else 0,1000)
            con.execute("SELECT 1").fetchone()
            collisions=[dict(r) for r in con.execute(
                "SELECT w.symbol symbol,w.period_key weekly_period,w.state weekly_state,"
                "m.period_key monthly_period,m.state monthly_state "
                "FROM recommendations w JOIN recommendations m ON w.symbol=m.symbol "
                "WHERE w.book='WEEKLY' AND m.book='MONTHLY' "
                "AND COALESCE(w.result,'')<>'VOID' AND COALESCE(m.result,'')<>'VOID' "
                "AND date(w.period_key)<=date(m.period_key||'-01','+1 month','-1 day') "
                "AND date(m.period_key||'-01')<=date(w.period_key,'+6 day') "
                "AND date(w.period_key,'+6 day')>=date(?) "
                "AND date(m.period_key||'-01','+1 month','-1 day')>=date(?) "
                "ORDER BY symbol,w.period_key,m.period_key",(today,today)
            ).fetchall()]
            old_intraday=int(con.execute("SELECT COUNT(*) FROM recommendations WHERE book='INTRADAY' AND state='LIVE' AND period_key<>?",(today,)).fetchone()[0])
            old_circuit=int(con.execute("SELECT COUNT(*) FROM recommendations WHERE book='CIRCUIT' AND state='LIVE' AND period_key<>?",(today,)).fetchone()[0])
            missing_levels=int(con.execute("SELECT COUNT(*) FROM recommendations WHERE state='LIVE' AND (target_price IS NULL OR stop_price IS NULL OR entry_price<=0)").fetchone()[0])
            duplicates=[dict(r) for r in con.execute(
                "SELECT book,period_key,symbol,side,COUNT(*) n FROM recommendations "
                "WHERE state='LIVE' GROUP BY book,period_key,symbol,side HAVING COUNT(*)>1"
            ).fetchall()]
            if is_regular_trading_day(now.date()) and MARKET_OPEN<=now.time().replace(tzinfo=None)<=MARKET_CLOSE:
                cutoff_iso=datetime.fromtimestamp(now.timestamp()-20*60,tz=IST).isoformat(timespec="seconds")
                stale_session_live=int(con.execute(
                    "SELECT COUNT(*) FROM recommendations WHERE state='LIVE' AND exchange='NSE' "
                    "AND book IN ('INTRADAY','CIRCUIT') AND period_key=? AND updated_at<?",(today,cutoff_iso)
                ).fetchone()[0])
            counts=[dict(r) for r in con.execute(
                "SELECT book,state,COUNT(*) n FROM recommendations GROUP BY book,state ORDER BY book,state"
            ).fetchall()]
            runtime_complete=True;runtime_db="ok"
    except Exception as exc:
        runtime_error=str(exc)[:180]
        runtime_db="TIME_BOUNDED" if "interrupted" in str(exc).lower() else "DEGRADED"
    workers=engine.worker_status_cached()
    dead=[name for name,x in workers.items() if not x.get("alive")]
    hung=[name for name,x in workers.items() if x.get("hung")]
    persistent=[name for name,x in workers.items() if int(x.get("restart_count") or 0)>=3]
    state=_cached_states(["last_daily_strategy_validation","last_recommendation_learning_evidence","position_reconciliation","last_verified_backup"]+
                         ["scan_status_"+b for b in ("INTRADAY","WEEKLY","MONTHLY","ETF","INTERNATIONAL","CIRCUIT","CIRCUIT_NEXTDAY")],.25)
    learning=state.get("last_daily_strategy_validation",{}) or {}
    evidence=state.get("last_recommendation_learning_evidence",{}) or {}
    backup=state.get("last_verified_backup",{}) or {}
    deep_ok=bool(backup.get("restore_verified") is True and str(backup.get("quick_check") or "").lower()=="ok")
    overdue=bool(is_regular_trading_day(now.date()) and now.hour>=20 and str(learning.get("day") or "")!=today)
    books={b:state.get("scan_status_"+b,{}) or {} for b in ("INTRADAY","WEEKLY","MONTHLY","ETF","INTERNATIONAL","CIRCUIT","CIRCUIT_NEXTDAY")}
    shortages={}
    for b in ("WEEKLY","MONTHLY","ETF","INTERNATIONAL"):
        contract=(books.get(b) or {}).get("contract") or {}
        if int(contract.get("shortage") or 0)>0:
            shortages[b]={"shortage":int(contract.get("shortage") or 0),"status":(books.get(b) or {}).get("status"),
                          "recovery_required":bool(contract.get("recovery_required",True))}
    integrity_clear=(not collisions and old_intraday==0 and old_circuit==0 and missing_levels==0 and not duplicates and stale_session_live==0)
    ok=bool(runtime_complete and integrity_clear and not dead and not hung and not overdue)
    return {
        "at":now_iso(),"version":VERSION,"ok":ok,
        "database_runtime_check":runtime_db,"database_runtime_checks_complete":runtime_complete,"database_runtime_error":runtime_error,
        "database_quick_check":"ok" if deep_ok else "DEFERRED_TO_VERIFIED_BACKUP",
        "deep_database_integrity":{"verified":deep_ok,"source":"SQLITE_BACKUP_RESTORE_QUICK_CHECK",
                                   "last_verified_backup":backup,
                                   "note":"Deep SQLite integrity verification is intentionally excluded from the request path."},
        "weekly_monthly_collisions":collisions,"old_intraday_live_rows":old_intraday,"old_circuit_live_rows":old_circuit,
        "stale_session_live_rows":stale_session_live,"live_rows_missing_entry_target_stop":missing_levels,
        "duplicate_live_identities":duplicates,"dead_workers":dead,"hung_workers":hung,"persistent_worker_restarts":persistent,
        "learning":{"last_daily_validation":learning,"last_ledger_evidence":evidence,
                    "strategy_worker_alive":bool(workers.get("strategy",{}).get("alive")),"validation_overdue":overdue},
        "frozen_book_shortages":shortages,"books":books,"recommendation_counts":counts,
        "execution_integrity":{"position_reconciliation":state.get("position_reconciliation") or {},"last_verified_backup":backup},
        "sanity_contract":{"passive":True,"network_calls":False,"deep_quick_check_inline":False,
                           "runtime_sql_budget_seconds":1.5,"elapsed_ms":round((time.monotonic()-started)*1000.0,1)},
        "policy":"V672_BOUNDED_RUNTIME_SANITY_AND_VERIFIED_BACKUP_DEEP_CHECK",
    }


@app.get("/api/lifecycle")
def lifecycle(page:Optional[str]=None):
    return lifecycle_payload(page)


@app.get("/api/history/recommendations")
def recommendation_history(book:Optional[str]=None,period_key:Optional[str]=None,limit:int=200):
    if book and book.upper() not in BOOKS:raise HTTPException(404,"Unknown book")
    return {"book":book.upper() if book else None,"period_key":period_key,
            "rows":recommendation_history_rows(book,period_key,limit),
            "policy":"EXPLICIT_HISTORY_ONLY_NOT_MIXED_IN_ACTIVE_BOOK_PAYLOADS"}


@app.get("/api/performance")
def performance(book:Optional[str]=None,group_by:str="book",limit:int=10000):
    allowed={"book","strategy","family","symbol","side","regime","horizon","period_key","result","close_reason","day","week","month","time_bucket","behavior_cluster"}
    if book and book.upper() not in BOOKS:raise HTTPException(404,"Unknown book")
    if group_by.lower() not in allowed:raise HTTPException(400,"Unsupported group_by")
    return performance_stats(book,group_by,limit,budget_seconds=2.5,db_timeout_seconds=.5)


@app.get("/api/diagnostics/no-trade")
def diagnostics_no_trade(book:Optional[str]=None,limit:int=12):
    if book and book.upper() not in BOOKS:raise HTTPException(404,"Unknown book")
    return no_trade_diagnostics(book,limit)


@app.get("/api/replay/decisions")
def decision_replay(decision_id:Optional[str]=None,limit:int=100):
    return replay_decisions(decision_id,limit)


@app.get("/api/execution/analytics")
def execution_quality_analytics(limit:int=500):
    return execution_analytics(limit)


@app.get("/api/experiments")
def experiment_registry(limit:int=200):
    return {"policy":"V670_EXPLICIT_EXPERIMENT_GOVERNANCE","experiments":experiment_rows(limit)}


@app.post("/api/experiments")
def experiment_register(payload:Dict[str,Any]):
    try:return register_experiment(payload)
    except Exception as exc:raise HTTPException(400,str(exc))


@app.get("/api/maintenance/backups")
def backups():
    return backup_status()


@app.post("/api/maintenance/backup-now")
def backup_now():
    try:return backup_database(force=True)
    except Exception as exc:raise HTTPException(500,str(exc))


@app.get("/api/book/{book}")
def book(book:str):
    b=book.upper()
    if b not in BOOKS:raise HTTPException(404,"Unknown book")
    return recommendations(b)



@app.get("/api/circuit/board")
def circuit_board():
    return {
        "same_day":recommendations("CIRCUIT"),
        "next_day_3pm":recommendations("CIRCUIT_NEXTDAY"),
        "same_day_scan":get_state("scan_status_CIRCUIT",{}),
        "next_day_scan":get_state("scan_status_CIRCUIT_NEXTDAY",{}),
        "policy":{
            "same_day_deadline_ist":"15:00",
            "same_day_targets_must_be_model_feasible_by_deadline":True,
            "next_day_freeze_ist":"15:00",
            "next_day_side":"LONG_ONLY",
            "next_day_target_is_prediction_not_guarantee":True,
        },
    }

@app.get("/api/international/board")
def international_board():
    return {
        "us_long":recommendations("INTERNATIONAL"),
        "global_to_india":global_india_board_payload(),
        "us_scan":get_state("scan_status_INTERNATIONAL",{}),
        "global_india_scan":get_state("scan_status_GLOBAL_INDIA",{}),
        "policy":{
            "us_regular_session_et":"09:30-16:00",
            "us_recommendation_side":"LONG_ONLY",
            "us_horizon":"WEEKLY",
            "us_weekly_freeze_et":"after Friday close through Monday pre-open; self-healing recovery if missed",
            "us_calls_close_at_us_regular_session_end":False,
            "us_calls_close_at_week_end":True,
            "us_no_replacement_after_contract_complete":True,
            "us_freeze_contract_minimum":5,
            "us_shortage_behavior":"EXPLICIT_RECOVERY_REQUIRED_NEVER_STALE_OR_FABRICATED",
            "global_to_india_freeze_ist":"09:00",
            "global_to_india_session_exit_ist":"15:00",
            "mapping":"SECTOR_AND_CROSS_ASSET_DRIVERS",
        },
    }

@app.get("/api/global/markets")
def global_markets():
    return get_state("global_context",{}) or {}

@app.get("/api/recommendations")
def recommendations_api(book:Optional[str]=None):
    """Research recommendations are independent of Static IP / broker execution readiness.

    Static IP is intentionally reported only as execution metadata. It never gates the
    recommendation ledger or research publication path.
    """
    if book:
        b=book.upper()
        if b not in BOOKS:raise HTTPException(404,"Unknown book")
        payload=recommendations(b)
        payload["research_policy"]={"recommendations_require_static_ip":False,"static_ip_scope":"ORDER_EXECUTION_ONLY"}
        return payload
    return {
        "research_policy":{"recommendations_require_static_ip":False,"static_ip_scope":"ORDER_EXECUTION_ONLY"},
        "books":{b:recommendations(b) for b in BOOKS},
        "execution":execution_readiness(use_cached=True),
    }

@app.get("/api/recommendations/{book}")
def recommendations_book_alias(book:str):
    return recommendations_api(book)

@app.get("/api/research/readiness")
def research_readiness():
    alive=bool(engine.thread and engine.thread.is_alive())
    return {
        "ready":alive,
        "blockers":[] if alive else ["research_engine_not_running"],
        "recommendations_require_static_ip":False,
        "static_ip_scope":"ORDER_EXECUTION_ONLY",
        "last_research_cycle":get_state("last_research_cycle",{}),
    }

@app.get("/api/regime")
def regime():return get_state("last_regime",{}) or {"regime":"WARMING","stale":True}

@app.get("/api/history/coverage")
def history_coverage(limit:int=0, interval:str="1day", minimum_rows:int=30):
    syms=full_nse_symbols()
    if int(limit)>0:syms=syms[:int(limit)]
    return cached_history_coverage(syms,interval,max(1,int(minimum_rows)))

@app.get("/api/universe/status")
def nse_universe_status():
    return universe_status()

@app.post("/api/regime/refresh")
def regime_refresh():return classify()

@app.get("/api/workers")
def workers():
    threads=engine.worker_status();state=_cached_states(["scheduler_v624"]+["worker_"+name for name in threads])
    return {"scheduler":state.get("scheduler_v624",{}),"threads":threads,"states":{name:state.get("worker_"+name,{}) for name in threads}}

@app.get("/api/scan/status")
def scan_status():
    state=_cached_states([p+b for b in BOOKS for p in ("scan_status_","scan_detail_")])
    return {b:{"worker":state.get("scan_status_"+b,{}),"detail":state.get("scan_detail_"+b,{})} for b in BOOKS}

@app.get("/api/strategy-lab")
def strategy_lab():return strategy_status()

@app.post("/api/strategy-lab/discover")
def strategy_discover():return discover_new_strategies()

@app.post("/api/strategy-lab/validate")
def strategy_validate():return validate_strategies()

@app.post("/api/strategy-lab/decay-check")
def strategy_decay_check():return monitor_strategy_decay()

@app.post("/api/strategy-lab/shadow-run")
def strategy_shadow_run():return run_shadow_cycle()

@app.post("/api/strategy-lab/shadow-resolve")
def strategy_shadow_resolve():return resolve_shadow_signals()

@app.get("/api/research-framework")
def research_framework():
    return {
        "handbook":handbook_status(),"strategies":strategy_catalog(),"candlesticks":candlestick_catalog(),"filters":filter_catalog(),"global_context":global_snapshot(force=False),
        "implemented_evidence_layers":[
            "PROSPECTIVE_POINT_IN_TIME_FUNDAMENTAL_AND_ANALYST_SNAPSHOTS",
            "OFFICIAL_NSE_2026_TRADING_CALENDAR_FOR_SESSION_ARITHMETIC",
            "NIFTY500_INDUSTRY_PEER_GRAPH_AND_CACHED_SECTOR_BREADTH",
            "TIMESTAMPED_EVENT_REGISTRY_WITH_PROSPECTIVE_EARNINGS_CAPTURE",
            "GROWW_ORDER_STATUS_DETAIL_TRADE_FILL_RECONCILIATION",
            "NON_EXECUTABLE_LIVE_SHADOW_CHALLENGER_PIPELINE",
            "CENTRAL_GROWW_HISTORY_PACING_WITH_ADAPTIVE_429_BACKOFF",
            "INVALID_HISTORY_SYMBOL_QUARANTINE_WITH_SHORTER_WINDOW_RETRY",
            "PRIORITY_HISTORY_WARMUP_AND_CACHED_ONLY_LOW_PRIORITY_RESEARCH",
            "FULL_GROWW_NSE_CASH_EQUITY_MASTER_WITH_MAINBOARD_TRADE_FOR_TRADE_AND_SME_DISCOVERY",
            "FULL_BREADTH_BATCHED_LTP_DISCOVERY_WITH_NEW_LISTING_PRIORITY",
            "SHARED_MARKET_EVIDENCE_FABRIC_ONE_OBSERVATION_MANY_CONSUMERS",
            "NSE_FII_DII_AND_LARGE_DEAL_POINT_IN_TIME_INSTITUTIONAL_CONTEXT",
            "OBV_CMF_MFI_ACCUMULATION_DISTRIBUTION_FEATURES",
            "BACKGROUND_PRIORITY_NEWS_AND_EARNINGS_EVENT_PRODUCERS",
            "ADAPTIVE_DAILY_ALGORITHM_VERSIONED_FROM_VALIDATED_CHAMPION_MANIFEST",
        ],
        "remaining_data_gaps":[
            "FULL_HISTORICAL_POINT_IN_TIME_FUNDAMENTALS_BEFORE_V620_CAPTURE_DATE",
            "AUTHORITATIVE_CPI_GDP_AND_OTHER_INDIA_MACRO_RELEASES_BEYOND_SEEDED_RBI_MPC_EVENTS",
            "PROMOTER_PLEDGE_GOVERNANCE_AND_DIRECT_INSIDER_TRANSACTION_POINT_IN_TIME_FEED",
            "AUTHORITATIVE_PER_STOCK_DELIVERABLE_VOLUME_PERCENTAGE_HISTORY",
            "DERIVATIVES_POSITIONING_OI_PCR_IV_SKEW_WHERE_APPLICABLE",
            "MAPPED_SECTOR_ETF_CONFIRMATION_FOR_EVERY_INDUSTRY",
            "FULL_LEVEL2_DEPTH_AND_MARKET_IMPACT_HISTORY",
        ],
        "data_gap_policy":"Missing evidence is exposed as UNKNOWN and never fabricated or silently treated as a pass.",
    }

@app.get("/api/trade-decisions")
def trade_decisions(limit:int=200):
    n=max(1,min(1000,int(limit)))
    with db() as con:
        rows=[dict(r) for r in con.execute("SELECT ts,book,period_key,symbol,side,decision,ensemble_score,intelligence_score,hard_fail_count,strategy_ids_json,payload_json FROM trade_decisions ORDER BY id DESC LIMIT ?",(n,)).fetchall()]
    for r in rows:
        try:r['strategy_ids']=json.loads(r.pop('strategy_ids_json') or '[]')
        except Exception:r['strategy_ids']=[]
        try:
            p=json.loads(r.pop('payload_json') or '{}');r['hard_blockers']=((p.get('trade_intelligence') or {}).get('hard_blockers') or [])[:8]
        except Exception:r['hard_blockers']=[]
    return {"decisions":rows}

@app.get("/api/settings")
def settings():return {**load_settings(),"maximum_trade_notional_rupees":TRADE_NOTIONAL_RUPEES,"maximum_rupee_risk_to_stop":MAX_RUPEE_RISK_PER_TRADE,"static_ip":broker.static_ip_status(),"research_policy":{"recommendations_require_static_ip":False,"static_ip_scope":"ORDER_EXECUTION_ONLY"}}

@app.post("/api/settings")
def settings_patch(patch:SettingsPatch):
    d={k:v for k,v in patch.dict().items() if v is not None};return {**update_settings(d),"static_ip":broker.static_ip_status(),"maximum_trade_notional_rupees":TRADE_NOTIONAL_RUPEES,"maximum_rupee_risk_to_stop":MAX_RUPEE_RISK_PER_TRADE,"research_policy":{"recommendations_require_static_ip":False,"static_ip_scope":"ORDER_EXECUTION_ONLY"}}

@app.get("/api/execution/readiness")
def readiness():return execution_readiness()

@app.post("/api/order/preview/{recommendation_id}")
def preview(recommendation_id:str):
    try:return create_preview(recommendation_id)
    except Exception as exc:raise HTTPException(409,str(exc))

@app.post("/api/order/execute/{preview_token}")
def execute(preview_token:str):
    try:return execute_preview(preview_token)
    except Exception as exc:raise HTTPException(409,str(exc))

@app.get("/api/orders")
def orders():return {"orders":recent_orders(),"fills":recent_fills(100),"maximum_trade_notional_rupees":TRADE_NOTIONAL_RUPEES,"maximum_rupee_risk_to_stop":MAX_RUPEE_RISK_PER_TRADE}

@app.post("/api/orders/reconcile")
def orders_reconcile():
    order_state=reconcile_orders()
    position_state=reconcile_positions()
    return {"orders":order_state,"positions":position_state}

@app.post("/api/execution/positions/reconcile")
def positions_reconcile():
    return reconcile_positions()

@app.get("/api/evidence/status")
def evidence_status():
    state=_cached_states(["universe_status","full_breadth_discovery","daily_history_warm_status","last_intraday_history_warm","live_price_cache_status"],.25)
    fundamentals,events=_bounded_evidence_db(.25)
    return {"fundamentals":fundamentals,"trading_calendar":trading_calendar_status(),"sector_breadth":sector_status_cached(),
            "event_calendar":events,"history_control":history_control_status_cached(),
            "nse_universe":_cached_universe_health(state),"shadow":strategy_status().get("shadow_signals",{}),
            "fabric":evidence_fabric_status(),"institutional":institutional_status(),
            "passive_nonblocking":True}

@app.get("/api/evidence/fabric")
def evidence_fabric():
    return evidence_fabric_status()

@app.get("/api/institutional")
def institutional_intelligence(limit:int=20):
    return {"current":institutional_status(),"point_in_time_history":institutional_history(max(1,min(int(limit),100)))}

@app.get("/api/algorithm")
def adaptive_algorithm():
    return algorithm_status()

@app.get("/api/algorithm/history")
def adaptive_algorithm_history(limit:int=30):
    return {"rows":algorithm_history(max(1,min(int(limit),365)))}

@app.get("/api/history/status")
def history_status():
    return history_control_status()

@app.get("/api/portfolio")
def portfolio():
    out={"holdings":None,"positions":None,"last_error":"","risk_engine":risk_summary(),
         "position_reconciliation":cached_position_reconciliation()}
    try:out["holdings"]=broker.holdings()
    except Exception as exc:out["last_error"]="holdings: "+str(exc)[:160]
    try:out["positions"]=broker.positions()
    except Exception as exc:out["last_error"]=(out["last_error"]+"; " if out["last_error"] else "")+"positions: "+str(exc)[:160]
    return out

# PS_SCANNER_V645_GROWW_GUARD_ROUTE
from .groww_guard import status as _groww_guard_status

@app.get("/api/groww/guard")
def groww_guard_status():
    """Passive telemetry only; does not contact Groww or refresh auth."""
    return _groww_guard_status()

# PS_SCANNER_V646_FRESHNESS_INTEGRITY
from . import freshness_guard as _ps_v646_freshness_guard
_ps_v646_freshness_guard.install_runtime(app)

@app.get("/api/freshness/guard")
def freshness_guard_status():
    """Passive intraday data-integrity telemetry. No provider request is made."""
    return _ps_v646_freshness_guard.status()

@app.get("/api/freshness/holds")
def freshness_guard_holds(limit: int = 50):
    """Audit-only list of stale candidates withheld from LIVE/learning states."""
    return _ps_v646_freshness_guard.holds(limit)

