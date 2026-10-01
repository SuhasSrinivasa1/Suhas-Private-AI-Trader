from __future__ import annotations

"""Broker-facing execution integrity for PS Scanner v6.7.0.

Recommendation research remains independent of broker permission.  These controls run only
when preparing/executing a manual Groww order or in the low-frequency execution worker.
"""

import json
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .broker import broker
from .config import load_settings
from .constants import IST
from .db import db, health, now_iso, get_state, set_state

POSITION_POLICY="V670_BROKER_POSITION_SOURCE_OF_TRUTH"
MARGIN_POLICY="V670_DYNAMIC_MARGIN_AND_MIS_PERMISSION"
COST_POLICY="V670_NET_EDGE_AFTER_LIVE_EXECUTION_COST_RESERVE"


def _float(v: Any, default: float = 0.0) -> float:
    try:return float(v)
    except Exception:return float(default)


def _int(v: Any, default: int = 0) -> int:
    try:return int(v)
    except Exception:return int(default)


def _position_rows(payload: Any) -> List[Dict[str,Any]]:
    if isinstance(payload,list):return [dict(x) for x in payload if isinstance(x,dict)]
    if isinstance(payload,dict):
        rows=payload.get("positions") or payload.get("position_list") or []
        if isinstance(rows,list):return [dict(x) for x in rows if isinstance(x,dict)]
    return []


def _session_quantity(row: Dict[str,Any]) -> int:
    # Groww's quantity is net position and net_carry_forward_quantity is the carried component.
    # The difference isolates today's activity for CNC while remaining the full MIS quantity.
    qty=_int(row.get("quantity"))
    carry=_int(row.get("net_carry_forward_quantity"))
    return qty-carry


def _local_expected_session_positions(day: Optional[str] = None) -> Dict[Tuple[str,str],int]:
    day=day or datetime.now(IST).date().isoformat()
    with db() as con:
        rows=con.execute(
            "SELECT UPPER(symbol) symbol,UPPER(product) product,side,SUM(COALESCE(filled_quantity,0)) qty "
            "FROM orders WHERE substr(created_at,1,10)=? AND COALESCE(filled_quantity,0)>0 "
            "GROUP BY UPPER(symbol),UPPER(product),side",(day,)
        ).fetchall()
    out:Dict[Tuple[str,str],int]={}
    for r in rows:
        key=(str(r["symbol"]).upper(),str(r["product"]).upper())
        signed=_int(r["qty"])*(1 if str(r["side"]).upper()=="LONG" else -1)
        out[key]=out.get(key,0)+signed
    return out


def reconcile_positions() -> Dict[str,Any]:
    """Compare PS Scanner's current-day filled exposure with Groww's net session positions.

    Any non-zero session position that cannot be reconciled to PS Scanner's fill ledger is a
    hard execution halt.  This is intentionally strict: the broker is the source of truth.
    """
    at=now_iso()
    try:
        payload=broker.positions()
        rows=_position_rows(payload)
        broker_map:Dict[Tuple[str,str],int]={}
        realized={}
        raw=[]
        for r in rows:
            sym=str(r.get("trading_symbol") or r.get("symbol") or "").upper()
            product=str(r.get("product") or "").upper() or "UNKNOWN"
            if not sym:continue
            sq=_session_quantity(r)
            broker_map[(sym,product)]=sq
            realized[f"{sym}|{product}"]=_float(r.get("realised_pnl"),0.0)
            raw.append({"symbol":sym,"product":product,"session_quantity":sq,
                        "broker_quantity":_int(r.get("quantity")),
                        "carry_forward_quantity":_int(r.get("net_carry_forward_quantity")),
                        "realised_pnl":_float(r.get("realised_pnl"),0.0)})
        expected=_local_expected_session_positions()
        keys=set(expected)|{k for k,v in broker_map.items() if v!=0}
        mismatches=[];external=[]
        for key in sorted(keys):
            exp=int(expected.get(key,0));actual=int(broker_map.get(key,0))
            if exp!=actual:
                item={"symbol":key[0],"product":key[1],"expected_session_quantity":exp,"broker_session_quantity":actual,"delta":actual-exp}
                mismatches.append(item)
                if exp==0 and actual!=0:external.append(item)
        out={
            "at":at,"verified":True,"hard_block":bool(mismatches),"mismatches":mismatches,
            "external_session_positions":external,
            "expected":{"%s|%s"%k:v for k,v in expected.items()},
            "broker":{"%s|%s"%k:v for k,v in broker_map.items()},
            "broker_realised_pnl":realized,"positions":raw,
            "policy":POSITION_POLICY,
        }
        set_state("position_reconciliation",out)
        if mismatches:
            health("position_reconcile","WARN","Broker/local position mismatch blocks new execution",
                   {"mismatch_count":len(mismatches),"sample":mismatches[:8],"policy":POSITION_POLICY})
        return out
    except Exception as exc:
        out={"at":at,"verified":False,"hard_block":True,"mismatches":[],"error":str(exc)[:240],"policy":POSITION_POLICY}
        set_state("position_reconciliation",out)
        health("position_reconcile","WARN",str(exc)[:220])
        return out


