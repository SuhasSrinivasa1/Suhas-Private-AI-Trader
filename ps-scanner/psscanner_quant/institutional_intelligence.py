from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional

import requests

from .constants import IST
from .db import db, health, get_state, now_iso, set_state

POLICY = "V680_INSTITUTIONAL_FLOW_POINT_IN_TIME_ADVISORY"
NSE_BASE = "https://www.nseindia.com"
FII_DII_API = "/api/fiidiiTradeReact"
LARGE_DEAL_API = "/api/snapshot-capital-market-largedeal"

_LOCK=RLock()
_CACHE:Dict[str,Any]={}
_SESSION=requests.Session()
_SESSION.headers.update({
    "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36",
    "Accept":"application/json,text/plain,*/*",
    "Accept-Language":"en-US,en;q=0.9",
    "Referer":"https://www.nseindia.com/",
})


def _f(v:Any,default:float=0.0)->float:
    try:
        x=float(str(v).replace(",","").strip())
        return x if math.isfinite(x) else default
    except Exception:return default


def _nse_json(path:str,timeout:float=4.0)->Any:
    # NSE commonly requires a homepage cookie before API calls. Keep this entirely in the
    # dedicated producer so scanner threads never perform exchange HTTP requests.
    try:
        if not _SESSION.cookies:
            _SESSION.get(NSE_BASE,timeout=min(3.0,timeout))
    except Exception:
        pass
    r=_SESSION.get(NSE_BASE+path,timeout=timeout)
    r.raise_for_status()
    return r.json()


def _flow_rows(payload:Any)->List[Dict[str,Any]]:
    if isinstance(payload,list):return [dict(x) for x in payload if isinstance(x,dict)]
    if isinstance(payload,dict):
        for k in ("data","rows","fiiDii","fii_dii"):
            v=payload.get(k)
            if isinstance(v,list):return [dict(x) for x in v if isinstance(x,dict)]
    return []


def _parse_flows(payload:Any)->Dict[str,Any]:
    rows=_flow_rows(payload);out={}
    for r in rows:
        label=str(r.get("category") or r.get("type") or r.get("clientType") or r.get("name") or "").upper()
        if "FII" in label or "FPI" in label:key="FII_FPI"
        elif "DII" in label:key="DII"
        else:continue
        buy=_f(r.get("buyValue") if r.get("buyValue") is not None else r.get("buy_value"))
        sell=_f(r.get("sellValue") if r.get("sellValue") is not None else r.get("sell_value"))
        net=_f(r.get("netValue") if r.get("netValue") is not None else r.get("net_value"),buy-sell)
        out[key]={"buy_crore":buy,"sell_crore":sell,"net_crore":net,
                  "date":r.get("date") or r.get("tradeDate") or r.get("asOnDate"),"raw":r}
    return out


def _iter_lists(obj:Any,path:str="")->Iterable[tuple[str,List[Dict[str,Any]]]]:
    if isinstance(obj,dict):
        for k,v in obj.items():
            p=f"{path}.{k}" if path else str(k)
            if isinstance(v,list) and any(isinstance(x,dict) for x in v):
                yield p,[dict(x) for x in v if isinstance(x,dict)]
            else:
                yield from _iter_lists(v,p)
    elif isinstance(obj,list):
        for i,v in enumerate(obj):
            yield from _iter_lists(v,f"{path}[{i}]")


