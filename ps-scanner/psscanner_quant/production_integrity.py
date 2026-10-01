from __future__ import annotations

"""Production-integrity services for PS Scanner v6.7.0.

This module is deliberately evidence-first.  It records enough point-in-time context to
explain prospective decisions, preserves scan-level rejection evidence, provides a
deterministic contract replay, governs experiments, and verifies that SQLite backups can
actually be restored.  It never changes a trading threshold or submits an order.
"""

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import load_settings
from .constants import (
    IST, VERSION, TRADE_NOTIONAL_RUPEES, MAX_RUPEE_RISK_PER_TRADE,
    INTRADAY_ENTRY_CUTOFF, SHORT_HARD_EXIT,
)
from .db import db, get_state, health, now_iso, set_state
from .paths import DATA, DB_PATH

AUDIT_POLICY = "V670_POINT_IN_TIME_PRODUCTION_ENVELOPE"
REPLAY_POLICY = "V670_STORED_INPUT_CONTRACT_REPLAY"
BACKUP_POLICY = "V670_SQLITE_BACKUP_AND_RESTORE_VERIFY"
EXPERIMENT_POLICY = "V670_EXPLICIT_EXPERIMENT_GOVERNANCE"


def _json(raw: Any, default: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw or ""))
    except Exception:
        return default


def _stable_hash(value: Any) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _safe_settings() -> Dict[str, Any]:
    settings=load_settings()
    # Never copy network identifiers or anything credential-like into historical audit rows.
    deny=("token","secret","password","credential","auth")
    return {k:v for k,v in settings.items()
            if k!="expected_static_ip" and not any(x in k.lower() for x in deny)}


def _strategy_versions(strategy_ids: Iterable[str]) -> List[Dict[str, Any]]:
    ids=list(dict.fromkeys(str(x) for x in strategy_ids if x))
    if not ids:
        return []
    marks=",".join("?" for _ in ids)
    try:
        with db() as con:
            rows=con.execute(
                f"SELECT strategy_id,family,horizon,side,status,version,params_json FROM strategies WHERE strategy_id IN ({marks})",
                tuple(ids),
            ).fetchall()
        out=[]
        for r in rows:
            out.append({
                "strategy_id":str(r["strategy_id"]),"family":r["family"],"horizon":r["horizon"],
                "side":r["side"],"status":r["status"],"version":int(r["version"] or 0),
                "params_hash":_stable_hash(_json(r["params_json"],{})),
            })
        return sorted(out,key=lambda x:x["strategy_id"])
    except Exception:
        return []


def common_audit_context(strategy_ids: Iterable[str] = ()) -> Dict[str, Any]:
    safe=_safe_settings()
    universe=get_state("universe_status",{}) or {}
    market=get_state("market_snapshot_status",{}) or {}
    return {
        "audit_policy":AUDIT_POLICY,
        "software_version":VERSION,
        "captured_at":now_iso(),
        "settings_hash":_stable_hash(safe),
        "policy_settings":{
            k:safe.get(k) for k in (
                "weekly_target_pct","monthly_target_pct","etf_target_pct",
                "weekly_min_score","monthly_min_score","horizon_min_confidence",
                "horizon_min_data_confidence","strategy_champions_per_horizon",
                "max_open_manual_orders","full_nse_breadth_enabled",
            )
        },
        "policy_constants":{
            "max_trade_notional_rupees":TRADE_NOTIONAL_RUPEES,
            "max_rupee_risk_to_stop":MAX_RUPEE_RISK_PER_TRADE,
            "intraday_entry_cutoff":INTRADAY_ENTRY_CUTOFF.isoformat(timespec="minutes"),
            "short_hard_exit":SHORT_HARD_EXIT.isoformat(timespec="minutes"),
        },
        "strategy_versions":_strategy_versions(strategy_ids),
        "universe":{
            "at":universe.get("at") or universe.get("refreshed_at"),
            "count":universe.get("n") or universe.get("count"),
            "source":universe.get("source"),
        },
        "market_snapshot":{
            "at":market.get("at"),"symbols":market.get("symbols"),"prices":market.get("prices"),
            "breadth_evaluated":market.get("breadth_evaluated"),
        },
    }