def cached_position_reconciliation(timeout_seconds:float=10.0) -> Dict[str,Any]:
    try:
        with db(timeout_seconds=timeout_seconds) as con:
            row=con.execute("SELECT value_json FROM system_state WHERE key='position_reconciliation'").fetchone()
        if row:
            try:
                data=json.loads(row[0] or "{}")
                if isinstance(data,dict) and data:return data
            except Exception:
                pass
    except Exception:
        return {
            "verified":False,"hard_block":False,"status":"CACHE_UNAVAILABLE_BOUNDED",
            "policy":POSITION_POLICY,"nonblocking":True,
        }
    return {
        "verified":False,"hard_block":False,"status":"NOT_YET_CHECKED","policy":POSITION_POLICY
    }


def _margin_requirement(payload: Dict[str,Any], product: str) -> float:
    product=str(product).upper()
    if product=="MIS" and payload.get("cash_mis_margin_required") is not None:
        return _float(payload.get("cash_mis_margin_required"))
    if product=="CNC" and payload.get("cash_cnc_margin_required") is not None:
        return _float(payload.get("cash_cnc_margin_required"))
    return _float(payload.get("total_requirement"))


def _available_for_product(payload: Dict[str,Any], product: str) -> Optional[float]:
    eq=payload.get("equity_margin_details") or {}
    key="mis_balance_available" if str(product).upper()=="MIS" else "cnc_balance_available"
    if eq.get(key) is not None:return _float(eq.get(key))
    if payload.get("clear_cash") is not None:return _float(payload.get("clear_cash"))+_float(payload.get("collateral_available"))
    return None


def _cost_summary(rec: Dict[str,Any], plan: Dict[str,Any], quality: Dict[str,Any],
                  margin: Dict[str,Any]) -> Dict[str,Any]:
    settings=load_settings()
    notional=_float(plan.get("estimated_notional"))
    target_pct=abs(_float(rec.get("target_pct")))
    gross_target=notional*target_pct/100.0
    entry_fees=max(0.0,_float(margin.get("brokerage_and_charges")))
    # Entry-margin response is authoritative for the proposed leg.  A symmetric second-leg
    # reserve is intentionally conservative; actual fill attribution is measured later.
    estimated_roundtrip_fees=entry_fees*2.0
    spread_pct=max(0.0,_float(quality.get("spread_pct")))
    spread_reserve=notional*spread_pct/100.0
    slip_bps=max(0.0,_float(settings.get("execution_slippage_reserve_bps"),10.0))
    slippage_reserve=notional*(slip_bps/10000.0)*2.0
    net=gross_target-estimated_roundtrip_fees-spread_reserve-slippage_reserve
    hurdle=_float(settings.get("execution_min_net_edge_rupees"),0.0)
    return {
        "gross_target_rupees":round(gross_target,2),
        "estimated_roundtrip_fees_rupees":round(estimated_roundtrip_fees,2),
        "spread_reserve_rupees":round(spread_reserve,2),
        "slippage_reserve_rupees":round(slippage_reserve,2),
        "slippage_reserve_bps_per_leg":round(slip_bps,2),
        "expected_net_edge_rupees":round(net,2),
        "minimum_net_edge_rupees":round(hurdle,2),
        "positive_after_costs":bool(net>hurdle),
        "policy":COST_POLICY,
        "note":"Broker margin quote supplies proposed-leg charges; exit fees are conservatively reserved symmetrically until actual fills exist.",
    }


