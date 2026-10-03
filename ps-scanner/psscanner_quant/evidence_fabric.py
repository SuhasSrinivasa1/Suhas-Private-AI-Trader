from __future__ import annotations

import json
import time
from datetime import datetime
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional

from .constants import IST
from .db import db, get_state, now_iso, set_state
from .event_calendar import risk_context as event_risk_context
from .institutional_intelligence import context as institutional_context, cached_status as institutional_status
from .news_context import context as news_context
from .sector_context import context_cached as sector_context_cached

FABRIC_POLICY = "V680_ONE_OBSERVATION_MANY_CONSUMERS"
_LOCK = RLock()
_DOMAINS: Dict[str, Dict[str, Any]] = {}

_DEFAULT_TTL = {
    "priority_quotes": 75.0,
    "full_market_quotes": 240.0,
    "market_regime": 240.0,
    "global_context": 1200.0,
    "fundamentals": 900.0,
    "sector_context": 1200.0,
    "news": 900.0,
    "events": 43200.0,
    "institutional": 600.0,
    "international_daily": 900.0,
    "international_intraday": 180.0,
    "algorithm": 900.0,
}


def publish(domain: str, *, source: str, consumers: Iterable[str], payload: Optional[Dict[str, Any]] = None,
            network_fetch: bool = False, ttl_seconds: Optional[float] = None, symbols: Optional[int] = None) -> Dict[str, Any]:
    """Publish one producer observation for many cache-only consumers.

    Payloads here are metadata/status only. Heavy price/history datasets remain in their
    existing optimized caches; this fabric records who produced them, freshness and reuse.
    """
    name=str(domain)
    now=time.time()
    with _LOCK:
        prev=dict(_DOMAINS.get(name) or {})
        entry={
            "domain":name,
            "source":str(source),
            "captured_at":now_iso(),
            "captured_epoch":now,
            "ttl_seconds":float(ttl_seconds if ttl_seconds is not None else _DEFAULT_TTL.get(name,900.0)),
            "network_fetch":bool(network_fetch),
            "consumers":sorted({str(x) for x in consumers if x}),
            "symbols":int(symbols) if symbols is not None else None,
            "payload":dict(payload or {}),
            "producer_runs":int(prev.get("producer_runs") or 0)+1,
            "network_fetch_runs":int(prev.get("network_fetch_runs") or 0)+(1 if network_fetch else 0),
            "policy":FABRIC_POLICY,
        }
        _DOMAINS[name]=entry
    # Persist a compact copy for restart diagnostics. Failure is telemetry-only.
    set_state("evidence_fabric:"+name,{k:v for k,v in entry.items() if k!="captured_epoch"})
    return dict(entry)


def _persisted_domains() -> Dict[str,Dict[str,Any]]:
    names=list(_DEFAULT_TTL)
    out={}
    try:
        marks=",".join("?" for _ in names)
        keys=["evidence_fabric:"+x for x in names]
        marks=",".join("?" for _ in keys)
        with db(timeout_seconds=.25) as con:
            rows=con.execute(f"SELECT key,value_json FROM system_state WHERE key IN ({marks})",tuple(keys)).fetchall()
        for row in rows:
            try:
                d=json.loads(row[1] or "{}");out[str(row[0]).split(":",1)[1]]=d
            except Exception:
                pass
    except Exception:
        pass
    return out


def status() -> Dict[str, Any]:
    now=time.time()
    with _LOCK:
        mem={k:dict(v) for k,v in _DOMAINS.items()}
    persisted=_persisted_domains()
    all_names=sorted(set(_DEFAULT_TTL)|set(persisted)|set(mem))
    domains={}
    for name in all_names:
        d=dict(mem.get(name) or persisted.get(name) or {})
        captured_epoch=d.get("captured_epoch")
        if captured_epoch is None:
            try:
                captured_epoch=datetime.fromisoformat(str(d.get("captured_at"))).timestamp()
            except Exception:
                captured_epoch=None
        age=max(0.0,now-float(captured_epoch)) if captured_epoch is not None else None
        ttl=float(d.get("ttl_seconds") or _DEFAULT_TTL.get(name,900.0))
        d["age_seconds"]=round(age,1) if age is not None else None
        d["fresh"]=bool(age is not None and age<=ttl)
        d.pop("captured_epoch",None)
        domains[name]=d
    fresh=sum(1 for x in domains.values() if x.get("fresh"))
    return {
        "policy":FABRIC_POLICY,
        "mode":"SHARED_PRODUCERS_CACHE_ONLY_CONSUMERS",
        "domains":domains,
        "fresh_domains":fresh,
        "domain_count":len(domains),
        "principle":"Network/broker observations are produced once at their natural cadence and reused by every scanner lane.",
        "frequency_policy":"No scanner cadence is reduced by the fabric; producer freshness is independent of consumer scan frequency.",
    }


def priority_symbols(limit: int = 160) -> List[str]:
    """Return a deterministic shared priority set without network access."""
    out=[]
    try:
        with db(timeout_seconds=.35) as con:
            for r in con.execute(
                "SELECT symbol FROM recommendations WHERE state='LIVE' AND exchange='NSE' "
                "ORDER BY updated_at DESC,score DESC LIMIT ?",(max(1,int(limit)),)
            ).fetchall():
                s=str(r[0] or "").upper()
                if s and s not in out:out.append(s)
    except Exception:
        pass
    # Add current full-breadth movers so news/event/fundamental producers work on the same
    # high-information names even before they become recommendations.
    breadth=get_state("full_breadth_discovery",{}) or {}
    for row in list(breadth.get("top_absolute_movers") or [])+list(breadth.get("top_turnover") or []):
        s=str((row or {}).get("symbol") or "").upper()
        if s and s not in out:out.append(s)
        if len(out)>=limit:break
    return out[:max(1,int(limit))]


def symbol_context(symbol: str, *, book: str, side: str, features: Dict[str,Any],
                   fundamentals: Optional[Dict[str,Any]]=None) -> Dict[str,Any]:
    """Compose all non-network per-symbol evidence from the shared fabric/caches."""
    sym=str(symbol).upper()
    fundamentals=fundamentals or {}
    return {
        "global":get_state("global_context",{}) or {"risk_state":"UNKNOWN","stale":True},
        "sector":sector_context_cached(sym,side),
        "news":news_context(sym,allow_refresh=False),
        "events":event_risk_context(sym,book),
        "institutional":institutional_context(sym,features=features,fundamentals=fundamentals),
        "fabric_policy":FABRIC_POLICY,
        "network_calls":False,
    }


def cached_institutional_status() -> Dict[str,Any]:
    return institutional_status()
