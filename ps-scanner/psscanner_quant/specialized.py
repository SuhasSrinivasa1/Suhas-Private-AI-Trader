from __future__ import annotations
import json
import math
import time
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

from .constants import (IST, MARKET_OPEN, MARKET_CLOSE, CIRCUIT_LIVE_CUTOFF, CIRCUIT_NEXTDAY_PREP_START,
    CIRCUIT_NEXTDAY_FREEZE, CIRCUIT_NEXTDAY_FREEZE_END, HORIZON_RESEARCH_START, HORIZON_RECOVERY_END)
from .data import (
    instrument_rows, instrument, history, live_prices, liquidity_rank, universe, full_nse_symbols,
    international_batch_history, GLOBAL_UNIVERSE, US_WEEKLY_UNIVERSE, _history_path,
    _load_raw_candles, _candle_fields, _number,
)
from .features import latest_features
from .candle_patterns import detect_patterns
from .db import db, health, get_state, set_state, now_iso
from .broker import broker
from .engine import (_insert_rec, _observe, _publish_frozen, period_key, _target_feasibility, _risk_geometry,
    _period_has_valid_frozen_book, _horizon_freeze_window, _freeze_contract_min, _freeze_contract_count,
    _horizon_target_context)
from .regime import classify
from .global_context import snapshot as global_snapshot
from .trade_intelligence import evaluate as evaluate_trade_intelligence
from .portfolio_risk import recommendation_cluster
from .trading_calendar import is_regular_trading_day, next_trading_day
from .sector_context import context as sector_context, context_cached as sector_context_cached
from .event_calendar import risk_context as event_risk_context
from .evidence_fabric import publish as fabric_publish, symbol_context as fabric_symbol_context
from .config import load_settings

NY = ZoneInfo("America/New_York")
US_OPEN = dtime(9, 30)
US_CLOSE = dtime(16, 0)

_INTL_SHARED:Dict[str,Any]={}


def _shared_international_history(symbols:List[str],period:str,interval:str,ttl_seconds:float)->Dict[str,Any]:
    """One yfinance transport observation, reused by weekly selection and lifecycle updates."""
    key=f"{period}|{interval}"
    now=time.time();entry=_INTL_SHARED.get(key) or {}
    data=entry.get("data") if isinstance(entry,dict) else None
    if isinstance(data,dict) and now-float(entry.get("at") or 0)<=float(ttl_seconds):
        if all(s in data for s in symbols):
            return {s:data.get(s) for s in symbols if s in data}
    fresh=international_batch_history(symbols,period,interval,chunk_size=20,timeout_seconds=12.0)
    merged=dict(data or {});merged.update(fresh or {})
    _INTL_SHARED[key]={"at":now,"data":merged}
    domain="international_intraday" if interval!="1d" else "international_daily"
    fabric_publish(domain,source="YFINANCE_BATCHED_SHARED_TRANSPORT",consumers=("INTERNATIONAL","LIVE_UPDATE","ALGORITHM"),payload={"period":period,"interval":interval,"symbols":len(fresh or {})},network_fetch=True,symbols=len(fresh or {}),ttl_seconds=ttl_seconds)
    return {s:merged.get(s) for s in symbols if s in merged}


def _is_etf(r:Dict[str,str])->bool:
    s=(r.get('trading_symbol') or '').upper(); n=(r.get('name') or '').upper(); t=(r.get('instrument_type') or '').upper()
    return t=='ETF' or ' ETF' in ' '+n or s.endswith('ETF') or 'BEES' in s or 'IETF' in s


def _etf_symbols()->List[str]:
    metas=[]
    for r in instrument_rows():
        if r.get('exchange')=='NSE' and r.get('segment')=='CASH' and _is_etf(r): metas.append(r)
    return [str(r.get('trading_symbol')).upper() for r in metas if r.get('trading_symbol')]


def warm_etf_history(max_symbols:int=None)->Dict[str,Any]:
    syms=_etf_symbols()
    if not syms:return {'attempted':0,'ready':0,'cursor':0}
    n=int(max_symbols if max_symbols is not None else load_settings().get('etf_history_warm_batch',6))
    n=max(0,min(n,len(syms)));cursor=int(get_state('etf_history_warm_cursor',0) or 0)%len(syms)
    chosen=[syms[(cursor+i)%len(syms)] for i in range(n)]
    ready=0
    for sym in chosen:
        if len(history(sym,'1day'))>=30:ready+=1
    set_state('etf_history_warm_cursor',(cursor+len(chosen))%len(syms))
    out={'attempted':len(chosen),'ready':ready,'cursor':cursor,'universe':len(syms),'policy':'LOW_PRIORITY_ROTATING_BACKGROUND_WARMUP','at':now_iso()}
    set_state('last_etf_history_warm',out);return out


