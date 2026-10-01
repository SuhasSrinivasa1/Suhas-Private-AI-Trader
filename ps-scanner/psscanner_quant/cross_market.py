from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Dict, List, Tuple

from .constants import IST, GLOBAL_INDIA_FREEZE_TIME, SHORT_HARD_EXIT
from .config import load_settings
from .data import universe, history, liquidity_rank, full_nse_symbols
from .db import db, get_state, now_iso, set_state, health
from .features import latest_features
from .trading_calendar import is_regular_trading_day, next_trading_day

# Sector/global-driver mapping. Matching is intentionally broad because the NIFTY500
# Industry field is not perfectly normalized across constituents.
DRIVER_RULES: List[Tuple[Tuple[str,...], Tuple[str,...]]] = [
    (("information technology","software","it services","computer","telecom"), ("NASDAQ","US_TECH","US_SEMIS","MSFT","ORCL","NVDA")),
    (("bank","financial","finance","insurance","nbfc"), ("US_FINANCIALS","US_BANKS","JPM","GS","BAC","SP500","USDINR")),
    (("oil","gas","petroleum","refinery","energy"), ("US_ENERGY","XOM","SHEL","CRUDE","NATGAS","DXY")),
    (("metal","mining","steel","aluminium","copper","zinc"), ("US_MATERIALS","BHP","RIO","COPPER","GOLD","DXY")),
    (("pharma","health","hospital","biotech","life science"), ("US_HEALTH","LLY","NVO","SP500","DXY")),
    (("auto","automobile","tyre","transport equipment"), ("US_DISCRETIONARY","TSLA","TM","NIKKEI225","DAX","CRUDE")),
    (("consumer","retail","textile","fmcg","food","beverage"), ("US_DISCRETIONARY","US_STAPLES","SP500","CRUDE")),
    (("industrial","capital goods","engineering","construction","infrastructure"), ("US_INDUSTRIALS","DAX","COPPER","CRUDE")),
    (("chemical","fertilizer","materials"), ("US_MATERIALS","CRUDE","NATGAS","DXY")),
    (("realty","real estate","housing"), ("SP500","US_FINANCIALS","DXY")),
]
DEFAULT_DRIVERS=("SP500","NASDAQ","STOXX50","NIKKEI225","HANGSENG","USDINR")


def _target_trade_date(now:datetime|None=None):
    now=now or datetime.now(IST)
    t=now.time().replace(tzinfo=None)
    if is_regular_trading_day(now.date()) and t < SHORT_HARD_EXIT:
        return now.date()
    return next_trading_day(now.date())


def _drivers(industry:str)->Tuple[str,...]:
    text=str(industry or '').lower()
    for needles,labels in DRIVER_RULES:
        if any(n in text for n in needles):return labels
    return DEFAULT_DRIVERS


def _driver_score(labels:Tuple[str,...], moves:Dict[str,float]) -> Tuple[float,List[Dict[str,Any]]]:
    vals=[];evidence=[]
    for lab in labels:
        if lab not in moves:continue
        mv=float(moves[lab]);
        # USDINR/DXY often act inversely for import-sensitive sectors; we keep them low weight
        # rather than pretending a universal sign relationship.
        w=.55 if lab in ("USDINR","DXY") else 1.0
        vals.append(mv*w);evidence.append({'driver':lab,'move_pct':round(mv,3),'weight':w})
    if not vals:return 0.0,evidence
    return sum(vals)/max(1,sum((x.get('weight') or 1.0) for x in evidence)),evidence


def _calibration_adjustment(side:str)->float:
    """Small bounded adjustment only after a meaningful resolved sample.

    Cross-market outcomes can inform the overnight cue, but they never directly promote an
    Indian Champion strategy. Until 30 resolved calls exist, calibration is exactly zero.
    """
    book='GLOBAL_INDIA_LONG' if side=='LONG' else 'GLOBAL_INDIA_SHORT'
    try:
        with db() as con:
            rows=con.execute("SELECT result FROM recommendations WHERE book=? AND state='CLOSED' AND result IN ('WIN','LOSS','MISS') ORDER BY closed_at DESC LIMIT 120",(book,)).fetchall()
        n=len(rows)
        if n<30:return 0.0
        wins=sum(1 for r in rows if r[0]=='WIN')
        wr=wins/n
        return max(-3.0,min(3.0,(wr-.5)*10.0))
    except Exception:return 0.0


