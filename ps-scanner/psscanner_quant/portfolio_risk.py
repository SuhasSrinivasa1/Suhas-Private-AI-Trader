from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from .data import history
from .db import db


def _corr(a: str, b: str) -> float:
    try:
        da=history(a,'1day',allow_network=False); dbb=history(b,'1day',allow_network=False)
        if len(da)<40 or len(dbb)<40:return 0.0
        ra=da['close'].pct_change().dropna().tail(80)
        rb=dbb['close'].pct_change().dropna().tail(80)
        idx=ra.index.intersection(rb.index)
        if len(idx)<25:return 0.0
        c=float(np.corrcoef(ra.loc[idx].values,rb.loc[idx].values)[0,1])
        return c if np.isfinite(c) else 0.0
    except Exception:return 0.0


def recommendation_cluster(symbol: str, side: str, exclude_id: str='') -> Dict[str, Any]:
    with db() as con:
        rs=[dict(r) for r in con.execute("SELECT recommendation_id,symbol,side,book FROM recommendations WHERE state='LIVE' AND exchange='NSE' AND side=? AND symbol<>?",(side.upper(),symbol.upper())).fetchall()]
    peers=[]
    for r in rs[:20]:
        if exclude_id and r['recommendation_id']==exclude_id:continue
        c=_corr(symbol,r['symbol'])
        if c>=0.70:peers.append({'symbol':r['symbol'],'book':r['book'],'correlation':round(c,3)})
    peers.sort(key=lambda x:x['correlation'],reverse=True)
    high=[x for x in peers if x['correlation']>=0.85]
    return {
        'symbol':symbol.upper(),'side':side.upper(),'highly_correlated_open_recommendations':len(high),
        'correlated_peers':peers[:8],
        'hard_block':len(high)>=3,
        'reason':'THREE_OR_MORE_HIGHLY_CORRELATED_SAME_SIDE_RECOMMENDATIONS' if len(high)>=3 else '',
    }


def risk_summary() -> Dict[str, Any]:
    with db() as con:
        live=[dict(r) for r in con.execute("SELECT book,side,symbol,entry_price,current_price,target_pct,created_at FROM recommendations WHERE state='LIVE' ORDER BY book,side,score DESC").fetchall()]
        orders=[dict(r) for r in con.execute("SELECT symbol,side,product,quantity,limit_price,state,created_at FROM orders ORDER BY created_at DESC LIMIT 50").fetchall()]
    by_book={}
    for r in live:
        k=r['book'];by_book.setdefault(k,{'LONG':0,'SHORT':0});by_book[k][r['side']]=by_book[k].get(r['side'],0)+1
    return {'live_recommendations':len(live),'by_book':by_book,'recent_orders':orders[:20],'principle':'Correlation and concentration are evaluated separately from signal quality; several correlated positions are treated as one risk cluster.'}