def scan_etfs(sides: Optional[tuple]=None, target_now: Optional[datetime]=None)->List[Dict[str,Any]]:
    started=time.monotonic();syms=_etf_symbols()
    syms=[s for s in syms if _history_path(s,'1day').exists()]
    prices=live_prices(syms,allow_network=False,max_age_seconds=180); regime_state=get_state('last_regime',{}) or {'regime':'WARMING','trend_vote':0,'breadth_up_pct':0,'breadth_down_pct':0,'stale':True};regime=(regime_state.get('regime') or 'WARMING');g=get_state('global_context',{}) or {'risk_state':'UNKNOWN','moves_pct':{},'stale':True};out=[]
    stats={'book':'ETF','started_at':now_iso(),'universe':len(syms),'history_ready':0,'eligible':0,
           'capacity_prefilter_reject':0,'intelligence_reject':0,
           'universe_policy':'ALL_CACHED_ETFS_NO_GATE_RELAXATION'}
    scan_sides=tuple(sides or ('LONG','SHORT'))
    for s in syms:
        df=history(s,'1day',allow_network=False)
        if len(df)<30: continue
        stats['history_ready']+=1
        f=latest_features(df);f['higher_tf_trend']=f.get('trend',0);px=float(prices.get(s) or f.get('close') or 0);f['close']=px
        if px<=0: continue
        candles=detect_patterns(df)
        for side in scan_sides:
            sign=1 if side=='LONG' else -1
            trend=sign*float(f.get('trend') or 0)>0; mom=sign*float(f.get('ret20') or 0)>0; vol=float(f.get('volume_ratio') or 0)
            score=45+(18 if trend else -10)+(18 if mom else -8)+min(14,max(0,(vol-1)*10))
            if (regime.startswith('TREND_DOWN') and side=='SHORT') or (regime.startswith('TREND_UP') and side=='LONG'): score+=8
            if score<68:continue
            data_conf=min(1.0,len(df)/120*.65+.25)
            # Capacity/data prefilter uses optimistic score/confidence. If even the
            # optimistic case cannot satisfy the unchanged ETF target gate, expensive
            # portfolio-correlation and intelligence work cannot rescue it.
            optimistic_tf=_target_feasibility('ETF',side,f,100.0,1.0,data_conf,None,now=target_now)
            if not optimistic_tf['target_qualified']:
                stats['capacity_prefilter_reject']+=1
                continue
            portfolio=recommendation_cluster(s,side)
            shared_ctx=fabric_symbol_context(s,book='ETF',side=side,features=f,fundamentals={})
            ti=evaluate_trade_intelligence(book='ETF',symbol=s,side=side,features=f,fundamentals={},regime_state=regime_state,candle_info=candles,news=shared_ctx['news'],global_ctx=g,portfolio=portfolio,sector_ctx=shared_ctx['sector'],event_ctx=shared_ctx['events'],institutional_ctx=shared_ctx['institutional'],target_pct=5.0,stop_pct=max(.7,min(4,float(f.get('atr_pct') or 1.5))),strategy_ids=['ETF_TREND','ETF_MOMENTUM','ETF_VOLUME'],data_confidence=data_conf)
            if ti['decision']!='ELIGIBLE':
                stats['intelligence_reject']+=1
                continue
            final=.72*min(100,score)+.28*ti['score']
            tf=_target_feasibility('ETF',side,f,final,min(1,.45+(score-68)/50),data_conf,None,now=target_now)
            if not tf['target_qualified']:continue
            stats['eligible']+=1
            out.append({'symbol':s,'side':side,'score':final,'confidence':min(1,.45+(score-68)/50),'price':px,'features':f,'regime':regime,'strategies':['ETF_TREND','ETF_MOMENTUM','ETF_VOLUME'],'target_feasibility':tf,'rationale':{'reasons':['ETF trend alignment','20-session momentum','volume/liquidity confirmation'],'data_confidence':data_conf,'candlestick_context':candles,'trade_intelligence':ti,'target_feasibility':tf,'global_context':g,'portfolio_fit':portfolio,'institutional_context':shared_ctx['institutional'],'evidence_fabric_policy':shared_ctx['fabric_policy']}})
    out.sort(key=lambda x:x['score'],reverse=True)
    stats.update({'candidates':len(out),'completed_at':now_iso(),'duration_seconds':round(time.monotonic()-started,2)})
    set_state('scan_detail_ETF',stats)
    return out


def _etf_missed_freeze_recovery_allowed(now: datetime, existing: int, required: int, preperiod: bool) -> bool:
    """Allow current-week ETF recovery only while the NSE can supply fresh evidence."""
    t=now.time().replace(tzinfo=None)
    return bool(not preperiod and existing<required and is_regular_trading_day(now.date())
                and HORIZON_RECOVERY_END<t<=MARKET_CLOSE)


def run_etf_cycle():
    """Enforce the ETF five-pick contract from cached data first.

    v6.5.1 adds deterministic missed-freeze self-heal: an incomplete current-period ETF
    book may recover after the legacy morning window, but only from already-cached fresh
    evidence and with every target/intelligence/risk gate unchanged. The worker never
    fabricates names merely to reach five.
    """
    started=time.monotonic();now=datetime.now(IST);t=now.time().replace(tzinfo=None)
    ctx=_horizon_target_context('ETF',now);pk=str(ctx['period_key']);target_now=ctx.get('target_now') or now;preperiod=bool(ctx.get('preperiod'))
    required=_freeze_contract_min('ETF') or 5;existing=_freeze_contract_count('ETF',pk)
    if existing>=required:
        contract={'required':required,'published_total':existing,'shortage':0,'recovery_required':False}
        set_state('scan_status_ETF',{'book':'ETF','running':False,'status':'PERIOD_BOOK_ALREADY_FROZEN','period_key':pk,'contract':contract,'target_period':ctx,'at':now_iso()})
        return 0

    normal_research=is_regular_trading_day(now.date()) and HORIZON_RESEARCH_START<=t<=HORIZON_RECOVERY_END
    missed_freeze_recovery=_etf_missed_freeze_recovery_allowed(now,existing,required,preperiod)
    research_window=preperiod or normal_research or missed_freeze_recovery
    publication_allowed=preperiod or bool(_horizon_freeze_window('ETF',now).get('open')) or missed_freeze_recovery
    if not research_window:
        freeze=_horizon_freeze_window('ETF',now);contract={'required':required,'published_total':existing,'shortage':max(0,required-existing),'recovery_required':existing<required}
        set_state('scan_status_ETF',{'book':'ETF','running':False,'status':freeze.get('status') or 'OUTSIDE_RESEARCH_WINDOW','freeze':freeze,'contract':contract,'target_period':ctx,'at':now_iso()})
        return 0

    mode='MISSED_FREEZE_CACHED_RECOVERY' if missed_freeze_recovery else ('PREPERIOD_CACHED_FREEZE' if preperiod else 'RECOVERY_SCANNING_CACHED_ETFS')
    set_state('scan_status_ETF',{'book':'ETF','running':True,'status':mode,'period_key':pk,
        'contract':{'required':required,'published_total':existing,'shortage':max(0,required-existing)},'target_period':ctx,'started_at':now_iso(),
        'recovery_policy':'CACHED_ONLY_NO_GATE_RELAXATION'})
    published=0
    if publication_allowed:
        published+=_publish_frozen('ETF',1,required,publication_anchor=now,period_key_override=pk,
            allow_preperiod=preperiod,allow_recovery=missed_freeze_recovery)
        existing=_freeze_contract_count('ETF',pk)
        if existing>=required:
            contract={'required':required,'published_total':existing,'shortage':0,'recovery_required':False}
            set_state('scan_status_ETF',{'book':'ETF','running':False,'status':'CONTRACT_FULFILLED_FROM_PREPARED_CANDIDATES','published':published,'period_key':pk,'contract':contract,'target_period':ctx,'at':now_iso()})
            return published

    # Cached-first is deliberate. No network warmup is allowed to block a recovery scan.
    c=scan_etfs(sides=('LONG',),target_now=target_now);_observe('ETF',c,period_key_override=pk)
    completion=datetime.now(IST)
    publication_at_completion=preperiod or bool(_horizon_freeze_window('ETF',completion).get('open')) or missed_freeze_recovery
    if publication_at_completion:
        published+=_publish_frozen('ETF',1,required,publication_anchor=completion,period_key_override=pk,
            allow_preperiod=preperiod,allow_recovery=missed_freeze_recovery)
    total=_freeze_contract_count('ETF',pk)
    contract={'required':required,'published_total':total,'shortage':max(0,required-total),'recovery_required':total<required,
              'reason':None if total>=required else ('NO_DATA_VALID_CANDIDATES' if not c else 'FEWER_THAN_FIVE_TARGET_QUALIFIED_CANDIDATES'),
              'cached_first':True,'no_gate_relaxation':True,'missed_freeze_recovery':missed_freeze_recovery}
    status='CONTRACT_FULFILLED' if total>=required else (
        'FREEZE_SHORTAGE_RECOVERY_REQUIRED' if publication_at_completion else 'PREPARED_WAITING_FOR_FREEZE'
    )
    detail=get_state('scan_detail_ETF',{}) or {}
    set_state('scan_status_ETF',{'book':'ETF','running':False,'status':status,'period_key':pk,'candidates':len(c),'published':published,
        'freeze':_horizon_freeze_window('ETF',datetime.now(IST)),'contract':contract,'target_period':ctx,
        'scan_detail_summary':{k:detail.get(k) for k in ('universe','history_ready','capacity_prefilter_reject','intelligence_reject','eligible','duration_seconds')},
        'completed_at':now_iso(),'duration_seconds':round(time.monotonic()-started,2)})
    return published

