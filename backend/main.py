from datetime import datetime
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from trading_policy import TradingPolicy, evaluate_entry

app = FastAPI(title='Suhas Private AI Trader', version='0.1.0')


class EntryRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    market: str = Field(min_length=1, max_length=16)
    direction: Literal['long', 'short']
    current_price: float = Field(gt=0)
    reference_price: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    target_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    portfolio_value: float = Field(gt=0)
    price_timestamp: datetime
    quote_source: str = Field(min_length=1, max_length=128)
    confirmation_source_count: int = Field(ge=0)
    news_checked: bool
    technical_checked: bool
    portfolio_checked: bool
    live_execution_requested: bool = False


@app.get('/health')
def health() -> dict:
    return {'status': 'ok', 'mode': 'paper', 'live_execution': False}


@app.get('/api/profile')
def profile() -> dict:
    policy = TradingPolicy()
    return {
        'name': 'Private Trading Profile',
        'execution_default': 'paper',
        'allow_live_execution': policy.allow_live_execution,
        'supported_markets': ['NSE', 'BSE', 'NYSE', 'NASDAQ'],
        'guardrails': {
            'max_risk_per_trade_pct': policy.max_risk_per_trade_pct,
            'min_reward_risk_ratio': policy.min_reward_risk_ratio,
            'max_chase_pct': policy.max_chase_pct,
            'max_price_age_seconds': policy.max_price_age_seconds,
            'min_confirmation_sources': policy.min_confirmation_sources,
        },
    }


@app.post('/api/evaluate-entry')
def evaluate(request: EntryRequest) -> dict:
    return evaluate_entry(**request.model_dump())
