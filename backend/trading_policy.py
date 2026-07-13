from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from math import floor
from typing import Any, Literal

Direction = Literal['long', 'short']
SUPPORTED_MARKETS = {'NSE', 'BSE', 'NYSE', 'NASDAQ'}

@dataclass(frozen=True)
class TradingPolicy:
    enabled: bool = True
    allow_live_execution: bool = False
    max_risk_per_trade_pct: float = 1.0
    min_reward_risk_ratio: float = 2.0
    max_chase_pct: float = 1.5
    max_price_age_seconds: int = 120
    min_confirmation_sources: int = 2
    max_position_value_pct: float = 20.0
    min_buy_confidence: float = 72.0
    min_watch_confidence: float = 58.0
    max_spread_pct: float = 0.35
    max_intraday_range_pct: float = 7.0

def _f(v: Any, d: float = 0.0) -> float:
    try: return float(v)
    except (TypeError, ValueError): return d

def _clamp(v: float, lo: float, hi: float) -> float: return max(lo, min(hi, v))
def _utc(v: datetime) -> datetime: return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)

def evaluate_entry(*, symbol: str, market: str, direction: Direction, current_price: float,
                   reference_price: float, entry_price: float, stop_loss: float,
                   target_price: float, quantity: float, portfolio_value: float,
                   price_timestamp: datetime, quote_source: str, confirmation_source_count: int,
                   news_checked: bool, technical_checked: bool, portfolio_checked: bool,
                   live_execution_requested: bool = False, now: datetime | None = None,
                   policy: TradingPolicy | None = None) -> dict:
    p = policy or TradingPolicy(); reasons: list[str] = []
    market = market.upper().strip(); symbol = symbol.upper().strip()
    if not p.enabled: reasons.append('Trading profile is disabled.')
    if not symbol: reasons.append('Symbol is required.')
    if market not in SUPPORTED_MARKETS: reasons.append(f'Unsupported market: {market or "blank"}.')
    if not quote_source.strip(): reasons.append('A live quote source is required.')
    vals = [current_price, reference_price, entry_price, stop_loss, target_price, quantity, portfolio_value]
    if any(v <= 0 for v in vals): reasons.append('All price, quantity, and portfolio values must be greater than zero.')
    age = max(0.0, (_utc(now or datetime.now(timezone.utc)) - _utc(price_timestamp)).total_seconds())
    if age > p.max_price_age_seconds: reasons.append(f'Quote is stale ({age:.0f}s old; maximum {p.max_price_age_seconds}s).')
    if confirmation_source_count < p.min_confirmation_sources: reasons.append('Insufficient independent confirmation sources.')
    missing = [n for n, ok in {'news':news_checked,'technical':technical_checked,'portfolio':portfolio_checked}.items() if not ok]
    if missing: reasons.append('Missing confirmations: ' + ', '.join(missing) + '.')
    if direction == 'long':
        if not stop_loss < entry_price < target_price: reasons.append('Long setup must satisfy stop_loss < entry_price < target_price.')
        risk, reward = entry_price-stop_loss, target_price-entry_price
        chase = ((current_price-reference_price)/reference_price)*100 if reference_price else 0
    else:
        if not target_price < entry_price < stop_loss: reasons.append('Short setup must satisfy target_price < entry_price < stop_loss.')
        risk, reward = stop_loss-entry_price, entry_price-target_price
        chase = ((reference_price-current_price)/reference_price)*100 if reference_price else 0
    rr = reward/risk if risk > 0 and reward > 0 else 0
    if rr < p.min_reward_risk_ratio: reasons.append(f'Reward/risk ratio {rr:.2f} is below the minimum {p.min_reward_risk_ratio:.2f}.')
    position_risk = max(0,risk)*max(0,quantity); risk_pct = position_risk/portfolio_value*100 if portfolio_value else 0
    if risk_pct > p.max_risk_per_trade_pct: reasons.append(f'Position risks {risk_pct:.2f}% of portfolio; maximum is {p.max_risk_per_trade_pct:.2f}%.')
    if chase > p.max_chase_pct: reasons.append(f'Do not chase: price moved {chase:.2f}% beyond the reference level.')
    mode = 'live' if live_execution_requested and p.allow_live_execution else 'paper'
    if live_execution_requested and not p.allow_live_execution: reasons.append('Live execution is disabled by policy.')
    eligible = not reasons
    return {'action':'BUY' if eligible and direction=='long' else 'SELL' if eligible else 'WAIT','eligible':eligible,
            'execution_mode':mode,'reasons':reasons,'metrics':{'quote_age_seconds':round(age,2),'reward_risk_ratio':round(rr,3),
            'risk_pct_of_capital':round(risk_pct,3),'chase_pct':round(chase,3),'position_risk':round(position_risk,2)}}

