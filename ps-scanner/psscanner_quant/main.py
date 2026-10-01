from __future__ import annotations
import json
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
from .engine import engine, recommendations
from .orders import create_preview, execute_preview, execution_readiness, recent_orders, reconcile_orders, recent_fills
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
from .history_control import status as history_control_status
from .data import liquidity_rank, cached_history_coverage, full_nse_symbols, universe_status
from .cross_market import board_payload as global_india_board_payload

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

@app.get("/api/groww/status")
def groww_status(refresh: bool=False):
    """Read-only Groww connectivity status. refresh=true performs an explicit broker probe.

    This endpoint never checks or gates on Static IP; Static IP is an order-execution control.
    """
    return broker.status() if refresh else broker.status_cached()

@app.get("/api/health")
def health():
    now=datetime.now(IST);market=is_regular_trading_day(now.date()) and MARKET_OPEN<=now.time().replace(tzinfo=None)<=MARKET_CLOSE
    with db() as con:
        recent=[dict(r) for r in con.execute("SELECT ts,component,level,message FROM health_events ORDER BY id DESC LIMIT 30").fetchall()]
        recs=con.execute("SELECT book,state,COUNT(*) n FROM recommendations GROUP BY book,state").fetchall()
    with db() as con:
        decisions=con.execute("SELECT decision,COUNT(*) FROM trade_decisions WHERE ts>=datetime('now','-1 day') GROUP BY decision").fetchall()
    return {"app":APP_NAME,"version":VERSION,"reliability_patch":{"version":"6.4.9","name":"RECOVERY_EXECUTION_AND_PREPERIOD_FREEZE","five_pick_contract_books":["WEEKLY","MONTHLY","ETF","INTERNATIONAL"],"worker_watchdog":True,"staged_recovery":True,"preperiod_freeze":True,"intraday_bootstrap":True,"bounded_international_transport":True}, "strategic_recovery":{"version":"6.5.1","name":"SANITY_AND_RECOVERY_HOTFIX","near_miss_telemetry":True,"strategy_promotion_validation":True,"candidate_funnel":True,"weekly_monthly_symbol_isolation":True,"etf_missed_freeze_recovery":True,"international_hard_timeout":True},"generated_at":now_iso(),"market_open":market,"engine_alive":bool(engine.thread and engine.thread.is_alive()),"engine_last_error":engine.last_error,"workers":engine.worker_status(),"groww":broker.status_cached(),"static_ip":broker.static_ip_status_cached(),"research":{"recommendations_require_static_ip":False,"static_ip_scope":"ORDER_EXECUTION_ONLY","status":"ACTIVE" if bool(engine.thread and engine.thread.is_alive()) else "ENGINE_STOPPED"},"execution":execution_readiness(use_cached=True),"regime":get_state("last_regime",{}),"global_context":get_state("global_context",{}),"last_research_cycle":get_state("last_research_cycle",{}),"scan_status":{b:get_state("scan_status_"+b,{}) for b in BOOKS},"evidence":{"fundamentals":fundamental_snapshot_status(),"trading_calendar":trading_calendar_status(),"sector_breadth":sector_status_cached(),"event_calendar":event_calendar_status(),"history_control":history_control_status(),"nse_universe":universe_status()},"recommendation_counts":[{"book":r[0],"state":r[1],"n":r[2]} for r in recs],"decision_counts_24h":{r[0]:r[1] for r in decisions},"recent_health_events":recent}


@app.get("/api/sanity")
def sanity():
    """Cheap cross-page integrity check; no provider/network calls."""
    now=datetime.now(IST);today=now.date().isoformat()
    with db() as con:
        collisions=[dict(r) for r in con.execute(
            "SELECT UPPER(symbol) symbol,GROUP_CONCAT(DISTINCT book) books,COUNT(*) n "
            "FROM recommendations WHERE book IN ('WEEKLY','MONTHLY') AND state='LIVE' "
            "AND COALESCE(result,'')<>'VOID' GROUP BY UPPER(symbol) "
            "HAVING COUNT(DISTINCT book)>1"
        ).fetchall()]
        old_intraday=int(con.execute(
            "SELECT COUNT(*) FROM recommendations WHERE book='INTRADAY' AND state='LIVE' AND period_key<>?",
            (today,),
        ).fetchone()[0])
        db_check=str(con.execute("PRAGMA quick_check").fetchone()[0])
        counts=[dict(r) for r in con.execute(
            "SELECT book,state,COUNT(*) n FROM recommendations GROUP BY book,state ORDER BY book,state"
        ).fetchall()]
    workers=engine.worker_status()
    dead=[name for name,x in workers.items() if not x.get("alive")]
    learning=get_state("last_daily_strategy_validation",{}) or {}
    scan={b:get_state("scan_status_"+b,{}) or {} for b in ("INTRADAY","WEEKLY","MONTHLY","ETF","INTERNATIONAL","CIRCUIT","CIRCUIT_NEXTDAY")}
    return {
        "at":now_iso(),"version":VERSION,"ok":db_check=="ok" and not collisions and old_intraday==0 and not dead,
        "database_quick_check":db_check,
        "weekly_monthly_collisions":collisions,
        "old_intraday_live_rows":old_intraday,
        "dead_workers":dead,
        "learning":{"last_daily_validation":learning,"strategy_worker_alive":bool(workers.get("strategy",{}).get("alive"))},
        "books":scan,
        "recommendation_counts":counts,
        "policy":"V651_NO_NETWORK_SANITY_CHECK",
    }


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
def workers():return {"scheduler":get_state("scheduler_v624",{}),"threads":engine.worker_status(),"states":{name:get_state("worker_"+name,{}) for name in engine.worker_status()}}

@app.get("/api/scan/status")
def scan_status():return {b:{"worker":get_state("scan_status_"+b,{}),"detail":get_state("scan_detail_"+b,{})} for b in BOOKS}

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
        ],
        "remaining_data_gaps":[
            "FULL_HISTORICAL_POINT_IN_TIME_FUNDAMENTALS_BEFORE_V620_CAPTURE_DATE",
            "AUTHORITATIVE_CPI_GDP_AND_OTHER_INDIA_MACRO_RELEASES_BEYOND_SEEDED_RBI_MPC_EVENTS",
            "PROMOTER_PLEDGE_AND_GOVERNANCE_POINT_IN_TIME_FEED",
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
def orders_reconcile():return reconcile_orders()

@app.get("/api/evidence/status")
def evidence_status():
    return {"fundamentals":fundamental_snapshot_status(),"trading_calendar":trading_calendar_status(),"sector_breadth":sector_status_cached(),"event_calendar":event_calendar_status(),"history_control":history_control_status(),"shadow":strategy_status().get("shadow_signals",{})}

@app.get("/api/history/status")
def history_status():
    return history_control_status()

@app.get("/api/portfolio")
def portfolio():
    out={"holdings":None,"positions":None,"last_error":"","risk_engine":risk_summary()}
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