def _minutes_until(t:dtime, now:Optional[datetime]=None)->int:
    now=now or datetime.now(IST)
    cur=now.hour*60+now.minute+now.second/60.0;end=t.hour*60+t.minute
    return max(0,int(end-cur))


def _same_session_capacity_pct(f:Dict[str,Any], remaining_minutes:int, factor:float=.82)->float:
    atr=max(.05,float(f.get('atr_pct') or .25));bars=max(0.0,remaining_minutes/5.0)
    momentum=max(0.0,abs(float(f.get('ret5') or 0))/5.0,abs(float(f.get('ret20') or 0))/20.0)
    return max(0.0,atr*math.sqrt(max(.25,bars))*factor+momentum*remaining_minutes/10.0)


def _save_nextday_circuit_candidate(sym:str, q:Dict[str,Any], f:Dict[str,Any], imbalance:float, candles:Dict[str,Any], now:datetime)->None:
    if now.time().replace(tzinfo=None)<CIRCUIT_NEXTDAY_PREP_START or now.time().replace(tzinfo=None)>MARKET_CLOSE:return
    px=float(q.get('last_price') or q.get('ltp') or f.get('close') or 0);up=float(q.get('upper_circuit_limit') or q.get('upperCircuitLimit') or 0)
    if px<=0 or up<=0:return
    prev=float(q.get('previous_close') or q.get('previousClose') or q.get('close') or 0)
    if prev<=0:
        try:
            d=history(sym,'1day',allow_network=False);prev=float(d['close'].dropna().iloc[-2] if len(d)>=2 else 0)
        except Exception:prev=0
    band_pct=((up/prev)-1)*100 if prev>0 else 0
    if not (1.0<=band_pct<=25.0):band_pct=5.0
    trend=float(f.get('trend') or 0);ret1=float(f.get('ret1') or 0);ret5=float(f.get('ret5') or 0);ret20=float(f.get('ret20') or 0)
    adx=float(f.get('adx14') or 0);vr=float(f.get('volume_ratio') or 0);pos=float(f.get('range20_pos') or .5)
    score=58+(9 if trend>0 else -6)+min(8,max(-5,ret1*2.0))+min(9,max(-6,ret5*.8))+min(8,max(-5,ret20*.25))+min(7,max(0,(vr-1)*6))+min(6,adx/7)+min(7,max(0,(pos-.55)*15))+min(7,max(0,(imbalance-1)*5))
    # Aligned bullish candle context is supportive but never sufficient by itself.
    try:
        aligned=max([float(x.get('quality_score') or 0) for x in candles.get('hits',[]) if x.get('direction')=='LONG'],default=0)
        score+=min(4,aligned/25)
    except Exception:pass
    settings=load_settings();threshold=float(settings.get('circuit_nextday_min_score',84.0))
    if score<threshold:return
    target_pct=max(1.0,min(25.0,band_pct));stop_pct=max(.6,min(3.5,float(f.get('atr_pct') or 1.0)*1.35))
    rec={'symbol':sym,'side':'LONG','score':round(score,2),'confidence':round(max(.55,min(.88,.55+(score-threshold)/45)),3),'price':px,'features':f,'candlestick_context':candles,'circuit_band_pct':round(band_pct,3),'projected_target_pct':round(target_pct,3),'stop_pct':round(stop_pct,3),'order_imbalance':round(imbalance,3),'prepared_at':now_iso(),'source_session':now.date().isoformat()}
    state=get_state('circuit_nextday_candidates',{}) or {}
    if state.get('source_session')!=now.date().isoformat():state={'source_session':now.date().isoformat(),'candidates':{}}
    cands=dict(state.get('candidates') or {});old=cands.get(sym)
    if not old or float(rec['score'])>=float(old.get('score') or 0):cands[sym]=rec
    # v6.4.1: keep every threshold-qualified next-session candidate. The frozen output
    # may still contain only a small actionable slate, but research discovery is not top-N capped.
    ranked=sorted(cands.values(),key=lambda x:float(x.get('score') or 0),reverse=True)
    set_state('circuit_nextday_candidates',{'source_session':now.date().isoformat(),'updated_at':now_iso(),'candidates':{x['symbol']:x for x in ranked}})


def _circuit_calibration()->Dict[str,Any]:
    try:
        with db() as con:rows=con.execute("SELECT result FROM recommendations WHERE book='CIRCUIT_NEXTDAY' AND state='CLOSED' AND result IN ('WIN','LOSS','MISS') ORDER BY closed_at DESC LIMIT 100").fetchall()
        n=len(rows);wins=sum(1 for r in rows if r[0]=='WIN');wr=(wins/n if n else None)
        return {'samples':n,'wins':wins,'win_rate':round(wr,3) if wr is not None else None,'active_adjustment':round(max(-3,min(3,(wr-.5)*10)),2) if n>=20 and wr is not None else 0.0,'minimum_samples_for_adjustment':20}
    except Exception:return {'samples':0,'active_adjustment':0.0}