def _parse_large_deals(payload:Any)->List[Dict[str,Any]]:
    out=[]
    for path,rows in _iter_lists(payload):
        lp=path.lower()
        kind="BLOCK" if "block" in lp else ("BULK" if "bulk" in lp else ("SHORT_SELL" if "short" in lp else "LARGE_DEAL"))
        for r in rows:
            sym=str(r.get("symbol") or r.get("tradingSymbol") or r.get("security") or "").upper()
            if not sym:continue
            side=str(r.get("buySell") or r.get("buy_sell") or r.get("side") or r.get("transactionType") or "").upper()
            qty=_f(r.get("quantity") if r.get("quantity") is not None else r.get("qty"))
            px=_f(r.get("price") if r.get("price") is not None else r.get("tradePrice"))
            client=str(r.get("clientName") or r.get("client") or r.get("name") or "")
            out.append({"symbol":sym,"kind":kind,"side":side,"quantity":qty,"price":px,
                        "value_rupees":round(qty*px,2) if qty and px else None,"client":client[:160],"raw":r})
    # Deduplicate identical nested views.
    seen=set();dedup=[]
    for x in out:
        key=(x["symbol"],x["kind"],x["side"],x["quantity"],x["price"],x["client"])
        if key in seen:continue
        seen.add(key);dedup.append(x)
    return dedup


def _persist_snapshot(payload:Dict[str,Any])->None:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str)
    digest=hashlib.sha256(raw.encode()).hexdigest()
    try:
        with db(timeout_seconds=1.0) as con:
            con.execute(
                "INSERT OR IGNORE INTO institutional_snapshots(snapshot_id,captured_at,source,payload_hash,payload_json) "
                "VALUES(?,?,?,?,?)",
                (digest[:32],payload.get("captured_at") or now_iso(),"NSE_OFFICIAL_PLUS_LOCAL_OHLCV",digest,raw),
            )
    except Exception as exc:
        health("institutional_intelligence","WARN",f"snapshot persistence: {str(exc)[:160]}")


def refresh(force:bool=False)->Dict[str,Any]:
    now=datetime.now(IST)
    with _LOCK:
        old=dict(_CACHE)
        try:
            ts=datetime.fromisoformat(str(old.get("captured_at"))) if old.get("captured_at") else None
            if ts and not force and now-ts<timedelta(minutes=5):return old
        except Exception:pass
    errors=[];flows={};deals=[]
    try:flows=_parse_flows(_nse_json(FII_DII_API))
    except Exception as exc:errors.append("fii_dii:"+str(exc)[:180])
    try:deals=_parse_large_deals(_nse_json(LARGE_DEAL_API))
    except Exception as exc:errors.append("large_deals:"+str(exc)[:180])
    out={
        "captured_at":now_iso(),
        "flows":flows,
        "large_deals":deals[:1200],
        "large_deal_count":len(deals),
        "status":"READY" if (flows or deals) else ("STALE_FALLBACK" if old else "UNAVAILABLE"),
        "errors":errors,
        "policy":POLICY,
        "sources":{
            "fii_dii":"NSE FII/FPI & DII trading activity",
            "large_deals":"NSE Bulk/Block Deals & Short Selling",
        },
        "scope_note":"Market-level FII/DII flow is not treated as proof that a specific stock is institutionally bought/sold.",
    }
    if not flows and old.get("flows"):out["flows"]=old.get("flows") or {}
    if not deals and old.get("large_deals"):out["large_deals"]=old.get("large_deals") or [];out["large_deal_count"]=len(out["large_deals"])
    with _LOCK:
        _CACHE.clear();_CACHE.update(out)
    set_state("institutional_intelligence",out)
    _persist_snapshot(out)
    if errors:health("institutional_intelligence","WARN","; ".join(errors)[:240])
    return dict(out)


def cached_status()->Dict[str,Any]:
    with _LOCK:
        if _CACHE:return dict(_CACHE)
    state=get_state("institutional_intelligence",{}) or {}
    if state:
        with _LOCK:
            if not _CACHE:_CACHE.update(dict(state))
            return dict(_CACHE)
    return {}


def _deal_signal(symbol:str,deals:List[Dict[str,Any]])->Dict[str,Any]:
    sym=symbol.upper();rows=[x for x in deals if str(x.get("symbol") or "").upper()==sym]
    buy=sell=0.0
    for x in rows:
        val=_f(x.get("value_rupees"),_f(x.get("quantity"))*_f(x.get("price")))
        side=str(x.get("side") or "").upper()
        if "BUY" in side or side in ("B","PURCHASE"):buy+=val
        elif "SELL" in side or side in ("S","SALE"):sell+=val
    net=buy-sell
    return {"rows":rows[:20],"buy_value_rupees":round(buy,2),"sell_value_rupees":round(sell,2),
            "net_value_rupees":round(net,2),"direction":"BUY" if net>0 else ("SELL" if net<0 else "NEUTRAL")}


