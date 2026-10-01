from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple, Optional

from .constants import IST
from .db import db, now_iso
from .handbook import strategy_catalog, status as handbook_status

FAMILIES = [
    "TREND_BREAKOUT", "TREND_PULLBACK", "MOMENTUM", "MEAN_REVERSION",
    "MACD_TREND", "RSI_REVERSAL", "DONCHIAN_BREAKOUT", "BOLLINGER_REVERSION",
    "VOLUME_BREAKOUT", "GAP_CONTINUATION", "GAP_FADE", "RELATIVE_STRENGTH",
    "VOLATILITY_EXPANSION", "VOLATILITY_COMPRESSION", "CANDLE_ENGULFING", "PINBAR_REVERSAL",
    # Handbook-derived concepts that can be represented safely by the local feature stack.
    "QUALITY_MOMENTUM", "VALUE_QUALITY", "LOW_VOL_QUALITY", "EARNINGS_EVENT",
    "VWAP_MEAN_REVERSION", "OPENING_RANGE_BREAKOUT", "NEWS_MOMENTUM",
]
HORIZONS = ["INTRADAY", "WEEKLY"]
SIDES = ["LONG", "SHORT"]
# The library intentionally contains hundreds of parameterized variants. Handbook-derived
# executable concepts expand the local deterministic library beyond the original 576 configs.
PARAM_LEVELS = [0, 1, 2, 3, 4, 5, 6, 7]
MONTHLY_LEVELS = [2, 5]


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    name: str
    family: str
    horizon: str
    side: str
    params: Dict[str, Any]
    source: str = "BUILTIN_GLOBAL_FAMILY"
    version: int = 1


def _params(family: str, level: int, horizon: str) -> Dict[str, Any]:
    aggress = level / 7.0
    return {
        "level": level,
        "lookback": int(round((10 if horizon == "INTRADAY" else 20) + aggress * (45 if horizon == "INTRADAY" else 100))),
        "min_adx": round(14 + aggress * 18, 1),
        "min_volume_ratio": round(1.05 + aggress * 1.45, 2),
        "rsi_low": round(38 - aggress * 13, 1),
        "rsi_high": round(62 + aggress * 13, 1),
        "z_threshold": round(0.7 + aggress * 1.5, 2),
        "gap_threshold": round(0.3 + aggress * 1.7, 2),
        "atr_floor": round(0.4 + aggress * 1.2, 2),
        "family": family,
    }


def build_library() -> List[StrategySpec]:
    out: List[StrategySpec] = []
    for family in FAMILIES:
        for horizon in HORIZONS:
            for side in SIDES:
                for level in PARAM_LEVELS:
                    params = _params(family, level, horizon)
                    sid = f"{family}-{horizon}-{side}-L{level}"
                    out.append(StrategySpec(
                        strategy_id=sid,
                        name=f"{family.replace('_',' ').title()} {horizon.title()} {side.title()} L{level}",
                        family=family,
                        horizon=horizon,
                        side=side,
                        params=params,
                    ))
        for side in SIDES:
            for level in MONTHLY_LEVELS:
                params = _params(family, level, "MONTHLY")
                sid = f"{family}-MONTHLY-{side}-L{level}"
                out.append(StrategySpec(
                    strategy_id=sid,
                    name=f"{family.replace('_',' ').title()} Monthly {side.title()} L{level}",
                    family=family,
                    horizon="MONTHLY",
                    side=side,
                    params=params,
                ))
    return out


