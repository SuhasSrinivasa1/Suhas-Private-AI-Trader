from __future__ import annotations

import statistics
import time
from threading import RLock
from typing import Any, Dict, List

from .data import universe, history, _history_path
from .features import latest_features
from .db import health

_CACHE: Dict[str, Any] = {"at":0.0,"snapshot":{}}
_LOCK=RLock()


def _industry_map() -> Dict[str,List[str]]:
    out:Dict[str,List[str]]={}
    for r in universe():
        ind=str(r.get("industry") or r.get("sector") or "UNKNOWN").strip() or "UNKNOWN"
        if ind.upper()=="UNKNOWN":continue
        out.setdefault(ind,[]).append(str(r.get("symbol") or "").upper())
    return out


def _feat(sym:str)->Dict[str,Any]:
    try:
        # Breadth must not turn one scan into hundreds of network requests. Use the
        # daily histories already maintained by the shared cache/bootstrap layer.
        if not _history_path(sym,"1day").exists():return {}
        df=history(sym,"1day",allow_network=False)
        return latest_features(df) if len(df)>=25 else {}
    except Exception:
        return {}


def build_snapshot(ttl_seconds:int=900, max_peers_per_industry:int=20) -> Dict[str,Any]:
    if _CACHE["snapshot"] and time.time()-float(_CACHE["at"])<ttl_seconds:
        return _CACHE["snapshot"]
    with _LOCK:
        if _CACHE["snapshot"] and time.time()-float(_CACHE["at"])<ttl_seconds:
            return _CACHE["snapshot"]
        snap={}
        try:
            for industry,syms in _industry_map().items():
                moves=[];ret20s=[];above20=0;trend_up=0;trend_down=0;n=0
                for s in syms[:max_peers_per_industry]:
                    f=_feat(s)
                    if not f:continue
                    n+=1;moves.append(float(f.get("ret1") or 0));ret20s.append(float(f.get("ret20") or 0))
                    if float(f.get("close") or 0)>float(f.get("sma20") or 1e99):above20+=1
                    tr=float(f.get("trend") or 0)
                    if tr>0:trend_up+=1
                    elif tr<0:trend_down+=1
                if n:
                    snap[industry]={"industry":industry,"sample":n,"members":len(syms),"median_move_pct":round(statistics.median(moves),3) if moves else 0.0,"median_ret20_pct":round(statistics.median(ret20s),3) if ret20s else 0.0,"positive_pct":round(100*sum(1 for x in moves if x>0)/n,1),"above_sma20_pct":round(100*above20/n,1),"trend_up_pct":round(100*trend_up/n,1),"trend_down_pct":round(100*trend_down/n,1)}
        except Exception as exc:
            health("sector_context","WARN",str(exc)[:180])
        _CACHE["at"]=time.time();_CACHE["snapshot"]=snap
        return snap


def context(symbol:str, side:str="LONG", build_if_missing:bool=True) -> Dict[str,Any]:
    sym=symbol.upper();row=next((x for x in universe() if str(x.get("symbol") or "").upper()==sym),{})
    industry=str(row.get("industry") or row.get("sector") or "UNKNOWN")
    snap=dict(_CACHE.get("snapshot") or {})
    if not snap and build_if_missing:
        snap=build_snapshot()
    s=snap.get(industry) or {}
    f=_feat(sym)
    if not s or not f:
        return {"status":"UNKNOWN","industry":industry,"reason":"sector peer snapshot not ready; scanner does not block to rebuild it"}
    sign=1 if side.upper()=="LONG" else -1
    stock_ret=float(f.get("ret20") or 0)
    supportive=(s.get("trend_up_pct",0)>=50 if sign>0 else s.get("trend_down_pct",0)>=50)
    relative=stock_ret-float(s.get("median_ret20_pct") or 0)
    return {**s,"status":"PASS" if supportive else "WARN","symbol":sym,"stock_ret20_pct":round(stock_ret,3),"stock_vs_industry_ret20_pct":round(relative,3),"supportive":supportive,"source":"FULL_NSE_MAPPED_INDUSTRY_PLUS_CACHED_DAILY_BREADTH"}

def context_cached(symbol:str, side:str="LONG") -> Dict[str,Any]:
    return context(symbol,side,build_if_missing=False)


def status()->Dict[str,Any]:
    snap=build_snapshot();return {"industries_ready":len(snap),"source":"FULL_NSE_MAPPED_INDUSTRY_PLUS_CACHED_DAILY_BREADTH","top":sorted(snap.values(),key=lambda x:x.get("sample",0),reverse=True)[:20]}

def status_cached()->Dict[str,Any]:
    snap=dict(_CACHE.get("snapshot") or {})
    return {"industries_ready":len(snap),"source":"FULL_NSE_MAPPED_INDUSTRY_PLUS_CACHED_DAILY_BREADTH","top":sorted(snap.values(),key=lambda x:x.get("sample",0),reverse=True)[:20],"cached":True,"cache_age_seconds":round(max(0.0,time.time()-float(_CACHE.get("at") or 0)),1) if _CACHE.get("at") else None}
