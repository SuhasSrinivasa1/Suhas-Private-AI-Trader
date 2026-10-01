from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from .constants import IST, MARKET_OPEN, INTRADAY_ENTRY_CUTOFF, TRADE_NOTIONAL_RUPEES
from .handbook import filter_catalog

_GROUPS={
    'Market regime and cross-market context':'MARKET',
    'Sector strength and stock leadership':'LEADERSHIP',
    'Fundamental quality and catalysts':'FUNDAMENTALS',
    'Technical context and confirmation':'TECHNICAL',
    'Execution, portfolio and risk intelligence':'RISK_EXECUTION',
}

_HORIZON_WEIGHTS={
    'INTRADAY':{'MARKET':1.25,'LEADERSHIP':1.0,'FUNDAMENTALS':0.35,'TECHNICAL':1.55,'RISK_EXECUTION':1.75},
    'WEEKLY':{'MARKET':1.10,'LEADERSHIP':1.25,'FUNDAMENTALS':1.30,'TECHNICAL':1.35,'RISK_EXECUTION':1.60},
    'MONTHLY':{'MARKET':1.00,'LEADERSHIP':1.20,'FUNDAMENTALS':1.80,'TECHNICAL':1.10,'RISK_EXECUTION':1.55},
    'ETF':{'MARKET':1.25,'LEADERSHIP':1.10,'FUNDAMENTALS':0.25,'TECHNICAL':1.40,'RISK_EXECUTION':1.65},
    'CIRCUIT':{'MARKET':1.15,'LEADERSHIP':0.70,'FUNDAMENTALS':0.25,'TECHNICAL':1.45,'RISK_EXECUTION':1.90},
    'INTERNATIONAL':{'MARKET':1.00,'LEADERSHIP':1.00,'FUNDAMENTALS':0.80,'TECHNICAL':1.30,'RISK_EXECUTION':1.45},
}


def _f(v:Any,d:float=0.0)->float:
    try:
        x=float(v);return x if math.isfinite(x) else d
    except Exception:return d


def _status(cond:Optional[bool], warn:bool=False)->str:
    if cond is None:return 'UNKNOWN'
    if cond:return 'WARN' if warn else 'PASS'
    return 'FAIL'


def _filter(rank:int,name:str,group:str,status:str,detail:str='',hard:bool=False,value:Any=None)->Dict[str,Any]:
    return {'rank':rank,'name':name,'group':group,'status':status,'hard_fail':bool(hard and status=='FAIL'),'detail':detail,'value':value}


