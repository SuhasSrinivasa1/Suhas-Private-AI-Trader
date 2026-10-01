from __future__ import annotations
import json, uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from .broker import broker, order_plan
from .config import load_settings
from .constants import IST, MARKET_OPEN, MARKET_CLOSE, SHORT_HARD_EXIT, TRADE_NOTIONAL_RUPEES, MAX_RUPEE_RISK_PER_TRADE
from .data import instrument, live_prices
from .db import db, now_iso
from .portfolio_risk import recommendation_cluster
from .trading_calendar import is_regular_trading_day
from .execution_integrity import (
    cached_position_reconciliation, pretrade_permission, order_execution_metrics,
)


def _rec(rec_id:str)->Dict[str,Any]:
    with db() as con:r=con.execute("SELECT * FROM recommendations WHERE recommendation_id=?",(rec_id,)).fetchone()
    if not r:raise ValueError("Recommendation not found")
    return dict(r)


def _today_order_count(timeout_seconds:float=10.0)->Optional[int]:
    day=datetime.now(IST).date().isoformat()
    try:
        with db(timeout_seconds=timeout_seconds) as con:
            return int(con.execute("SELECT COUNT(*) FROM orders WHERE substr(created_at,1,10)=? AND state NOT IN ('FAILED','CANCELLED')",(day,)).fetchone()[0])
    except Exception:
        return None


def execution_readiness(rec:Optional[Dict[str,Any]]=None, use_cached:bool=False)->Dict[str,Any]:
    settings=load_settings();ip=broker.static_ip_status_cached() if use_cached else broker.static_ip_status();bs=broker.status_cached() if use_cached else broker.status();now=datetime.now(IST);blockers=[]
    if not settings.get("manual_execution_enabled",True):blockers.append("manual_execution_disabled")
    if not bs.get("connected"):blockers.append("groww_not_connected")
    if not ip.get("configured"):blockers.append("static_ip_not_set")
    elif not ip.get("matches"):blockers.append("current_ip_does_not_match_configured_static_ip")
    if (not is_regular_trading_day(now.date())) or not (MARKET_OPEN<=now.time().replace(tzinfo=None)<=MARKET_CLOSE):blockers.append("market_closed_or_nse_holiday")
    order_count=_today_order_count(.25 if use_cached else 2.0)
    if order_count is None:blockers.append("daily_order_count_unavailable")
    elif order_count>=int(settings.get('max_open_manual_orders',8) or 8):blockers.append('daily_manual_order_limit_reached')
    position_state=cached_position_reconciliation(.25 if use_cached else 2.0)
    if position_state.get("hard_block") and position_state.get("verified"):
        blockers.append("broker_position_mismatch")
    portfolio=None
    if rec:
        if rec.get("exchange")!="NSE":blockers.append("venue_not_supported_by_groww")
        if rec.get("state")!="LIVE":blockers.append("recommendation_not_live")
        if rec.get("side")=="SHORT" and str(rec.get("book") or "").upper() in ("WEEKLY","MONTHLY","ETF"):
            blockers.append("horizon_short_research_only")
        if rec.get("side")=="SHORT" and now.time().replace(tzinfo=None)>=SHORT_HARD_EXIT:blockers.append("short_entry_cutoff_1500")
        portfolio=recommendation_cluster(str(rec.get('symbol') or ''),str(rec.get('side') or ''),str(rec.get('recommendation_id') or ''))
        if portfolio.get('hard_block'):blockers.append('portfolio_correlation_cluster_limit')
    return {"ready":not blockers,"blockers":list(dict.fromkeys(blockers)),"groww":bs,"static_ip":ip,
            "max_notional":TRADE_NOTIONAL_RUPEES,"max_rupee_risk_to_stop":MAX_RUPEE_RISK_PER_TRADE,
            "today_manual_orders":order_count,"portfolio_fit":portfolio,
            "position_reconciliation":position_state}


