from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from .config import load_settings
from .db import db, health, now_iso

_FIELDS = [
    "marketCap","enterpriseValue","trailingPE","forwardPE","priceToBook","enterpriseToEbitda","enterpriseToRevenue",
    "returnOnEquity","returnOnAssets","profitMargins","operatingMargins","grossMargins","ebitdaMargins",
    "revenueGrowth","earningsGrowth","earningsQuarterlyGrowth","revenuePerShare","freeCashflow","operatingCashflow",
    "totalCash","totalDebt","debtToEquity","currentRatio","quickRatio","dividendYield","payoutRatio","beta",
    "sharesOutstanding","floatShares","heldPercentInsiders","heldPercentInstitutions","bookValue","targetMeanPrice",
    "targetHighPrice","targetLowPrice","recommendationMean","recommendationKey","numberOfAnalystOpinions",
    "earningsTimestamp","earningsTimestampStart","earningsTimestampEnd","mostRecentQuarter",
]


def _clean_payload(payload: Dict[str,Any]) -> Dict[str,Any]:
    return {k:v for k,v in payload.items() if not str(k).startswith("_")}


def _snapshot(symbol:str, ts:str, source:str, payload:Dict[str,Any]) -> None:
    clean=_clean_payload(payload)
    raw=json.dumps(clean,sort_keys=True,separators=(",",":"),default=str)
    digest=hashlib.sha256(raw.encode()).hexdigest()
    with db() as con:
        # De-duplicate identical consecutive observations while still preserving real revisions.
        last=con.execute("SELECT payload_hash FROM fundamental_snapshots WHERE symbol=? ORDER BY asof DESC LIMIT 1",(symbol.upper(),)).fetchone()
        if last and last[0]==digest:return
        con.execute("INSERT OR IGNORE INTO fundamental_snapshots(symbol,asof,source,payload_hash,payload_json) VALUES(?,?,?,?,?)",(symbol.upper(),ts,source,digest,raw))


def get_cached(symbol: str) -> Optional[Dict[str,Any]]:
    with db() as con:
        r=con.execute("SELECT * FROM fundamentals_cache WHERE symbol=?",(symbol.upper(),)).fetchone()
    if not r:return None
    d=dict(r)
    try:
        asof=datetime.fromisoformat(d["asof"])
        if asof.tzinfo is None:asof=asof.astimezone()
        ttl=timedelta(hours=float(load_settings().get("fundamentals_ttl_hours",24)))
        if datetime.now(asof.tzinfo)-asof>ttl:return None
        payload=json.loads(d["payload_json"] or "{}")
        payload["_source"]=d["source"];payload["_asof"]=d["asof"]
        return payload
    except Exception:return None


def get_asof(symbol:str, at:datetime) -> Dict[str,Any]:
    """Return only information that had actually been captured by the requested timestamp.

    This enables prospective point-in-time fundamental validation without leaking today's
    fundamentals backward into older backtests. Before enough snapshots accumulate this
    intentionally returns an empty dict for historical dates.
    """
    iso=at.isoformat()
    with db() as con:
        r=con.execute("SELECT asof,source,payload_json FROM fundamental_snapshots WHERE symbol=? AND asof<=? ORDER BY asof DESC LIMIT 1",(symbol.upper(),iso)).fetchone()
    if not r:return {}
    try:d=json.loads(r[2] or "{}")
    except Exception:d={}
    d["_asof"]=r[0];d["_source"]=r[1];d["_point_in_time"]=True
    return d


def refresh(symbol: str) -> Dict[str,Any]:
    ticker=symbol.upper()+".NS"
    try:
        import yfinance as yf
        t=yf.Ticker(ticker);info=t.info or {}
        payload={k:info.get(k) for k in _FIELDS if info.get(k) is not None}
        payload["currency"]=info.get("currency")
        payload["sector"]=info.get("sector")
        payload["industry"]=info.get("industry")
        payload["shortName"]=info.get("shortName")
        # Some yfinance versions expose analyst targets through a separate endpoint.
        try:
            targets=t.get_analyst_price_targets() or {}
            if isinstance(targets,dict):
                for src,dst in (("mean","targetMeanPrice"),("high","targetHighPrice"),("low","targetLowPrice"),("current","analystCurrentPrice")):
                    if targets.get(src) is not None:payload[dst]=targets.get(src)
        except Exception:pass
        ts=now_iso();source="YAHOO_FINANCE_PUBLIC_POINT_IN_TIME_CAPTURE"
        with db() as con:
            con.execute("INSERT INTO fundamentals_cache(symbol,asof,source,payload_json) VALUES(?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET asof=excluded.asof,source=excluded.source,payload_json=excluded.payload_json",(symbol.upper(),ts,source,json.dumps(payload,separators=(",",":"),default=str)))
        _snapshot(symbol,ts,source,payload)
        payload["_source"]=source;payload["_asof"]=ts;payload["_point_in_time"]=True
        return payload
    except Exception as exc:
        health("fundamentals","WARN",f"{symbol}: {exc}")
        return {}


