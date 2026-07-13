from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from groww_adapter import get_ltp_batch_sync, get_ohlc_batch_sync
from trading_policy import TradingPolicy, build_agentic_opportunity, coarse_rank

load_dotenv()
IST = ZoneInfo("Asia/Kolkata")

DEFAULT_UNIVERSE = (
    "RELIANCE,TCS,HDFCBANK,ICICIBANK,INFY,SBIN,BHARTIARTL,ITC,LT,AXISBANK,"
    "KOTAKBANK,HINDUNLVR,BAJFINANCE,MARUTI,SUNPHARMA,NTPC,TITAN,M&M,"
    "ULTRACEMCO,ONGC,POWERGRID,NESTLEIND,TATAMOTORS,ADANIPORTS,COALINDIA,"
    "BAJAJFINSV,ASIANPAINT,JSWSTEEL,TATASTEEL,HCLTECH,TECHM,WIPRO,CIPLA,"
    "DRREDDY,GRASIM,HINDALCO,INDUSINDBK,EICHERMOT,HEROMOTOCO,APOLLOHOSP,"
    "BEL,TRENT,SHRIRAMFIN,BAJAJ-AUTO,ADANIENT,ETERNAL,JIOFIN,SBILIFE,HDFCLIFE"
)
SCANNER_UNIVERSE = [
    item.strip().upper()
    for item in os.getenv("SCANNER_UNIVERSE", DEFAULT_UNIVERSE).split(",")
    if item.strip()
]
SCAN_INTERVAL_SECONDS = max(3.0, float(os.getenv("SCAN_INTERVAL_SECONDS", "15")))
DEEP_SCAN_CANDIDATES = max(3, min(20, int(os.getenv("DEEP_SCAN_CANDIDATES", "10"))))
MAX_DISPLAY_OPPORTUNITIES = max(3, min(20, int(os.getenv("MAX_DISPLAY_OPPORTUNITIES", "8"))))
DEFAULT_PORTFOLIO_VALUE = float(os.getenv("DEFAULT_PORTFOLIO_VALUE", "500000"))
SIGNAL_VALID_SECONDS = max(5, min(90, int(os.getenv("SIGNAL_VALID_SECONDS", "20"))))


def _env_bool(name: str, default: bool = False) -> bool:
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


TRADING_PROFILE_ENABLED = _env_bool("TRADING_PROFILE_ENABLED", True)
GROWW_LIVE_EXECUTION_ENABLED = _env_bool("GROWW_LIVE_EXECUTION_ENABLED", False)

policy = TradingPolicy(
    enabled=TRADING_PROFILE_ENABLED,
    allow_live_execution=GROWW_LIVE_EXECUTION_ENABLED,
    max_risk_per_trade_pct=float(os.getenv("MAX_RISK_PER_TRADE_PCT", "1.0")),
    min_reward_risk_ratio=float(os.getenv("MIN_REWARD_RISK_RATIO", "2.0")),
    max_chase_pct=float(os.getenv("MAX_CHASE_PCT", "1.5")),
    max_price_age_seconds=int(os.getenv("MAX_PRICE_AGE_SECONDS", "120")),
    min_confirmation_sources=int(os.getenv("MIN_CONFIRMATION_SOURCES", "2")),
    max_position_value_pct=float(os.getenv("MAX_POSITION_VALUE_PCT", "20")),
    min_buy_confidence=float(os.getenv("MIN_BUY_CONFIDENCE", "72")),
    min_watch_confidence=float(os.getenv("MIN_WATCH_CONFIDENCE", "58")),
    max_spread_pct=float(os.getenv("MAX_SPREAD_PCT", "0.35")),
    max_intraday_range_pct=float(os.getenv("MAX_INTRADAY_RANGE_PCT", "7.0")),
)