def _quote_execution_quality(symbol:str, side:str, fallback_px:float)->Dict[str,Any]:
    out={'status':'UNKNOWN','hard_block':False,'blockers':[],'spread_pct':None}
    try:
        q=broker.quote(symbol);out['quote']=q
        def first(*keys):
            for k in keys:
                try:
                    v=float(q.get(k) or 0)
                    if v>0:return v
                except Exception:pass
            return 0.0
        bid=first('bid_price','best_bid_price','bidPrice','bestBidPrice');ask=first('ask_price','best_ask_price','askPrice','bestAskPrice');last=first('last_price','ltp','lastPrice') or fallback_px
        if bid>0 and ask>0 and last>0:
            spread=(ask-bid)/last*100;out['spread_pct']=round(spread,4)
            if spread>0.80:out['hard_block']=True;out['blockers'].append('live_bid_ask_spread_too_wide')
            out['status']='PASS' if spread<=0.35 else ('WARN' if spread<=0.80 else 'FAIL')
        up=first('upper_circuit_limit','upperCircuitLimit');dn=first('lower_circuit_limit','lowerCircuitLimit')
        if last>0 and ((side=='LONG' and up>0 and abs(up-last)/last*100<.03) or (side=='SHORT' and dn>0 and abs(last-dn)/last*100<.03)):
            out['hard_block']=True;out['blockers'].append('price_effectively_at_circuit_limit')
        return out
    except Exception as exc:
        out['detail']=str(exc)[:180];return out


def _merge_permission(ready:Dict[str,Any], permission:Dict[str,Any])->Dict[str,Any]:
    merged=dict(ready)
    merged['blockers']=list(dict.fromkeys((merged.get('blockers') or [])+(permission.get('blockers') or [])))
    merged['ready']=not merged['blockers']
    merged['execution_permission']=permission
    return merged


def create_preview(rec_id:str)->Dict[str,Any]:
    rec=_rec(rec_id);ready=execution_readiness(rec)
    meta=instrument(rec["symbol"]);tick=float((meta or {}).get("tick_size") or .05)
    px=live_prices([rec["symbol"]]).get(rec["symbol"],float(rec["current_price"])) if rec.get("exchange")=="NSE" else float(rec["current_price"])
    plan=order_plan(rec["side"],float(px),tick,stop_price=float(rec.get('stop_price') or 0) or None)
    quality=_quote_execution_quality(rec['symbol'],rec['side'],float(px)) if rec.get('exchange')=='NSE' else {'status':'UNSUPPORTED','hard_block':True,'blockers':['venue_not_supported_by_groww']}
    if quality.get('hard_block'):
        ready=dict(ready);ready['blockers']=list(dict.fromkeys((ready.get('blockers') or [])+(quality.get('blockers') or [])));ready['ready']=False
    permission={"ready":False,"blockers":["base_execution_readiness_failed"],"policy":"V670_EXECUTION_INTEGRITY_PRETRADE"}
    if ready.get("ready") and int(plan.get("quantity") or 0)>0:
        permission=pretrade_permission(rec,plan,quality)
        ready=_merge_permission(ready,permission)
    token=uuid.uuid4().hex;now=datetime.now(IST);exp=now+timedelta(seconds=90)
    payload={"recommendation_id":rec_id,"symbol":rec["symbol"],"book":rec["book"],"plan":plan,"readiness":ready,
             "execution_quality":quality,"execution_permission":permission,
             "decision_price":float(px),"decision_ts":now.isoformat(timespec='milliseconds'),
             "warning":"CNC delivery can continue to lose value. ₹20,000 is a maximum notional; stop-risk, broker permission, net-edge and liquidity controls may reduce or block quantity."}
    with db() as con:
        con.execute("INSERT INTO order_previews(preview_token,recommendation_id,created_at,expires_at,consumed,payload_json) VALUES(?,?,?,?,0,?)",
                    (token,rec_id,now.isoformat(timespec='seconds'),exp.isoformat(timespec='seconds'),json.dumps(payload,default=str)))
    payload["preview_token"]=token;payload["expires_at"]=exp.isoformat(timespec='seconds');return payload