def evaluate(*, book:str, symbol:str, side:str, features:Dict[str,Any], fundamentals:Optional[Dict[str,Any]],
             regime_state:Dict[str,Any], candle_info:Optional[Dict[str,Any]]=None, news:Optional[Dict[str,Any]]=None,
             global_ctx:Optional[Dict[str,Any]]=None, portfolio:Optional[Dict[str,Any]]=None,
             sector_ctx:Optional[Dict[str,Any]]=None, event_ctx:Optional[Dict[str,Any]]=None,
             target_pct:float=0.0, stop_pct:float=0.0, strategy_ids:Optional[List[str]]=None,
             suspended_strategy_ids:Optional[List[str]]=None, data_confidence:float=1.0)->Dict[str,Any]:
    book=book.upper();side=side.upper();sign=1 if side=='LONG' else -1
    fundamentals=fundamentals or {}; candle_info=candle_info or {};news=news or {};global_ctx=global_ctx or {};portfolio=portfolio or {};sector_ctx=sector_ctx or {};event_ctx=event_ctx or {}
    strategy_ids=strategy_ids or []; suspended=set(suspended_strategy_ids or [])
    f=features; filters=[]
    catalog={int(x['rank']):x for x in filter_catalog()}
    def add(rank:int,status:str,detail:str='',hard:bool=False,value:Any=None):
        meta=catalog.get(rank,{})
        group=_GROUPS.get(meta.get('group'),'OTHER')
        filters.append(_filter(rank,meta.get('name',f'Filter {rank}'),group,status,detail,hard,value))

    reg=str(regime_state.get('regime') or 'WARMING');tv=_f(regime_state.get('trend_vote'));up=_f(regime_state.get('breadth_up_pct'));down=_f(regime_state.get('breadth_down_pct'))
    atr=_f(f.get('atr_pct'));gap=_f(f.get('gap_pct'));rs=_f(f.get('relative_strength20'));ret20=sign*_f(f.get('ret20'));ret60=sign*_f(f.get('ret60'));trend=sign*_f(f.get('trend'));vr=_f(f.get('volume_ratio'));turn=_f(f.get('turnover20'))
    open_observed=bool(f.get('open_observed', True))
    px=_f(f.get('close'));rpos=_f(f.get('range20_pos'),.5);vwap=_f(f.get('vwap'));higher=sign*_f(f.get('higher_tf_trend'))
    now=datetime.now(IST);t=now.time().replace(tzinfo=None)

    # 1-10 market context
    add(1,'WARN' if reg=='WARMING' else ('WARN' if reg.startswith('HIGH_VOL') else 'PASS'),f'regime={reg}',False,reg)
    bench=sign*tv
    add(2,'PASS' if bench>0.15 else ('WARN' if bench>-0.15 else 'FAIL'),f'trend_vote={tv:.3f}')
    breadth=up if side=='LONG' else down
    add(3,'PASS' if breadth>=55 else ('WARN' if breadth>=45 else 'FAIL'),f'{side.lower()} breadth={breadth:.1f}%')
    add(4,'PASS' if .25<=atr<=5.5 else ('WARN' if .10<=atr<=8 else 'FAIL'),f'ATR%={atr:.2f}')
    extreme_gap=abs(gap)>max(4.0,atr*3.0) if open_observed else False
    if open_observed:add(5,'WARN' if extreme_gap else 'PASS',f'gap={gap:.2f}% ATR={atr:.2f}%')
    else:add(5,'UNKNOWN','daily open unavailable; gap condition is not inferred')
    risk_state=str(global_ctx.get('risk_state') or 'UNKNOWN')
    if risk_state=='UNKNOWN':add(6,'UNKNOWN','global proxy context unavailable')
    else:add(6,'PASS' if (side=='LONG' and risk_state=='RISK_ON') or (side=='SHORT' and risk_state=='RISK_OFF') else 'WARN',f'global={risk_state}')
    event_rows=event_ctx.get('events') or []
    high_events=event_ctx.get('high_impact_events') or []
    if event_rows:
        add(7,'WARN' if high_events else 'PASS',f"timestamped event calendar: {len(event_rows)} nearby, {len(high_events)} high-impact")
    else:
        add(7,'UNKNOWN','No timestamped market/macro event is available for this decision window; safety is not inferred.')
    gm=global_ctx.get('moves_pct') or {};fx=abs(_f(gm.get('USDINR')))
    add(8,'PASS' if gm and fx<1.5 else ('WARN' if gm else 'UNKNOWN'),f'USDINR move={fx:.2f}%' if gm else 'global rates/FX proxy unavailable')
    add(9,'PASS' if risk_state in ('RISK_ON','RISK_OFF') else ('WARN' if risk_state=='MIXED' else 'UNKNOWN'),f'risk state={risk_state}')
    if book=='INTRADAY':
        add(10,'PASS' if MARKET_OPEN<=t<=INTRADAY_ENTRY_CUTOFF else 'FAIL',f'time={t.strftime("%H:%M")}',hard=True)
    else:add(10,'PASS','horizon is not dependent on intraday entry-time expectancy')

    # 11-18 leadership. Sector context comes from the official NIFTY500 industry map
    # plus cached daily peer histories. Missing peer data remains UNKNOWN.
    if sector_ctx.get('status')=='UNKNOWN' or not sector_ctx:
        add(11,'UNKNOWN','sector trend unavailable until peer histories are cached')
        add(12,'UNKNOWN','sector breadth unavailable until peer histories are cached')
        add(14,'UNKNOWN','sector-relative return unavailable')
        add(16,'UNKNOWN','peer confirmation unavailable')
        add(17,'UNKNOWN','mapped sector/index vehicle confirmation not yet integrated')
    else:
        up_sector=_f(sector_ctx.get('trend_up_pct'));down_sector=_f(sector_ctx.get('trend_down_pct'));pos=_f(sector_ctx.get('positive_pct'));rel20=_f(sector_ctx.get('stock_vs_industry_ret20_pct'))
        direction_trend=up_sector if side=='LONG' else down_sector
        direction_breadth=pos if side=='LONG' else 100-pos
        add(11,'PASS' if direction_trend>=55 else ('WARN' if direction_trend>=40 else 'FAIL'),f"{sector_ctx.get('industry','UNKNOWN')} directional trend={direction_trend:.1f}%")
        add(12,'PASS' if direction_breadth>=55 else ('WARN' if direction_breadth>=45 else 'FAIL'),f"sector directional breadth={direction_breadth:.1f}%")
        add(14,'PASS' if sign*rel20>0 else 'WARN',f'stock-vs-industry ret20={rel20:.2f}%')
        add(16,'PASS' if bool(sector_ctx.get('supportive')) else 'WARN',f"peer sample={sector_ctx.get('sample',0)}")
        add(17,'UNKNOWN','sector/index ETF confirmation is not fabricated without mapped vehicle history')
    add(13,'UNKNOWN' if abs(rs)<1e-9 else ('PASS' if sign*rs>0 else 'FAIL'),f'relative strength20={rs:.2f}' if abs(rs)>=1e-9 else 'benchmark-relative series not supplied')
    add(15,'PASS' if ret20>0 and ret60>=0 else ('WARN' if ret20>0 else 'FAIL'),f'directional ret20={ret20:.2f}, ret60={ret60:.2f}')
    inst=_f(fundamentals.get('heldPercentInstitutions'),-1)
    add(18,'PASS' if inst>=.05 else ('WARN' if inst>=0 else 'UNKNOWN'),f'institutional ownership={inst:.3f}' if inst>=0 else 'not available')

    # 19-30 fundamentals/catalysts. Low direct weight intraday, high weight monthly.
    rev=_f(fundamentals.get('revenueGrowth'),999);earn=_f(fundamentals.get('earningsGrowth'),999);margin=_f(fundamentals.get('profitMargins'),999);opm=_f(fundamentals.get('operatingMargins'),999)
    roe=_f(fundamentals.get('returnOnEquity'),999);roa=_f(fundamentals.get('returnOnAssets'),999);fcf=_f(fundamentals.get('freeCashflow'),999);ocf=_f(fundamentals.get('operatingCashflow'),999);debt=_f(fundamentals.get('debtToEquity'),999);pe=_f(fundamentals.get('trailingPE'),999)
    def dir_stat(v:float,long_good:float,short_bad:float)->str:
        if v==999:return 'UNKNOWN'
        if side=='LONG':return 'PASS' if v>=long_good else ('WARN' if v>=0 else 'FAIL')
        return 'PASS' if v<=short_bad else ('WARN' if v<=long_good else 'FAIL')
    add(19,dir_stat(rev,.05,0),f'revenueGrowth={rev:.3f}' if rev!=999 else 'not available')
    if earn==999:add(20,'UNKNOWN','earnings growth not available')
    else:
        cash_ok=(ocf>0 if ocf!=999 else True)
        good=(earn>.05 and cash_ok) if side=='LONG' else (earn<0 or not cash_ok)
        add(20,'PASS' if good else 'WARN',f'earningsGrowth={earn:.3f}, cash_supported={cash_ok}')
    m=max(v for v in (margin,opm) if v!=999) if any(v!=999 for v in (margin,opm)) else 999
    add(21,dir_stat(m,.08,.04),f'margin={m:.3f}' if m!=999 else 'not available')
    q=max(v for v in (roe,roa) if v!=999) if any(v!=999 for v in (roe,roa)) else 999
    add(22,dir_stat(q,.10,.03),f'ROE/ROA proxy={q:.3f}' if q!=999 else 'not available')
    if fcf==999:add(23,'UNKNOWN','free cash flow unavailable')
    else:add(23,'PASS' if (fcf>0 if side=='LONG' else fcf<0) else 'WARN',f'FCF={fcf:.0f}')
    if debt==999:add(24,'UNKNOWN','debt/equity unavailable')
    else:add(24,'PASS' if (debt<150 if side=='LONG' else debt>180) else 'WARN',f'debt/equity={debt:.1f}')
    add(25,'UNKNOWN','promoter pledge/governance feed not configured; severe governance cannot be inferred')
    add(26,'PASS' if inst>=.05 else ('WARN' if inst>=0 else 'UNKNOWN'),f'institutional ownership={inst:.3f}' if inst>=0 else 'not available')
    if pe==999:add(27,'UNKNOWN','valuation unavailable')
    else:add(27,'PASS' if ((0<pe<70) if side=='LONG' else (pe<=0 or pe>70)) else 'WARN',f'P/E={pe:.2f}')
    news_status=str(news.get('status') or 'UNKNOWN');sent=_f(news.get('sentiment_score'));mat=_f(news.get('materiality'));binary=bool(news.get('binary_event_risk'))
    add(28,'PASS' if news_status=='READY' and mat>=.25 else ('UNKNOWN' if news_status=='UNKNOWN' else 'WARN'),f'news materiality={mat:.2f}')
    if news_status=='UNKNOWN':add(29,'UNKNOWN','news context not refreshed')
    else:add(29,'PASS' if mat>=.25 and sign*sent>=0 else ('WARN' if mat<.25 else 'FAIL'),f'news sentiment={sent:.2f}, materiality={mat:.2f}')
    event_hard=bool(high_events and book=='INTRADAY')
    if event_hard:
        add(30,'FAIL',f'{len(high_events)} high-impact scheduled event(s) inside intraday risk window',hard=True)
    elif high_events or binary:
        add(30,'WARN',f"scheduled_high_impact={len(high_events)}, binary_headline={binary}")
    else:
        add(30,'PASS' if (news_status!='UNKNOWN' or event_rows) else 'UNKNOWN','no high-impact event detected in available timestamped evidence')

    # 31-40 technical confirmation.
    add(31,'PASS' if trend>0 else ('WARN' if trend==0 else 'FAIL'),f'directional trend={trend:.1f}')
    location_ok=(rpos>=.35 if side=='LONG' else rpos<=.65)
    add(32,'PASS' if location_ok else 'WARN',f'range20 position={rpos:.2f}')
    if vwap>0:add(33,'PASS' if sign*(px-vwap)>0 else 'WARN',f'price={px:.2f}, VWAP={vwap:.2f}')
    else:add(33,'UNKNOWN','VWAP only available on intraday bars')
    ema12=_f(f.get('ema12'));ema26=_f(f.get('ema26'))
    add(34,'PASS' if sign*(ema12-ema26)>0 else 'WARN',f'EMA12-EMA26={ema12-ema26:.3f}')
    add(35,'PASS' if vr>=1.10 else ('WARN' if vr>=.8 else 'FAIL'),f'RVOL={vr:.2f}')
    add(36,'PASS' if .25<=atr<=6 else ('WARN' if atr>0 else 'FAIL'),f'ATR%={atr:.2f}')
    breakout=(rpos>=.82 if side=='LONG' else rpos<=.18) and vr>=1.0
    add(37,'PASS' if breakout else 'WARN',f'breakout edge={breakout}')
    if open_observed:add(38,'WARN' if extreme_gap else 'PASS',f'gap={gap:.2f}%')
    else:add(38,'UNKNOWN','daily open unavailable; gap analysis is not inferred')
    orpos=_f(f.get('opening_range_position'),999)
    if orpos==999:add(39,'UNKNOWN','opening-range feature unavailable on this timeframe')
    else:add(39,'PASS' if (orpos>1 if side=='LONG' else orpos<0) else 'WARN',f'opening_range_position={orpos:.2f}')
    if higher==0:add(40,'WARN' if book=='INTRADAY' else 'UNKNOWN','higher-timeframe trend mixed/unavailable')
    else:add(40,'PASS' if higher>0 else 'FAIL',f'directional higher_tf_trend={higher:.1f}')

    # Candle trigger is intentionally context-only. Report strongest aligned hit in technical detail.
    aligned=[h for h in candle_info.get('hits',[]) if h.get('direction')==side]
    candle_quality=max([_f(h.get('quality_score')) for h in aligned] or [0])

    # 41-50 execution/risk. These are where hard failures live.
    if turn<=0:add(41,'UNKNOWN','turnover unavailable')
    else:add(41,'FAIL' if turn<200_000 else ('WARN' if turn<1_000_000 else 'PASS'),f'average turnover proxy=₹{turn:,.0f}',hard=turn<200_000)
    add(42,'UNKNOWN','live spread/depth hard gate is evaluated again at manual order preview')
    add(43,'PASS','execution adapter uses price-protected LIMIT orders')
    expected_edge=max(target_pct,atr*1.5)
    est_cost=.35
    add(44,'PASS' if expected_edge>est_cost*2 else 'FAIL',f'edge proxy={expected_edge:.2f}% vs cost reserve={est_cost:.2f}%',hard=expected_edge<=est_cost*2)
    rr=(target_pct/stop_pct) if target_pct>0 and stop_pct>0 else 0.0
    add(45,'PASS' if rr>=1.5 else 'FAIL',f'R:R proxy={rr:.2f}',hard=True,value=rr)
    if book=='INTERNATIONAL': add(46,'UNKNOWN','international execution adapter is not enabled; ₹ risk sizing is not applied to foreign quote currency')
    else: add(46,'PASS' if 0<px<=TRADE_NOTIONAL_RUPEES else 'FAIL',f'price ₹{px:.2f}; max notional ₹{TRADE_NOTIONAL_RUPEES:,.0f}',hard=True)
    add(47,'PASS' if stop_pct>0 else 'FAIL',f'stop distance={stop_pct:.2f}%',hard=True)
    if portfolio:
        add(48,'FAIL' if portfolio.get('hard_block') else ('WARN' if portfolio.get('highly_correlated_open_recommendations',0)>=1 else 'PASS'),portfolio.get('reason') or f"high correlations={portfolio.get('highly_correlated_open_recommendations',0)}",hard=True)
    else:add(48,'UNKNOWN','portfolio correlation evaluated on shortlisted candidates/order preview')
    add(49,'PASS','no active application kill switch supplied to this evaluation')
    decayed=[s for s in strategy_ids if s in suspended]
    required_votes=2 if book in ('INTRADAY','WEEKLY','MONTHLY') else 1
    add(50,'FAIL' if len(strategy_ids)<required_votes or decayed else 'PASS',f'strategy_votes={len(strategy_ids)}, required={required_votes}, suspended_selected={len(decayed)}',hard=True)

    # Score only information we actually have. Unknown data never earns points and never silently becomes a fail.
    weights=_HORIZON_WEIGHTS.get(book,_HORIZON_WEIGHTS['INTRADAY'])
    earned=possible=0.0
    val={'PASS':1.0,'WARN':0.45,'FAIL':0.0}
    for r in filters:
        if r['status']=='UNKNOWN':continue
        w=weights.get(r['group'],1.0)
        possible+=w;earned+=w*val.get(r['status'],0.0)
    score=100.0*earned/possible if possible else 0.0
    # Candles can improve timing/context by at most 5 points, never erase a failed hard gate.
    if candle_quality>0:score=min(100.0,score+min(5.0,candle_quality/20.0))
    hard_blockers=[r['name']+': '+r['detail'] for r in filters if r['hard_fail']]
    if data_confidence<.55:hard_blockers.append(f'Data confidence too low: {data_confidence:.2f}')
    threshold={'INTRADAY':62,'WEEKLY':67,'MONTHLY':70,'ETF':65,'CIRCUIT':68,'INTERNATIONAL':64}.get(book,65)
    decision='NO_TRADE' if hard_blockers else ('ELIGIBLE' if score>=threshold else 'WATCH')
    return {
        'decision':decision,'score':round(score,2),'minimum_score':threshold,'hard_blockers':hard_blockers,
        'filters':filters,'evaluated_filters':sum(1 for r in filters if r['status']!='UNKNOWN'),
        'unknown_filters':sum(1 for r in filters if r['status']=='UNKNOWN'),
        'hard_fail_count':len(hard_blockers),'aligned_candlestick_quality':round(candle_quality,1),
        'principle':'A strategy/candle signal cannot override a failed liquidity, reward-risk, portfolio, execution or strategy-decay hard gate.',
    }