def pretrade_permission(rec: Dict[str,Any], plan: Dict[str,Any], quality: Dict[str,Any]) -> Dict[str,Any]:
    """Live execution-only permission gate: positions, margin/MIS eligibility and net edge."""
    blockers=[]
    pos=reconcile_positions()
    if not pos.get("verified"):blockers.append("broker_position_reconciliation_unavailable")
    elif pos.get("hard_block"):blockers.append("broker_position_mismatch")

    product=str(plan.get("product") or "").upper()
    side=str(rec.get("side") or "").upper()
    tx="BUY" if side=="LONG" else "SELL"
    margin={};available={};margin_error=None
    try:
        margin=broker.required_margin(
            trading_symbol=str(rec.get("symbol") or ""),transaction_type=tx,
            quantity=max(1,_int(plan.get("quantity"),1)),price=_float(plan.get("limit_price")),
            product=product,exchange=str(rec.get("exchange") or "NSE"),
        )
        available=broker.available_margin()
    except Exception as exc:
        margin_error=str(exc)[:220]
        blockers.append("broker_margin_permission_unavailable")

    required=_margin_requirement(margin,product) if margin else None
    avail=_available_for_product(available,product) if available else None
    if side=="SHORT":
        # A successful Groww MIS SELL margin quote is the dynamic broker-side eligibility
        # check.  Missing MIS-specific margin evidence fails closed.
        if not margin or (margin.get("cash_mis_margin_required") is None and margin.get("total_requirement") is None):
            blockers.append("short_mis_eligibility_unverified")
    if required is not None and avail is not None and required>avail+1e-9:
        blockers.append("insufficient_available_margin")

    costs=_cost_summary(rec,plan,quality,margin or {})
    if not costs.get("positive_after_costs"):
        blockers.append("expected_net_edge_not_positive_after_execution_costs")

    return {
        "ready":not blockers,"blockers":list(dict.fromkeys(blockers)),
        "position_reconciliation":pos,
        "margin":{
            "status":"PASS" if margin and not margin_error else "FAIL","product":product,
            "transaction_type":tx,"required_rupees":round(required,2) if required is not None else None,
            "available_rupees":round(avail,2) if avail is not None else None,
            "shortability":"BROKER_MIS_MARGIN_VALIDATED" if side=="SHORT" and margin and not margin_error else ("NOT_APPLICABLE" if side!="SHORT" else "UNVERIFIED"),
            "raw_requirement":margin,"error":margin_error,"policy":MARGIN_POLICY,
        },
        "costs":costs,
        "policy":"V670_EXECUTION_INTEGRITY_PRETRADE",
    }


def _parse_dt(raw: Any) -> Optional[datetime]:
    if not raw:return None
    try:
        s=str(raw).replace("Z","+00:00")
        dt=datetime.fromisoformat(s)
        if dt.tzinfo is None:dt=dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except Exception:
        return None


