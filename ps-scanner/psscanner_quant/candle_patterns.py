from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from .features import enrich
from .handbook import candlestick_catalog


def _b(r) -> float:
    return abs(float(r.close) - float(r.open))

def _rng(r) -> float:
    return max(1e-9, float(r.high) - float(r.low))

def _bull(r) -> bool:
    return float(r.close) > float(r.open)

def _bear(r) -> bool:
    return float(r.close) < float(r.open)

def _upper(r) -> float:
    return max(0.0, float(r.high) - max(float(r.open), float(r.close)))

def _lower(r) -> float:
    return max(0.0, min(float(r.open), float(r.close)) - float(r.low))

def _doji(r) -> bool:
    return _b(r) <= 0.12 * _rng(r)

def _small(r) -> bool:
    return _b(r) <= 0.35 * _rng(r)

def _large(r) -> bool:
    return _b(r) >= 0.65 * _rng(r)

def _near(a: float, b: float, tol: float) -> bool:
    return abs(a-b) <= tol

def _contains(a, b) -> bool:
    return float(a.high) >= float(b.high) and float(a.low) <= float(b.low)

def _body_contains(a, b) -> bool:
    alo, ahi = sorted((float(a.open), float(a.close)))
    blo, bhi = sorted((float(b.open), float(b.close)))
    return alo <= blo and ahi >= bhi


def _context_score(x: pd.DataFrame, direction: int) -> Dict[str, float]:
    r=x.iloc[-1]
    close=float(r.close)
    trend=float(r.get('trend') or 0)
    vr=float(r.get('volume_ratio') or 0)
    rp=float(r.get('range20_pos') or 0.5)
    body=float(r.get('body_frac') or 0)
    upper=float(r.get('upper_wick_frac') or 0)
    lower=float(r.get('lower_wick_frac') or 0)
    location = 0.0
    if direction>0:
        location = 1.0 if rp <= .25 else (.5 if rp <= .45 else 0.0)
    elif direction<0:
        location = 1.0 if rp >= .75 else (.5 if rp >= .55 else 0.0)
    else:
        location = .5
    trend_align = 1.0 if direction*trend>0 else (.5 if trend==0 else 0.0)
    volume = min(1.0, max(0.0, (vr-.8)/1.2))
    close_quality = min(1.0, max(body, lower if direction>0 else upper))
    confirmation = 0.0
    if len(x)>=2:
        p=x.iloc[-2]
        if direction>0 and close>float(p.high): confirmation=1.0
        elif direction<0 and close<float(p.low): confirmation=1.0
        elif direction==0: confirmation=.5
    return {"location":location,"trend_alignment":trend_align,"volume":volume,"candle_quality":close_quality,"confirmation":confirmation}