def _fresh_intraday_session_evidence(df, now:Optional[datetime]=None, max_age_minutes:int=30):
    """Require a real bar from the current NSE session for actionable same-day circuit calls."""
    now=now or datetime.now(IST)
    if df is None or len(df)<5:
        return False, None, "fewer_than_5_intraday_bars"
    try:
        ts=df.index[-1]
        dt=ts.to_pydatetime() if hasattr(ts,"to_pydatetime") else ts
        if dt.tzinfo is None: dt=dt.replace(tzinfo=IST)
        else: dt=dt.astimezone(IST)
        age=(now-dt).total_seconds()/60.0
        if dt.date()!=now.date(): return False, round(age,1), "latest_bar_not_current_session"
        if age < -5 or age > max_age_minutes: return False, round(age,1), "latest_bar_stale"
        return True, round(max(0.0,age),1), "fresh_current_session_bar"
    except Exception:
        return False, None, "intraday_timestamp_unreadable"


def _circuit_execution_permission(symbol:str, side:str)->tuple[bool,str]:
    m=instrument(symbol) or {}
    if side=='LONG':
        return (bool(m.get('buy_allowed')), 'buy_allowed' if m.get('buy_allowed') else 'buy_not_allowed')
    ok=bool(m.get('sell_allowed')) and bool(m.get('is_intraday'))
    return (ok, 'mis_short_allowed' if ok else 'intraday_short_not_allowed')