def context(symbol:str, *, features:Optional[Dict[str,Any]]=None,
            fundamentals:Optional[Dict[str,Any]]=None)->Dict[str,Any]:
    """Return auditable institutional/accumulation evidence without making identity claims."""
    state=cached_status();features=features or {};fundamentals=fundamentals or {}
    cmf=_f(features.get("cmf20"));mfi=_f(features.get("mfi14"),50.0);obv=_f(features.get("obv_trend5"))
    vr=_f(features.get("volume_ratio"),1.0);ownership=_f(fundamentals.get("heldPercentInstitutions"),-1)
    deal=_deal_signal(symbol,list(state.get("large_deals") or []))
    # Price/volume accumulation indicators are evidence of flow behavior, not the identity of
    # the buyer. Keep them separate from direct exchange large-deal evidence.
    technical=0.0
    technical+=max(-30,min(30,cmf*100.0))
    technical+=max(-20,min(20,(mfi-50.0)*0.8))
    technical+=max(-20,min(20,obv*20.0))
    technical+=max(-10,min(10,(vr-1.0)*8.0))
    deal_net=_f(deal.get("net_value_rupees"))
    direct=0.0
    if deal_net:
        direct=(1 if deal_net>0 else -1)*min(20.0,4.0+math.log10(max(1.0,abs(deal_net)))*2.0)
    flows=state.get("flows") or {}
    market_net=_f((flows.get("FII_FPI") or {}).get("net_crore"))+_f((flows.get("DII") or {}).get("net_crore"))
    market_context=max(-6.0,min(6.0,market_net/1000.0))
    score=max(-100.0,min(100.0,technical+direct+market_context))
    available=sum([1 if features.get("cmf20") is not None else 0,1 if features.get("mfi14") is not None else 0,
                   1 if features.get("obv_trend5") is not None else 0,1 if ownership>=0 else 0,1 if deal.get("rows") else 0])
    confidence=min(1.0,available/5.0)
    direction="ACCUMULATION" if score>=18 else ("DISTRIBUTION" if score<=-18 else ("NEUTRAL" if available else "UNKNOWN"))
    return {
        "symbol":symbol.upper(),"direction":direction,"score":round(score,2),"confidence":round(confidence,3),
        "accumulation_indicators":{"cmf20":round(cmf,4),"mfi14":round(mfi,2),"obv_trend5":round(obv,4),"volume_ratio":round(vr,3)},
        "institutional_ownership":None if ownership<0 else round(ownership,5),
        "large_deal_evidence":deal,
        "market_flow":{"FII_FPI":flows.get("FII_FPI"),"DII":flows.get("DII"),"combined_net_crore":round(market_net,2),"score_contribution":round(market_context,2)},
        "source_status":state.get("status") or "UNKNOWN","captured_at":state.get("captured_at"),
        "policy":POLICY,
        "identity_caution":"OHLCV accumulation does not identify the buyer; only direct exchange disclosures are labeled direct evidence.",
        "live_scoring_mode":"ADVISORY_UNTIL_CHALLENGER_OOS_PROMOTION",
    }


def point_in_time_history(limit:int=60)->List[Dict[str,Any]]:
    try:
        with db(timeout_seconds=.5) as con:
            rs=con.execute("SELECT captured_at,source,payload_json FROM institutional_snapshots ORDER BY captured_at DESC LIMIT ?",(max(1,min(int(limit),500)),)).fetchall()
        out=[]
        for r in rs:
            try:p=json.loads(r[2] or "{}")
            except Exception:p={}
            out.append({"captured_at":r[0],"source":r[1],"payload":p})
        return out
    except Exception:return []
