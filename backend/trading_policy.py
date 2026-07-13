from dataclasses import dataclass
from datetime import datetime, timezone
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
        reasons.append(f'Insufficient independent confirmation sources ({confirmation_source_count}; minimum {policy.min_confirmation_sources}).')

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
        reasons.append(f'Reward/risk ratio {reward_risk_ratio:.2f} is below the minimum {policy.min_reward_risk_ratio:.2f}.')

    position_risk = max(0.0, risk_per_share) * max(0.0, quantity)
    risk_pct = (position_risk / portfolio_value) * 100 if portfolio_value > 0 else 0.0
    if risk_pct > policy.max_risk_per_trade_pct:
        reasons.append(f'Position risks {risk_pct:.2f}% of portfolio; maximum is {policy.max_risk_per_trade_pct:.2f}%.')

    if chase_pct > policy.max_chase_pct:
        reasons.append(f'Do not chase: price moved {chase_pct:.2f}% beyond the reference level; maximum is {policy.max_chase_pct:.2f}%.')

    execution_mode = 'paper'
    if live_execution_requested:
        if policy.allow_live_execution:
            execution_mode = 'live'
        else:
            reasons.append('Live execution is disabled by policy; use paper mode.')

    eligible = not reasons
    action = 'BUY' if eligible and direction == 'long' else 'SELL' if eligible else 'WAIT'
    return {
        'action': action,
        'eligible': eligible,
        'execution_mode': execution_mode,
        'reasons': reasons,
        'warnings': [
            'Policy validation only: this endpoint does not place broker orders.',
            'Revalidate live price, news, and market conditions immediately before execution.',
        ],
        'metrics': {
            'quote_age_seconds': round(quote_age, 2),
            'reward_risk_ratio': round(reward_risk_ratio, 3),
            'risk_pct_of_capital': round(risk_pct, 3),
            'chase_pct': round(chase_pct, 3),
            'position_risk': round(position_risk, 2),
        },
    }