def execute_preview(token:str)->Dict[str,Any]:
    with db() as con:r=con.execute("SELECT * FROM order_previews WHERE preview_token=?",(token,)).fetchone()
    if not r:raise ValueError("Preview token not found")
    d=dict(r)
    if int(d["consumed"]):raise ValueError("Preview already consumed")
    if datetime.now(IST)>datetime.fromisoformat(d["expires_at"]):raise ValueError("Preview expired")
    payload=json.loads(d["payload_json"]);rec=_rec(d["recommendation_id"]);ready=execution_readiness(rec)
    plan=payload["plan"]
    quality=_quote_execution_quality(rec['symbol'],rec['side'],float(rec.get('current_price') or payload.get("decision_price") or 0))
    if quality.get('hard_block'):
        ready['blockers']=list(dict.fromkeys((ready.get('blockers') or [])+(quality.get('blockers') or [])));ready['ready']=False
    if int(plan["quantity"])<1:raise RuntimeError("Risk/notional caps are below one share at the current protected limit price")
    permission=pretrade_permission(rec,plan,quality) if ready.get("ready") else {"ready":False,"blockers":["base_execution_readiness_failed"]}
    ready=_merge_permission(ready,permission)
    if not ready["ready"]:raise RuntimeError("Order blocked: "+", ".join(ready["blockers"]))
    ref=("PSQ-"+uuid.uuid4().hex[:14]).upper();local=uuid.uuid4().hex;ts=now_iso()
    margin_check=(permission.get("margin") or {});costs=(permission.get("costs") or {});pos=(permission.get("position_reconciliation") or {})
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        fresh=con.execute("SELECT consumed FROM order_previews WHERE preview_token=?",(token,)).fetchone()
        if not fresh or int(fresh[0]):con.execute("ROLLBACK");raise ValueError("Preview already consumed")
        con.execute("UPDATE order_previews SET consumed=1 WHERE preview_token=?",(token,))
        con.execute(
            "INSERT INTO orders(local_order_id,recommendation_id,order_reference_id,symbol,side,product,quantity,limit_price,notional_cap,state,"
            "response_json,decision_price,decision_ts,submitted_at,margin_check_json,cost_estimate_json,position_reconcile_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,'SUBMITTING','{}',?,?,?,?,?,?,?,?)",
            (local,rec["recommendation_id"],ref,rec["symbol"],rec["side"],plan["product"],int(plan["quantity"]),float(plan["limit_price"]),
             TRADE_NOTIONAL_RUPEES,float(payload.get("decision_price") or rec.get("current_price") or 0),payload.get("decision_ts"),ts,
             json.dumps(margin_check,default=str,separators=(',',':')),json.dumps(costs,default=str,separators=(',',':')),
             json.dumps(pos,default=str,separators=(',',':')),ts,ts))
        con.execute("COMMIT")
    try:
        response=broker.place_cash_order(trading_symbol=rec["symbol"],side=rec["side"],quantity=int(plan["quantity"]),product=plan["product"],limit_price=float(plan["limit_price"]),order_reference_id=ref,exchange=rec["exchange"])
        oid=response.get("groww_order_id");state=response.get("order_status") or "SUBMITTED";ack=now_iso()
        with db() as con:
            con.execute("UPDATE orders SET groww_order_id=?,state=?,response_json=?,acknowledged_at=?,updated_at=? WHERE local_order_id=?",
                        (oid,state,json.dumps(response,default=str),ack,ack,local))
        return {"ok":True,"local_order_id":local,"groww_order_id":oid,"state":state,"plan":plan,
                "execution_quality":quality,"execution_permission":permission,"response":response}
    except Exception as exc:
        with db() as con:
            con.execute("UPDATE orders SET state='FAILED',response_json=?,acknowledged_at=?,updated_at=? WHERE local_order_id=?",
                        (json.dumps({"error":str(exc)[:500]}),now_iso(),now_iso(),local))
        raise