_groww: Any | None = None
_groww_error: str | None = None
latest_opportunities: dict[str, dict] = {}
recommendation_cache: dict[str, dict] = {}
latest_holdings: list[dict] = []
latest_positions: list[dict] = []
latest_prices: dict[str, dict[str, Any]] = {}
latest_market_regime: dict[str, Any] = {"score": 50.0, "label": "neutral"}
connected_sockets: set[WebSocket] = set()
background_task: asyncio.Task | None = None
last_scan_at: str | None = None
last_scan_error: str | None = None
alerted_signal_ids: set[str] = set()


class BuyRecommendationRequest(BaseModel):
    recommendation_id: str = Field(min_length=8, max_length=64)


class SingleScanRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    exchange: str = Field(default="NSE", min_length=3, max_length=3)
    portfolio_value: float = Field(default=DEFAULT_PORTFOLIO_VALUE, gt=0)


def _mask_error(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {str(exc)[:220]}"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _market_open_now() -> bool:
    now = datetime.now(IST)
    return now.weekday() < 5 and time(9, 15) <= now.time() <= time(15, 20)


def _broker_configured() -> bool:
    return bool(os.getenv("GROWW_API_KEY", "").strip() and os.getenv("GROWW_API_SECRET", "").strip())


def _scanner_status() -> str:
    if not TRADING_PROFILE_ENABLED:
        return "profile_disabled"
    if not _broker_configured():
        return "broker_not_configured"
    if not _market_open_now():
        return "market_closed"
    return "active"


def get_groww() -> Any:
    global _groww, _groww_error
    if _groww is not None:
        return _groww
    api_key = os.getenv("GROWW_API_KEY", "").strip()
    api_secret = os.getenv("GROWW_API_SECRET", "").strip()
    if not api_key or not api_secret:
        raise RuntimeError("Groww API credentials are not configured in backend/.env.")
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
    if exchange == "NSE":
        return groww.EXCHANGE_NSE
    if exchange == "BSE":
        return groww.EXCHANGE_BSE
    raise ValueError(f"Unsupported Groww cash exchange: {exchange}")


def _extract_list(payload: Any, key: str) -> list[dict]:
    if isinstance(payload, dict):
        value = payload.get(key, [])
        return value if isinstance(value, list) else []
    return []


def _holding_symbol(item: dict) -> str:
    return str(item.get("trading_symbol") or item.get("tradingSymbol") or item.get("symbol") or "").upper()


def _portfolio_exposure_pct(symbol: str, price: float) -> float:
    if DEFAULT_PORTFOLIO_VALUE <= 0:
        return 0.0
    value = 0.0
    for item in latest_holdings + latest_positions:
        if _holding_symbol(item) != symbol.upper():
            continue
        quantity = _f(item.get("quantity") or item.get("qty") or item.get("net_quantity"))
        average = _f(
            item.get("average_price")
            or item.get("averagePrice")
            or item.get("avg_price")
            or item.get("net_price"),
            price,
        )
        value += abs(quantity) * (price or average)
    return (value / DEFAULT_PORTFOLIO_VALUE) * 100


def _record_prices(prices: dict[str, float], exchange: str = "NSE") -> None:
    timestamp = _now().isoformat()
    for symbol, price in prices.items():
        if price > 0:
            latest_prices[f"{exchange.upper()}:{symbol.upper()}"] = {
                "ltp": round(price, 4),
                "last_price": round(price, 4),
                "ts": timestamp,
            }


async def broadcast(message: dict) -> None:
    dead: list[WebSocket] = []
    for socket in list(connected_sockets):
        try:
            await socket.send_json(message)
        except Exception:
            dead.append(socket)
    for socket in dead:
        connected_sockets.discard(socket)


async def _quote(symbol: str, exchange: str = "NSE") -> dict:
    groww = get_groww()
    quote = await asyncio.to_thread(
        groww.get_quote,
        exchange=_exchange_constant(groww, exchange),
        segment=groww.SEGMENT_CASH,
        trading_symbol=symbol,
    )
    if isinstance(quote, dict):
        price = _f(quote.get("last_price"))
        if price > 0:
            _record_prices({symbol.upper(): price}, exchange)
        return quote
    raise RuntimeError(f"Groww quote response for {exchange}:{symbol} was not a dictionary.")


async def _get_ltp_batch(symbols: list[str], exchange: str = "NSE") -> dict[str, float]:
    """Fetch up to 50 LTP values using the current Groww SDK contract, with a legacy fallback."""
    if not symbols:
        return {}
    groww = get_groww()
    try:
        parsed = await asyncio.to_thread(get_ltp_batch_sync, groww, symbols, exchange)
        if parsed:
            _record_prices(parsed, exchange)
            return parsed
    except Exception:
        pass

    # Slow compatibility fallback. Throttle individual quote calls to stay below the documented live-data rate limit.
    result: dict[str, float] = {}
    for index, symbol in enumerate(symbols):
        if index and index % 8 == 0:
            await asyncio.sleep(1.05)
        try:
            quote = await _quote(symbol, exchange)
            price = _f(quote.get("last_price"))
            if price > 0:
                result[symbol.upper()] = price
        except Exception:
            continue
    return result


async def _get_ohlc_batch(symbols: list[str], exchange: str = "NSE") -> dict[str, dict]:
    if not symbols:
        return {}
    groww = get_groww()
    try:
        return await asyncio.to_thread(get_ohlc_batch_sync, groww, symbols, exchange)
    except Exception:
        return {}


async def _refresh_prices_for_symbols(symbols: list[str], exchange: str = "NSE") -> None:
    unique = list(dict.fromkeys(symbol.upper() for symbol in symbols if symbol))
    for start in range(0, len(unique), 50):
        await _get_ltp_batch(unique[start : start + 50], exchange)


async def refresh_portfolio() -> None:
    global latest_holdings, latest_positions
    if not _broker_configured():
        return
    try:
        groww = get_groww()
        holdings_payload, positions_payload = await asyncio.gather(
            asyncio.to_thread(groww.get_holdings_for_user, timeout=5),
            asyncio.to_thread(groww.get_positions_for_user, segment=groww.SEGMENT_CASH),
        )
        latest_holdings = _extract_list(holdings_payload, "holdings")
        latest_positions = _extract_list(positions_payload, "positions")
        symbols = [_holding_symbol(item) for item in latest_holdings + latest_positions]
        await _refresh_prices_for_symbols(symbols)
        await broadcast(
            {
                "type": "portfolio",
                "holdings": latest_holdings,
                "positions": latest_positions,
                "prices": latest_prices,
                "ts": _now().isoformat(),
            }
        )
    except Exception:
        return


async def _market_regime_score() -> dict[str, Any]:
    """Estimate broad market regime from diversified liquid leaders."""
    leaders = ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "LT", "BHARTIARTL"]
    ltps = await _get_ltp_batch(leaders)
    ohlc = await _get_ohlc_batch(list(ltps))
    scores: list[float] = []
    for symbol, last in ltps.items():
        ranked = coarse_rank(
            symbol=symbol,
            exchange="NSE",
            last_price=last,
            ohlc=ohlc.get(symbol),
            market_regime_score=50,
        )
        scores.append(_f(ranked.get("coarse_score"), 50))
    score = sum(scores) / len(scores) if scores else 50.0
    label = "bullish" if score >= 62 else "weak" if score < 42 else "neutral"
    return {"score": round(score, 2), "label": label}