def make_audit_envelope(book: str, period_key: str, symbol: str, side: str,
                        features: Optional[Dict[str,Any]] = None,
                        rationale: Optional[Dict[str,Any]] = None,
                        strategy_ids: Iterable[str] = (),
                        common: Optional[Dict[str,Any]] = None,
                        decision_ts: Optional[str] = None) -> Dict[str, Any]:
    f=dict(features or {});r=dict(rationale or {});common=dict(common or common_audit_context(strategy_ids))
    strategy_map={x["strategy_id"]:x for x in common.get("strategy_versions",[]) if x.get("strategy_id")}
    strategies=[strategy_map.get(str(s),{"strategy_id":str(s),"metadata":"NOT_FOUND_AT_CAPTURE"}) for s in strategy_ids]
    contexts={
        "feature_asof":f.get("_asof") or f.get("asof") or f.get("timestamp"),
        "fundamentals_asof":r.get("fundamentals_asof"),
        "news_asof":(r.get("news_context") or {}).get("asof") if isinstance(r.get("news_context"),dict) else None,
        "sector_asof":(r.get("sector_context") or {}).get("asof") if isinstance(r.get("sector_context"),dict) else None,
        "event_asof":(r.get("event_context") or {}).get("asof") if isinstance(r.get("event_context"),dict) else None,
        "global_asof":(r.get("global_context") or {}).get("asof") if isinstance(r.get("global_context"),dict) else None,
    }
    return {
        "audit_policy":AUDIT_POLICY,
        "software_version":common.get("software_version") or VERSION,
        "decision_ts":decision_ts or now_iso(),
        "book":str(book).upper(),"period_key":str(period_key),"symbol":str(symbol).upper(),"side":str(side).upper(),
        "settings_hash":common.get("settings_hash"),
        "policy_settings":common.get("policy_settings") or {},
        "policy_constants":common.get("policy_constants") or {},
        "strategy_versions":strategies,
        "feature_snapshot_hash":_stable_hash(f),
        "context_timestamps":contexts,
        "universe":common.get("universe") or {},
        "market_snapshot":common.get("market_snapshot") or {},
        "data_confidence":r.get("data_confidence"),
        "regime":r.get("regime") or None,
    }


def record_scan_run(book: str, stats: Dict[str,Any]) -> str:
    run_id="SCAN-"+uuid.uuid4().hex[:16]
    funnel=dict(stats.get("funnel") or {})
    started=str(stats.get("started_at") or now_iso());completed=str(stats.get("completed_at") or now_iso())
    period=str(stats.get("target_period_key") or stats.get("period_key") or "")
    status=str(stats.get("status") or stats.get("stage") or "DONE")
    try:
        with db() as con:
            con.execute(
                "INSERT INTO scan_runs(run_id,book,period_key,started_at,completed_at,status,universe_total,scan_scope_total,processed,"
                "funnel_json,near_misses_json,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id,str(book).upper(),period,started,completed,status,
                 int(funnel.get("universe_total") or stats.get("full_nse_universe") or stats.get("universe") or 0),
                 int(funnel.get("scan_scope_total") or stats.get("universe") or 0),
                 int(funnel.get("scan_scope_processed") or stats.get("processed") or 0),
                 json.dumps(funnel,separators=(",",":"),default=str),
                 json.dumps(stats.get("near_misses") or [],separators=(",",":"),default=str),
                 json.dumps(stats,separators=(",",":"),default=str)),
            )
            con.execute("DELETE FROM scan_runs WHERE id NOT IN (SELECT id FROM scan_runs ORDER BY id DESC LIMIT 25000)")
    except Exception as exc:
        health("scan_audit","WARN",str(exc)[:200])
    return run_id