def recent_orders()->list[dict]:
    with db() as con:return [dict(r) for r in con.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 100").fetchall()]


def _fill_key(local_order_id:str, trade:Dict[str,Any], idx:int)->str:
    import hashlib
    raw=f"{local_order_id}|{trade.get('trade_id') or trade.get('exchange_trade_id') or idx}|{trade.get('quantity') or trade.get('filled_quantity')}|{trade.get('price') or trade.get('trade_price') or trade.get('average_fill_price')}|{trade.get('exchange_time') or trade.get('trade_date')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def reconcile_orders(limit:int=100)->Dict[str,Any]:
    """Reconcile local order intents with Groww status, actual fills and execution quality."""
    with db() as con:
        rows=[dict(r) for r in con.execute("SELECT * FROM orders WHERE groww_order_id IS NOT NULL AND groww_order_id<>'' ORDER BY updated_at DESC LIMIT ?",(max(1,min(500,int(limit))),)).fetchall()]
    checked=updated=fills=errors=0
    terminal={'EXECUTED','COMPLETED','CANCELLED','REJECTED','FAILED','DELIVERY_AWAITED'}
    for r in rows:
        try:
            with db() as con:
                existing_fills=int(con.execute("SELECT COUNT(*) FROM order_fills WHERE local_order_id=?",(r['local_order_id'],)).fetchone()[0])
            metrics_existing=json.loads(r.get("execution_metrics_json") or "{}") if r.get("execution_metrics_json") is not None else {}
            if str(r.get('state') or '').upper() in terminal and existing_fills>0 and metrics_existing.get("average_fill_price") is not None:continue
            oid=str(r['groww_order_id']);checked+=1
            status=broker.order_status(oid);detail={}
            try:detail=broker.order_detail(oid)
            except Exception:detail=status
            state=str(detail.get('order_status') or status.get('order_status') or r.get('state') or 'UNKNOWN').upper()
            filled=int(detail.get('filled_quantity') or status.get('filled_quantity') or 0)
            remain=detail.get('remaining_quantity')
            try:remain=int(remain) if remain is not None else max(0,int(r.get('quantity') or 0)-filled)
            except Exception:remain=None
            avg=detail.get('average_fill_price')
            try:avg=float(avg) if avg is not None else None
            except Exception:avg=None
            trades=[]
            try:trades=broker.order_trades(oid)
            except Exception:trades=[]
            ts=now_iso();recon={'status':status,'detail':detail,'trade_count':len(trades)}
            with db() as con:
                con.execute("UPDATE orders SET state=?,filled_quantity=?,remaining_quantity=?,average_fill_price=?,broker_status_at=?,reconciliation_json=?,updated_at=? WHERE local_order_id=?",
                            (state,filled,remain,avg,ts,json.dumps(recon,default=str,separators=(',',':')),ts,r['local_order_id']))
                for i,tr in enumerate(trades):
                    q=tr.get('quantity') or tr.get('filled_quantity') or tr.get('trade_quantity') or 0
                    px=tr.get('price') or tr.get('trade_price') or tr.get('average_fill_price')
                    try:q=int(q or 0)
                    except Exception:q=0
                    try:px=float(px) if px is not None else None
                    except Exception:px=None
                    key=_fill_key(r['local_order_id'],tr,i)
                    con.execute("INSERT OR IGNORE INTO order_fills(fill_key,local_order_id,groww_order_id,quantity,price,trade_id,exchange_time,payload_json,captured_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                (key,r['local_order_id'],oid,q,px,str(tr.get('trade_id') or tr.get('exchange_trade_id') or '') or None,
                                 str(tr.get('exchange_time') or tr.get('trade_date') or '') or None,json.dumps(tr,default=str,separators=(',',':')),ts))
                    if con.execute('SELECT changes()').fetchone()[0]:fills+=1
                fs=[dict(x) for x in con.execute("SELECT * FROM order_fills WHERE local_order_id=? ORDER BY captured_at",(r['local_order_id'],)).fetchall()]
                current=dict(r);current.update({"state":state,"filled_quantity":filled,"remaining_quantity":remain,"average_fill_price":avg})
                metrics=order_execution_metrics(current,fs)
                con.execute("UPDATE orders SET execution_metrics_json=?,updated_at=? WHERE local_order_id=?",
                            (json.dumps(metrics,default=str,separators=(',',':')),ts,r['local_order_id']))
            updated+=1
        except Exception as exc:
            errors+=1
            try:
                from .db import health
                health('order_reconcile','WARN',f"{r.get('groww_order_id')}: {exc}"[:240])
            except Exception:pass
    return {'checked':checked,'updated':updated,'new_fills':fills,'errors':errors,'at':now_iso(),
            'policy':'Broker reconciliation is read-only; decision-to-fill metrics are persisted and no order is submitted.'}


def recent_fills(limit:int=200)->list[dict]:
    with db() as con:return [dict(r) for r in con.execute("SELECT * FROM order_fills ORDER BY captured_at DESC LIMIT ?",(max(1,min(1000,int(limit))),)).fetchall()]
