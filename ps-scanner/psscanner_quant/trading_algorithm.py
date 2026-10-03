from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .constants import IST, VERSION
from .db import db, get_state, now_iso, set_state
from .evidence_fabric import status as fabric_status
from .institutional_intelligence import cached_status as institutional_status

POLICY="V680_ADAPTIVE_EVIDENCE_GATED_TRADING_ALGORITHM"
ACCURACY_TARGET=0.80
MIN_TARGET_SAMPLES=50
BOOKS=("INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","CIRCUIT_NEXTDAY","INTERNATIONAL","GLOBAL_INDIA_LONG","GLOBAL_INDIA_SHORT")


def _wilson(wins:int,n:int,z:float=1.96)->Tuple[Optional[float],Optional[float]]:
    if n<=0:return None,None
    p=wins/n;den=1+z*z/n
    center=(p+z*z/(2*n))/den
    margin=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/den
    return max(0.0,center-margin),min(1.0,center+margin)


def _strategy_manifest()->List[Dict[str,Any]]:
    try:
        with db(timeout_seconds=.75) as con:
            rows=con.execute(
                "SELECT s.strategy_id,s.family,s.horizon,s.side,s.status,s.version,s.updated_at,"
                "st.sample_count,st.score,st.holdout_avg_r,st.cost_adjusted_avg_r,st.decay_state "
                "FROM strategies s LEFT JOIN strategy_stats st ON st.strategy_id=s.strategy_id AND st.regime='ALL' "
                "WHERE s.status IN ('CHAMPION','SEED_CHAMPION') ORDER BY s.horizon,s.side,s.family,s.strategy_id"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:return []


def _manifest_hash(rows:List[Dict[str,Any]])->str:
    raw=json.dumps(rows,sort_keys=True,separators=(",",":"),default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _accuracy_rows()->List[Dict[str,Any]]:
    try:
        with db(timeout_seconds=.75) as con:
            rows=con.execute(
                "SELECT book,result,entry_price,current_price,side FROM recommendations "
                "WHERE state='CLOSED' AND result IN ('WIN','LOSS','MISS') ORDER BY COALESCE(closed_at,updated_at) DESC LIMIT 5000"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:return []


def _metrics(rows:List[Dict[str,Any]])->Dict[str,Any]:
    n=len(rows);wins=sum(1 for r in rows if str(r.get("result"))=="WIN")
    losses=sum(1 for r in rows if str(r.get("result"))=="LOSS");misses=sum(1 for r in rows if str(r.get("result"))=="MISS")
    positive=0;directional_n=0
    for r in rows:
        try:
            entry=float(r.get("entry_price") or 0);px=float(r.get("current_price") or 0)
            if entry<=0 or px<=0:continue
            directional_n+=1
            ret=(px/entry-1)*(1 if str(r.get("side")).upper()=="LONG" else -1)
            if ret>0:positive+=1
        except Exception:pass
    lo,hi=_wilson(wins,n)
    dlo,dhi=_wilson(positive,directional_n)
    rate=wins/n if n else None;dr=positive/directional_n if directional_n else None
    return {
        "sample_size":n,"wins":wins,"losses":losses,"misses":misses,
        "target_hit_rate":round(rate,4) if rate is not None else None,
        "target_hit_wilson_95":{"low":round(lo,4) if lo is not None else None,"high":round(hi,4) if hi is not None else None},
        "directional_sample_size":directional_n,
        "directional_accuracy":round(dr,4) if dr is not None else None,
        "directional_wilson_95":{"low":round(dlo,4) if dlo is not None else None,"high":round(dhi,4) if dhi is not None else None},
        "accuracy_target":ACCURACY_TARGET,
        "minimum_target_samples":MIN_TARGET_SAMPLES,
        "observed_target_met":bool(n>=MIN_TARGET_SAMPLES and rate is not None and rate>=ACCURACY_TARGET),
        "confidence_supported_80":bool(n>=MIN_TARGET_SAMPLES and lo is not None and lo>=ACCURACY_TARGET),
        "claim_policy":"80% is an evidence target, never a guaranteed or hard-coded accuracy claim.",
    }


def accuracy()->Dict[str,Any]:
    rows=_accuracy_rows();by=defaultdict(list)
    for r in rows:by[str(r.get("book") or "UNKNOWN")].append(r)
    return {"overall":_metrics(rows),"by_book":{k:_metrics(v) for k,v in sorted(by.items())}}


def _live_outputs()->Dict[str,Any]:
    out={b:[] for b in BOOKS}
    try:
        with db(timeout_seconds=.75) as con:
            rows=con.execute(
                "SELECT recommendation_id,book,period_key,symbol,exchange,side,score,confidence,entry_price,current_price,"
                "target_price,stop_price,target_pct,regime,created_at FROM recommendations WHERE state='LIVE' "
                "ORDER BY book,score DESC,created_at"
            ).fetchall()
        for r in rows:
            d=dict(r);b=str(d.get("book") or "")
            if b in out and len(out[b])<12:out[b].append(d)
    except Exception:pass
    return out


def snapshot(record:bool=False)->Dict[str,Any]:
    manifest=_strategy_manifest();mh=_manifest_hash(manifest);day=datetime.now(IST).date().isoformat()
    algo_version=f"{day.replace('-','')}-{mh[:10]}"
    acc=accuracy();overall=acc["overall"]
    by_status=defaultdict(int);by_family=defaultdict(int)
    for s in manifest:
        by_status[str(s.get("status") or "UNKNOWN")]+=1
        by_family[str(s.get("family") or "UNKNOWN")]+=1
    last_daily=get_state("last_daily_strategy_validation",{}) or {}
    last_weekly=get_state("last_weekly_strategy_validation",{}) or {}
    payload={
        "software_version":VERSION,
        "algorithm_version":algo_version,
        "policy":POLICY,
        "generated_at":now_iso(),
        "adaptive_manifest_hash":mh,
        "active_strategy_count":len(manifest),
        "strategy_status_counts":dict(by_status),
        "active_family_counts":dict(sorted(by_family.items())),
        "accuracy":acc,
        "accuracy_target":{
            "target":ACCURACY_TARGET,
            "minimum_samples":MIN_TARGET_SAMPLES,
            "status":"CONFIDENCE_SUPPORTED" if overall.get("confidence_supported_80") else (
                "OBSERVED_TARGET_MET_NOT_CONFIDENCE_SUPPORTED" if overall.get("observed_target_met") else "EVIDENCE_BUILDING_OR_BELOW_TARGET"
            ),
            "guaranteed":False,
        },
        "adaptation":{
            "cadence":"DAILY_AFTER_18_IST_ON_NSE_TRADING_DAYS_PLUS_SUNDAY_DEEP_VALIDATION",
            "last_daily_validation":last_daily,
            "last_weekly_validation":last_weekly,
            "rule":"Only strategies satisfying chronological OOS/holdout/cost/stability/shadow evidence can become Champions; live decay can suspend them.",
            "institutional_family":"CHALLENGER_ONLY_UNTIL_OOS_AND_LIVE_SHADOW_PROMOTION",
        },
        "outputs":_live_outputs(),
        "evidence_fabric":fabric_status(),
        "institutional_intelligence":institutional_status(),
        "execution_policy":"Algorithm publishes research/recommendations automatically; Groww orders remain explicit manual preview/confirm and all execution gates remain fail-closed.",
    }
    set_state("adaptive_algorithm_current",{
        "algorithm_version":algo_version,"generated_at":payload["generated_at"],"accuracy":overall,
        "active_strategy_count":len(manifest),"manifest_hash":mh,"policy":POLICY,
    })
    if record:_record(payload)
    return payload


def _record(payload:Dict[str,Any])->None:
    a=payload.get("accuracy",{}).get("overall",{}) or {}
    try:
        with db(timeout_seconds=1.0) as con:
            con.execute(
                "INSERT OR IGNORE INTO algorithm_versions(algorithm_version,day,generated_at,manifest_hash,active_strategy_count,"
                "accuracy_target,observed_accuracy,wilson_low,wilson_high,sample_size,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (payload["algorithm_version"],datetime.now(IST).date().isoformat(),payload["generated_at"],
                 payload.get("adaptive_manifest_hash"),int(payload.get("active_strategy_count") or 0),ACCURACY_TARGET,
                 a.get("target_hit_rate"),(a.get("target_hit_wilson_95") or {}).get("low"),(a.get("target_hit_wilson_95") or {}).get("high"),
                 int(a.get("sample_size") or 0),json.dumps(payload,separators=(",",":"),default=str)),
            )
    except Exception:pass


def refresh()->Dict[str,Any]:
    return snapshot(record=True)


def history(limit:int=30)->List[Dict[str,Any]]:
    try:
        with db(timeout_seconds=.5) as con:
            rs=con.execute(
                "SELECT algorithm_version,day,generated_at,manifest_hash,active_strategy_count,accuracy_target,"
                "observed_accuracy,wilson_low,wilson_high,sample_size FROM algorithm_versions "
                "ORDER BY generated_at DESC LIMIT ?",(max(1,min(int(limit),365)),)
            ).fetchall()
        return [dict(r) for r in rs]
    except Exception:return []


def status()->Dict[str,Any]:
    out=snapshot(record=False);out["version_history"]=history(30);return out