async def _coarse_scan() -> list[dict]:
    candidates: list[dict] = []
    for start in range(0, len(SCANNER_UNIVERSE), 50):
        chunk = SCANNER_UNIVERSE[start : start + 50]
        ltps, ohlc = await asyncio.gather(_get_ltp_batch(chunk), _get_ohlc_batch(chunk))
        for symbol, last in ltps.items():
            ranked = coarse_rank(
                symbol=symbol,
                exchange="NSE",
                last_price=last,
                ohlc=ohlc.get(symbol),
                market_regime_score=_f(latest_market_regime.get("score"), 50),
            )
            candidates.append(ranked)
    candidates.sort(key=lambda item: _f(item.get("coarse_score")), reverse=True)
    return candidates[:DEEP_SCAN_CANDIDATES]


def _news_context_for_symbol(symbol: str) -> tuple[float, list[str]]:
    # Hook point for a future licensed/official news provider or LLM news interpreter.
    # Until configured, the news agent stays neutral and cannot manufacture sentiment.
    _ = symbol
    return 0.0, []


def _signal_identity(recommendation: dict) -> str:
    basis = (
        f"{recommendation.get('exchange')}:{recommendation.get('symbol')}:"
        f"{recommendation.get('state')}:{round(_f(recommendation.get('entry_price')), 2)}"
    )
    return uuid.uuid5(uuid.NAMESPACE_URL, basis).hex