def no_trade_diagnostics(book: Optional[str] = None, limit: int = 12) -> Dict[str,Any]:
    books=[str(book).upper()] if book else ["INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","CIRCUIT_NEXTDAY","INTERNATIONAL"]
    out={}
    for b in books:
        status=get_state("scan_status_"+b,{}) or {};detail=get_state("scan_detail_"+b,{}) or {}
        funnel=dict(detail.get("funnel") or {})
        blockers=Counter()
        decisions=[]
        try:
            with db() as con:
                rows=con.execute(
                    "SELECT decision,payload_json FROM trade_decisions WHERE book=? ORDER BY id DESC LIMIT ?",
                    (b,max(20,min(500,int(limit)*20))),
                ).fetchall()
            for row in rows:
                payload=_json(row["payload_json"],{})
                ti=payload.get("trade_intelligence") or {}
                for reason in ti.get("hard_blockers") or []:
                    blockers[str(reason)]+=1
                if len(decisions)<limit:
                    decisions.append({
                        "symbol":payload.get("symbol"),"side":payload.get("side"),"decision":row["decision"],
                        "pipeline_stage":payload.get("pipeline_stage"),
                        "pipeline_verdict":payload.get("pipeline_verdict"),
                        "rejection_code":payload.get("rejection_code"),
                    })
        except Exception:
            pass
        coverage={
            "universe_total":funnel.get("universe_total") or detail.get("full_nse_universe") or detail.get("universe"),
            "scan_scope_total":funnel.get("scan_scope_total") or detail.get("universe"),
            "processed":funnel.get("scan_scope_processed") or detail.get("processed"),
            "full_universe_scan":funnel.get("full_universe_scan"),
        }
        classification=status.get("availability_class") or status.get("availability_reason") or status.get("status")
        out[b]={
            "classification":classification,"coverage":coverage,"funnel":funnel,
            "near_misses":(detail.get("near_misses") or [])[:limit],
            "top_hard_blockers":[{"reason":k,"count":v} for k,v in blockers.most_common(limit)],
            "recent_candidate_decisions":decisions,
            "search_evidence":status.get("search_evidence") or (status.get("bootstrap_recovery") or {}).get("pass_summary"),
            "contract":status.get("contract"),
            "principle":"NO_OPPORTUNITY is distinct from SEARCH_INCOMPLETE, DATA_NOT_READY and SOFTWARE_OR_EXECUTION_BOTTLENECK.",
        }
    return {"generated_at":now_iso(),"books":out,"policy":"V670_FIRST_CLASS_NO_TRADE_DIAGNOSTICS"}


def _replay_verdict(payload: Dict[str,Any]) -> Dict[str,Any]:
    strategies=payload.get("strategies") or []
    ti=payload.get("trade_intelligence") or {}
    tf=payload.get("target_feasibility") or (payload.get("rationale") or {}).get("target_feasibility")
    if not strategies:
        return {"verdict":"REJECT","stage":"STRATEGY_EVIDENCE","reason":"NO_AUDITED_STRATEGY_EVIDENCE"}
    if str(ti.get("decision") or "").upper()=="NO_TRADE" or int(ti.get("hard_fail_count") or 0)>0:
        return {"verdict":"REJECT","stage":"TRADE_INTELLIGENCE","reason":"; ".join((ti.get("hard_blockers") or [])[:3]) or "HARD_GATE"}
    if str(ti.get("decision") or "").upper() not in ("ELIGIBLE",""):
        return {"verdict":"WATCH","stage":"TRADE_INTELLIGENCE","reason":"INTELLIGENCE_SCORE_BELOW_ELIGIBLE"}
    if isinstance(tf,dict) and tf and tf.get("target_qualified") is False:
        return {"verdict":"REJECT","stage":"TARGET_FEASIBILITY","reason":"; ".join(tf.get("rejection_reasons") or []) or "TARGET_NOT_QUALIFIED"}
    return {"verdict":"PUBLICATION_READY","stage":"FINAL_GATES","reason":None}