def run_circuit_cycle(max_symbols:int=120):
    """Full-NSE circuit discovery with staged exact-band verification.

    Every NSE equity is cheaply screened from the batched LTP cache. Exact Groww quote
    calls are made only when price movement/new-listing evidence makes the name plausibly circuit-relevant, rather than for every cache-missing security or an arbitrary top-liquidity pool.
    """
    started=time.monotonic();now=datetime.now(IST);t=now.time().replace(tzinfo=None)
    pool=full_nse_symbols()
    stats={'book':'CIRCUIT','started_at':now_iso(),'running':True,'processed':0,'breadth_screened':0,
           'full_nse_universe':len(pool),'exact_quote_candidates':0,'quotes_ok':0,'verified_bands':0,
           'near_band':0,'deadline_reject':0,'hard_blocked':0,'evidence_reject':0,'stale_intraday_reject':0,'execution_permission_reject':0,'inserted':0,'user_deadline_ist':'15:00',
           'watchlist_long':[],'watchlist_short':[],'universe_policy':'FULL_NSE_COARSE_SCREEN_NO_LIQUIDITY_CAP'}
    set_state('scan_status_CIRCUIT',stats)
    if not is_regular_trading_day(now.date()):
        stats.update({'running':False,'status':'MARKET_CLOSED','completed_at':now_iso(),'duration_seconds':0});set_state('scan_status_CIRCUIT',stats);return 0
    if not (MARKET_OPEN<=t<CIRCUIT_LIVE_CUTOFF):
        stats.update({'running':False,'status':'OUTSIDE_SAME_DAY_LIVE_WINDOW','completed_at':now_iso(),'duration_seconds':round(time.monotonic()-started,2)});set_state('scan_status_CIRCUIT',stats);return 0
    if not pool:
        stats.update({'running':False,'status':'NO_SCANNABLE_UNIVERSE','completed_at':now_iso(),'duration_seconds':round(time.monotonic()-started,2)});set_state('scan_status_CIRCUIT',stats);return 0

    prices=live_prices(pool,allow_network=False,max_age_seconds=360)
    ustate=get_state('universe_status',{}) or {};new_symbols=set(str(x).upper() for x in (ustate.get('new_since_last_refresh') or []))
    exact=[]
    for idx,sym in enumerate(pool,1):
        stats['breadth_screened']=idx
        px=float(prices.get(sym) or 0)
        raw=_load_raw_candles(_history_path(sym,'1day'));prev=None
        for row in reversed(raw):
            f=_candle_fields(row)
            if not f:continue
            prev=_number(f[4])
            if prev and prev>0:break
        limited=len(raw)<30;intraday_move=None
        move=abs((px/prev-1)*100) if px>0 and prev and prev>0 else None
        # Full breadth remains unconditional, but exact quote calls are evidence-triggered.
        # Missing cache alone is not evidence that an old illiquid stock is near circuit.
        exact_needed=bool(move is not None and move>=1.0) or sym in new_symbols
        if limited and not exact_needed and px>0:
            iraw=_load_raw_candles(_history_path(sym,'5minute'));first_px=None
            for row in iraw:
                f=_candle_fields(row)
                if not f:continue
                first_px=_number(f[4])
                if first_px and first_px>0:break
            intraday_move=abs((px/first_px-1)*100) if first_px and first_px>0 else None
            exact_needed=bool(intraday_move is not None and intraday_move>=1.0)
        if exact_needed:
            priority=float(move or 0.0)
            if intraday_move is not None:priority=max(priority,float(intraday_move))
            if sym in new_symbols:priority=max(priority,2.0)
            exact.append((priority,sym))
    settings=load_settings()
    quote_budget=max(20,min(300,int(settings.get('circuit_exact_quote_budget',max_symbols) or max_symbols)))
    exact_total=len(exact)
    exact=[sym for _,sym in sorted(exact,key=lambda x:x[0],reverse=True)[:quote_budget]]
    stats['exact_quote_candidates_total']=exact_total;stats['exact_quote_candidates']=len(exact);stats['quote_budget']=quote_budget
    stats['exact_quote_deferred']=max(0,exact_total-len(exact));stats['pool_size']=len(pool);stats['scanned']=len(exact)
    set_state('scan_status_CIRCUIT',stats)

    regime_state=get_state('last_regime',{}) or {'regime':'WARMING','trend_vote':0,'breadth_up_pct':0,'breadth_down_pct':0,'stale':True};reg=(regime_state.get('regime') or 'WARMING');g=get_state('global_context',{}) or {'risk_state':'UNKNOWN','moves_pct':{},'stale':True};made=0;pk=period_key('CIRCUIT')
    # V627 compatibility/invariant: fabric_symbol_context delegates to sector_context_cached;
    # Circuit scoring remains cache-only for sector context and never rebuilds it inline.
    max_side=max(1,min(5,int(settings.get('circuit_live_max_per_side',3))))
    with db() as con:live_counts={side:int(con.execute("SELECT COUNT(*) FROM recommendations WHERE book='CIRCUIT' AND period_key=? AND side=? AND state='LIVE'",(pk,side)).fetchone()[0]) for side in ('LONG','SHORT')}
    for idx,s in enumerate(exact,1):
        stats['processed']=idx;stats['current_symbol']=s;stats['elapsed_seconds']=round(time.monotonic()-started,2)
        if idx==1 or idx%10==0:set_state('scan_status_CIRCUIT',stats)
        try:q=broker.quote(s)
        except Exception:continue
        stats['quotes_ok']+=1;px=float(q.get('last_price') or q.get('ltp') or 0);up=float(q.get('upper_circuit_limit') or q.get('upperCircuitLimit') or 0);dn=float(q.get('lower_circuit_limit') or q.get('lowerCircuitLimit') or 0)
        if px<=0 or up<=0 or dn<=0:continue
        stats['verified_bands']+=1;b=float(q.get('total_buy_quantity') or 0);a=float(q.get('total_sell_quantity') or 0);vol=float(q.get('volume') or 0)
        df=history(s,'5minute',allow_network=False);has_intraday=len(df)>=5;basef=latest_features(df) if has_intraday else {}
        fresh_intraday,intraday_age,intraday_freshness_reason=_fresh_intraday_session_evidence(df,datetime.now(IST))
        daily=history(s,'1day',allow_network=False)
        if len(daily)>=20:
            df_daily=latest_features(daily)
            # Daily HLC is valid next-session research evidence, but it never substitutes
            # for a fresh same-session intraday bar in an actionable CIRCUIT call.
            if not has_intraday:basef=dict(df_daily)
            basef['higher_tf_trend']=df_daily.get('trend',0)
        basef['close']=px
        candles=detect_patterns(df) if len(df)>=5 else {'hits':[],'status':'LIMITED_INTRADAY_HISTORY'}
        long_imb=(b+1)/(a+1);_save_nextday_circuit_candidate(s,q,basef,long_imb,candles,datetime.now(IST))
        if datetime.now(IST).time().replace(tzinfo=None)>=CIRCUIT_LIVE_CUTOFF:continue
        remaining=_minutes_until(CIRCUIT_LIVE_CUTOFF)
        for side,limit in (('LONG',up),('SHORT',dn)):
            if live_counts.get(side,0)>=max_side:continue
            dist=((limit-px)/px*100) if side=='LONG' else ((px-limit)/px*100)
            if dist<0.08 or dist>4.0:continue
            stats['near_band']+=1;imbalance=long_imb if side=='LONG' else (a+1)/(b+1)
            capacity=_same_session_capacity_pct(basef,remaining,.82);deadline_ok=remaining>=15 and capacity>=dist*1.10
            score=72+min(14,max(0,(4-dist)*3))+min(10,max(0,(imbalance-1)*8))+min(5,max(0,(capacity-dist)*2))
            watch={'symbol':s,'side':side,'price':round(px,4),'circuit_limit':round(limit,4),'distance_pct':round(dist,3),'order_imbalance':round(imbalance,3),'capacity_pct':round(capacity,3),'minutes_to_1500':remaining,'deadline_feasible':bool(deadline_ok),'score':round(score,2)}
            wk='watchlist_long' if side=='LONG' else 'watchlist_short';stats[wk].append(watch);stats[wk]=sorted(stats[wk],key=lambda x:(x['deadline_feasible'],x['score'],-x['distance_pct']),reverse=True)[:12]
            if not deadline_ok:stats['deadline_reject']+=1;continue
            if (reg.startswith('TREND_UP') and side=='LONG') or (reg.startswith('TREND_DOWN') and side=='SHORT'):score+=5
            if score<80:continue
            with db() as con:
                if con.execute("SELECT 1 FROM recommendations WHERE book='CIRCUIT' AND period_key=? AND symbol=? AND side=?",(pk,s,side)).fetchone():continue
            f=dict(basef);f.update({'close':px,'atr_pct':max(.5,float(basef.get('atr_pct') or dist/2)),'circuit_limit':limit,'circuit_distance_pct':dist,'order_imbalance':imbalance,'volume':vol,'live_turnover':px*vol,'deadline_capacity_pct':capacity,'deadline_remaining_minutes':remaining})
            shared_ctx=fabric_symbol_context(s,book='CIRCUIT',side=side,features=f,fundamentals={})
            ti=evaluate_trade_intelligence(book='CIRCUIT',symbol=s,side=side,features=f,fundamentals={},regime_state=regime_state,candle_info=candles,news=shared_ctx['news'],global_ctx=g,portfolio=recommendation_cluster(s,side),sector_ctx=shared_ctx['sector'],event_ctx=shared_ctx['events'],institutional_ctx=shared_ctx['institutional'],target_pct=dist,stop_pct=max(.35,min(dist/1.6,1.8)),strategy_ids=['CIRCUIT_DISTANCE','CIRCUIT_ORDER_IMBALANCE','1500_DEADLINE_CAPACITY'],data_confidence=.9)
            filter_by_rank={int(x.get('rank') or 0):x for x in (ti.get('filters') or [])}
            liquidity_status=str((filter_by_rank.get(41) or {}).get('status') or 'UNKNOWN')
            volume_status=str((filter_by_rank.get(35) or {}).get('status') or 'UNKNOWN')
            permission_ok,permission_reason=_circuit_execution_permission(s,side)
            counterpart_ok=(a>0 if side=='LONG' else b>0)
            live_turnover=px*vol
            evidence_reasons=[]
            if not fresh_intraday:evidence_reasons.append(intraday_freshness_reason)
            if live_turnover<1_000_000:evidence_reasons.append('live_turnover_below_1m')
            if liquidity_status not in ('PASS','WARN'):evidence_reasons.append('historical_liquidity_unknown_or_failed')
            if volume_status not in ('PASS','WARN'):evidence_reasons.append('relative_volume_not_confirmed')
            if not counterpart_ok:evidence_reasons.append('no_executable_counterparty_depth')
            if not permission_ok:evidence_reasons.append(permission_reason)
            if ti.get('decision')!='ELIGIBLE':evidence_reasons.append('intelligence_not_eligible')
            if ti['hard_fail_count']>0:stats['hard_blocked']+=1
            if evidence_reasons:
                stats['evidence_reject']+=1
                if not fresh_intraday:stats['stale_intraday_reject']+=1
                if not permission_ok:stats['execution_permission_reject']+=1
                watch['actionable']=False;watch['evidence_status']='WATCH_ONLY';watch['evidence_reasons']=evidence_reasons[:6]
                watch['intraday_age_minutes']=intraday_age;watch['live_turnover']=round(live_turnover,2)
                continue
            final=.80*min(100,score)+.20*ti['score'];rationale={'reasons':['verified Groww circuit band',f'{dist:.2f}% from circuit','order-book imbalance',f'modeled capacity {capacity:.2f}% before 15:00','fresh current-session intraday evidence','liquidity and execution permission confirmed'],'circuit_limit':limit,'data_confidence':.9,'candlestick_context':candles,'trade_intelligence':ti,'global_context':g,'deadline_policy':'SAME_SESSION_TARGET_BY_15_00_IST','deadline_remaining_minutes':remaining,'deadline_capacity_pct':round(capacity,3),'target_is_not_guaranteed':True,'universe_policy':'FULL_NSE_BREADTH','actionable_evidence_policy':'V642_FRESH_INTRADAY_LIQUIDITY_EXECUTION','intraday_age_minutes':intraday_age,'live_turnover':round(live_turnover,2),'execution_permission':permission_reason,'institutional_context':shared_ctx['institutional'],'evidence_fabric_policy':shared_ctx['fabric_policy']}
            _insert_rec('CIRCUIT',s,side,final,.75,px,f,reg,['CIRCUIT_DISTANCE','CIRCUIT_ORDER_IMBALANCE','1500_DEADLINE_CAPACITY'],rationale,target_pct_override=dist,stop_pct_override=max(.35,min(dist/1.6,1.8)));made+=1;live_counts[side]=live_counts.get(side,0)+1
    stats.update({'running':False,'inserted':made,'completed_at':now_iso(),'duration_seconds':round(time.monotonic()-started,2),'status':'OK' if made else 'NO_ACTIONABLE_CANDIDATES','reason':None if made else 'ALL_NEAR_BAND_NAMES_FAILED_FRESH_INTRADAY_LIQUIDITY_EXECUTION_OR_DEADLINE_GATES','calibration':_circuit_calibration()});set_state('scan_status_CIRCUIT',stats);return made