def get(symbol: str, allow_refresh: bool=True) -> Dict[str,Any]:
    c=get_cached(symbol)
    if c is not None:return c
    return refresh(symbol) if allow_refresh else {}


def quality_score(f: Dict[str,Any]) -> float:
    if not f:return 0.0
    score=50.0
    def num(k,d=0.0):
        try:return float(f.get(k))
        except Exception:return d
    roe=num("returnOnEquity");growth=num("revenueGrowth");earn=num("earningsGrowth");debt=num("debtToEquity",999);fcf=num("freeCashflow");ocf=num("operatingCashflow");margin=num("profitMargins")
    if roe>0.15:score+=10
    elif roe<0:score-=12
    if growth>0.10:score+=9
    elif growth<0:score-=7
    if earn>0.10:score+=8
    elif earn<0:score-=7
    if debt<80:score+=6
    elif debt>200:score-=8
    if fcf>0:score+=5
    if ocf>0:score+=5
    if margin>0.1:score+=5
    return max(0,min(100,score))


def refresh_batch(symbols, limit: int = 4) -> Dict[str, Any]:
    from .db import get_state, set_state
    syms=list(symbols or [])
    if not syms:return {"attempted":0,"ready":0}
    cursor=int(get_state("fundamentals_cursor",0) or 0)%len(syms)
    chosen=[syms[(cursor+i)%len(syms)] for i in range(min(limit,len(syms)))]
    ready=0
    for s in chosen:
        if refresh(s):ready+=1
    set_state("fundamentals_cursor",(cursor+len(chosen))%len(syms))
    return {"attempted":len(chosen),"ready":ready,"cursor":cursor}


def snapshot_status()->Dict[str,Any]:
    with db() as con:
        total=con.execute("SELECT COUNT(*) FROM fundamental_snapshots").fetchone()[0]
        symbols=con.execute("SELECT COUNT(DISTINCT symbol) FROM fundamental_snapshots").fetchone()[0]
        first=con.execute("SELECT MIN(asof) FROM fundamental_snapshots").fetchone()[0]
        last=con.execute("SELECT MAX(asof) FROM fundamental_snapshots").fetchone()[0]
    return {"snapshots":total,"symbols":symbols,"first_asof":first,"last_asof":last,"mode":"PROSPECTIVE_POINT_IN_TIME_CAPTURE","historical_backtest_policy":"Only snapshots captured by the decision timestamp are eligible; current fundamentals are never backfilled into the past."}


def snapshot_history(symbol:str)->list[tuple[datetime,Dict[str,Any]]]:
    with db() as con:
        rs=con.execute("SELECT asof,source,payload_json FROM fundamental_snapshots WHERE symbol=? ORDER BY asof",(symbol.upper(),)).fetchall()
    out=[]
    for r in rs:
        try:
            dt=datetime.fromisoformat(r[0]);payload=json.loads(r[2] or '{}');payload['_asof']=r[0];payload['_source']=r[1];payload['_point_in_time']=True;out.append((dt,payload))
        except Exception:pass
    return out


def resolve_snapshot(history_rows:list[tuple[datetime,Dict[str,Any]]], at:datetime)->Dict[str,Any]:
    best={}
    # Snapshot counts are intentionally modest; linear scan avoids timezone/bisect edge cases.
    for dt,payload in history_rows:
        try:
            a=at
            if getattr(a,'tzinfo',None) is None and dt.tzinfo is not None:a=a.replace(tzinfo=dt.tzinfo)
            if dt<=a:best=payload
            else:break
        except Exception:continue
    return dict(best)