def detect_patterns(df: pd.DataFrame) -> Dict[str, Any]:
    """Numerically encode all 50 handbook candlestick patterns.

    Pattern hits are context features, never standalone trade instructions. Definitions are
    deliberately mechanical so the exact same logic is available to backtests and live scans.
    """
    x=enrich(df)
    if x is None or len(x)<5:
        return {"hits":[],"hit_count":0,"bullish_count":0,"bearish_count":0,"catalog_count":50,"status":"INSUFFICIENT_HISTORY"}
    # Candlestick bodies/wicks genuinely require the observed open. If any bar in the
    # current five-bar pattern window lacks it, abstain from candle classification rather
    # than backfilling or silently treating previous close as the open.
    if "open_observed" in x.columns and not bool(x["open_observed"].tail(5).all()):
        return {
            "hits":[],"hit_count":0,"bullish_count":0,"bearish_count":0,"catalog_count":50,
            "status":"UNAVAILABLE_DAILY_OPEN_MISSING",
            "open_observed_recent":int(x["open_observed"].tail(5).sum()),
            "principle":"Candlestick patterns require observed opens; missing opens are never fabricated.",
        }
    r0=x.iloc[-1]; r1=x.iloc[-2]; r2=x.iloc[-3]; r3=x.iloc[-4]; r4=x.iloc[-5]
    avg_body=float((x['close']-x['open']).abs().tail(20).mean() or 0)
    atr=float(r0.get('atr14') or _rng(r0)); tol=max(1e-9,atr*.12)
    uptrend=float(r0.get('trend') or 0)>0
    downtrend=float(r0.get('trend') or 0)<0
    vol_ok=float(r0.get('volume_ratio') or 0)>=1.0
    # Gaps use candle ranges, not only opens, to keep the definition deterministic.
    gap_up=lambda a,b: float(a.low)>float(b.high)
    gap_dn=lambda a,b: float(a.high)<float(b.low)
    inside=lambda a,b: float(a.high)<float(b.high) and float(a.low)>float(b.low)
    same_open=lambda a,b: _near(float(a.open),float(b.open),tol)

    cond: Dict[int, Tuple[bool,int]] = {}
    cond[1]=(_bull(r0) and _bear(r1) and _body_contains(r0,r1),1)
    cond[2]=(_bear(r0) and _bull(r1) and _body_contains(r0,r1),-1)
    cond[3]=(_small(r0) and _lower(r0)>=2*max(_b(r0),tol*.2) and _upper(r0)<=max(_b(r0),tol),1)
    cond[4]=(uptrend and _small(r0) and _lower(r0)>=2*max(_b(r0),tol*.2),-1)
    cond[5]=(downtrend and _small(r0) and _upper(r0)>=2*max(_b(r0),tol*.2),1)
    cond[6]=(uptrend and _small(r0) and _upper(r0)>=2*max(_b(r0),tol*.2),-1)
    cond[7]=(_bear(r2) and _large(r2) and _small(r1) and _bull(r0) and float(r0.close)>=(float(r2.open)+float(r2.close))/2,1)
    cond[8]=(_bull(r2) and _large(r2) and _small(r1) and _bear(r0) and float(r0.close)<=(float(r2.open)+float(r2.close))/2,-1)
    cond[9]=(_bear(r2) and _doji(r1) and _bull(r0) and float(r0.close)>=(float(r2.open)+float(r2.close))/2,1)
    cond[10]=(_bull(r2) and _doji(r1) and _bear(r0) and float(r0.close)<=(float(r2.open)+float(r2.close))/2,-1)
    cond[11]=(_bear(r1) and _bull(r0) and float(r0.close)>(float(r1.open)+float(r1.close))/2 and float(r0.close)<float(r1.open),1)
    cond[12]=(_bull(r1) and _bear(r0) and float(r0.close)<(float(r1.open)+float(r1.close))/2 and float(r0.close)>float(r1.open),-1)
    cond[13]=(all(_bull(r) and _large(r) for r in (r2,r1,r0)) and float(r0.close)>float(r1.close)>float(r2.close),1)
    cond[14]=(all(_bear(r) and _large(r) for r in (r2,r1,r0)) and float(r0.close)<float(r1.close)<float(r2.close),-1)
    cond[15]=(_bear(r1) and _large(r1) and _bull(r0) and _body_contains(r1,r0),1)
    cond[16]=(_bull(r1) and _large(r1) and _bear(r0) and _body_contains(r1,r0),-1)
    cond[17]=(_bear(r1) and _large(r1) and _doji(r0) and _body_contains(r1,r0),1)
    cond[18]=(_bull(r1) and _large(r1) and _doji(r0) and _body_contains(r1,r0),-1)
    cond[19]=(_doji(r0),0)
    cond[20]=(_doji(r0) and _lower(r0)>=.65*_rng(r0) and _upper(r0)<=.12*_rng(r0),1)
    cond[21]=(_doji(r0) and _upper(r0)>=.65*_rng(r0) and _lower(r0)<=.12*_rng(r0),-1)
    cond[22]=(_doji(r0) and _upper(r0)>=.3*_rng(r0) and _lower(r0)>=.3*_rng(r0),0)
    cond[23]=(_rng(r0)<=max(1e-9,atr*.03) and _doji(r0),0)
    cond[24]=(_small(r0) and _upper(r0)>=.2*_rng(r0) and _lower(r0)>=.2*_rng(r0),0)
    cond[25]=(_bull(r0) and _b(r0)>=.85*_rng(r0) and _upper(r0)<=.08*_rng(r0) and _lower(r0)<=.08*_rng(r0),1)
    cond[26]=(_bear(r0) and _b(r0)>=.85*_rng(r0) and _upper(r0)<=.08*_rng(r0) and _lower(r0)<=.08*_rng(r0),-1)
    # Three Inside/Outside patterns: r2+r1 form the two-candle base; r0 confirms.
    harami_up=_bear(r2) and _large(r2) and _bull(r1) and _body_contains(r2,r1)
    harami_dn=_bull(r2) and _large(r2) and _bear(r1) and _body_contains(r2,r1)
    engulf_up=_bear(r2) and _bull(r1) and _body_contains(r1,r2)
    engulf_dn=_bull(r2) and _bear(r1) and _body_contains(r1,r2)
    cond[27]=(harami_up and _bull(r0) and float(r0.close)>float(r1.high),1)
    cond[28]=(harami_dn and _bear(r0) and float(r0.close)<float(r1.low),-1)
    cond[29]=(engulf_up and _bull(r0) and float(r0.close)>float(r1.high),1)
    cond[30]=(engulf_dn and _bear(r0) and float(r0.close)<float(r1.low),-1)
    cond[31]=(_near(float(r0.low),float(r1.low),tol) and _bull(r0),1)
    cond[32]=(_near(float(r0.high),float(r1.high),tol) and _bear(r0),-1)
    cond[33]=(_bull(r4) and _large(r4) and all(inside(r,r4) for r in (r3,r2,r1)) and _bull(r0) and float(r0.close)>float(r4.high),1)
    cond[34]=(_bear(r4) and _large(r4) and all(inside(r,r4) for r in (r3,r2,r1)) and _bear(r0) and float(r0.close)<float(r4.low),-1)
    cond[35]=(uptrend and _bear(r1) and _bull(r0) and same_open(r1,r0) and _large(r0),1)
    cond[36]=(downtrend and _bull(r1) and _bear(r0) and same_open(r1,r0) and _large(r0),-1)
    cond[37]=(_bull(r0) and _large(r0) and _lower(r0)<=.08*_rng(r0),1)
    cond[38]=(_bear(r0) and _large(r0) and _upper(r0)<=.08*_rng(r0),-1)
    cond[39]=(_bear(r1) and _bull(r0) and gap_up(r0,r1) and _large(r0),1)
    cond[40]=(_bull(r1) and _bear(r0) and gap_dn(r0,r1) and _large(r0),-1)
    cond[41]=(_bear(r2) and gap_dn(r1,r2) and _doji(r1) and gap_up(r0,r1) and _bull(r0),1)
    cond[42]=(_bull(r2) and gap_up(r1,r2) and _doji(r1) and gap_dn(r0,r1) and _bear(r0),-1)
    cond[43]=(uptrend and _bull(r2) and _bull(r1) and gap_up(r1,r2) and _bear(r0) and float(r0.low)>float(r2.high),1)
    cond[44]=(downtrend and _bear(r2) and _bear(r1) and gap_dn(r1,r2) and _bull(r0) and float(r0.high)<float(r2.low),-1)
    cond[45]=(_bull(r4) and _large(r4) and all(float(r.low)>float(r4.low) for r in (r3,r2,r1)) and _bull(r0) and float(r0.close)>float(r4.high),1)
    cond[46]=(_bear(r1) and _bull(r0) and _near(float(r0.close),float(r1.close),tol) and float(r0.open)<float(r1.low),1)
    cond[47]=(_bull(r1) and _bear(r0) and _near(float(r0.close),float(r1.close),tol) and float(r0.open)>float(r1.high),-1)
    cond[48]=(_small(r0) and _lower(r0)>=2.2*max(_b(r0),tol*.2),1)
    cond[49]=(_small(r0) and _upper(r0)>=2.2*max(_b(r0),tol*.2),-1)
    cond[50]=(inside(r0,r1),0)

    names={int(x.get('rank') or 0):str(x.get('name') or '') for x in candlestick_catalog()}
    hits=[]
    for rank,(hit,direction) in cond.items():
        if not hit: continue
        ctx=_context_score(x,direction)
        quality=round(20*sum(ctx.values()),1) # 0..100, five independent 0..1 components
        hits.append({
            'rank':rank,'name':names.get(rank,f'Pattern {rank}'),
            'direction':'LONG' if direction>0 else ('SHORT' if direction<0 else 'NEUTRAL'),
            'quality_score':quality,'context':ctx,
            'volume_confirmed':bool(vol_ok),
        })
    hits.sort(key=lambda h:(h['quality_score'],h['rank']),reverse=True)
    return {
        'hits':hits,
        'hit_count':len(hits),
        'bullish_count':sum(1 for h in hits if h['direction']=='LONG'),
        'bearish_count':sum(1 for h in hits if h['direction']=='SHORT'),
        'catalog_count':50,
        'principle':'Candlestick patterns are numeric context features, never standalone trade instructions.',
    }