def coarse_rank(*, symbol: str, exchange: str, last_price: float, ohlc: dict[str,Any] | None,
                market_regime_score: float = 50.0) -> dict:
    o = ohlc or {}; last=_f(last_price); op=_f(o.get('open'),last); hi=_f(o.get('high'),last); lo=_f(o.get('low'),last); close=_f(o.get('close'),op)
    if min(last,op,hi,lo) <= 0: return {'symbol':symbol,'exchange':exchange,'coarse_score':0.0,'eligible':False}
    day=(last-close)/close*100 if close else 0; open_move=(last-op)/op*100 if op else 0; rng=(hi-lo)/last*100 if hi>=lo else 0; pos=(last-lo)/(hi-lo) if hi>lo else .5
    momentum=_clamp(50+day*14+open_move*10,0,100); technical=_clamp(pos*100,0,100); volatility=100-_clamp(abs(rng-2)*18,0,100); regime=_clamp(market_regime_score,0,100)
    score=momentum*.38+technical*.30+volatility*.17+regime*.15; eligible=last>op and day>-.25 and .25<=rng<=8 and pos>=.55
    if not eligible: score*=.65
    return {'symbol':symbol,'exchange':exchange,'coarse_score':round(score,3),'eligible':eligible,'last_price':round(last,2),
            'day_move_pct':round(day,3),'open_move_pct':round(open_move,3),'intraday_range_pct':round(rng,3),'range_position':round(pos,3)}

