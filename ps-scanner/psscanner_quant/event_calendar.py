from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .constants import IST
from .db import db, health, now_iso, get_state, set_state
from .trading_calendar import holiday_map, NSE_HOLIDAY_SOURCE


def _id(kind:str, title:str, starts_at:str, symbol:str="") -> str:
    return hashlib.sha256(f"{kind}|{title}|{starts_at}|{symbol}".encode()).hexdigest()[:28]


def upsert_event(*,kind:str,title:str,starts_at:str,ends_at:Optional[str]=None,impact:str="MEDIUM",source:str="LOCAL",source_url:Optional[str]=None,symbol:Optional[str]=None,payload:Optional[Dict[str,Any]]=None)->None:
    eid=_id(kind,title,starts_at,symbol or "")
    with db() as con:
        con.execute("INSERT INTO market_events(event_id,kind,title,starts_at,ends_at,impact,source,source_url,symbol,payload_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET ends_at=excluded.ends_at,impact=excluded.impact,source=excluded.source,source_url=excluded.source_url,payload_json=excluded.payload_json,updated_at=excluded.updated_at",(eid,kind,title,starts_at,ends_at,impact,source,source_url,symbol,json.dumps(payload or {},default=str,separators=(',',':')),now_iso()))


RBI_MPC_SCHEDULE_SOURCE = "RBI Monetary Policy Committee schedule 2026-27"
RBI_MPC_SCHEDULE_URL = "https://www.rbi.org.in/"
# Decision dates from RBI's published 2026-27 MPC calendar. These are persisted as
# known high-impact macro events; other macro releases remain UNKNOWN until added.
_RBI_MPC_DECISION_DATES = {
    "2026-04-08": "RBI MPC policy decision",
    "2026-06-05": "RBI MPC policy decision",
    "2026-08-05": "RBI MPC policy decision",
    "2026-10-07": "RBI MPC policy decision",
    "2026-12-04": "RBI MPC policy decision",
    "2027-02-05": "RBI MPC policy decision",
}


def seed_official_calendar()->int:
    n=0
    for d,title in holiday_map(2026).items():
        starts=datetime(d.year,d.month,d.day,0,0,tzinfo=IST).isoformat()
        upsert_event(kind="NSE_HOLIDAY",title=title,starts_at=starts,impact="HIGH",source="NSE_OFFICIAL",source_url=NSE_HOLIDAY_SOURCE,payload={"regular_equity_session":False});n+=1
    for ds,title in _RBI_MPC_DECISION_DATES.items():
        d=datetime.fromisoformat(ds).date()
        starts=datetime(d.year,d.month,d.day,10,0,tzinfo=IST).isoformat()
        upsert_event(kind="RBI_MPC",title=title,starts_at=starts,impact="HIGH",source="RBI_OFFICIAL_SCHEDULE",source_url=RBI_MPC_SCHEDULE_URL,payload={"scheduled":True,"decision_day":True});n+=1
    return n