def run_circuit_nextday_cycle()->int:
    now=datetime.now(IST);t=now.time().replace(tzinfo=None);settings=load_settings();target=next_trading_day(now.date()).isoformat();stats={'book':'CIRCUIT_NEXTDAY','at':now_iso(),'target_session':target,'freeze_time_ist':'15:00','published':0,'calibration':_circuit_calibration()}
    if not is_regular_trading_day(now.date()):stats['status']='SOURCE_MARKET_CLOSED';set_state('scan_status_CIRCUIT_NEXTDAY',stats);return 0
    if t<CIRCUIT_NEXTDAY_FREEZE:stats['status']='PREPARING_3PM_FREEZE';state=get_state('circuit_nextday_candidates',{}) or {};stats['prepared_candidates']=len(state.get('candidates') or {});set_state('scan_status_CIRCUIT_NEXTDAY',stats);return 0
    if t>MARKET_CLOSE:stats['status']='FREEZE_WINDOW_CLOSED';set_state('scan_status_CIRCUIT_NEXTDAY',stats);return 0
    with db() as con:
        if con.execute("SELECT COUNT(*) FROM recommendations WHERE book='CIRCUIT_NEXTDAY' AND period_key=?",(target,)).fetchone()[0]:stats['status']='ALREADY_FROZEN';set_state('scan_status_CIRCUIT_NEXTDAY',stats);return 0
    state=get_state('circuit_nextday_candidates',{}) or {};cands=list((state.get('candidates') or {}).values()) if state.get('source_session')==now.date().isoformat() else []
    cands=sorted(cands,key=lambda x:float(x.get('score') or 0),reverse=True);limit=max(1,min(8,int(settings.get('circuit_nextday_max_longs',5))))
    made=0
    for c in cands[:limit]:
        f=dict(c.get('features') or {});rationale={'reasons':['3PM frozen next-session upper-circuit propensity','daily trend/momentum','relative volume/order-book participation'],'lane':'3PM_NEXT_SESSION_LONG_ONLY','freeze_policy':'IDENTITY_ENTRY_TARGET_FROZEN_AT_15_00_IST','target_session':target,'source_session':now.date().isoformat(),'projected_circuit_band_pct':c.get('circuit_band_pct'),'order_imbalance':c.get('order_imbalance'),'candlestick_context':c.get('candlestick_context'),'data_confidence':c.get('confidence'),'target_is_not_guaranteed':True,'research_calibration':_circuit_calibration()}
        _insert_rec('CIRCUIT_NEXTDAY',c['symbol'],'LONG',float(c['score']),float(c['confidence']),float(c['price']),f,'NEXT_SESSION_CIRCUIT',['NEXTDAY_CIRCUIT_PROPENSITY','DAILY_TREND','PARTICIPATION'],rationale,exchange='NSE',target_pct_override=float(c.get('projected_target_pct') or 5),stop_pct_override=float(c.get('stop_pct') or 1.5),period_key_override=target);made+=1
    stats.update({'status':'FROZEN' if made>=5 else 'FREEZE_SHORTAGE','published':made,'required':5,'shortage':max(0,5-made),'recovery_required':made<5,'prepared_candidates':len(cands),'frozen_at':now_iso()});set_state('scan_status_CIRCUIT_NEXTDAY',stats);return made


def _us_session(now:Optional[datetime]=None)->Dict[str,Any]:
    local=(now or datetime.now(IST)).astimezone(NY);open_now=local.weekday()<5 and US_OPEN<=local.time().replace(tzinfo=None)<=US_CLOSE
    return {'open':open_now,'session_key':local.date().isoformat(),'local_time':local.isoformat(timespec='seconds'),'minutes_to_close':max(0,(16*60)-(local.hour*60+local.minute)) if open_now else 0,'regular_hours_et':'09:30-16:00'}


def _us_week_key(local_date)->str:
    monday=local_date-timedelta(days=local_date.weekday())
    return monday.isoformat()