def build_global_india_board() -> Dict[str,Any]:
    now=datetime.now(IST);target=_target_trade_date(now);g=get_state('global_context',{}) or {};moves=g.get('moves_pct') or {}
    settings=load_settings();max_side=max(1,min(10,int(settings.get('global_india_max_per_side',5))))
    syms=full_nse_symbols()
    meta={str(x.get('symbol') or '').upper():x for x in universe()}
    candidates=[]
    for sym in [str(x or '').upper() for x in syms if x]:
        try:df=history(sym,'1day',allow_network=False)
        except Exception:continue
        if len(df)<60:continue
        f=latest_features(df);px=float(f.get('close') or 0)
        if px<=0:continue
        row=meta.get(sym,{})
        labels=_drivers(str(row.get('industry') or 'UNKNOWN'));cue,evidence=_driver_score(labels,moves)
        if not evidence:continue
        # Combine overnight cross-market cue with the stock's own daily trend so the mapping
        # does not become a naive one-to-one "US stock up => Indian stock up" rule.
        own=float(f.get('ret20') or 0)/20.0
        trend=float(f.get('trend') or 0)
        adx=float(f.get('adx14') or 0);atr=max(.15,float(f.get('atr_pct') or 1.0))
        combined=.68*cue+.32*own
        for side in ('LONG','SHORT'):
            sign=1 if side=='LONG' else -1
            aligned=sign*combined
            if aligned<=0.12:continue
            trend_ok=sign*trend>=0
            score=68+min(16,aligned*9)+(7 if trend_ok else -4)+min(7,adx/8)+_calibration_adjustment(side)
            if score<78:continue
            target_pct=max(.55,min(3.0,atr*1.15+min(1.0,abs(combined))*.35))
            stop_pct=max(.35,min(1.8,target_pct/1.6))
            candidates.append({'symbol':sym,'side':side,'score':round(score,2),'confidence':round(max(.52,min(.84,.55+abs(combined)*.08+min(20,len(evidence))*0.005)),3),'price':px,'features':f,'industry':row.get('industry') or 'UNKNOWN','driver_cue_pct':round(cue,3),'combined_cue_pct':round(combined,3),'drivers':evidence,'target_pct':round(target_pct,4),'stop_pct':round(stop_pct,4),'target_date':target.isoformat()})
    candidates.sort(key=lambda x:x['score'],reverse=True)
    board={'generated_at':now_iso(),'target_session':target.isoformat(),'freeze_time_ist':'09:00','state':'FROZEN' if is_regular_trading_day(now.date()) and now.date()==target and now.time().replace(tzinfo=None)>=GLOBAL_INDIA_FREEZE_TIME else 'PROVISIONAL_OVERNIGHT','long':[x for x in candidates if x['side']=='LONG'][:max_side],'short':[x for x in candidates if x['side']=='SHORT'][:max_side],'global_context_generated_at':g.get('generated_at'),'global_coverage':g.get('coverage',len(moves)),'policy':'GLOBAL_MARKETS_TO_INDIA_OVERNIGHT_CUE_FULL_NSE_V640','universe_scanned':len(syms)}
    set_state('global_india_board',board)
    return board


def freeze_global_india_board() -> int:
    from .engine import _insert_rec
    now=datetime.now(IST);target=_target_trade_date(now)
    # Freeze only for today's India session once 09:00 has passed. After market close the
    # board remains provisional for the next trading day.
    if not (is_regular_trading_day(now.date()) and target==now.date() and now.time().replace(tzinfo=None)>=GLOBAL_INDIA_FREEZE_TIME):return 0
    board=get_state('global_india_board',{}) or build_global_india_board()
    if str(board.get('target_session'))!=target.isoformat():return 0
    made=0
    for side,key,book in [('LONG','long','GLOBAL_INDIA_LONG'),('SHORT','short','GLOBAL_INDIA_SHORT')]:
        with db() as con:
            exists=con.execute("SELECT COUNT(*) FROM recommendations WHERE book=? AND period_key=?",(book,target.isoformat())).fetchone()[0]
        if exists:continue
        for c in board.get(key) or []:
            rationale={'reasons':['major global-market overnight alignment','industry-driver mapping','Indian stock daily-trend confirmation'],'mapping_type':'SECTOR_AND_CROSS_ASSET_NOT_NAIVE_EQUIVALENT','industry':c.get('industry'),'global_drivers':c.get('drivers'),'driver_cue_pct':c.get('driver_cue_pct'),'combined_cue_pct':c.get('combined_cue_pct'),'target_session':target.isoformat(),'freeze_time_ist':'09:00','data_confidence':c.get('confidence'),'deadline':'15:00 IST same session','learning_policy':'US/global outcomes are research evidence only; no direct Champion promotion without Indian OOS validation.'}
            _insert_rec(book,c['symbol'],side,c['score'],c['confidence'],c['price'],c['features'],'GLOBAL_OVERNIGHT',['GLOBAL_SECTOR_CUE','GLOBAL_CROSS_ASSET','INDIA_DAILY_CONFIRM'],rationale,exchange='NSE',target_pct_override=c['target_pct'],stop_pct_override=c['stop_pct'],period_key_override=target.isoformat());made+=1
    if made:
        board=dict(board);board['state']='FROZEN';board['frozen_at']=now_iso();set_state('global_india_board',board)
    return made


def run_global_india_cycle() -> int:
    try:
        board=build_global_india_board();made=freeze_global_india_board()
        set_state('scan_status_GLOBAL_INDIA',{'book':'GLOBAL_INDIA','status':'OK','generated_at':board.get('generated_at'),'target_session':board.get('target_session'),'state':board.get('state'),'long':len(board.get('long') or []),'short':len(board.get('short') or []),'published':made,'at':now_iso()})
        return made
    except Exception as exc:
        health('global_india','WARN',str(exc)[:220]);set_state('scan_status_GLOBAL_INDIA',{'book':'GLOBAL_INDIA','status':'ERROR','error':str(exc)[:220],'at':now_iso()});return 0


def board_payload() -> Dict[str,Any]:
    from .engine import recommendations
    board=get_state('global_india_board',{}) or {}
    return {'provisional':board,'frozen_long':recommendations('GLOBAL_INDIA_LONG'),'frozen_short':recommendations('GLOBAL_INDIA_SHORT')}
