from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from trading_policy import TradingPolicy, generate_long_recommendation

load_dotenv()

WATCHLIST = [
    item.strip().upper()
    for item in os.getenv(
        'RECOMMENDATION_WATCHLIST',
        'RELIANCE,TCS,HDFCBANK,ICICIBANK,INFY',
    ).split(',')
    if item.strip()
]
RECOMMENDATION_INTERVAL_SECONDS = max(
    1.0, float(os.getenv('RECOMMENDATION_INTERVAL_SECONDS', '2'))
)
DEFAULT_PORTFOLIO_VALUE = float(os.getenv('DEFAULT_PORTFOLIO_VALUE', '500000'))
GROWW_LIVE_EXECUTION_ENABLED = (
    os.getenv('GROWW_LIVE_EXECUTION_ENABLED', 'false').strip().lower()
    in {'1', 'true', 'yes', 'on'}
)

policy = TradingPolicy(
    allow_live_execution=GROWW_LIVE_EXECUTION_ENABLED,
    max_risk_per_trade_pct=float(os.getenv('MAX_RISK_PER_TRADE_PCT', '1.0')),
    min_reward_risk_ratio=float(os.getenv('MIN_REWARD_RISK_RATIO', '2.0')),
    max_chase_pct=float(os.getenv('MAX_CHASE_PCT', '1.5')),
    max_price_age_seconds=int(os.getenv('MAX_PRICE_AGE_SECONDS', '120')),
    min_confirmation_sources=int(os.getenv('MIN_CONFIRMATION_SOURCES', '2')),
)

_groww: Any | None = None
_groww_error: str | None = None
latest_recommendations: dict[str, dict] = {}
recommendation_cache: dict[str, dict] = {}
latest_holdings: list[dict] = []
latest_positions: list[dict] = []
connected_sockets: set[WebSocket] = set()
background_task: asyncio.Task | None = None


class RecommendationRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    exchange: str = Field(default='NSE', min_length=3, max_length=3)
    portfolio_value: float = Field(default=DEFAULT_PORTFOLIO_VALUE, gt=0)


class BuyRecommendationRequest(BaseModel):
    recommendation_id: str = Field(min_length=8, max_length=64)


def _mask_error(exc: Exception) -> str:
    return f'{exc.__class__.__name__}: {str(exc)[:200]}'


def get_groww() -> Any:
    global _groww, _groww_error
    if _groww is not None:
        return _groww

    api_key = os.getenv('GROWW_API_KEY', '').strip()
    api_secret = os.getenv('GROWW_API_SECRET', '').strip()
    if not api_key or not api_secret:
        raise RuntimeError('Groww API credentials are not configured in backend/.env.')

    try:
        from growwapi import GrowwAPI

        access_token = GrowwAPI.get_access_token(api_key=api_key, secret=api_secret)
        _groww = GrowwAPI(access_token)
        _groww_error = None
        return _groww
    except Exception as exc:
        _groww_error = _mask_error(exc)
        raise


def _exchange_constant(groww: Any, exchange: str) -> str:
    exchange = exchange.upper()
    if exchange == 'NSE':
        return groww.EXCHANGE_NSE
    if exchange == 'BSE':
        return groww.EXCHANGE_BSE
    raise ValueError(f'Unsupported Groww cash exchange: {exchange}')


def _extract_list(payload: Any, key: str) -> list[dict]:
    if isinstance(payload, dict):
        value = payload.get(key, [])
        return value if isinstance(value, list) else []
    return []


async def broadcast(message: dict) -> None:
    dead: list[WebSocket] = []
    for socket in connected_sockets:
        try:
            await socket.send_json(message)
        except Exception:
            dead.append(socket)
    for socket in dead:
        connected_sockets.discard(socket)


async def fetch_recommendation(symbol: str, exchange: str, portfolio_value: float) -> dict:
    groww = get_groww()
    quote = await asyncio.to_thread(
        groww.get_quote,
        exchange=_exchange_constant(groww, exchange),
        segment=groww.SEGMENT_CASH,
        trading_symbol=symbol,
    )
    recommendation = generate_long_recommendation(
        symbol=symbol,
        exchange=exchange,
        quote=quote,
        portfolio_value=portfolio_value,
        policy=policy,
    )
    recommendation_id = uuid.uuid4().hex
    recommendation['recommendation_id'] = recommendation_id
    recommendation['live_execution_enabled'] = GROWW_LIVE_EXECUTION_ENABLED
    recommendation_cache[recommendation_id] = recommendation
    latest_recommendations[f'{exchange}:{symbol}'] = recommendation

    # Keep only recent cache entries to avoid unbounded growth.
    if len(recommendation_cache) > 500:
        for key in list(recommendation_cache)[:250]:
            recommendation_cache.pop(key, None)
    return recommendation