def _international_weekly_geometry(f:Dict[str,Any],remaining_sessions:int,cost_reserve_pct:float,target_cap_pct:float)->Dict[str,Any]:
    atr=max(.10,float(f.get('atr_pct') or 1.0))
    sessions=max(1,int(remaining_sessions))
    momentum=max(0.0,float(f.get('ret5') or 0))*0.12+max(0.0,float(f.get('ret20') or 0))*0.05
    capacity=atr*math.sqrt(sessions)*1.08+momentum
    target=max(1.50,min(float(target_cap_pct),capacity*.64))
    stop=max(.60,min(3.50,atr*1.05))
    target=max(target,stop*1.60)
    feasible=bool(target<=float(target_cap_pct)+1e-9 and capacity>=target*1.04 and target-float(cost_reserve_pct)>=.80)
    return {
        'target_pct':round(target,4),
        'stop_pct':round(stop,4),
        'capacity_pct':round(capacity,4),
        'cost_reserve_pct':round(float(cost_reserve_pct),4),
        'expected_net_target_pct':round(target-float(cost_reserve_pct),4),
        'remaining_sessions':sessions,
        'feasible':feasible,
    }


def update_international_books(intraday_map:Optional[Dict[str,Any]]=None)->int:
    # v6.3.1: INTERNATIONAL is a frozen weekly LONG-only book. Rows are repriced
    # while U.S. data is available but are NOT closed at each daily session end.
    session=_us_session();now=datetime.now(IST);local=now.astimezone(NY);week_key=_us_week_key(local.date());closed=0
    with db() as con:rows=[dict(r) for r in con.execute("SELECT * FROM recommendations WHERE book='INTERNATIONAL' AND state='LIVE'").fetchall()]
    if not rows:return 0
    symbols=sorted({r['symbol'] for r in rows});imap=intraday_map if intraday_map is not None else _shared_international_history(symbols,'5d','5m',90.0)
    week_over=bool(local.weekday()>4 or (local.weekday()==4 and local.time().replace(tzinfo=None)>=US_CLOSE))
    with db() as con:
        for r in rows:
            df=imap.get(r['symbol']) if isinstance(imap,dict) else None;px=float(r['current_price'] or r['entry_price'])
            if df is not None and len(df):
                try:px=float(df['close'].dropna().iloc[-1])
                except Exception:pass
            entry=float(r['entry_price'] or 0);move=(px/entry-1)*100 if entry>0 else 0.0;mfe=max(float(r['max_favourable_pct'] or 0),move);mae=min(float(r['max_adverse_pct'] or 0),move);reason=result=None
            if move>=float(r['target_pct'] or 0):reason='WEEKLY_TARGET_REACHED';result='WIN'
            elif px<=float(r['stop_price'] or 0):reason='WEEKLY_THESIS_INVALIDATED';result='LOSS'
            elif r['period_key']!=week_key or week_over:reason='US_WEEK_END';result='MISS'
            if reason:
                con.execute("UPDATE recommendations SET current_price=?,max_favourable_pct=?,max_adverse_pct=?,state='CLOSED',closed_at=?,result=?,close_reason=?,updated_at=? WHERE recommendation_id=? AND state='LIVE'",(px,mfe,mae,now_iso(),result,reason,now_iso(),r['recommendation_id']));closed+=1
            else:
                con.execute("UPDATE recommendations SET current_price=?,max_favourable_pct=?,max_adverse_pct=?,updated_at=? WHERE recommendation_id=?",(px,mfe,mae,now_iso(),r['recommendation_id']))
    return closed


def _international_target_week(local:datetime)->tuple[str,bool]:
    """Return target Monday and whether this is the preferred pre-week publication window."""
    lt=local.time().replace(tzinfo=None);d=local.date();preweek=False
    if local.weekday()==4 and lt>=US_CLOSE:
        d=d+timedelta(days=3);preweek=True
    elif local.weekday()==5:
        d=d+timedelta(days=2);preweek=True
    elif local.weekday()==6:
        d=d+timedelta(days=1);preweek=True
    elif local.weekday()==0 and lt<US_OPEN:
        preweek=True
    return _us_week_key(d),preweek


def _daily_bar_age_days(df, local:datetime)->Optional[int]:
    if df is None or not len(df):return None
    try:
        x=df.index[-1]
        if hasattr(x,'date'):d=x.date()
        else:d=datetime.fromisoformat(str(x)).date()
        return (local.date()-d).days
    except Exception:return None


