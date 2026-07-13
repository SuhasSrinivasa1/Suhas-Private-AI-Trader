from dataclasses import dataclass
from datetime import datetime, timezone
from math import floor
from typing import Literal

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


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def evaluate_entry(*, symbol: str, market: str, direction: Direction, current_price: float,
                   reference_price: float, entry_price: float, stop_loss: float,
                   target_price: float, quantity: float, portfolio_value: float,
                   price_timestamp: datetime, quote_source: str,
                   confirmation_source_count: int, news_checked: bool,
                   technical_checked: bool, portfolio_checked: bool,
                   live_execution_requested: bool = False,
                   now: datetime | None = None,
                   policy: TradingPolicy | None = None) -> dict:
    policy = policy or TradingPolicy()
    reasons: list[str] = []
    market = market.upper().strip()
    symbol = symbol.upper().strip()

    if not policy.enabled:
        reasons.append('Trading profile is disabled.')
    if not symbol:
        reasons.append('Symbol is required.')
    if market not in SUPPORTED_MARKETS:
        reasons.append(f'Unsupported market: {market or "blank"}.')
    if not quote_source.strip():
        reasons.append('A live quote source is required.')

    values = [current_price, reference_price, entry_price, stop_loss, target_price, quantity, portfolio_value]
    if any(v <= 0 for v in values):
        reasons.append('All price, quantity, and portfolio values must be greater than zero.')

    now_utc = _utc(now or datetime.now(timezone.utc))
    quote_utc = _utc(price_timestamp)
    raw_age = (now_utc - quote_utc).total_seconds()
    if raw_age < -30:
        reasons.append('Quote timestamp is too far in the future.')
    quote_age = max(0.0, raw_age)
    if quote_age > policy.max_price_age_seconds:
        reasons.append(f'Quote is stale ({quote_age:.0f}s old; maximum {policy.max_price_age_seconds}s).')

    if confirmation_source_count < policy.min_confirmation_sources:
        reasons.append(
            f'Insufficient independent confirmation sources '
            f'({confirmation_source_count}; minimum {policy.min_confirmation_sources}).'
        )

    missing = [name for name, ok in {
        'news': news_checked,
        'technical': technical_checked,
        'portfolio': portfolio_checked,
    }.items() if not ok]
    if missing:
        reasons.append('Missing confirmations: ' + ', '.join(missing) + '.')

    if direction == 'long':
        if not stop_loss < entry_price < target_price:
            reasons.append('Long setup must satisfy stop_loss < entry_price < target_price.')
        risk_per_share = entry_price - stop_loss
        reward_per_share = target_price - entry_price
        chase_pct = ((current_price - reference_price) / reference_price) * 100 if reference_price > 0 else 0.0
    else:
        if not target_price < entry_price < stop_loss:
            reasons.append('Short setup must satisfy target_price < entry_price < stop_loss.')
        risk_per_share = stop_loss - entry_price
        reward_per_share = entry_price - target_price
        chase_pct = ((reference_price - current_price) / reference_price) * 100 if reference_price > 0 else 0.0

    reward_risk_ratio = reward_per_share / risk_per_share if risk_per_share > 0 and reward_per_share > 0 else 0.0
    if reward_risk_ratio < policy.min_reward_risk_ratio:
        reasons.append(
            f'Reward/risk ratio {reward_risk_ratio:.2f} is below the minimum '
            f'{policy.min_reward_risk_ratio:.2f}.'
        )

    position_risk = max(0.0, risk_per_share) * max(0.0, quantity)
    risk_pct = (position_risk / portfolio_value) * 100 if portfolio_value > 0 else 0.0
    if risk_pct > policy.max_risk_per_trade_pct:
        reasons.append(
            f'Position risks {risk_pct:.2f}% of portfolio; maximum is '
            f'{policy.max_risk_per_trade_pct:.2f}%.'
        )

    if chase_pct > policy.max_chase_pct:
        reasons.append(
            f'Do not chase: price moved {chase_pct:.2f}% beyond the reference level; '
            f'maximum is {policy.max_chase_pct:.2f}%.'
        )

    execution_mode = 'paper'
    if live_execution_requested:
        if policy.allow_live_execution:
            execution_mode = 'live'
        else:
            reasons.append('Live execution is disabled by policy.')

    eligible = not reasons
    action = 'BUY' if eligible and direction == 'long' else 'SELL' if eligible else 'WAIT'
    return {
        'action': action,
        'eligible': eligible,
        'execution_mode': execution_mode,
        'reasons': reasons,
        'warnings': [
            'Policy validation only: recommendation quality depends on the market and news inputs supplied.',
            'Revalidate price and risk immediately before sending a real order.',
        ],
        'metrics': {
            'quote_age_seconds': round(quote_age, 2),
            'reward_risk_ratio': round(reward_risk_ratio, 3),
            'risk_pct_of_capital': round(risk_pct, 3),
            'chase_pct': round(chase_pct, 3),
            'position_risk': round(position_risk, 2),
        },
    }