def seed_library() -> int:
    specs = build_library()
    ts = now_iso()
    handbook = strategy_catalog()
    with db() as con:
        for s in specs:
            # Existing deterministic templates remain probationary until the chronological
            # Champion contract has enough evidence to replace seeds.
            status = "SEED_CHAMPION" if s.params["level"] in (2, 4) else "CHALLENGER"
            con.execute(
                "INSERT INTO strategies(strategy_id,name,family,horizon,side,params_json,status,source,version,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(strategy_id) DO NOTHING",
                (s.strategy_id,s.name,s.family,s.horizon,s.side,json.dumps(s.params,separators=(",",":")),status,s.source,s.version,ts,ts),
            )
        # Seed the complete 100-strategy handbook into the research registry. It is not
        # executable code: supported concepts map into audited local templates; unsupported
        # institutional/derivative concepts remain references until infrastructure exists.
        for h in handbook:
            fp=hashlib.sha256(("MASTER_HANDBOOK|"+str(h.get("rank"))+"|"+str(h.get("name"))).encode()).hexdigest()
            meta={"rank":h.get("rank"),"evidence":h.get("evidence"),"scale":h.get("scale"),"horizon":h.get("horizon"),"family":h.get("family"),"failure_modes":h.get("failure_modes"),"implementation_status":h.get("implementation_status"),"automatic_code_execution":False}
            con.execute(
                "INSERT OR IGNORE INTO strategy_discovery(fingerprint,discovered_at,source_name,title,source_url,published_at,abstract,mapped_family,status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (fp,ts,"MASTER_HANDBOOK_2026_09_24",h.get("name") or "",None,"2026-09-24",h.get("core_rule") or "",h.get("mapped_local_family"),"MAPPED_TEMPLATE_REVIEW" if h.get("mapped_local_family") else "REFERENCE_ONLY",json.dumps(meta,separators=(",",":"),default=str)),
            )
    return len(specs)


def active_strategies(horizon: str, side: str, limit: int = 24) -> List[Dict[str, Any]]:
    # Keep the active pool family-diverse. A small global LIMIT can otherwise let alphabetic
    # parameter variants crowd out entire strategy families before the ensemble even votes.
    effective_limit=max(int(limit), len(FAMILIES)*2)
    with db() as con:
        rs = con.execute(
            "SELECT s.*, COALESCE(MAX(st.score),-999) validation_score FROM strategies s "
            "LEFT JOIN strategy_stats st ON st.strategy_id=s.strategy_id "
            "WHERE s.horizon=? AND s.side=? AND s.status IN ('CHAMPION','SEED_CHAMPION') "
            "GROUP BY s.strategy_id ORDER BY CASE s.status WHEN 'CHAMPION' THEN 0 ELSE 1 END, validation_score DESC, s.strategy_id LIMIT ?",
            (horizon, side, max(200,effective_limit*3)),
        ).fetchall()
    parsed=[]
    for r in rs:
        d=dict(r)
        try:d["params"]=json.loads(d.pop("params_json") or "{}")
        except Exception:d["params"]={}
        parsed.append(d)
    # At most two variants per family, preferring validated Champions over seeds.
    per_family={};out=[]
    for d in parsed:
        fam=str(d.get('family') or '')
        if per_family.get(fam,0)>=2:continue
        out.append(d);per_family[fam]=per_family.get(fam,0)+1
        if len(out)>=effective_limit:break
    return out


def _f(x: Any, d: float = 0.0) -> float:
    try:
        v=float(x); return v if math.isfinite(v) else d
    except Exception:return d