def run_international_cycle():
    """Five-name U.S. weekly freeze with pre-week publication and deterministic recovery.

    Uses completed daily bars for pre-week publication. It never treats an empty freeze marker
    as a completed book, never backfills with stale data, and never lowers trade-intelligence
    or weekly-capacity gates merely to reach five.
    """
    started=time.monotonic();now=datetime.now(IST);session=_us_session(now);settings=load_settings();local=now.astimezone(NY)
    week_key,preweek=_international_target_week(local);required=_freeze_contract_min('INTERNATIONAL') or 5
    stats={'book':'INTERNATIONAL','started_at':now_iso(),'session':session,'week_key':week_key,'inserted':0,'updated_or_closed':0,
           'side_policy':'LONG_ONLY','holding_policy':'FROZEN_WEEKLY_NO_REPLACEMENT','contract_required':required,'preferred_window':'AFTER_FRIDAY_CLOSE_TO_MONDAY_OPEN',
           'running':True,'status':'RECOVERY_STARTING'}
    set_state('scan_status_INTERNATIONAL',stats)
    stats['updated_or_closed']=update_international_books()
    if not settings.get('international_enabled',True):
        stats.update({'status':'DISABLED','running':False,'completed_at':now_iso(),'duration_seconds':round(time.monotonic()-started,2)});set_state('scan_status_INTERNATIONAL',stats);return 0

    existing=_freeze_contract_count('INTERNATIONAL',week_key)
    with db() as con:
        existing_symbols={str(r[0]) for r in con.execute("SELECT symbol FROM recommendations WHERE book='INTERNATIONAL' AND period_key=? AND side='LONG' AND COALESCE(result,'')<>'VOID'",(week_key,)).fetchall()}
    if existing>=required:
        freeze_payload={'frozen':True,'contract_complete':True,'required':required,'published_total':existing,'shortage':0,'week_key':week_key,'policy':'V649_PREWEEK_FIVE_PICK_FREEZE_NO_REPLACEMENT'}
        old=get_state('international_weekly_freeze_'+week_key,{}) or {};freeze_payload['frozen_at']=old.get('frozen_at') or now_iso();set_state('international_weekly_freeze_'+week_key,freeze_payload)
        stats.update({'status':'WEEKLY_BOOK_FROZEN','running':False,'published':existing,'contract':freeze_payload,'frozen_at':freeze_payload['frozen_at'],'completed_at':now_iso(),'duration_seconds':round(time.monotonic()-started,2)});set_state('scan_status_INTERNATIONAL',stats);return 0

    # Normal publication is after Friday close/weekend/Monday pre-open. If that was missed,
    # recover during the current week from recent completed daily bars rather than staying empty.
    current_week=_us_week_key(local.date())
    recovery=(week_key==current_week and not preweek)
    stats.update({'status':'FETCHING_BOUNDED_DAILY_RECOVERY_DATA','preweek_window':preweek,'recovery_mode':recovery})
    set_state('scan_status_INTERNATIONAL',stats)
    daily=_shared_international_history(US_WEEKLY_UNIVERSE,'1y','1d',600.0)
    stats['daily_symbols']=len(daily)
    stats['transport']=get_state('international_batch_transport',{}) or {}
    stats['status']='SCORING_BOUNDED_DAILY_RECOVERY_DATA'
    set_state('scan_status_INTERNATIONAL',stats)
    g=get_state('global_context',{}) or {};regime_state={'regime':'US_WEEKLY','trend_vote':0,'breadth_up_pct':50,'breadth_down_pct':50}
    remaining_sessions=5 if preweek else max(1,5-local.weekday())
    reserve=float(settings.get('international_weekly_cost_reserve_pct',.50));cap=float(settings.get('international_weekly_target_cap_pct',8.0));min_score=float(settings.get('international_weekly_min_score',78.0));candidates=[];stale=0
    for sym in US_WEEKLY_UNIVERSE:
        if sym in existing_symbols:continue
        dd=daily.get(sym)
        if dd is None or len(dd)<120:continue
        age=_daily_bar_age_days(dd,local)
        if age is None or age<0 or age>5:
            stale+=1;continue
        try:px=float(dd['close'].dropna().iloc[-1])
        except Exception:continue
        if px<=0:continue
        f=latest_features(dd);f['close']=px;f['higher_tf_trend']=f.get('trend',0);candles=detect_patterns(dd)
        trend=float(f.get('trend') or 0)>0;ret5=float(f.get('ret5') or 0);ret20=float(f.get('ret20') or 0);ret60=float(f.get('ret60') or 0);adx=float(f.get('adx14') or 0);z=float(f.get('z20') or 0)
        if not trend or ret20<=0 or ret60<=0 or z>2.8:continue
        geom=_international_weekly_geometry(f,remaining_sessions,reserve,cap)
        if not geom['feasible']:continue
        score=52.0+min(14,max(0,ret5)*2.0)+min(16,max(0,ret20)*.75)+min(8,max(0,ret60)*.20)+min(8,max(0,adx-15)*.35)
        if score<min_score:continue
        ti=evaluate_trade_intelligence(book='INTERNATIONAL',symbol=sym,side='LONG',features=f,fundamentals={},regime_state=regime_state,candle_info=candles,global_ctx=g,target_pct=geom['target_pct'],stop_pct=geom['stop_pct'],strategy_ids=['US_WEEKLY_TREND','US_WEEKLY_MOMENTUM','US_WEEKLY_LOW_TURNOVER'],data_confidence=.86)
        if ti['decision']!='ELIGIBLE':continue
        edge=max(0.0,geom['capacity_pct']*min(1.05,max(.65,score/100.0))*.58-reserve)
        candidates.append((edge,score,sym,px,f,candles,ti,geom,age))
    need=max(0,required-existing);made=0
    configured_max=max(1,int(settings.get('international_weekly_max_longs',5) or 5))
    max_longs=required  # a preserved lower legacy setting may not weaken the five-pick contract
    take=min(need,max_longs)
    for rank,(edge,score,sym,px,f,candles,ti,geom,age) in enumerate(sorted(candidates,key=lambda x:(x[0],x[1]),reverse=True)[:take],start=existing+1):
        rationale={'reasons':['frozen U.S. weekly LONG opportunity','completed daily trend and multi-week momentum','ranked by expected net weekly edge after turnover/friction reserve'],
            'data_confidence':.86,'candlestick_context':candles,'trade_intelligence':ti,'global_context':g,'session_policy':'US_WEEKLY_FROZEN_LONG_ONLY',
            'freeze_policy':'V649_PREWEEK_OR_RECOVERY_RECENT_DAILY_CLOSE','week_key':week_key,'remaining_sessions':geom['remaining_sessions'],'capacity_pct':geom['capacity_pct'],
            'cost_reserve_pct':geom['cost_reserve_pct'],'expected_net_target_pct':geom['expected_net_target_pct'],'expected_net_weekly_edge_pct':round(edge,4),
            'weekly_rank':rank,'daily_bar_age_days':age,'selection_objective':'MAX_EXPECTED_NET_WEEKLY_RETURN_AMONG_DATA_VALID_US_UNIVERSE',
            'turnover_policy':'ONE_FROZEN_ENTRY_PER_SYMBOL_PER_WEEK_NO_REPLACEMENT','target_is_not_guaranteed':True}
        _insert_rec('INTERNATIONAL',sym,'LONG',score,.78,px,f,'US_WEEKLY',['US_WEEKLY_TREND','US_WEEKLY_MOMENTUM','US_WEEKLY_LOW_TURNOVER'],rationale,exchange='US',target_pct_override=geom['target_pct'],stop_pct_override=geom['stop_pct'],period_key_override=week_key);made+=1
    total=_freeze_contract_count('INTERNATIONAL',week_key);shortage=max(0,required-total);complete=total>=required
    freeze_payload={'frozen':complete,'contract_complete':complete,'week_key':week_key,'frozen_at':now_iso() if complete else None,'published_this_cycle':made,
                    'published_total':total,'required':required,'shortage':shortage,'qualified_candidates':len(candidates),'universe':len(US_WEEKLY_UNIVERSE),
                    'stale_daily_rejects':stale,'recovery_required':not complete,'policy':'V649_PREWEEK_FIVE_PICK_FREEZE_NO_REPLACEMENT'}
    set_state('international_weekly_freeze_'+week_key,freeze_payload)
    status='CONTRACT_FULFILLED' if complete else 'FREEZE_CONTRACT_SHORTAGE_RECOVERY_REQUIRED'
    freeze_payload['reason']=None if complete else ('NO_FRESH_DAILY_DATA' if not daily else ('FEWER_THAN_FIVE_DATA_VALID_US_CANDIDATES' if len(candidates)<required else 'QUALIFIED_CANDIDATES_ACCUMULATING'))
    stats.update({'inserted':made,'published':total,'qualified_candidates':len(candidates),'status':status,'contract':freeze_payload,
                  'running':False,'completed_at':now_iso(),'duration_seconds':round(time.monotonic()-started,2)})
    set_state('scan_status_INTERNATIONAL',stats);return made