def refresh_symbol_event(symbol:str, min_refresh_hours:float=12.0)->Dict[str,Any]:
    """Capture currently-known earnings dates prospectively.

    Yahoo is used only as a discovery provider here. Every observation is timestamped and
    persisted; historical backtests only use snapshots/events that existed by that timestamp.
    Per-symbol refresh is throttled because an earnings calendar changes far more slowly than
    the five-minute market scan.
    """
    sym=symbol.upper();out={"symbol":sym,"events":0,"source":"YAHOO_FINANCE_PUBLIC"}
    state_key=f"event_refresh:{sym}"
    last=get_state(state_key,{}) or {}
    try:
        at=last.get("at") if isinstance(last,dict) else None
        if at and datetime.now(IST)-datetime.fromisoformat(at)<timedelta(hours=float(min_refresh_hours)):
            return {"symbol":sym,"events":int(last.get("events") or 0),"source":"YAHOO_FINANCE_PUBLIC","cached":True,"last_refresh":at}
    except Exception:pass
    try:
        import yfinance as yf
        cal=yf.Ticker(sym+".NS").calendar
        items=[]
        if hasattr(cal,"to_dict"): items=cal.to_dict()
        elif isinstance(cal,dict):items=cal
        raw=items or {}
        candidates=[]
        for raw_key,val in raw.items():
            if "earning" not in str(raw_key).lower():continue
            values=val if isinstance(val,(list,tuple)) else [val]
            for v in values:
                try:
                    dt=v.to_pydatetime() if hasattr(v,"to_pydatetime") else datetime.fromisoformat(str(v).replace('Z','+00:00'))
                    if dt.tzinfo is None:dt=dt.replace(tzinfo=IST)
                    dt=dt.astimezone(IST);candidates.append(dt)
                except Exception:pass
        for dt in candidates:
            if dt < datetime.now(IST)-timedelta(days=2):continue
            upsert_event(kind="CORPORATE_EARNINGS",title=f"{sym} earnings",starts_at=dt.isoformat(),impact="HIGH",source="YAHOO_FINANCE_PUBLIC",symbol=sym,payload={"captured_at":now_iso()});out["events"]+=1
        set_state(state_key,{"at":datetime.now(IST).isoformat(timespec="seconds"),"events":out["events"]})
    except Exception as exc:
        out["error"]=str(exc)[:180];health("event_calendar","WARN",f"{sym}: {exc}"[:220])
    return out


def events_near(*,symbol:Optional[str]=None,now:Optional[datetime]=None,hours_before:float=12,hours_after:float=24)->List[Dict[str,Any]]:
    now=now or datetime.now(IST);a=(now-timedelta(hours=hours_before)).isoformat();b=(now+timedelta(hours=hours_after)).isoformat()
    with db() as con:
        if symbol:
            rs=con.execute("SELECT * FROM market_events WHERE starts_at BETWEEN ? AND ? AND (symbol IS NULL OR symbol='' OR symbol=?) ORDER BY starts_at",(a,b,symbol.upper())).fetchall()
        else:
            rs=con.execute("SELECT * FROM market_events WHERE starts_at BETWEEN ? AND ? ORDER BY starts_at",(a,b)).fetchall()
    out=[]
    for r in rs:
        d=dict(r)
        try:d["payload"]=json.loads(d.pop("payload_json") or "{}")
        except Exception:d["payload"]={}
        out.append(d)
    return out


def risk_context(symbol:str,book:str,now:Optional[datetime]=None)->Dict[str,Any]:
    now=now or datetime.now(IST)
    before=1 if book=="INTRADAY" else 18
    after=2 if book=="INTRADAY" else (72 if book=="WEEKLY" else 120)
    ev=events_near(symbol=symbol,now=now,hours_before=before,hours_after=after)
    high=[x for x in ev if str(x.get("impact") or "").upper()=="HIGH" and x.get("kind")!="NSE_HOLIDAY"]
    return {"status":"WARN" if high else "PASS","high_impact_events":high,"events":ev[:12],"window_hours":{"before":before,"after":after},"source":"PERSISTED_POINT_IN_TIME_EVENT_CALENDAR"}


def status()->Dict[str,Any]:
    with db() as con:
        total=con.execute("SELECT COUNT(*) FROM market_events").fetchone()[0]
        future=con.execute("SELECT COUNT(*) FROM market_events WHERE starts_at>=?",(now_iso(),)).fetchone()[0]
        recent=[dict(r) for r in con.execute("SELECT kind,title,starts_at,impact,source,symbol FROM market_events WHERE starts_at>=? ORDER BY starts_at LIMIT 30",(now_iso(),)).fetchall()]
    return {"total_events":total,"future_events":future,"upcoming":recent,"policy":"Only persisted timestamped events are used. Missing macro data remains UNKNOWN rather than assumed safe."}