def score_strategy(spec: Dict[str, Any], f: Dict[str, Any], regime: str, fundamentals: Optional[Dict[str, Any]] = None) -> Tuple[float, List[str]]:
    family=str(spec.get("family") or "")
    side=str(spec.get("side") or "LONG")
    p=spec.get("params") or {}
    sign=1 if side=="LONG" else -1
    trend=_f(f.get("trend")); ret1=_f(f.get("ret1")); ret5=_f(f.get("ret5")); ret20=_f(f.get("ret20")); rs=_f(f.get("relative_strength20"))
    rsi=_f(f.get("rsi14"),50); z=_f(f.get("z20")); vr=_f(f.get("volume_ratio"),1); adxv=_f(f.get("adx14")); gap=_f(f.get("gap_pct")); atrp=_f(f.get("atr_pct"))
    range_pos=_f(f.get("range20_pos"),0.5); macd=_f(f.get("macd")); macds=_f(f.get("macd_signal"))
    bull=int(_f(f.get("bull_engulf"))); bear=int(_f(f.get("bear_engulf"))); upper=_f(f.get("upper_wick_frac")); lower=_f(f.get("lower_wick_frac"))
    score=0.0; reasons=[]
    min_adx=_f(p.get("min_adx"),20); min_vr=_f(p.get("min_volume_ratio"),1.2); zt=_f(p.get("z_threshold"),1.2); gt=_f(p.get("gap_threshold"),0.8); af=_f(p.get("atr_floor"),0.5)

    def add(cond: bool, pts: float, reason: str):
        nonlocal score
        if cond:
            score += pts; reasons.append(reason)

    if family=="TREND_BREAKOUT":
        add(sign*trend>0,28,"trend aligned"); add(adxv>=min_adx,18,"ADX trend strength"); add(vr>=min_vr,20,"volume confirms"); add((range_pos>=.86 if side=="LONG" else range_pos<=.14),22,"near directional range extreme")
    elif family=="TREND_PULLBACK":
        add(sign*trend>0,32,"primary trend aligned"); add(adxv>=min_adx,14,"trend established"); add((42<=rsi<=55 if side=="LONG" else 45<=rsi<=58),22,"controlled pullback"); add(sign*ret20>0,18,"20-period momentum intact")
    elif family=="MOMENTUM":
        add(sign*ret5>0,24,"short momentum"); add(sign*ret20>0,28,"medium momentum"); add(sign*rs>0,22,"relative strength"); add(vr>=min_vr,16,"participation")
    elif family=="MEAN_REVERSION":
        add((z<=-zt if side=="LONG" else z>=zt),34,"statistical stretch"); add((rsi<=_f(p.get('rsi_low'),30) if side=="LONG" else rsi>=_f(p.get('rsi_high'),70)),28,"RSI extreme"); add(adxv<max(28,min_adx+5),14,"not strong opposing trend")
    elif family=="MACD_TREND":
        add(sign*(macd-macds)>0,32,"MACD aligned"); add(sign*trend>=0,24,"trend support"); add(sign*ret5>0,20,"momentum confirms")
    elif family=="RSI_REVERSAL":
        add((rsi<=_f(p.get('rsi_low'),30) if side=="LONG" else rsi>=_f(p.get('rsi_high'),70)),38,"RSI reversal zone"); add((lower>.45 if side=="LONG" else upper>.45),22,"rejection wick"); add(vr>=1.0,12,"volume present")
    elif family=="DONCHIAN_BREAKOUT":
        add((range_pos>=.95 if side=="LONG" else range_pos<=.05),38,"Donchian edge"); add(vr>=min_vr,22,"breakout volume"); add(adxv>=min_adx,18,"trend strength")
    elif family=="BOLLINGER_REVERSION":
        add((z<=-zt if side=="LONG" else z>=zt),36,"band extension"); add(sign*ret1>0,18,"reversal candle"); add(adxv<30,14,"range-friendly regime")
    elif family=="VOLUME_BREAKOUT":
        add(vr>=min_vr,34,"relative-volume expansion"); add(sign*ret1>0,18,"price confirms volume"); add(sign*ret5>0,20,"momentum follows")
    elif family=="GAP_CONTINUATION":
        add((gap>=gt if side=="LONG" else gap<=-gt),34,"directional gap"); add(sign*ret1>0,20,"gap holds"); add(vr>=min_vr,20,"volume supports gap")
    elif family=="GAP_FADE":
        add((gap<=-gt if side=="LONG" else gap>=gt),30,"opposing gap for fade"); add(sign*ret1>0,28,"fade confirmation"); add((rsi<45 if side=="LONG" else rsi>55),16,"mean-reversion context")
    elif family=="RELATIVE_STRENGTH":
        add(sign*rs>0,36,"relative strength vs benchmark"); add(sign*ret20>0,24,"absolute trend confirms"); add(sign*trend>0,18,"moving averages aligned")
    elif family=="VOLATILITY_EXPANSION":
        add(atrp>=af,24,"volatility active"); add(vr>=min_vr,24,"volume expansion"); add(sign*ret5>0,28,"directional expansion")
    elif family=="VOLATILITY_COMPRESSION":
        add(atrp>0 and atrp<max(1.5,af+0.5),24,"volatility compression"); add((range_pos>=.8 if side=="LONG" else range_pos<=.2),24,"compression near edge"); add(vr>=1.0,14,"participation returns")
    elif family=="CANDLE_ENGULFING":
        add(bool(bull if side=="LONG" else bear),40,"engulfing reversal"); add(sign*ret20>=0,16,"higher-timeframe support"); add(vr>=1.0,14,"volume support")
    elif family=="PINBAR_REVERSAL":
        add((lower>=.55 if side=="LONG" else upper>=.55),36,"pinbar rejection"); add((rsi<45 if side=="LONG" else rsi>55),18,"oscillator context"); add(vr>=1.0,12,"participation")
    elif family=="QUALITY_MOMENTUM":
        add(sign*trend>0,24,"trend supports quality sleeve"); add(sign*ret20>0,26,"medium momentum"); add(sign*rs>0,22,"relative leadership"); add(vr>=1.0,12,"participation")
    elif family=="VALUE_QUALITY":
        add(sign*trend>=0,18,"price not fighting thesis"); add(sign*ret20>=0,18,"medium trend support"); add(sign*rs>=0,14,"relative condition supportive"); add(adxv>=12,10,"price structure measurable")
    elif family=="LOW_VOL_QUALITY":
        add(0<atrp<=2.5,28,"controlled realized volatility"); add(sign*trend>=0,20,"directional structure supportive"); add(sign*ret20>=0,18,"medium trend not deteriorating"); add(vr>=.75,10,"adequate participation")
    elif family=="EARNINGS_EVENT":
        add(sign*gap>0 and abs(gap)>=max(.4,gt*.6),26,"event-style directional repricing"); add(sign*ret5>0,20,"post-event continuation"); add(vr>=min_vr,24,"event participation"); add(sign*trend>=0,12,"structure supports continuation")
    elif family=="VWAP_MEAN_REVERSION":
        vwap=_f(f.get("vwap"));px=_f(f.get("close"))
        stretched=(vwap>0 and ((px<vwap and side=="LONG") or (px>vwap and side=="SHORT")))
        add(stretched,30,"extension away from VWAP"); add((z<=-zt if side=="LONG" else z>=zt),26,"statistical extension"); add(adxv<30,14,"mean-reversion-friendly trend strength"); add(sign*ret1>0,16,"reversion confirmation")
    elif family=="OPENING_RANGE_BREAKOUT":
        orp=_f(f.get("opening_range_position"),.5)
        add((orp>1 if side=="LONG" else orp<0),34,"opening range accepted outside"); add(vr>=min_vr,24,"opening participation"); add(sign*trend>=0,16,"higher structure supportive"); add(sign*ret1>0,12,"breakout close confirms")
    elif family=="NEWS_MOMENTUM":
        # Material-news verification is applied later by Trade Intelligence. This template
        # only measures the price/volume continuation component so news cannot be fabricated.
        add(sign*ret1>0,20,"immediate reaction persists"); add(sign*ret5>0,22,"continuation momentum"); add(vr>=min_vr,28,"abnormal participation"); add(abs(gap)>=max(.3,gt*.5),14,"repricing magnitude")

    # Regime is a hard influence, not an afterthought.
    if regime in ("TREND_UP","HIGH_VOL_TREND_UP"):
        score += 14 if side=="LONG" else -18
    elif regime in ("TREND_DOWN","HIGH_VOL_TREND_DOWN"):
        score += 14 if side=="SHORT" else -18
    elif regime in ("RANGE","LOW_VOL_RANGE") and family in ("MEAN_REVERSION","BOLLINGER_REVERSION","RSI_REVERSAL","GAP_FADE","VWAP_MEAN_REVERSION"):
        score += 12
    elif regime.startswith("SHOCK"):
        score -= 20

    # Fundamentals support every swing horizon and are stronger for Monthly.
    # They never override price/risk, but the official horizon admission gate requires
    # fundamental data to be present so a recommendation is not based on candles alone.
    if spec.get("horizon") in ("WEEKLY", "MONTHLY") and fundamentals:
        horizon = str(spec.get("horizon"))
        mult = 1.0 if horizon == "WEEKLY" else 1.35
        pe=_f(fundamentals.get("trailingPE"),0); fpe=_f(fundamentals.get("forwardPE"),0)
        roe=_f(fundamentals.get("returnOnEquity"),0); roa=_f(fundamentals.get("returnOnAssets"),0)
        growth=_f(fundamentals.get("revenueGrowth"),0); egrowth=_f(fundamentals.get("earningsGrowth"),0)
        debt=_f(fundamentals.get("debtToEquity"),999); margin=_f(fundamentals.get("profitMargins"),0)
        opmargin=_f(fundamentals.get("operatingMargins"),0); fcf=_f(fundamentals.get("freeCashflow"),0); ocf=_f(fundamentals.get("operatingCashflow"),0)
        current=_f(fundamentals.get("currentRatio"),0); inst=_f(fundamentals.get("heldPercentInstitutions"),0)
        if side=="LONG":
            add(roe>0.12,8*mult,"healthy ROE"); add(roa>0.05,4*mult,"positive ROA")
            add(growth>0.05,7*mult,"revenue growth"); add(egrowth>0.05,7*mult,"earnings growth")
            add(margin>0.08,5*mult,"profitability support"); add(opmargin>0.10,4*mult,"operating margin support")
            add(fcf>0 and ocf>0,6*mult,"cash-flow quality"); add(debt<150,4*mult,"leverage acceptable")
            add((0<pe<70) or (0<fpe<55),4*mult,"valuation not extreme"); add(current>=1.0,3*mult,"liquidity acceptable")
            add(inst>=0.05,2*mult,"institutional participation")
        else:
            add(roe<0.06,6*mult,"weak ROE"); add(roa<0.02,3*mult,"weak ROA")
            add(growth<0,7*mult,"revenue contraction"); add(egrowth<0,7*mult,"earnings contraction")
            add(margin<0.04,5*mult,"weak profitability"); add(fcf<0 or ocf<0,6*mult,"cash-flow stress")
            add(debt>180,5*mult,"leverage stress"); add(pe>80 or pe<=0,4*mult,"valuation/earnings stress")

    return max(0.0,min(100.0,score)), reasons


