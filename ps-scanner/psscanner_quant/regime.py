from __future__ import annotations

from statistics import median, pstdev
from typing import Any, Dict

from .data import full_nse_symbols, live_prices, _history_path, _load_raw_candles, _candle_fields, _number
from .db import get_state, now_iso, set_state


def _recent_closes(symbol: str, limit: int = 60):
    raw=_load_raw_candles(_history_path(symbol,"1day"));out=[]
    for row in reversed(raw):
        f=_candle_fields(row)
        if not f: continue
        c=_number(f[4])
        if c is None or c<=0: continue
        out.append(float(c))
        if len(out)>=limit: break
    out.reverse();return out


def classify(prices: Dict[str,float] | None=None, allow_network_prices: bool=True) -> Dict[str, Any]:
    """Classify the Indian market from the full data-ready NSE equity breadth.

    v6.4.1 removes the legacy top-80 liquidity sample. Every equity from the dynamic
    Groww NSE CASH master with enough daily history contributes to breadth/regime.
    """
    syms=full_nse_symbols()
    if not syms:
        state=get_state("last_regime",{}) or {}
        if state:
            state=dict(state);state["stale"]=True;return state
        return {"regime":"WARMING","breadth_up_pct":0.0,"breadth_down_pct":0.0,"median_move_pct":0.0,"sample":0,"universe":0,"generated_at":now_iso(),"stale":True}
    prices=dict(prices or (live_prices(syms,allow_network=allow_network_prices,max_age_seconds=20) if allow_network_prices else live_prices(syms,allow_network=False,max_age_seconds=300)))
    moves=[];trend_votes=[];vol=[];history_ready=0
    for s in syms:
        closes=_recent_closes(s,60)
        if len(closes)<25: continue
        history_ready+=1
        prev=float(closes[-1]);px=float(prices.get(s,prev))
        if prev>0:moves.append((px/prev-1)*100)
        last20=closes[-20:];last50=closes[-50:] if len(closes)>=50 else last20
        sma20=sum(last20)/len(last20);sma50=sum(last50)/len(last50)
        trend_votes.append(1 if px>sma20>sma50 else (-1 if px<sma20<sma50 else 0))
        rets=[]
        for a,b in zip(closes[-21:-1],closes[-20:]):
            if a>0:rets.append((b/a-1)*100)
        if len(rets)>=5:vol.append(float(pstdev(rets)))
    if not moves:
        return {"regime":"WARMING","sample":0,"universe":len(syms),"history_ready":history_ready,"generated_at":now_iso(),"stale":True,"breadth_policy":"FULL_NSE_DATA_READY_EQUITIES"}
    up=sum(1 for x in moves if x>0.15)/len(moves)*100;down=sum(1 for x in moves if x<-0.15)/len(moves)*100
    med=median(moves);tv=sum(trend_votes)/max(1,len(trend_votes));rv=median(vol) if vol else 0.0;high_vol=rv>=2.2
    if down>=60 and tv<-0.25:regime="HIGH_VOL_TREND_DOWN" if high_vol else "TREND_DOWN"
    elif up>=60 and tv>0.25:regime="HIGH_VOL_TREND_UP" if high_vol else "TREND_UP"
    elif high_vol and (up>=45 or down>=45):regime="HIGH_VOL_RANGE"
    elif rv<0.9:regime="LOW_VOL_RANGE"
    else:regime="RANGE"
    state={"regime":regime,"breadth_up_pct":round(up,1),"breadth_down_pct":round(down,1),
           "median_move_pct":round(float(med),3),"trend_vote":round(tv,3),"realized_volatility_median_pct":round(rv,3),
           "sample":len(moves),"universe":len(syms),"history_ready":history_ready,"live_prices":len(prices),
           "generated_at":now_iso(),"stale":False,"breadth_policy":"FULL_NSE_DATA_READY_EQUITIES_NO_TOP_N_CAP"}
    set_state("last_regime",state);return state