def replay_decisions(decision_id: Optional[str] = None, limit: int = 100) -> Dict[str,Any]:
    where="WHERE decision_id=?" if decision_id else ""
    args=(decision_id,) if decision_id else ()
    lim=max(1,min(1000,int(limit)))
    try:
        with db() as con:
            rows=[dict(r) for r in con.execute(
                f"SELECT * FROM trade_decisions {where} ORDER BY id DESC LIMIT ?",args+(lim,)
            ).fetchall()]
    except Exception:
        rows=[]
    replay=[]
    for row in rows:
        payload=_json(row.get("payload_json"),{})
        envelope=_json(row.get("audit_envelope_json"),{}) if "audit_envelope_json" in row else {}
        computed=_replay_verdict(payload)
        stored_verdict=payload.get("pipeline_verdict")
        stored_stage=payload.get("pipeline_stage")
        published=False
        try:
            with db() as con:
                published=bool(con.execute(
                    "SELECT 1 FROM recommendations WHERE book=? AND period_key=? AND symbol=? AND side=? AND COALESCE(result,'')<>'VOID' LIMIT 1",
                    (row.get("book"),row.get("period_key"),row.get("symbol"),row.get("side")),
                ).fetchone())
        except Exception:
            pass
        replay.append({
            "decision_id":row.get("decision_id"),"ts":row.get("ts"),"book":row.get("book"),
            "symbol":row.get("symbol"),"side":row.get("side"),"stored_decision":row.get("decision"),
            "stored_pipeline_verdict":stored_verdict,"stored_pipeline_stage":stored_stage,
            "replayed":computed,"published":published,
            "audit_envelope_present":bool(envelope),
            "input_replayability":"PROSPECTIVE_COMPLETE" if envelope.get("audit_policy")==AUDIT_POLICY else "LEGACY_PARTIAL",
            "contract_match":None if stored_verdict is None else str(stored_verdict)==computed["verdict"],
        })
    return {
        "generated_at":now_iso(),"policy":REPLAY_POLICY,"rows":replay,
        "scope":"Replays stored production gate inputs and verdicts. It does not invent unavailable pre-v6.7 point-in-time inputs.",
    }


def seed_release_experiment() -> None:
    exp_id="EXP-V670-PRODUCTION-INTEGRITY"
    ts=now_iso()
    try:
        with db() as con:
            con.execute(
                "INSERT OR IGNORE INTO experiments(experiment_id,title,hypothesis,affected_books_json,change_summary,"
                "sample_requirement,promotion_criterion,rollback_criterion,status,release_version,started_at,metrics_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (exp_id,"v6.7 production integrity rollout",
                 "Stronger execution and observability controls reduce operational error without weakening recommendation safety gates.",
                 json.dumps(["INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","INTERNATIONAL"]),
                 "Execution permission, position reconciliation, audit envelope, replay, diagnostics, backups and cohort analytics.",
                 "Observe at least 50 executed or resolved eligible samples before using new cohort evidence as a live selector.",
                 "No safety regression; execution mismatch/shortability failures are caught before order submission; diagnostics remain reproducible.",
                 "Rollback any live-use policy if it increases operational rejects incorrectly or cannot be replayed from stored evidence.",
                 "RUNNING",VERSION,ts,"{}"),
            )
    except Exception as exc:
        health("experiments","WARN",str(exc)[:180])


def experiments(limit: int = 200) -> List[Dict[str,Any]]:
    try:
        with db() as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM experiments ORDER BY COALESCE(started_at,'') DESC LIMIT ?",
                (max(1,min(1000,int(limit))),),
            ).fetchall()]
    except Exception:
        return []


def register_experiment(payload: Dict[str,Any]) -> Dict[str,Any]:
    exp_id=str(payload.get("experiment_id") or ("EXP-"+uuid.uuid4().hex[:12])).upper()
    title=str(payload.get("title") or "").strip()
    hypothesis=str(payload.get("hypothesis") or "").strip()
    if not title or not hypothesis:
        raise ValueError("title and hypothesis are required")
    ts=now_iso()
    row={
        "experiment_id":exp_id,"title":title,"hypothesis":hypothesis,
        "affected_books_json":json.dumps(payload.get("affected_books") or []),
        "change_summary":str(payload.get("change_summary") or ""),
        "sample_requirement":str(payload.get("sample_requirement") or ""),
        "promotion_criterion":str(payload.get("promotion_criterion") or ""),
        "rollback_criterion":str(payload.get("rollback_criterion") or ""),
        "status":str(payload.get("status") or "PLANNED").upper(),
        "release_version":str(payload.get("release_version") or VERSION),
        "started_at":str(payload.get("started_at") or ts),"ended_at":payload.get("ended_at"),
        "metrics_json":json.dumps(payload.get("metrics") or {},separators=(",",":"),default=str),
    }
    with db() as con:
        con.execute(
            "INSERT INTO experiments(experiment_id,title,hypothesis,affected_books_json,change_summary,sample_requirement,"
            "promotion_criterion,rollback_criterion,status,release_version,started_at,ended_at,metrics_json) "
            "VALUES(:experiment_id,:title,:hypothesis,:affected_books_json,:change_summary,:sample_requirement,"
            ":promotion_criterion,:rollback_criterion,:status,:release_version,:started_at,:ended_at,:metrics_json)",
            row,
        )
    return row