def library_status() -> Dict[str, Any]:
    with db() as con:
        total=con.execute("SELECT COUNT(*) FROM strategies").fetchone()[0]
        rows=con.execute("SELECT status,COUNT(*) n FROM strategies GROUP BY status").fetchall()
        by_h=con.execute("SELECT horizon,status,COUNT(*) n FROM strategies GROUP BY horizon,status ORDER BY horizon,status").fetchall()
        fam=con.execute("SELECT family,COUNT(*) n FROM strategies GROUP BY family ORDER BY family").fetchall()
    hb=handbook_status()
    return {
        "strategy_configurations":int(total),
        "handbook":hb,
        "research_idea_count":int(total)+int(hb.get("strategy_families") or 0),
        "by_status":{r[0]:int(r[1]) for r in rows},
        "by_horizon":[{"horizon":r[0],"status":r[1],"n":int(r[2])} for r in by_h],
        "families":[{"family":r[0],"n":int(r[1])} for r in fam],
        "principle":"Internet/PDF-discovered ideas enter research only; production promotion requires chronological out-of-sample validation and live decay monitoring.",
    }


def challenger_strategies(horizon: str, side: str, limit: int = 18) -> List[Dict[str, Any]]:
    """Return a family-diverse shadow pool that can never place an order directly."""
    with db() as con:
        rs=con.execute(
            "SELECT s.*,COALESCE(st.score,-999) validation_score FROM strategies s "
            "LEFT JOIN strategy_stats st ON st.strategy_id=s.strategy_id AND st.regime='ALL' "
            "WHERE s.horizon=? AND s.side=? AND s.status='CHALLENGER' "
            "ORDER BY validation_score DESC,s.strategy_id LIMIT 300",
            (horizon,side),
        ).fetchall()
    out=[];families=set()
    for r in rs:
        d=dict(r)
        try:d['params']=json.loads(d.pop('params_json') or '{}')
        except Exception:d['params']={}
        fam=str(d.get('family') or '')
        if fam in families:continue
        families.add(fam);out.append(d)
        if len(out)>=limit:break
    return out