def order_execution_metrics(order: Dict[str,Any], fills: List[Dict[str,Any]]) -> Dict[str,Any]:
    side=str(order.get("side") or "").upper();sign=1.0 if side=="LONG" else -1.0
    decision=_float(order.get("decision_price"))
    limit=_float(order.get("limit_price"))
    total_qty=sum(max(0,_int(x.get("quantity"))) for x in fills)
    avg_fill=None
    if total_qty>0:
        value=sum(max(0,_int(x.get("quantity")))*_float(x.get("price")) for x in fills)
        avg_fill=value/total_qty if value>0 else None
    if avg_fill is None and order.get("average_fill_price") is not None:avg_fill=_float(order.get("average_fill_price"))
    decision_slip=None;limit_slip=None
    if avg_fill and decision>0:decision_slip=(avg_fill/decision-1.0)*10000.0*sign
    if avg_fill and limit>0:limit_slip=(avg_fill/limit-1.0)*10000.0*sign
    dts=_parse_dt(order.get("decision_ts"));sub=_parse_dt(order.get("submitted_at") or order.get("created_at"));ack=_parse_dt(order.get("acknowledged_at"))
    fill_times=[_parse_dt(x.get("exchange_time")) for x in fills];fill_times=[x for x in fill_times if x]
    first_fill=min(fill_times) if fill_times else None
    def ms(a,b):
        return round((b-a).total_seconds()*1000.0,1) if a and b else None
    return {
        "filled_quantity":total_qty or _int(order.get("filled_quantity")),
        "average_fill_price":round(avg_fill,4) if avg_fill else None,
        "decision_slippage_bps":round(decision_slip,3) if decision_slip is not None else None,
        "limit_slippage_bps":round(limit_slip,3) if limit_slip is not None else None,
        "decision_to_submit_ms":ms(dts,sub),
        "submit_to_ack_ms":ms(sub,ack),
        "decision_to_first_fill_ms":ms(dts,first_fill),
        "positive_slippage_bps_means_execution_cost":True,
        "policy":"V670_DECISION_TO_FILL_ATTRIBUTION",
    }


def execution_analytics(limit: int = 500) -> Dict[str,Any]:
    n=max(1,min(5000,int(limit)))
    with db() as con:
        orders=[dict(r) for r in con.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?",(n,)).fetchall()]
        fill_rows=[dict(r) for r in con.execute(
            "SELECT f.* FROM order_fills f JOIN orders o ON o.local_order_id=f.local_order_id "
            "ORDER BY f.captured_at DESC LIMIT ?",(n*5,)
        ).fetchall()]
    by_order:Dict[str,List[Dict[str,Any]]]={}
    for f in fill_rows:by_order.setdefault(str(f.get("local_order_id")),[]).append(f)
    rows=[];slips=[];latencies=[]
    for o in orders:
        metrics=order_execution_metrics(o,by_order.get(str(o.get("local_order_id")),[]))
        if metrics.get("decision_slippage_bps") is not None:slips.append(float(metrics["decision_slippage_bps"]))
        if metrics.get("decision_to_first_fill_ms") is not None:latencies.append(float(metrics["decision_to_first_fill_ms"]))
        rows.append({
            "local_order_id":o.get("local_order_id"),"recommendation_id":o.get("recommendation_id"),
            "symbol":o.get("symbol"),"side":o.get("side"),"product":o.get("product"),"state":o.get("state"),
            "created_at":o.get("created_at"),"metrics":metrics,
            "estimated_costs":json.loads(o.get("cost_estimate_json") or "{}") if o.get("cost_estimate_json") is not None else {},
        })
    pos=cached_position_reconciliation()
    return {
        "generated_at":now_iso(),"orders_scanned":len(orders),"orders":rows[:200],
        "summary":{
            "filled_orders_with_slippage":len(slips),
            "average_decision_slippage_bps":round(sum(slips)/len(slips),3) if slips else None,
            "average_decision_to_first_fill_ms":round(sum(latencies)/len(latencies),1) if latencies else None,
            "broker_realised_pnl_latest":pos.get("broker_realised_pnl") or {},
        },
        "position_reconciliation":pos,
        "principle":"Signal quality and execution quality are reported separately; estimated costs are never substituted for actual fills.",
    }