async def _deep_scan(candidate: dict) -> dict:
    symbol = candidate["symbol"]
    exchange = candidate.get("exchange", "NSE")
    quote = await _quote(symbol, exchange)
    news_score, headlines = _news_context_for_symbol(symbol)
    exposure = _portfolio_exposure_pct(symbol, _f(quote.get("last_price")))
    opportunity = build_agentic_opportunity(
        symbol=symbol,
        exchange=exchange,
        quote=quote,
        portfolio_value=DEFAULT_PORTFOLIO_VALUE,
        market_regime_score=_f(latest_market_regime.get("score"), 50),
        news_score=news_score,
        news_headlines=headlines,
        portfolio_exposure_pct=exposure,
        policy=policy,
    )
    opportunity["coarse_score"] = candidate.get("coarse_score", 0)
    opportunity["valid_for_seconds"] = SIGNAL_VALID_SECONDS
    opportunity["live_execution_enabled"] = GROWW_LIVE_EXECUTION_ENABLED
    opportunity["recommendation_id"] = _signal_identity(opportunity)
    recommendation_cache[opportunity["recommendation_id"]] = opportunity
    return opportunity


async def scan_market_once() -> list[dict]:
    global latest_market_regime, latest_opportunities, last_scan_at, last_scan_error
    if not _broker_configured():
        last_scan_error = None
        return []
    try:
        latest_market_regime = await _market_regime_score()
        coarse = await _coarse_scan()
        deep = await asyncio.gather(*(_deep_scan(item) for item in coarse), return_exceptions=True)
        opportunities = [item for item in deep if isinstance(item, dict)]
        opportunities.sort(
            key=lambda item: (
                item.get("state") == "BUY",
                item.get("state") == "WATCHING",
                _f(item.get("rank_score")),
            ),
            reverse=True,
        )
        opportunities = opportunities[:MAX_DISPLAY_OPPORTUNITIES]
        latest_opportunities = {f"{item['exchange']}:{item['symbol']}": item for item in opportunities}
        last_scan_at = _now().isoformat()
        last_scan_error = None

        buy_items = [item for item in opportunities if item.get("state") == "BUY"]
        new_alerts = [item for item in buy_items if item["recommendation_id"] not in alerted_signal_ids]
        for item in new_alerts:
            alerted_signal_ids.add(item["recommendation_id"])

        await broadcast(
            {
                "type": "opportunities",
                "items": opportunities,
                "prices": latest_prices,
                "market_regime": latest_market_regime,
                "scan_at": last_scan_at,
                "ts": last_scan_at,
            }
        )
        if new_alerts:
            await broadcast(
                {
                    "type": "buy_alert",
                    "items": new_alerts,
                    "mode": "single" if len(new_alerts) == 1 else "list",
                    "ts": last_scan_at,
                }
            )

        if len(recommendation_cache) > 1000:
            active_ids = {item["recommendation_id"] for item in opportunities}
            for key in list(recommendation_cache):
                if key not in active_ids:
                    recommendation_cache.pop(key, None)
                    if len(recommendation_cache) <= 500:
                        break
        return opportunities
    except Exception as exc:
        last_scan_error = _mask_error(exc)
        await broadcast({"type": "scanner_error", "message": last_scan_error, "ts": _now().isoformat()})
        return []