BACKUP_DIR=DATA/"backups"


def backup_database(force: bool = False, retention: int = 14) -> Dict[str,Any]:
    BACKUP_DIR.mkdir(parents=True,exist_ok=True)
    today=datetime.now(IST).date().isoformat()
    last={}
    if not force:
        try:
            with db(timeout_seconds=.25) as con:
                row=con.execute("SELECT value_json FROM system_state WHERE key='last_verified_backup'").fetchone()
            if row:last=_json(row[0],{}) or {}
        except Exception:
            last={}
    if not force and str(last.get("day") or "")==today and last.get("restore_verified") is True:
        return last
    stamp=datetime.now(IST).strftime("%Y%m%d-%H%M%S")
    target=BACKUP_DIR/f"psscanner_quant-{stamp}.db"
    started=now_iso()
    src=sqlite3.connect(str(DB_PATH),timeout=10)
    dst=sqlite3.connect(str(target),timeout=10)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close();src.close()
    # Restore-test into a separate temporary database.  This proves the backup can be
    # consumed by SQLite without ever touching the live ledger.
    with tempfile.TemporaryDirectory(prefix="psq_restore_") as td:
        restored=Path(td)/"restored.db"
        bsrc=sqlite3.connect(str(target),timeout=10)
        rdst=sqlite3.connect(str(restored),timeout=10)
        try:
            bsrc.backup(rdst);rdst.commit()
            quick=str(rdst.execute("PRAGMA quick_check").fetchone()[0])
            tables={str(r[0]) for r in rdst.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            required={"recommendations","orders","trade_decisions","system_state"}
            restore_verified=quick=="ok" and required.issubset(tables)
        finally:
            rdst.close();bsrc.close()
    size=target.stat().st_size if target.exists() else 0
    status={
        "day":today,"started_at":started,"completed_at":now_iso(),"path":str(target),
        "bytes":size,"quick_check":quick,"restore_verified":bool(restore_verified),
        "policy":BACKUP_POLICY,
    }
    set_state("last_verified_backup",status)
    if not restore_verified:
        health("backup","ERROR","SQLite backup restore verification failed",status)
    # Keep newest N verified/raw backups; deletion failure is non-fatal.
    files=sorted(BACKUP_DIR.glob("psscanner_quant-*.db"),key=lambda p:p.stat().st_mtime,reverse=True)
    for old in files[max(2,int(retention)):]:
        try:old.unlink()
        except Exception:pass
    return status


def backup_status(timeout_seconds:float=.25) -> Dict[str,Any]:
    status={}
    try:
        with db(timeout_seconds=timeout_seconds) as con:
            row=con.execute("SELECT value_json FROM system_state WHERE key='last_verified_backup'").fetchone()
        if row:
            status=_json(row[0],{}) or {}
    except Exception as exc:
        status={"status":"CACHE_UNAVAILABLE_BOUNDED","error":str(exc)[:160],"restore_verified":False}
    files=[]
    try:
        for p in sorted(BACKUP_DIR.glob("psscanner_quant-*.db"),key=lambda x:x.stat().st_mtime,reverse=True)[:10]:
            files.append({"name":p.name,"bytes":p.stat().st_size,"mtime":datetime.fromtimestamp(p.stat().st_mtime,tz=IST).isoformat(timespec="seconds")})
    except Exception:
        pass
    return {"last":status,"backups":files,"policy":BACKUP_POLICY,"bounded":True}


def maybe_daily_backup() -> Dict[str,Any]:
    try:
        result=backup_database(force=False)
        set_state("backup_worker_status",{"at":now_iso(),"ok":bool(result.get("restore_verified")),"last":result})
        return result
    except Exception as exc:
        health("backup","ERROR",str(exc)[:220])
        out={"at":now_iso(),"restore_verified":False,"error":str(exc)[:220],"policy":BACKUP_POLICY}
        set_state("backup_worker_status",out)
        return out