def generate_long_recommendation(*, symbol: str, exchange: str, quote: dict,
                                 portfolio_value: float, policy: TradingPolicy | None = None) -> dict:
    """Generate a rules-based intraday long recommendation from a fresh Groww quote.

    This is decision support, not a guarantee of profit. It intentionally returns WAIT
    unless several independent quote/market-structure checks are positive.
    """
    policy = policy or TradingPolicy()
    symbol = symbol.upper().strip()
    exchange = exchange.upper().strip()

    last = float(quote.get('last_price') or 0)
    ohlc = quote.get('ohlc') or {}
    open_price = float(ohlc.get('open') or last or 0)
    high = float(ohlc.get('high') or last or 0)
    low = float(ohlc.get('low') or last or 0)
    close = float(ohlc.get('close') or open_price or last or 0)
    day_change_pct = float(quote.get('day_change_perc') or 0)
    bid_qty = float(quote.get('total_buy_quantity') or 0)
    ask_qty = float(quote.get('total_sell_quantity') or 0)
    bid_price = float(quote.get('bid_price') or last or 0)
    offer_price = float(quote.get('offer_price') or last or 0)

    if last <= 0 or portfolio_value <= 0:
        return {'symbol': symbol, 'exchange': exchange, 'action': 'WAIT', 'reasons': ['No valid live price or portfolio value.']}

    intraday_range_pct = ((high - low) / last) * 100 if last > 0 and high >= low else 0.0
    spread_pct = ((offer_price - bid_price) / last) * 100 if offer_price >= bid_price and last > 0 else 0.0
    buy_pressure = bid_qty / (bid_qty + ask_qty) if (bid_qty + ask_qty) > 0 else 0.5

    score = 0
    reasons: list[str] = []
    if last > open_price:
        score += 1
        reasons.append('Price is above the session open.')
    if last >= close:
        score += 1
        reasons.append('Price is holding at or above the previous close reference.')
    if day_change_pct >= 0.25:
        score += 1
        reasons.append(f'Positive day momentum ({day_change_pct:.2f}%).')
    if buy_pressure >= 0.55:
        score += 1
        reasons.append(f'Buy-side quantity pressure is supportive ({buy_pressure:.0%}).')
    if spread_pct > 0.35:
        score -= 2
        reasons.append(f'Spread is too wide ({spread_pct:.2f}%).')
    if intraday_range_pct > 6.0:
        score -= 1
        reasons.append(f'Intraday volatility is elevated ({intraday_range_pct:.2f}%).')

    risk_pct_price = min(max(intraday_range_pct * 0.35, 0.6), 2.5)
    entry = round(offer_price if offer_price > 0 else last, 2)
    stop = round(entry * (1 - risk_pct_price / 100), 2)
    risk_per_share = max(entry - stop, 0.01)
    target = round(entry + policy.min_reward_risk_ratio * risk_per_share, 2)
    max_risk_rupees = portfolio_value * policy.max_risk_per_trade_pct / 100
    quantity = max(0, floor(max_risk_rupees / risk_per_share))

    action = 'BUY' if score >= 3 and quantity >= 1 else 'WAIT'
    if action == 'WAIT' and score < 3:
        reasons.append(f'Only {score} of the required confirmation points are present.')
    if quantity < 1:
        reasons.append('Risk-sized quantity is below one share.')

    return {
        'symbol': symbol,
        'exchange': exchange,
        'action': action,
        'score': score,
        'entry_price': entry,
        'target_price': target,
        'stop_loss': stop,
        'quantity': quantity,
        'reward_risk_ratio': policy.min_reward_risk_ratio,
        'risk_per_share': round(risk_per_share, 2),
        'max_position_risk': round(quantity * risk_per_share, 2),
        'last_price': round(last, 2),
        'day_change_pct': round(day_change_pct, 3),
        'intraday_range_pct': round(intraday_range_pct, 3),
        'spread_pct': round(spread_pct, 3),
        'buy_pressure': round(buy_pressure, 3),
        'reasons': reasons,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'valid_for_seconds': 15,
    }
