from datetime import datetime
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from brokers import PaperBroker
from brokers.base import BrokerOrderRequest
from trading_policy import TradingPolicy, evaluate_entry

app = FastAPI(title='Suhas Private AI Trader', version='0.2.0')
paper_broker = PaperBroker()


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


class PaperOrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    market: Literal['NSE', 'BSE', 'NYSE', 'NASDAQ']
    side: Literal['buy', 'sell']
    quantity: float = Field(gt=0)
    order_type: Literal['market', 'limit'] = 'market'
    price: float | None = Field(default=None, gt=0)


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


@app.get('/api/brokers')
def brokers() -> dict:
    return {
        'brokers': [
            {
                'id': 'paper',
                'name': 'Paper Broker',
                'connected': True,
                'mode': 'paper',
                'capabilities': paper_broker.capabilities.to_dict(),
            }
        ],
        'live_execution_enabled': False,
    }


@app.get('/api/brokers/paper/account')
def paper_account() -> dict:
    return paper_broker.get_account()


@app.get('/api/brokers/paper/positions')
def paper_positions() -> list[dict]:
    return paper_broker.get_positions()


@app.get('/api/brokers/paper/orders')
def paper_orders() -> list[dict]:
    return paper_broker.get_orders()


@app.post('/api/brokers/paper/orders')
def place_paper_order(request: PaperOrderRequest) -> dict:
    result = paper_broker.place_order(BrokerOrderRequest(**request.model_dump()))
    return result.to_dict()


@app.post('/api/brokers/paper/orders/{order_id}/cancel')
def cancel_paper_order(order_id: str) -> dict:
    return paper_broker.cancel_order(order_id).to_dict()
