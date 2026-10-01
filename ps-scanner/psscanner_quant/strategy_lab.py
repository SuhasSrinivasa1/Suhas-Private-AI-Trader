from __future__ import annotations

import hashlib
import json
import math
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple, Optional

import requests

from .constants import IST
from .data import history, liquidity_rank, live_prices
from .db import db, get_state, health, now_iso, set_state
from .features import enrich, latest_features
from .handbook import strategy_catalog, family_evidence_grade
from .regime import classify
from .trading_calendar import add_trading_sessions, is_regular_trading_day
from .fundamentals import snapshot_history, resolve_snapshot, get as fundamentals_get
from .strategy_library import score_strategy, library_status, challenger_strategies

KEYWORDS={
    "momentum":"MOMENTUM","mean reversion":"MEAN_REVERSION","breakout":"TREND_BREAKOUT",
    "volatility":"VOLATILITY_EXPANSION","volume":"VOLUME_BREAKOUT","relative strength":"RELATIVE_STRENGTH",
    "macd":"MACD_TREND","rsi":"RSI_REVERSAL","bollinger":"BOLLINGER_REVERSION",
    "donchian":"DONCHIAN_BREAKOUT","gap":"GAP_CONTINUATION","pullback":"TREND_PULLBACK",
}


def _mapped_family(text:str)->Optional[str]:
    low=text.lower()
    return next((v for k,v in KEYWORDS.items() if k in low),None)


def discover_new_strategies() -> Dict[str,Any]:
    found=[]
    queries=["quantitative trading strategy","momentum mean reversion market microstructure","systematic equity trading","factor investing trading strategy","intraday regime liquidity strategy"]
    for q in queries:
        try:
            url="https://export.arxiv.org/api/query?"+urllib.parse.urlencode({"search_query":"all:"+q,"start":0,"max_results":15,"sortBy":"submittedDate","sortOrder":"descending"})
            txt=requests.get(url,timeout=20,headers={"User-Agent":"PSScannerQuant/6.2"}).text
            root=ET.fromstring(txt);ns={"a":"http://www.w3.org/2005/Atom"}
            for e in root.findall("a:entry",ns):
                title=" ".join((e.findtext("a:title",default="",namespaces=ns) or "").split());abstract=" ".join((e.findtext("a:summary",default="",namespaces=ns) or "").split());link=e.findtext("a:id",default="",namespaces=ns);pub=e.findtext("a:published",default="",namespaces=ns)
                fp=hashlib.sha256((title+link).encode()).hexdigest();found.append((fp,"arXiv",title,link,pub,abstract))
        except Exception as exc: health("strategy_discovery","WARN",str(exc)[:200])
    # The uploaded handbook is a permanent research source. It is seeded separately by
    # strategy_library.seed_library; discovery uses it for duplicate/concept matching.
    handbook_names=[str(x.get('name') or '').lower() for x in strategy_catalog()]
    mapped=0;duplicates=0
    with db() as con:
        for fp,src,title,url,pub,abstract in found:
            text=(title+" "+abstract).lower();family=_mapped_family(text)
            handbook_overlap=any(name and (name in text or text[:100] in name) for name in handbook_names)
            if handbook_overlap:duplicates+=1
            con.execute("INSERT OR IGNORE INTO strategy_discovery(fingerprint,discovered_at,source_name,title,source_url,published_at,abstract,mapped_family,status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)",(fp,now_iso(),src,title,url,pub,abstract[:5000],family,"MAPPED_TEMPLATE_REVIEW" if family else "DISCOVERED",json.dumps({"automatic_code_execution":False,"handbook_overlap":handbook_overlap})))
            if family:mapped+=1
    result={"at":now_iso(),"fetched":len(found),"mapped_to_safe_templates":mapped,"handbook_overlaps":duplicates,"policy":"Never execute downloaded or AI-generated strategy code. New research can only map into audited local templates and must pass chronological validation before promotion."}
    set_state("last_strategy_discovery",result);return result


def _pf(vals:List[float])->float:
    pos=sum(x for x in vals if x>0);neg=abs(sum(x for x in vals if x<0));return pos/neg if neg>1e-9 else 9.9