async def refresh_portfolio() -> None:
    global latest_holdings, latest_positions
    try:
        groww = get_groww()
        holdings_payload, positions_payload = await asyncio.gather(
            asyncio.to_thread(groww.get_holdings_for_user, timeout=5),
            asyncio.to_thread(groww.get_positions_for_user, segment=groww.SEGMENT_CASH),
        )
        latest_holdings = _extract_list(holdings_payload, 'holdings')
        latest_positions = _extract_list(positions_payload, 'positions')
        await broadcast({
            'type': 'portfolio',
            'holdings': latest_holdings,
            'positions': latest_positions,
            'ts': datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        return


async def recommendation_loop() -> None:
    portfolio_refresh_counter = 0
    while True:
        try:
            for symbol in WATCHLIST:
                try:
                    rec = await fetch_recommendation(
                        symbol=symbol,
                        exchange='NSE',
                        portfolio_value=DEFAULT_PORTFOLIO_VALUE,
                    )
                    await broadcast({
                        'type': 'recommendation',
                        'data': rec,
                        'ts': datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:
                    continue

            portfolio_refresh_counter += 1
            if portfolio_refresh_counter >= 15:
                portfolio_refresh_counter = 0
                await refresh_portfolio()
        finally:
            await asyncio.sleep(RECOMMENDATION_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global background_task
    background_task = asyncio.create_task(recommendation_loop())
    yield
    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title='Suhas Private AI Trader',
    version='0.4.0',
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://127.0.0.1:8080', 'http://localhost:8080'],
    allow_credentials=False,
    allow_methods=['GET', 'POST'],
    allow_headers=['Content-Type'],
)


@app.get('/health')
def health() -> dict:
    configured = bool(os.getenv('GROWW_API_KEY') and os.getenv('GROWW_API_SECRET'))
    return {
        'status': 'ok',
        'broker': 'groww',
        'configured': configured,
        'connected': _groww is not None,
        'connection_error': _groww_error,
        'live_execution_enabled': GROWW_LIVE_EXECUTION_ENABLED,
        'recommendation_watchlist': WATCHLIST,
    }


@app.get('/api/live/state')
def live_state() -> dict:
    return {
        'recommendations': latest_recommendations,
        'holdings': latest_holdings,
        'positions': latest_positions,
        'news': [],
        'live_execution_enabled': GROWW_LIVE_EXECUTION_ENABLED,
    }


@app.post('/api/recommendation')
async def recommendation(request: RecommendationRequest) -> dict:
    try:
        return await fetch_recommendation(
            symbol=request.symbol.upper().strip(),
            exchange=request.exchange.upper().strip(),
            portfolio_value=request.portfolio_value,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=_mask_error(exc)) from exc


@app.get('/api/recommendations')
def recommendations() -> dict:
    return {'items': list(latest_recommendations.values())}


@app.get('/api/groww/holdings')
async def groww_holdings() -> dict:
    try:
        groww = get_groww()
        return await asyncio.to_thread(groww.get_holdings_for_user, timeout=5)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=_mask_error(exc)) from exc


@app.get('/api/groww/positions')
async def groww_positions() -> dict:
    try:
        groww = get_groww()
        return await asyncio.to_thread(
            groww.get_positions_for_user,
            segment=groww.SEGMENT_CASH,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=_mask_error(exc)) from exc


@app.post('/api/orders/buy-recommendation')
async def buy_recommendation(request: BuyRecommendationRequest) -> dict:
    if not GROWW_LIVE_EXECUTION_ENABLED:
        raise HTTPException(
            status_code=403,
            detail='Live execution is disabled. Set GROWW_LIVE_EXECUTION_ENABLED=true locally only after testing.',
        )

    cached = recommendation_cache.get(request.recommendation_id)
    if not cached:
        raise HTTPException(status_code=404, detail='Recommendation not found or expired.')
    if cached.get('action') != 'BUY':
        raise HTTPException(status_code=409, detail='Only an active BUY recommendation can be executed.')

    generated_at = datetime.fromisoformat(cached['generated_at'])
    age = (datetime.now(timezone.utc) - generated_at).total_seconds()
    if age > float(cached.get('valid_for_seconds', 15)):
        raise HTTPException(status_code=409, detail='Recommendation expired. Wait for a fresh recommendation.')

    # Revalidate against a fresh Groww quote immediately before sending the order.
    fresh = await fetch_recommendation(
        symbol=cached['symbol'],
        exchange=cached['exchange'],
        portfolio_value=DEFAULT_PORTFOLIO_VALUE,
    )
    if fresh.get('action') != 'BUY':
        raise HTTPException(status_code=409, detail='Market conditions changed; the fresh recommendation is no longer BUY.')

    old_entry = float(cached['entry_price'])
    fresh_entry = float(fresh['entry_price'])
    if fresh_entry > old_entry * 1.005:
        raise HTTPException(status_code=409, detail='Price moved more than 0.5% above the approved entry. Order blocked to avoid chasing.')

    quantity = int(fresh['quantity'])
    if quantity < 1:
        raise HTTPException(status_code=409, detail='Risk-sized quantity is below one share.')

    try:
        groww = get_groww()
        reference_id = f'AI-{uuid.uuid4().hex[:14]}'
        result = await asyncio.to_thread(
            groww.place_order,
            trading_symbol=fresh['symbol'],
            quantity=quantity,
            validity=groww.VALIDITY_DAY,
            exchange=_exchange_constant(groww, fresh['exchange']),
            segment=groww.SEGMENT_CASH,
            product=groww.PRODUCT_CNC,
            order_type=groww.ORDER_TYPE_LIMIT,
            transaction_type=groww.TRANSACTION_TYPE_BUY,
            price=fresh_entry,
            order_reference_id=reference_id,
        )
        await broadcast({
            'type': 'order',
            'data': result,
            'recommendation': fresh,
            'ts': datetime.now(timezone.utc).isoformat(),
        })
        return {
            'submitted': True,
            'broker': 'groww',
            'order': result,
            'executed_recommendation': fresh,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_mask_error(exc)) from exc


@app.websocket('/ws/live')
async def live_websocket(socket: WebSocket):
    await socket.accept()
    connected_sockets.add(socket)
    try:
        await socket.send_json({
            'type': 'snapshot',
            'recommendations': latest_recommendations,
            'holdings': latest_holdings,
            'positions': latest_positions,
            'live_execution_enabled': GROWW_LIVE_EXECUTION_ENABLED,
            'ts': datetime.now(timezone.utc).isoformat(),
        })
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        connected_sockets.discard(socket)