async def scanner_loop() -> None:
    counter = 0
    while True:
        try:
            if _scanner_status() == "active":
                await scan_market_once()
                counter += 1
                if counter % 4 == 0:
                    await refresh_portfolio()
        finally:
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global background_task
    _ = app
    background_task = asyncio.create_task(scanner_loop())
    yield
    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Suhas Private AI Trader", version="0.8.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8080", "http://localhost:8080"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "broker": "groww",
        "configured": _broker_configured(),
        "connected": _groww is not None,
        "connection_error": _groww_error,
        "trading_profile_enabled": TRADING_PROFILE_ENABLED,
        "live_execution_enabled": GROWW_LIVE_EXECUTION_ENABLED,
        "intraday_only": True,
        "market_open_now": _market_open_now(),
        "scanner_status": _scanner_status(),
        "scanner_universe_size": len(SCANNER_UNIVERSE),
        "scan_interval_seconds": SCAN_INTERVAL_SECONDS,
        "last_scan_at": last_scan_at,
        "last_scan_error": last_scan_error,
        "market_regime": latest_market_regime,
        "rules_contract_version": "1.0.0",
        "groww_sdk_contract": "1.5.x-current-with-legacy-batch-fallback",
    }


@app.get("/api/live/state")
def live_state() -> dict:
    return {
        "recommendations": latest_opportunities,
        "opportunities": list(latest_opportunities.values()),
        "holdings": latest_holdings,
        "positions": latest_positions,
        "prices": latest_prices,
        "news": [],
        "broker_configured": _broker_configured(),
        "market_open_now": _market_open_now(),
        "scanner_status": _scanner_status(),
        "live_execution_enabled": GROWW_LIVE_EXECUTION_ENABLED,
        "market_regime": latest_market_regime,
        "scan_at": last_scan_at,
        "scanner_universe_size": len(SCANNER_UNIVERSE),
    }


@app.get("/api/opportunities")
def opportunities() -> dict:
    return {
        "items": list(latest_opportunities.values()),
        "prices": latest_prices,
        "market_regime": latest_market_regime,
        "scan_at": last_scan_at,
        "scanner_status": _scanner_status(),
    }


@app.post("/api/opportunities/scan-now")
async def scan_now() -> dict:
    if not _broker_configured():
        raise HTTPException(status_code=503, detail="Groww API credentials are not configured. Scanner remains safely paused.")
    if not _market_open_now():
        raise HTTPException(status_code=409, detail="Intraday live scan is paused outside the configured NSE session window.")
    items = await scan_market_once()
    return {
        "items": items,
        "prices": latest_prices,
        "market_regime": latest_market_regime,
        "scan_at": last_scan_at,
    }


@app.post("/api/opportunity")
async def single_opportunity(request: SingleScanRequest) -> dict:
    quote = await _quote(request.symbol.upper().strip(), request.exchange.upper().strip())
    news_score, headlines = _news_context_for_symbol(request.symbol)
    result = build_agentic_opportunity(
        symbol=request.symbol,
        exchange=request.exchange,
        quote=quote,
        portfolio_value=request.portfolio_value,
        market_regime_score=_f(latest_market_regime.get("score"), 50),
        news_score=news_score,
        news_headlines=headlines,
        portfolio_exposure_pct=_portfolio_exposure_pct(request.symbol, _f(quote.get("last_price"))),
        policy=policy,
    )
    result["recommendation_id"] = _signal_identity(result)
    result["live_execution_enabled"] = GROWW_LIVE_EXECUTION_ENABLED
    recommendation_cache[result["recommendation_id"]] = result
    return result


@app.get("/api/groww/holdings")
async def groww_holdings() -> dict:
    try:
        groww = get_groww()
        return await asyncio.to_thread(groww.get_holdings_for_user, timeout=5)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=_mask_error(exc)) from exc


@app.get("/api/groww/positions")
async def groww_positions() -> dict:
    try:
        groww = get_groww()
        return await asyncio.to_thread(groww.get_positions_for_user, segment=groww.SEGMENT_CASH)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=_mask_error(exc)) from exc


def _get_intraday_product(groww: Any) -> Any:
    for name in ("PRODUCT_MIS", "PRODUCT_INTRADAY"):
        if hasattr(groww, name):
            return getattr(groww, name)
    raise RuntimeError("The installed Groww SDK does not expose an intraday MIS product constant.")