def build_agentic_opportunity(*, symbol: str, exchange: str, quote: dict[str,Any], portfolio_value: float,
                              market_regime_score: float, news_score: float = 0.0, news_headlines: list[str] | None = None,
                              portfolio_exposure_pct: float = 0.0, policy: TradingPolicy | None = None) -> dict:
    p=policy or TradingPolicy(); symbol=symbol.upper().strip(); exchange=exchange.upper().strip(); o=quote.get('ohlc') or {}
    last=_f(quote.get('last_price')); op=_f(o.get('open'),last); hi=_f(o.get('high'),last); lo=_f(o.get('low'),last); close=_f(o.get('close'),op)
    day=_f(quote.get('day_change_perc')); bid=_f(quote.get('bid_price'),last); offer=_f(quote.get('offer_price'),last)
    buyq=_f(quote.get('total_buy_quantity')); sellq=_f(quote.get('total_sell_quantity')); volume=_f(quote.get('volume'))
    if last<=0 or portfolio_value<=0: return {'symbol':symbol,'exchange':exchange,'action':'WAIT','state':'WAIT','confidence':0.0,'reasons':['No valid live price or portfolio value.'],'risk_vetoes':['Missing required live data.'],'generated_at':datetime.now(timezone.utc).isoformat(),'valid_for_seconds':20}
    rng=(hi-lo)/last*100 if hi>=lo else 0; pos=(last-lo)/(hi-lo) if hi>lo else .5; spread=(offer-bid)/last*100 if offer>=bid>0 else 0; pressure=buyq/(buyq+sellq) if buyq+sellq>0 else .5
    momentum=_clamp(50+(18 if last>op else -20)+(12 if last>=close else 0)+day*7,0,100)
    technical=_clamp(pos*100,0,100); liquidity=_clamp((100-_clamp(spread*180,0,100))*.8+(65 if volume>0 else 45)*.2,0,100)
    orderflow=_clamp(50+(pressure-.5)*140,0,100); regime=_clamp(market_regime_score,0,100); news=_clamp(50+_clamp(news_score,-1,1)*45,0,100)
    scores={'momentum':round(momentum,2),'technical':round(technical,2),'liquidity':round(liquidity,2),'order_flow':round(orderflow,2),'market_regime':round(regime,2),'news':round(news,2)}
    confidence=momentum*.24+technical*.22+liquidity*.18+orderflow*.16+regime*.14+news*.06
    vetoes: list[str]=[]
    if spread>p.max_spread_pct: vetoes.append(f'Spread {spread:.2f}% exceeds the {p.max_spread_pct:.2f}% limit.')
    if rng>p.max_intraday_range_pct: vetoes.append(f'Intraday range {rng:.2f}% is too volatile for this profile.')
    if pos<.52: vetoes.append('Price is not holding the upper half of its intraday range.')
    if market_regime_score<35: vetoes.append('Broad-market regime is too weak for a fresh long trade.')
    if news_score<=-.55: vetoes.append('Negative news risk is too high for a new long entry.')
    if portfolio_exposure_pct>=p.max_position_value_pct: vetoes.append('Existing portfolio exposure is already at the configured cap.')
    entry=round(offer if offer>0 else last,2); stop_pct=_clamp(rng*.32,.55,1.8); technical_stop=lo if 0<lo<entry else entry*(1-stop_pct/100)
    stop=round(min(max(technical_stop,entry*(1-2.2/100)),entry*(1-.35/100)),2); risk=max(entry-stop,.01); target=round(entry+p.min_reward_risk_ratio*risk,2)
    risk_qty=floor((portfolio_value*p.max_risk_per_trade_pct/100)/risk); cap_qty=floor((portfolio_value*p.max_position_value_pct/100)/entry) if entry>0 else 0; qty=max(0,min(risk_qty,cap_qty))
    if qty<1: vetoes.append('Risk-sized quantity is below one share.')
    state='WAIT' if vetoes else 'BUY' if confidence>=p.min_buy_confidence else 'WATCHING' if confidence>=p.min_watch_confidence else 'WAIT'; action='BUY' if state=='BUY' else 'WAIT'
    reasons=[]
    if last>op: reasons.append('Price is above the session open.')
    if last>=close: reasons.append('Price is at or above the previous close.')
    if day>=.5: reasons.append(f'Positive intraday momentum is {day:.2f}%.')
    if pos>=.75: reasons.append('Price is trading in the upper quartile of the intraday range.')
    if spread<=.15: reasons.append(f'Spread is tight at {spread:.2f}%.')
    if pressure>=.56: reasons.append(f'Order-flow pressure favors buyers ({pressure:.0%}).')
    if news_headlines: reasons.append(f'{len(news_headlines)} relevant headline(s) were considered.')
    if state=='WATCHING': reasons.append(f'Confidence {confidence:.1f}% is below the BUY threshold {p.min_buy_confidence:.1f}%.')
    if state=='WAIT' and not vetoes: reasons.append('The multi-agent ensemble is not strong enough for a BUY alert.')
    return {'symbol':symbol,'exchange':exchange,'action':action,'state':state,'confidence':round(confidence,2),'rank_score':round(confidence-len(vetoes)*12,2),
            'entry_price':entry,'target_price':target,'stop_loss':stop,'quantity':qty,'reward_risk_ratio':p.min_reward_risk_ratio,'risk_per_share':round(risk,2),
            'max_position_risk':round(qty*risk,2),'estimated_position_value':round(qty*entry,2),'last_price':round(last,2),'day_change_pct':round(day,3),
            'intraday_range_pct':round(rng,3),'range_position':round(pos,3),'spread_pct':round(spread,3),'buy_pressure':round(pressure,3),
            'expected_move_pct':round((target-entry)/entry*100,3) if entry else 0,'stop_distance_pct':round((entry-stop)/entry*100,3) if entry else 0,
            'portfolio_exposure_pct':round(portfolio_exposure_pct,3),'agent_scores':scores,'risk_vetoes':vetoes,'reasons':reasons,
            'decision_model':'agentic-ensemble-v1','generated_at':datetime.now(timezone.utc).isoformat(),'valid_for_seconds':20}

def generate_long_recommendation(*, symbol: str, exchange: str, quote: dict[str,Any], portfolio_value: float,
                                 policy: TradingPolicy | None = None) -> dict:
    return build_agentic_opportunity(symbol=symbol,exchange=exchange,quote=quote,portfolio_value=portfolio_value,market_regime_score=50.0,policy=policy)