def _avg(vals:List[float])->float:
    return sum(vals)/len(vals) if vals else 0.0


def _drawdown(vals:List[float])->float:
    eq=peak=0.0;dd=0.0
    for x in vals:eq+=x;peak=max(peak,eq);dd=min(dd,eq-peak)
    return dd


def validate_strategies(max_symbols:int=18)->Dict[str,Any]:
    """Chronological Champion contract with train/walk/holdout and cost reserve.

    Fundamental inputs are used only when a snapshot had already been captured at the historical
    decision timestamp. Older dates intentionally receive no fundamental payload.
    """
    syms=liquidity_rank(max_symbols)
    if len(syms)<5:return {"status":"WAITING_FOR_HISTORY","symbols":len(syms)}
    with db() as con:
        specs=[dict(r) for r in con.execute("SELECT * FROM strategies WHERE horizon IN ('INTRADAY','WEEKLY','MONTHLY') AND status<>'HANDBOOK_REFERENCE'").fetchall()]
    cache={}
    for horizon in ("INTRADAY","WEEKLY","MONTHLY"):
        interval="5minute" if horizon=="INTRADAY" else "1day";cache[horizon]={}
        for s in syms:
            df=history(s,interval,allow_network=False);cache[horizon][s]=enrich(df) if len(df)>=50 else None
    # Point-in-time fundamental snapshots are prospective. Before v6.2 capture begins they
    # simply resolve to {}, which is safer than leaking today's fundamentals into the past.
    fund_cache={s:snapshot_history(s) for s in syms}
    raw_metrics={};M=max(2,len(specs));run_id='VAL-'+uuid.uuid4().hex[:12]
    for sp in specs:
        try:sp["params"]=json.loads(sp.get("params_json") or "{}")
        except Exception:sp["params"]={}
        horizon=sp["horizon"];side=sp["side"];fwd=6 if horizon=="INTRADAY" else (5 if horizon=="WEEKLY" else 20)
        # Avoid treating heavily overlapping forward outcomes as independent evidence.
        step=8 if horizon=="INTRADAY" else fwd
        cost_pct=.22 if horizon=="INTRADAY" else .16
        vals=[]
        for s,df in cache.get(horizon,{}).items():
            if df is None or len(df)<fwd+45:continue
            for i in range(35,len(df)-fwd,step):
                r=df.iloc[i];feat={k:(None if isinstance(v,float) and math.isnan(v) else v) for k,v in r.to_dict().items()};reg="TREND_UP" if float(feat.get("trend") or 0)>0 else ("TREND_DOWN" if float(feat.get("trend") or 0)<0 else "RANGE")
                bar_ts=df.index[i]
                pit_fund=resolve_snapshot(fund_cache.get(s) or [], bar_ts.to_pydatetime() if hasattr(bar_ts,'to_pydatetime') else bar_ts)
                sc,_=score_strategy(sp,feat,reg,pit_fund)
                if sc<70:continue
                p0=float(r["close"]);p1=float(df.iloc[i+fwd]["close"]);raw=(p1/p0-1)*100*(1 if side=="LONG" else -1);atr=max(.35,float(feat.get("atr_pct") or 1));rval=max(-3,min(3,(raw-cost_pct)/atr))
                vals.append((bar_ts,rval))
        vals.sort(key=lambda x:x[0]);rv=[x[1] for x in vals];n=len(rv)
        if n<24:continue
        a=max(1,int(n*.60));b=max(a+1,int(n*.80));train=rv[:a];walk=rv[a:b];hold=rv[b:]
        wr=sum(1 for x in rv if x>0)/n*100;avg=_avg(rv);train_avg=_avg(train);walk_avg=_avg(walk);hold_avg=_avg(hold);pf=_pf(rv);dd=_drawdown(rv)
        robust=sum(1 for v in (train_avg,walk_avg,hold_avg) if v>0)/3.0
        mt_penalty=math.sqrt(2.0*math.log(M)/max(1,n))*0.12
        raw_metrics[sp['strategy_id']]={'sp':sp,'n':n,'wr':wr,'avg':avg,'train':train_avg,'walk':walk_avg,'hold':hold_avg,'pf':pf,'dd':dd,'robust':robust,'penalty':mt_penalty}
    # Parameter-neighborhood stability: prefer broad positive regions over a lucky parameter.
    groups={}
    for sid,m in raw_metrics.items():
        sp=m['sp'];groups.setdefault((sp['family'],sp['horizon'],sp['side']),[]).append(m)
    for g in groups.values():
        g.sort(key=lambda m:int((m['sp'].get('params') or {}).get('level',0)))
        for idx,m in enumerate(g):
            neighbors=g[max(0,idx-1):idx+2]
            m['stability']=sum(1 for x in neighbors if x['avg']>0 and x['hold']>=0)/max(1,len(neighbors))
    promoted=[];suspended=[];updated=0;ts=now_iso()
    with db() as con:
        for sid,m in raw_metrics.items():
            adjusted=m['avg']-m['penalty'];score=adjusted*24+m['hold']*18+m['walk']*12+(m['wr']-50)*.20+min(10,(m['pf']-1)*7)+m['robust']*9+m['stability']*7+max(-12,m['dd']*.20)
            evidence_grade=family_evidence_grade(m['sp'].get('family'))
            minimum_samples={'A':50,'B':70,'C':100,'UNRATED':120}.get(evidence_grade,120)
            sh=shadow_stats(sid);shadow_required={'INTRADAY':20,'WEEKLY':8,'MONTHLY':3}.get(m['sp'].get('horizon'),8)
            shadow_ok=(m['sp'].get('status')=='SEED_CHAMPION') or (sh['n']>=shadow_required and sh['avg_r']>0 and sh['profit_factor']>1.0)
            eligible=bool(m['n']>=minimum_samples and adjusted>.035 and m['walk']>.015 and m['hold']>.015 and m['pf']>1.10 and m['robust']>=2/3 and m['stability']>=.5 and shadow_ok)
            con.execute("INSERT INTO strategy_stats(strategy_id,regime,sample_count,win_rate,avg_r,profit_factor,max_drawdown,robustness,walk_forward_score,score,last_validated_at,holdout_avg_r,cost_adjusted_avg_r,parameter_stability,multiple_testing_penalty,decay_state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(strategy_id,regime) DO UPDATE SET sample_count=excluded.sample_count,win_rate=excluded.win_rate,avg_r=excluded.avg_r,profit_factor=excluded.profit_factor,max_drawdown=excluded.max_drawdown,robustness=excluded.robustness,walk_forward_score=excluded.walk_forward_score,score=excluded.score,last_validated_at=excluded.last_validated_at,holdout_avg_r=excluded.holdout_avg_r,cost_adjusted_avg_r=excluded.cost_adjusted_avg_r,parameter_stability=excluded.parameter_stability,multiple_testing_penalty=excluded.multiple_testing_penalty,decay_state=excluded.decay_state",(sid,'ALL',m['n'],m['wr'],m['avg'],m['pf'],m['dd'],m['robust'],m['walk'],score,ts,m['hold'],adjusted,m['stability'],m['penalty'],'HEALTHY' if eligible else 'REVIEW'))
            con.execute("INSERT INTO strategy_validation_runs(run_id,strategy_id,validated_at,sample_count,train_avg_r,walk_avg_r,holdout_avg_r,cost_adjusted_avg_r,parameter_stability,multiple_testing_penalty,promotion_eligible,metrics_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,sid,ts,m['n'],m['train'],m['walk'],m['hold'],adjusted,m['stability'],m['penalty'],1 if eligible else 0,json.dumps({'win_rate':m['wr'],'profit_factor':m['pf'],'max_drawdown':m['dd'],'robustness':m['robust'],'score':score,'handbook_evidence_grade':evidence_grade,'minimum_samples_required':minimum_samples,'shadow':sh,'shadow_required':shadow_required,'shadow_ok':shadow_ok},separators=(',',':'))))
            if not eligible and m['n']>=50 and m['sp'].get('status')=='CHAMPION' and (m['hold']<-.03 or adjusted<0):
                con.execute("UPDATE strategies SET status='SUSPENDED',updated_at=? WHERE strategy_id=?",(ts,sid));suspended.append(sid)
            updated+=1
        eligible_ids=[]
        for sid,m in raw_metrics.items():
            sh=shadow_stats(sid);shadow_required={'INTRADAY':20,'WEEKLY':8,'MONTHLY':3}.get(m['sp'].get('horizon'),8)
            shadow_ok=(m['sp'].get('status')=='SEED_CHAMPION') or (sh['n']>=shadow_required and sh['avg_r']>0 and sh['profit_factor']>1.0)
            if (m['n'] >= {'A':50,'B':70,'C':100,'UNRATED':120}.get(family_evidence_grade(m['sp'].get('family')),120)
                and (m['avg']-m['penalty'])>.035 and m['walk']>.015 and m['hold']>.015
                and m['pf']>1.10 and m['robust']>=2/3 and m.get('stability',0)>=.5 and shadow_ok):eligible_ids.append(sid)
        grouped={}
        for sid in eligible_ids:
            m=raw_metrics[sid];sp=m['sp']
            if sp.get('status') not in ('CHALLENGER','SEED_CHAMPION','SUSPENDED'):continue
            grouped.setdefault((sp['family'],sp['horizon'],sp['side']),[]).append((sid, (m['avg']-m['penalty'])*24+m['hold']*18+m['walk']*12))
        for _,items in grouped.items():
            items.sort(key=lambda x:x[1],reverse=True)
            for sid,_ in items[:2]:
                con.execute("UPDATE strategies SET status='CHAMPION',updated_at=? WHERE strategy_id=?",(ts,sid));promoted.append(sid)
        counts=con.execute("SELECT horizon,side,COUNT(*) FROM strategies WHERE status='CHAMPION' GROUP BY horizon,side").fetchall()
        for h,side,n in counts:
            if n>=5:con.execute("UPDATE strategies SET status='CHALLENGER',updated_at=? WHERE horizon=? AND side=? AND status='SEED_CHAMPION'",(ts,h,side))
    result={'status':'OK','run_id':run_id,'validated':updated,'promoted':len(set(promoted)),'suspended':len(set(suspended)),'symbols':len(syms),'strategies_tested':len(specs),'point_in_time_fundamental_backtest':'ENABLED_WHERE_PROSPECTIVE_SNAPSHOTS_EXIST; EMPTY_BEFORE_FIRST_CAPTURE','at':ts}
    set_state('last_strategy_validation',result);return result


def monitor_strategy_decay(min_live_samples:int=12)->Dict[str,Any]:
    """Suspend Champions only after predeclared live evidence thresholds are breached."""
    with db() as con:
        champs=[r[0] for r in con.execute("SELECT strategy_id FROM strategies WHERE status='CHAMPION'").fetchall()]
        closed=[dict(r) for r in con.execute("SELECT strategy_ids_json,side,entry_price,current_price,stop_price FROM recommendations WHERE state='CLOSED' ORDER BY closed_at DESC LIMIT 3000").fetchall()]
    stats={sid:[] for sid in champs}
    for r in closed:
        try:ids=json.loads(r.get('strategy_ids_json') or '[]')
        except Exception:ids=[]
        entry=float(r.get('entry_price') or 0);px=float(r.get('current_price') or entry);stop=float(r.get('stop_price') or 0);side=r.get('side')
        if entry<=0:continue
        risk=abs(entry-stop)/entry*100 if stop>0 else 1.0
        ret=(px/entry-1)*100*(1 if side=='LONG' else -1);rv=max(-5,min(5,ret/max(.2,risk)))
        for sid in ids:
            if sid in stats and len(stats[sid])<60:stats[sid].append(rv)
    suspended=[]
    with db() as con:
        for sid,vals in stats.items():
            if len(vals)<min_live_samples:continue
            recent=vals[:min_live_samples];avg=_avg(recent);pf=_pf(recent);loss_rate=sum(1 for x in recent if x<=0)/len(recent)
            if avg<-.12 or pf<.70 or loss_rate>=.78:
                con.execute("UPDATE strategies SET status='SUSPENDED',updated_at=? WHERE strategy_id=? AND status='CHAMPION'",(now_iso(),sid));con.execute("UPDATE strategy_stats SET decay_state='SUSPENDED_LIVE_DECAY' WHERE strategy_id=?",(sid,));suspended.append(sid)
    out={'at':now_iso(),'evaluated':sum(1 for v in stats.values() if len(v)>=min_live_samples),'suspended':suspended,'min_live_samples':min_live_samples}
    set_state('last_strategy_decay_monitor',out);return out



def _shadow_due(horizon:str, opened:datetime)->datetime:
    if horizon=='INTRADAY':return opened.replace(microsecond=0)+timedelta(minutes=30)
    if horizon=='WEEKLY':return add_trading_sessions(opened,5)
    return add_trading_sessions(opened,20)


def run_shadow_cycle(max_symbols:int=28, challengers_per_side:int=14)->Dict[str,Any]:
    """Run Challengers against live data without capital or recommendation publication."""
    now=datetime.now(IST)
    # Intraday shadowing is only meaningful during the trading session. Weekly/monthly
    # challengers can be observed once per hour while the market is open.
    if (not is_regular_trading_day(now.date())) or not (datetime.strptime('09:15','%H:%M').time() <= now.time().replace(tzinfo=None) <= datetime.strptime('15:05','%H:%M').time()):
        return {'status':'MARKET_CLOSED_OR_OUTSIDE_SHADOW_WINDOW','at':now_iso()}
    syms=liquidity_rank(max_symbols)
    if not syms:return {'status':'WAITING_FOR_UNIVERSE','at':now_iso()}
    prices=live_prices(syms);reg=str((classify() or {}).get('regime') or 'RANGE')
    opened=0;bucket=now.replace(minute=(now.minute//15)*15,second=0,microsecond=0)
    for horizon in ('INTRADAY','WEEKLY','MONTHLY'):
        interval='5minute' if horizon=='INTRADAY' else '1day'
        for side in ('LONG','SHORT'):
            specs=challenger_strategies(horizon,side,challengers_per_side)
            if not specs:continue
            for sym in syms:
                df=history(sym,interval,allow_network=False)
                if len(df)<35:continue
                f=latest_features(df);px=float(prices.get(sym) or f.get('close') or 0)
                if px<=0:continue
                f['close']=px
                fund={} if horizon=='INTRADAY' else fundamentals_get(sym,allow_refresh=False)
                if horizon!='INTRADAY' and not fund:continue
                scored=[]
                for sp in specs:
                    sc,reasons=score_strategy(sp,f,reg,fund)
                    if sc>=74:scored.append((sc,sp,reasons))
                scored.sort(key=lambda x:x[0],reverse=True)
                for sc,sp,reasons in scored[:3]:
                    sid=str(sp['strategy_id']);shadow_id=hashlib.sha256(f'{sid}|{sym}|{side}|{bucket.isoformat()}'.encode()).hexdigest()[:30]
                    due=_shadow_due(horizon,now);atr=max(.25,float(f.get('atr_pct') or 1.0))
                    try:
                        with db() as con:
                            con.execute("INSERT OR IGNORE INTO shadow_signals(shadow_id,strategy_id,horizon,symbol,side,regime,score,entry_price,atr_pct,opened_at,due_at,state,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,'OPEN',?)",(shadow_id,sid,horizon,sym,side,reg,sc,px,atr,now_iso(),due.isoformat(timespec='seconds'),json.dumps({'reasons':reasons[:5],'family':sp.get('family'),'non_executable':True},separators=(',',':'))))
                            if con.execute('SELECT changes()').fetchone()[0]:opened+=1
                    except Exception as exc:health('shadow','WARN',str(exc)[:180])
    out={'status':'OK','opened':opened,'at':now_iso(),'policy':'Shadow signals never publish recommendations or place orders.'}
    set_state('last_shadow_cycle',out);return out


def _shadow_exit_price(row:Dict[str,Any], now:datetime, live:Dict[str,float])->float:
    """Resolve at the scheduled horizon timestamp, not at an arbitrarily later restart time."""
    try:due=datetime.fromisoformat(str(row.get('due_at')))
    except Exception:due=now
    if due.tzinfo is None:due=due.replace(tzinfo=IST)
    interval='1day' if row.get('horizon')!='INTRADAY' else '5minute'
    try:
        df=history(str(row['symbol']),interval,allow_network=False)
        if len(df):
            idx=df.index
            target=due
            try:
                if getattr(idx,'tz',None) is not None and target.tzinfo is None:target=target.replace(tzinfo=IST)
                if getattr(idx,'tz',None) is None and target.tzinfo is not None:target=target.replace(tzinfo=None)
            except Exception:pass
            eligible=df.loc[idx<=target]
            if len(eligible):return float(eligible.iloc[-1]['close'])
    except Exception:pass
    # A near-real-time resolution may safely use the current quote. If the application was
    # offline well past the due time, WAIT for historical data rather than introducing horizon drift.
    if abs((now-due).total_seconds())<=900:
        try:return float(live.get(str(row['symbol'])) or 0)
        except Exception:return 0.0
    return 0.0


def resolve_shadow_signals(limit:int=400)->Dict[str,Any]:
    now=datetime.now(IST)
    with db() as con:
        rows=[dict(r) for r in con.execute("SELECT * FROM shadow_signals WHERE state='OPEN' AND due_at<=? ORDER BY due_at LIMIT ?",(now.isoformat(timespec='seconds'),limit)).fetchall()]
    if not rows:return {'resolved':0,'waiting_for_asof_price':0,'at':now_iso()}
    prices=live_prices([r['symbol'] for r in rows]);waiting=0

    # v6.3.7: historical/as-of price resolution may parse hundreds of cached frames.
    # Do all of that outside a database context. The prior implementation held the
    # shared DB context across this loop, which could starve live scanners for minutes.
    updates=[]
    for r in rows:
        px=_shadow_exit_price(r,now,prices)
        if px<=0:
            waiting+=1;continue
        sign=1 if r['side']=='LONG' else -1
        ret=(px/float(r['entry_price'])-1)*100*sign
        atr=max(.25,float(r.get('atr_pct') or 1))
        rv=max(-5,min(5,ret/atr))
        updates.append((px,now_iso(),ret,rv,r['shadow_id']))

    resolved=0
    if updates:
        with db() as con:
            for args in updates:
                cur=con.execute("UPDATE shadow_signals SET state='RESOLVED',exit_price=?,resolved_at=?,return_pct=?,r_multiple=? WHERE shadow_id=? AND state='OPEN'",args)
                resolved += max(0,int(cur.rowcount or 0))
    out={'resolved':resolved,'waiting_for_asof_price':waiting,'at':now_iso(),'policy':'Exit is measured at/just before due_at; overdue signals are not silently repriced at a later restart time. History resolution runs outside DB write contexts.'};set_state('last_shadow_resolution',out);return out


def shadow_stats(strategy_id:str)->Dict[str,Any]:
    with db() as con:
        rs=con.execute("SELECT r_multiple FROM shadow_signals WHERE strategy_id=? AND state='RESOLVED' ORDER BY resolved_at DESC LIMIT 80",(strategy_id,)).fetchall()
    vals=[float(r[0]) for r in rs if r[0] is not None]
    return {'n':len(vals),'avg_r':_avg(vals),'profit_factor':_pf(vals) if vals else 0.0,'win_rate':(100*sum(1 for x in vals if x>0)/len(vals)) if vals else 0.0}

def maybe_weekly_jobs()->None:
    """Maintain strategy evidence continuously and validate after each NSE trading day.

    Daily validation updates evidence/statistics only once after 18:00 IST. Promotion still
    requires the unchanged Champion contract. Saturday discovery and an independent Sunday
    post-discovery validation are retained.
    """
    now=datetime.now(IST);week=now.strftime("%G-W%V");day=now.date().isoformat()

    if now.weekday()==5 and now.hour>=10 and get_state("strategy_discovery_week")!=week:
        discover_new_strategies();set_state("strategy_discovery_week",week)

    if is_regular_trading_day(now.date()) and now.hour>=18 and get_state("strategy_validation_day")!=day:
        result=validate_strategies()
        set_state("strategy_validation_day",day)
        set_state("last_daily_strategy_validation",{"day":day,"week":week,"trigger":"DAILY_TRADING_DAY_AFTER_18_IST","result":result})

    # Independent marker: a Friday daily validation must never suppress the Sunday
    # post-discovery pass for the same ISO week.
    if now.weekday()==6 and now.hour>=18 and get_state("strategy_validation_week")!=week:
        result=validate_strategies()
        set_state("strategy_validation_week",week)
        set_state("last_weekly_strategy_validation",{"week":week,"trigger":"SUNDAY_AFTER_18_IST","result":result})

    if now.hour>=16 and get_state('strategy_decay_day')!=day:
        monitor_strategy_decay();set_state('strategy_decay_day',day)


def status()->Dict[str,Any]:
    base=library_status();base["last_discovery"]=get_state("last_strategy_discovery",{});base["last_validation"]=get_state("last_strategy_validation",{});base['last_decay_monitor']=get_state('last_strategy_decay_monitor',{})
    with db() as con:
        base["recent_discoveries"]=[dict(r) for r in con.execute("SELECT discovered_at,source_name,title,source_url,mapped_family,status FROM strategy_discovery ORDER BY discovered_at DESC LIMIT 20").fetchall()]
        base['champion_validation']=[dict(r) for r in con.execute("SELECT s.strategy_id,s.name,s.family,s.horizon,s.side,s.status,st.sample_count,st.win_rate,st.avg_r,st.profit_factor,st.holdout_avg_r,st.cost_adjusted_avg_r,st.parameter_stability,st.multiple_testing_penalty,st.decay_state,st.score FROM strategies s LEFT JOIN strategy_stats st ON st.strategy_id=s.strategy_id AND st.regime='ALL' WHERE s.status IN ('CHAMPION','SUSPENDED') ORDER BY s.status,st.score DESC LIMIT 60").fetchall()]
    with db() as con:
        sr=con.execute("SELECT state,COUNT(*) n FROM shadow_signals GROUP BY state").fetchall();base['shadow_signals']={r[0]:r[1] for r in sr}
        base['recent_shadow_resolved']=[dict(r) for r in con.execute("SELECT resolved_at,strategy_id,horizon,symbol,side,return_pct,r_multiple FROM shadow_signals WHERE state='RESOLVED' ORDER BY resolved_at DESC LIMIT 30").fetchall()]
    base['last_shadow_cycle']=get_state('last_shadow_cycle',{});base['last_shadow_resolution']=get_state('last_shadow_resolution',{})
    base['learning_cadence']={'validation':'DAILY_AFTER_18_IST_ON_NSE_TRADING_DAYS','weekly_deep_validation':'SUNDAY_AFTER_18_IST_POST_DISCOVERY','decay':'DAILY_AFTER_16_IST','discovery':'SATURDAY_AFTER_10_IST','promotion':'UNCHANGED_STRICT_CHAMPION_CONTRACT'};base['last_daily_validation']=get_state('last_daily_strategy_validation',{});base['last_weekly_validation']=get_state('last_weekly_strategy_validation',{})
    base['champion_contract']={'minimum_samples_by_handbook_evidence':{'A':50,'B':70,'C':100,'UNRATED':120},'requires_positive_walk_forward':True,'requires_positive_untouched_holdout':True,'cost_adjusted':True,'parameter_neighborhood_stability':True,'multiple_testing_penalty':True,'live_shadow_required_for_challenger_promotion':True,'shadow_minimums':{'INTRADAY':20,'WEEKLY':8,'MONTHLY':3},'live_decay_suspension':True,'point_in_time_fundamentals':'prospective snapshots are now accumulated and only used at/after their capture timestamp'}
    return base