@app.post("/api/orders/buy-recommendation")
async def buy_recommendation(request: BuyRecommendationRequest) -> dict:
    if not GROWW_LIVE_EXECUTION_ENABLED:
        raise HTTPException(status_code=403, detail="Live execution is disabled in backend/.env.")
    if not _market_open_now():
        raise HTTPException(status_code=409, detail="Intraday BUY is blocked outside the configured NSE session window.")

    cached = recommendation_cache.get(request.recommendation_id)
    if not cached:
        raise HTTPException(status_code=404, detail="Recommendation not found or expired.")
    if cached.get("state") != "BUY":
        raise HTTPException(status_code=409, detail="Only an active BUY opportunity can be executed.")

    generated_at = datetime.fromisoformat(cached["generated_at"])
    age = (_now() - generated_at).total_seconds()
    if age > float(cached.get("valid_for_seconds", SIGNAL_VALID_SECONDS)):
        raise HTTPException(status_code=409, detail="Recommendation expired. Wait for a fresh opportunity.")

    fresh = await _deep_scan(
        {
            "symbol": cached["symbol"],
            "exchange": cached["exchange"],
            "coarse_score": cached.get("coarse_score", 0),
        }
    )
    if fresh.get("state") != "BUY":
        raise HTTPException(status_code=409, detail="Market conditions changed; the fresh opportunity is no longer BUY.")
    if _f(fresh.get("confidence")) < policy.min_buy_confidence:
        raise HTTPException(status_code=409, detail="Fresh confidence fell below the BUY threshold.")

    old_entry = _f(cached.get("entry_price"))
    fresh_entry = _f(fresh.get("entry_price"))
    if old_entry <= 0 or fresh_entry > old_entry * (1 + policy.max_chase_pct / 100):
        raise HTTPException(status_code=409, detail="Price moved beyond the anti-chase limit. Order blocked.")

    quantity = int(fresh.get("quantity") or 0)
    if quantity < 1:
        raise HTTPException(status_code=409, detail="Risk-sized quantity is below one share.")

    try:
        groww = get_groww()
        reference_id = f"INTRA-{uuid.uuid4().hex[:12]}"
        result = await asyncio.to_thread(
            groww.place_order,
            trading_symbol=fresh["symbol"],
            quantity=quantity,
            validity=groww.VALIDITY_DAY,
            exchange=_exchange_constant(groww, fresh["exchange"]),
            segment=groww.SEGMENT_CASH,
            product=_get_intraday_product(groww),
            order_type=groww.ORDER_TYPE_LIMIT,
            transaction_type=groww.TRANSACTION_TYPE_BUY,
            price=fresh_entry,
            order_reference_id=reference_id,
        )
        await broadcast(
            {
                "type": "order",
                "data": result,
                "recommendation": fresh,
                "ts": _now().isoformat(),
            }
        )
        return {
            "submitted": True,
            "broker": "groww",
            "intraday": True,
            "order": result,
            "executed_recommendation": fresh,
            "protective_levels": {
                "target_price": fresh["target_price"],
                "stop_loss": fresh["stop_loss"],
                "note": "Protective target/stop monitoring is displayed, but linked exit-order automation is not enabled yet.",
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_mask_error(exc)) from exc


@app.websocket("/ws/live")
async def live_websocket(socket: WebSocket):
    await socket.accept()
    connected_sockets.add(socket)
    try:
        await socket.send_json(
            {
                "type": "snapshot",
                "recommendations": latest_opportunities,
                "opportunities": list(latest_opportunities.values()),
                "holdings": latest_holdings,
                "positions": latest_positions,
                "prices": latest_prices,
                "broker_configured": _broker_configured(),
                "market_open_now": _market_open_now(),
                "scanner_status": _scanner_status(),
                "live_execution_enabled": GROWW_LIVE_EXECUTION_ENABLED,
                "market_regime": latest_market_regime,
                "scan_at": last_scan_at,
                "ts": _now().isoformat(),
            }
        )
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        connected_sockets.discard(socket)
