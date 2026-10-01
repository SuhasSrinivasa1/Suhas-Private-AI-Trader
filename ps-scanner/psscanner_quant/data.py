from __future__ import annotations

import csv
import io
import json
import os
import re
import time
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests

from .broker import broker
from .config import load_settings
from .constants import GROWW_INSTRUMENT_CSV, IST, NIFTY500_CSV
from .db import db, get_state, health, now_iso, set_state
from .paths import DATA, INSTRUMENTS_PATH, UNIVERSE_PATH
from .history_control import wait_for_slot, record_rate_limit, record_success, quarantine_status, quarantine, clear_quarantine

_CACHE = DATA / "history"
_CACHE.mkdir(parents=True, exist_ok=True)
_LOCK = RLock()
_INSTRUMENT_ROWS_CACHE = []
_INSTRUMENT_INDEX = {}
_INSTRUMENT_MTIME = 0.0
_LIQUIDITY_RANK_CACHE = {"at": 0.0, "symbols": []}
_LIQUIDITY_RANK_LOCK = RLock()
_LTP_CACHE = {"prices": {}, "updated": {}}
_LTP_LOCK = RLock()

GLOBAL_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","BRK-B","JPM","V","MA","LLY","WMT","ORCL","NFLX","COST","XOM","JNJ","PG",
    "HD","BAC","KO","PEP","CRM","AMD","ADBE","CSCO","MCD","DIS","INTC","QCOM","TXN","AMGN","IBM","GE","CAT","BA","GS","MS","UBER","SHOP",
    "ASML","TSM","NVO","SAP","SONY","TM","BABA","PDD","JD","MELI","RIO","BHP","SHEL","BP","AZN","GSK","NVS","UBS","HSBC","UL","DEO",
]

# U.S.-listed liquid ETFs added to the weekly low-turnover opportunity set.
US_WEEKLY_ETFS = [
    "SPY","QQQ","IWM","DIA","XLK","SOXX","SMH","XLF","KBE","XLE","XLV","XLI","XLY","XLP","XLB","GLD","SLV","TLT",
]
US_WEEKLY_UNIVERSE = list(dict.fromkeys(GLOBAL_UNIVERSE + US_WEEKLY_ETFS))

# NSE equity-share series, grounded in NSE's Legend of Series.  Groww's CASH
# instrument_type=EQ is not sufficient by itself: the master also carries debt /
# government / other securities under CASH with N*, Y*, Z*, A*, B*, GB, GS, SG, etc.
# The research universe therefore uses the exchange series to identify actual shares.
NSE_FULLY_PAID_EQUITY_SERIES = {"EQ", "BE", "BZ", "SM", "ST", "SZ"}
NSE_EQUITY_TYPES = {"EQ", "STOCK", "EQUITY"}
_PARTLY_PAID_EQUITY_SERIES = re.compile(r"^[EX][1-9A-Z]$")

def _is_equity_share_series(series: Any) -> bool:
    s=str(series or "").strip().upper()
    return s in NSE_FULLY_PAID_EQUITY_SERIES or bool(_PARTLY_PAID_EQUITY_SERIES.fullmatch(s))

def _looks_like_etf_row(r: Dict[str, Any]) -> bool:
    # ETF has its own book in PS Scanner.  Keep it out of the stock universe even when
    # Groww represents the fund with instrument_type=EQ / series=EQ.
    sym=str(r.get("trading_symbol") or "").upper()
    name=str(r.get("name") or "").upper()
    typ=str(r.get("instrument_type") or "").upper()
    return typ=="ETF" or " ETF" in (" "+name) or sym.endswith("ETF") or "BEES" in sym or "IETF" in sym

def _looks_like_rights_entitlement(r: Dict[str, Any]) -> bool:
    sym=str(r.get("trading_symbol") or "").upper()
    name=str(r.get("name") or "").upper()
    return "RIGHTS ENTITLEMENT" in name or sym.endswith("-RE") or sym.endswith("_RE")

def _is_nse_cash_equity_row(r: Dict[str, Any]) -> bool:
    if str(r.get("exchange") or "").upper() != "NSE": return False
    if str(r.get("segment") or "").upper() != "CASH": return False
    if str(r.get("instrument_type") or "").upper() not in NSE_EQUITY_TYPES: return False
    if not _is_equity_share_series(r.get("series")): return False
    if _looks_like_etf_row(r) or _looks_like_rights_entitlement(r): return False
    return bool(str(r.get("trading_symbol") or "").strip())

def _truthy(v: Any) -> bool:
    return str(v or "").strip().lower() in ("1","true","yes","y")


def _atomic_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    os.replace(tmp, path)


def refresh_instruments(force: bool = False) -> Dict[str, Any]:
    if INSTRUMENTS_PATH.exists() and not force and time.time() - INSTRUMENTS_PATH.stat().st_mtime < 12 * 3600:
        return instrument_summary()
    r = requests.get(GROWW_INSTRUMENT_CSV, timeout=30)
    r.raise_for_status()
    INSTRUMENTS_PATH.write_bytes(r.content)
    return instrument_summary()


def instrument_rows() -> List[Dict[str, str]]:
    global _INSTRUMENT_ROWS_CACHE, _INSTRUMENT_INDEX, _INSTRUMENT_MTIME
    if not INSTRUMENTS_PATH.exists():
        refresh_instruments()
    mtime=INSTRUMENTS_PATH.stat().st_mtime if INSTRUMENTS_PATH.exists() else 0.0
    with _LOCK:
        if _INSTRUMENT_ROWS_CACHE and _INSTRUMENT_MTIME==mtime:
            return _INSTRUMENT_ROWS_CACHE
        out=[];idx={}
        with INSTRUMENTS_PATH.open(newline="", errors="ignore") as f:
            for row in csv.DictReader(f):
                d={str(k): str(v or "") for k,v in row.items()};out.append(d)
                if d.get("exchange")=="NSE" and d.get("segment")=="CASH" and d.get("trading_symbol"):
                    idx[d["trading_symbol"].upper()]=d
        _INSTRUMENT_ROWS_CACHE=out;_INSTRUMENT_INDEX=idx;_INSTRUMENT_MTIME=mtime
        return _INSTRUMENT_ROWS_CACHE


def instrument_summary() -> Dict[str, Any]:
    try:
        rows=instrument_rows() if INSTRUMENTS_PATH.exists() else []
        cash=[r for r in rows if r.get("segment")=="CASH"];equities=[r for r in rows if _is_nse_cash_equity_row(r)]
        return {"rows":len(rows),"cash":len(cash),"nse_cash_equities":len(equities),"updated_at":datetime.fromtimestamp(INSTRUMENTS_PATH.stat().st_mtime,IST).isoformat(timespec="seconds") if INSTRUMENTS_PATH.exists() else None}
    except Exception as exc:
        return {"rows":0,"cash":0,"error":str(exc)[:180]}


def _nifty500_constituents() -> List[Dict[str,str]]:
    r=requests.get(NIFTY500_CSV,timeout=20,headers={"User-Agent":"Mozilla/5.0"})
    r.raise_for_status()
    text=r.content.decode("utf-8-sig",errors="ignore")
    reader=csv.DictReader(io.StringIO(text))
    out=[]
    for row in reader:
        sym=(row.get("Symbol") or row.get("SYMBOL") or "").strip().upper()
        if not sym:continue
        out.append({
            "symbol":sym,
            "company":(row.get("Company Name") or row.get("Company_Name") or row.get("Company") or "").strip(),
            "industry":(row.get("Industry") or row.get("INDUSTRY") or row.get("Sector") or "UNKNOWN").strip() or "UNKNOWN",
        })
    return out

def _nifty500_symbols() -> List[str]:
    return [x["symbol"] for x in _nifty500_constituents()]


def refresh_universe(force: bool = False) -> Dict[str, Any]:
    """Build the full NSE cash-equity research universe from Groww's instrument master.

    v6.4.2 keeps full breadth and hardens the security-type boundary: research scans
    every NSE equity share series (main board, trade-for-trade, SME and partly-paid equity)
    while excluding debt, government securities, mutual funds, REIT/InvIT, warrants,
    preference shares and ETFs from the stock universe. ETF research remains separate.
    """
    ttl=30*60
    if UNIVERSE_PATH.exists() and not force and time.time()-UNIVERSE_PATH.stat().st_mtime<ttl:
        try:
            d=json.loads(UNIVERSE_PATH.read_text())
            if d.get("source") in ("GROWW_NSE_EQUITY_SHARE_MASTER_V642",): return d
        except Exception: pass
    rows=instrument_rows()
    previous={}
    if UNIVERSE_PATH.exists():
        try: previous=json.loads(UNIVERSE_PATH.read_text())
        except Exception: previous={}
    prev_symbols={str(x.get("symbol") or "").upper() for x in (previous.get("symbols") or []) if x.get("symbol")}

    # Industry metadata is enrichment only; failure never narrows the universe.
    meta={}
    try:
        meta={x["symbol"]:x for x in _nifty500_constituents()}
    except Exception as exc:
        health("universe_industry","WARN",f"NIFTY500 industry enrichment unavailable: {exc}")

    # One research row per trading symbol. Prefer the most executable/main-board row if
    # duplicate symbols ever coexist during an exchange series migration.
    priority={"EQ":6,"BE":5,"BZ":4,"SM":3,"ST":2,"SZ":1,"":0}
    by_symbol={}
    for r in rows:
        if not _is_nse_cash_equity_row(r): continue
        sym=str(r.get("trading_symbol") or "").strip().upper()
        cur=by_symbol.get(sym)
        score=(1 if _truthy(r.get("buy_allowed")) else 0, 1 if _truthy(r.get("sell_allowed")) else 0, priority.get(str(r.get("series") or "").upper(),-1))
        if cur is None:
            by_symbol[sym]=(score,r)
        elif score>cur[0]:
            by_symbol[sym]=(score,r)

    universe=[];series_counts={};restricted=0
    excluded_series_counts={}
    for r in rows:
        if str(r.get("exchange") or "").upper()!="NSE" or str(r.get("segment") or "").upper()!="CASH":
            continue
        if str(r.get("instrument_type") or "").upper() not in NSE_EQUITY_TYPES:
            continue
        if _is_nse_cash_equity_row(r):
            continue
        series=str(r.get("series") or "").upper() or "BLANK"
        excluded_series_counts[series]=excluded_series_counts.get(series,0)+1
    for s in sorted(by_symbol):
        r=by_symbol[s][1];m=meta.get(s,{})
        series=str(r.get("series") or "").upper()
        series_counts[series or "BLANK"]=series_counts.get(series or "BLANK",0)+1
        buy=_truthy(r.get("buy_allowed"));sell=_truthy(r.get("sell_allowed"));intra=_truthy(r.get("is_intraday"))
        if not (buy and sell): restricted+=1
        universe.append({
            "symbol":s,"exchange":"NSE","groww_symbol":r.get("groww_symbol") or f"NSE-{s}","isin":r.get("isin"),
            "name":m.get("company") or r.get("name") or s,"industry":m.get("industry") or "UNKNOWN",
            "tick_size":float(r.get("tick_size") or 0.05),"buy_allowed":buy,"sell_allowed":sell,"is_intraday":intra,
            "instrument_type":str(r.get("instrument_type") or "EQ").upper(),"series":series,
            "is_sme":series in ("SM","ST","SZ"),"research_eligible":True,
        })
    current={x["symbol"] for x in universe}
    new_symbols=sorted(current-prev_symbols) if prev_symbols else []
    payload={
        "source":"GROWW_NSE_EQUITY_SHARE_MASTER_V642","generated_at":now_iso(),"n":len(universe),
        "series_counts":series_counts,"excluded_non_share_series_counts":excluded_series_counts,
        "execution_restricted":restricted,"new_since_last_refresh":new_symbols[:200],
        "new_since_last_refresh_count":len(new_symbols),"symbols":universe,
        "equity_series_policy":"NSE_FULLY_PAID_EQ_BE_BZ_SM_ST_SZ_PLUS_PARTLY_PAID_E_OR_X_SERIES",
        "policy":"NO_MARKET_CAP_OR_LIQUIDITY_CAP_ALL_NSE_EQUITY_SHARES_ONLY",
    }
    _atomic_json(UNIVERSE_PATH,payload);set_state("universe",payload)
    set_state("universe_status",{k:v for k,v in payload.items() if k!="symbols"})
    old_breadth=get_state("full_breadth_discovery",{}) or {}
    if previous.get("source")!="GROWW_NSE_EQUITY_SHARE_MASTER_V642" or current!=prev_symbols or int(old_breadth.get("universe") or 0)!=len(universe):
        set_state("full_breadth_discovery",{
            "at":now_iso(),"universe":len(universe),"evaluated":0,"live_prices":0,
            "daily_history_ready":None,"intraday_history_ready":None,
            "new_or_limited_history":None,"status":"STALE_UNIVERSE",
            "policy":"AWAITING_CURRENT_EQUITY_BREADTH_PASS",
        })
    return payload


def universe() -> List[Dict[str, Any]]:
    try:
        d=json.loads(UNIVERSE_PATH.read_text()) if UNIVERSE_PATH.exists() else refresh_universe()
        if d.get("source") != "GROWW_NSE_EQUITY_SHARE_MASTER_V642":
            d=refresh_universe(force=True)
        return list(d.get("symbols") or [])
    except Exception:
        return list(refresh_universe(force=True).get("symbols") or [])


def instrument(symbol: str) -> Optional[Dict[str, Any]]:
    sym=symbol.upper()
    for r in universe():
        if r.get("symbol")==sym:return r
    try:
        instrument_rows()
        r=_INSTRUMENT_INDEX.get(sym)
        if r:
            return {"symbol":sym,"exchange":"NSE","groww_symbol":r.get("groww_symbol") or f"NSE-{sym}","isin":r.get("isin"),"name":r.get("name") or sym,"industry":"UNKNOWN","tick_size":float(r.get("tick_size") or 0.05),"buy_allowed":str(r.get("buy_allowed")).lower() in ("1","true","yes"),"sell_allowed":str(r.get("sell_allowed")).lower() in ("1","true","yes"),"is_intraday":str(r.get("is_intraday")).lower() in ("1","true","yes"),"instrument_type":r.get("instrument_type")}
    except Exception: pass
    return None


def _history_path(symbol: str, interval: str) -> Path:
    safe="".join(c if c.isalnum() or c in "-_" else "_" for c in symbol.upper())
    return _CACHE/f"{safe}.{interval}.json"


def _number(value: Any, default: Optional[float] = None) -> Optional[float]:
    """Parse broker/cache numeric fields without throwing away the whole candle.

    Groww responses are normally numeric, but older caches and SDK/JSON round-trips can
    contain numeric strings (including comma separators). Volume is non-critical for
    price history, so an unparseable volume becomes 0 rather than invalidating OHLC.
    """
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return float(value)
    try:
        if isinstance(value, str):
            value = value.strip().replace(",", "")
            if not value:
                return default
        return float(value)
    except Exception:
        return default


def _coerce_candle_timestamp(value: Any):
    """Accept every timestamp representation seen in Groww/legacy PS caches.

    Current /v1/historical/candles documentation shows ISO-like timestamp strings,
    while older history responses/caches used epoch seconds. Some JSON/SDK paths can
    stringify epochs or expose millisecond epochs. Normalise all of them to IST.
    """
    if value is None:
        raise ValueError("missing candle timestamp")

    # pandas/native datetime objects.
    if isinstance(value, (pd.Timestamp, datetime)):
        ts = pd.Timestamp(value)
    else:
        raw = value
        if isinstance(raw, str):
            raw = raw.strip()
            if not raw:
                raise ValueError("empty candle timestamp")
            # Numeric strings must not be handed to pd.to_datetime directly; pandas
            # interprets/ rejects them differently across versions.
            try:
                if raw.replace(".", "", 1).lstrip("+-").isdigit():
                    raw = float(raw) if "." in raw else int(raw)
            except Exception:
                pass

        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            n = float(raw)
            a = abs(n)
            # YYYYMMDD sometimes appears in exported/legacy daily caches.
            if float(n).is_integer() and 19000101 <= int(a) <= 22001231:
                ts = pd.to_datetime(str(int(n)), format="%Y%m%d")
            else:
                # Epoch magnitude detection: seconds / milliseconds / microseconds / ns.
                if a >= 1e17:
                    unit = "ns"
                elif a >= 1e14:
                    unit = "us"
                elif a >= 1e11:
                    unit = "ms"
                else:
                    unit = "s"
                ts = pd.to_datetime(n, unit=unit, utc=True)
        else:
            # ISO / yyyy-MM-dd HH:mm:ss / timezone-bearing strings.
            ts = pd.to_datetime(raw)

    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("Asia/Kolkata")
    else:
        ts = ts.tz_convert("Asia/Kolkata")
    return ts


def _candle_fields(c: Any) -> Optional[Tuple[Any, Any, Any, Any, Any, Any]]:
    """Return timestamp, OHLCV from list/tuple or legacy dict candle rows."""
    if isinstance(c, (list, tuple)):
        if len(c) < 5:
            return None
        return (c[0], c[1], c[2], c[3], c[4], c[5] if len(c) > 5 else 0)
    if isinstance(c, dict):
        def pick(*names):
            for name in names:
                if name in c and c.get(name) not in (None, ""):
                    return c.get(name)
            return None
        ts = pick("timestamp", "time", "ts", "datetime", "date", "candle_timestamp")
        o = pick("open", "o")
        h = pick("high", "h")
        l = pick("low", "l")
        cl = pick("close", "c")
        v = pick("volume", "v")
        # Daily Groww caches can legitimately contain HLCV rows with a missing open.
        # Keep them for horizon analytics instead of discarding months of valid history.
        # Open-dependent features are masked later and reported as unavailable.
        if ts is None or None in (h, l, cl):
            return None
        return (ts, o, h, l, cl, 0 if v is None else v)
    return None


def _parse_candles(candles: List[List[Any]]) -> pd.DataFrame:
    rows=[]
    for c in candles or []:
        fields = _candle_fields(c)
        if not fields:
            continue
        ts,o,h,l,cl,vol = fields
        try:
            idx = _coerce_candle_timestamp(ts)
            o = _number(o); h = _number(h); l = _number(l); cl = _number(cl)
            # H/L/C are required for trend, returns, ATR, range and target-capacity work.
            # Open is optional because the live Groww daily cache observed in v6.3.5
            # contains long HLCV stretches with open=None. Never invent an open here.
            if None in (h,l,cl):
                continue
            vol = _number(vol, 0.0)
            open_value = float(o) if o is not None else float("nan")
            rows.append((idx,open_value,float(h),float(l),float(cl),float(vol or 0.0)))
        except Exception:
            continue
    if not rows:return pd.DataFrame(columns=["open","high","low","close","volume"])
    df=pd.DataFrame(rows,columns=["ts","open","high","low","close","volume"]).set_index("ts").sort_index()
    return df[~df.index.duplicated(keep="last")]

def _cached_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return _parse_candles(json.loads(path.read_text()).get("candles") or [])
    except Exception:
        return pd.DataFrame()


def _http_status(exc: Exception) -> int:
    try:
        return int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
    except Exception:
        return 0


# Groww Backtesting /v1/historical/candles per-request duration contract.
# We stay below the published ceiling where practical to avoid inclusive-boundary ambiguity.
_HISTORY_MAX_DAYS = {
    "1minute": 30, "2minute": 30, "3minute": 30, "5minute": 30,
    "10minute": 90, "15minute": 90, "30minute": 90,
    "1hour": 180, "4hour": 180, "1day": 180, "1week": 180, "1month": 180,
}


def _history_window_limit_days(interval: str) -> int:
    return int(_HISTORY_MAX_DAYS.get(str(interval).lower(), 30))


def _load_raw_candles(path: Path) -> List[List[Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text())
        return list(raw.get("candles") or []) if isinstance(raw, dict) else []
    except Exception:
        return []


def _candle_epoch_key(c: Any) -> float:
    try:
        fields = _candle_fields(c)
        if not fields:
            return 0.0
        return float(_coerce_candle_timestamp(fields[0]).timestamp())
    except Exception:
        return 0.0


def _merge_candles(*parts: List[List[Any]]) -> List[Any]:
    merged: Dict[str, Any] = {}
    for part in parts:
        for c in part or []:
            fields = _candle_fields(c)
            if not fields:
                continue
            try:
                key = _coerce_candle_timestamp(fields[0]).isoformat()
            except Exception:
                key = str(fields[0])
            merged[key] = dict(c) if isinstance(c, dict) else list(c)
    out = list(merged.values())
    out.sort(key=_candle_epoch_key)
    return out


def _request_history_window(groww_symbol: str, interval: str, start: datetime, end: datetime, max_429: int):
    """Return (candles, status_code, exception) for one broker-safe window."""
    last_exc = None
    for attempt in range(max_429 + 1):
        try:
            wait_for_slot()
            candles = broker.historical(
                groww_symbol,
                start.strftime("%Y-%m-%d %H:%M:%S"),
                end.strftime("%Y-%m-%d %H:%M:%S"),
                interval=interval,
            )
            record_success()
            return list(candles or []), 200, None
        except Exception as exc:
            last_exc = exc
            status = _http_status(exc)
            if status == 429:
                retry_after = None
                try:
                    retry_after = getattr(exc.response, "headers", {}).get("Retry-After")
                except Exception:
                    pass
                delay = record_rate_limit(retry_after)
                health("history_rate_limit", "WARN", f"{groww_symbol} {interval}: HTTP 429; global cooldown {delay:.1f}s")
                if attempt < max_429:
                    continue
            return [], status, last_exc
    return [], _http_status(last_exc) if last_exc else 0, last_exc


def _persist_history(path: Path, symbol: str, interval: str, candles: List[List[Any]]) -> pd.DataFrame:
    _atomic_json(path, {"symbol": symbol, "interval": interval, "fetched_at": now_iso(), "candles": candles})
    return _parse_candles(candles)


def history(symbol: str, interval: str="1day", force: bool=False, allow_network: bool=True) -> pd.DataFrame:
    """Return cached candles first; require instrument metadata only for network refresh.

    v6.2.8 invariant: a cached-only scanner must never lose valid local candles merely
    because broker/universe metadata lookup is unavailable or stale. Cache identity is
    symbol+interval, so local reads happen before instrument() resolution.
    """
    interval = str(interval).lower()
    path = _history_path(symbol, interval)
    settings = load_settings()
    ttl = settings.get("daily_history_ttl_hours", 12) * 3600 if interval == "1day" else settings.get("intraday_history_ttl_minutes", 5) * 60
    if not allow_network:
        return _cached_history(path)
    if path.exists() and not force and time.time() - path.stat().st_mtime < ttl:
        return _cached_history(path)
    meta = instrument(symbol)
    if not meta:
        return _cached_history(path)

    groww_symbol = meta.get("groww_symbol") or f"NSE-{symbol}"
    q = quarantine_status(groww_symbol, interval)
    if q.get("quarantined") and not force:
        return _cached_history(path)

    now = datetime.now(IST)
    max_429 = max(0, int(settings.get("history_429_max_retries", 3)))
    cached_raw = _load_raw_candles(path)
    cached_df = _parse_candles(cached_raw)

    if interval == "1day":
        # Published max for this endpoint is 180 days/request. Use 175-day chunks.
        chunk_days = min(175, max(30, int(settings.get("history_daily_chunk_days", 175))))
        target_days = max(chunk_days, int(settings.get("history_daily_target_days", 350)))
        min_rows = max(200, int(settings.get("history_daily_min_rows", 220)))
        chunks_needed = max(1, (target_days + chunk_days - 1) // chunk_days)
        # If the cache already has enough bars, refresh only the newest chunk and merge it.
        if len(cached_df) >= min_rows and not force:
            chunks_needed = 1

        combined = list(cached_raw)
        any_success = False
        end = now
        for chunk_idx in range(chunks_needed):
            start = end - timedelta(days=chunk_days)
            candles, status, exc = _request_history_window(groww_symbol, interval, start, end, max_429)

            # If the newest full chunk is rejected, try a smaller 90-day window before
            # deciding the symbol itself is invalid. This also helps newly listed names.
            short_window_recovery = False
            if status in (400, 404, 422) and chunk_idx == 0:
                retry_start = end - timedelta(days=min(90, chunk_days))
                candles, status, exc = _request_history_window(groww_symbol, interval, retry_start, end, max_429)
                short_window_recovery = (status == 200)

            if status == 200:
                any_success = True
                combined = _merge_candles(combined, candles)
                clear_quarantine(groww_symbol, interval)
                # A successful shorter-window retry usually means a newly listed or
                # limited-history instrument. Keep the valid recent data and stop rather
                # than probing older ranges that are likely outside its listing history.
                if short_window_recovery:
                    break
                # Once we have enough bars for SMA200/long-horizon features, do not burn
                # more broker capacity during the foreground warm-up.
                if len(_parse_candles(combined)) >= min_rows:
                    break
            elif status in (400, 404, 422):
                if any_success or len(combined) > 0:
                    # Older pre-listing windows can legitimately fail. Keep the valid recent
                    # data and do not quarantine the whole instrument.
                    break
                quarantine(groww_symbol, interval, f"HTTP {status} historical request rejected", status_code=status)
                return _cached_history(path)
            else:
                if exc is not None:
                    health("history", "WARN", f"{symbol} {interval}: {str(exc)[:220]}")
                break
            end = start - timedelta(seconds=1)

        if any_success:
            return _persist_history(path, symbol, interval, combined)
        return _cached_history(path)

    # Intraday/other intervals: never exceed Groww's published per-request window.
    max_days = _history_window_limit_days(interval)
    if interval in ("1minute", "2minute", "3minute", "5minute"):
        intraday_days=max(2,min(max_days,int(settings.get("history_intraday_target_days",5))))
        ranges = [intraday_days, max(1,min(intraday_days,2))]
    elif interval in ("10minute", "15minute", "30minute"):
        ranges = [min(max_days, 60), min(max_days, 15)]
    elif interval in ("1hour", "4hour", "1week", "1month"):
        ranges = [min(max_days, 120), min(max_days, 30)]
    else:
        ranges = [min(max_days, 30), min(max_days, 10)]
    ranges = list(dict.fromkeys(max(1, int(x)) for x in ranges))

    last_exc = None
    for ridx, days in enumerate(ranges):
        start = now - timedelta(days=days)
        candles, status, exc = _request_history_window(groww_symbol, interval, start, now, max_429)
        last_exc = exc
        if status == 200:
            clear_quarantine(groww_symbol, interval)
            return _persist_history(path, symbol, interval, candles)
        if status in (400, 404, 422):
            if ridx < len(ranges) - 1:
                continue
            quarantine(groww_symbol, interval, f"HTTP {status} historical request rejected", status_code=status)
            return _cached_history(path)
        break
    if last_exc is not None:
        health("history", "WARN", f"{symbol} {interval}: {str(last_exc)[:220]}")
    return _cached_history(path)

def live_prices(symbols: Iterable[str], *, allow_network: bool=True, max_age_seconds: float=12.0) -> Dict[str,float]:
    """Shared per-symbol LTP cache that scales to the full NSE equity master.

    Network refresh happens outside the cache lock. A full-NSE refresh can require many
    50-symbol Groww LTP batches; cached-only scanners must remain able to read the previous
    snapshot while that refresh is in flight.
    """
    req=[]
    seen=set()
    for s in symbols:
        u=str(s or '').upper().strip()
        if u and u not in seen:
            seen.add(u);req.append(u)
    if not req:return {}
    now=time.time()
    with _LTP_LOCK:
        cached=dict(_LTP_CACHE.get("prices") or {});updated=dict(_LTP_CACHE.get("updated") or {})
    fresh={s:float(cached[s]) for s in req if s in cached and now-float(updated.get(s) or 0)<=float(max_age_seconds)}
    if len(fresh)==len(req) or not allow_network:return fresh
    need=req if float(max_age_seconds)<=0 else [s for s in req if s not in fresh]
    try:
        # broker.ltp performs the documented 50-symbol batching. Do NOT hold _LTP_LOCK
        # across this network operation; readers keep using the last completed snapshot.
        raw=broker.ltp([f"NSE_{s}" for s in need]);stamp=time.time();received={}
        for k,v in raw.items():
            sym=str(k).split("_",1)[1] if str(k).startswith("NSE_") else str(k)
            if sym in seen:
                try:received[sym]=float(v)
                except Exception:pass
        with _LTP_LOCK:
            merged=dict(_LTP_CACHE.get("prices") or {});merged_updated=dict(_LTP_CACHE.get("updated") or {})
            for sym,v in received.items():
                merged[sym]=v;merged_updated[sym]=stamp
            _LTP_CACHE["prices"]=merged;_LTP_CACHE["updated"]=merged_updated
        ltp_status=dict(getattr(broker,"_last_ltp_status",{}) or {})
        set_state("live_price_cache_status",{
            "at":now_iso(),"cached_symbols":len(merged),"requested":len(req),"network_requested":len(need),"network_received":len(received),
            "fresh_returned":sum(1 for s in req if s in merged and stamp-float(merged_updated.get(s) or 0)<=max(180.0,float(max_age_seconds))),
            "ltp_batches":ltp_status,
            "policy":"PER_SYMBOL_FRESHNESS_FULL_NSE_BATCHED_LTP_PARTIAL_SUCCESS_NETWORK_OUTSIDE_LOCK",
        })
        now2=time.time();ttl=max(float(max_age_seconds),180.0 if float(max_age_seconds)<=0 else float(max_age_seconds))
        return {s:float(merged[s]) for s in req if s in merged and now2-float(merged_updated.get(s) or 0)<=ttl}
    except Exception as exc:
        health("live_data","ERROR",str(exc)[:240])
        return fresh


def cached_live_prices(symbols: Iterable[str], max_age_seconds: float=180.0) -> Dict[str,float]:
    return live_prices(symbols,allow_network=False,max_age_seconds=max_age_seconds)

def refresh_live_price_cache(symbols: Iterable[str]) -> Dict[str,float]:
    return live_prices(symbols,allow_network=True,max_age_seconds=0.0)


def _raw_turnover20(path: Path) -> Optional[float]:
    """Fast turnover proxy without constructing a pandas DataFrame.

    v6.2.5 rebuilt liquidity ranking by parsing every cached daily candle through
    pandas for every worker. On a 400-500 name universe that could cost >2 minutes
    per worker and cause startup contention. Ranking only needs close*volume for the
    most recent 20 valid rows, so read those values directly from the cached JSON.
    """
    try:
        candles=(json.loads(path.read_text()).get("candles") or [])
    except Exception:
        return None
    vals=[]
    for c in reversed(candles):
        if not isinstance(c,(list,tuple)) or len(c)<6:
            continue
        try:
            cl=float(c[4]);vol=float(c[5] or 0)
        except Exception:
            continue
        if cl>0 and vol>=0:
            vals.append(cl*vol)
        if len(vals)>=20:
            break
    if len(vals)<20:
        return None
    return sum(vals)/len(vals)


def full_nse_symbols() -> List[str]:
    return [str(x.get("symbol") or "").upper() for x in universe() if x.get("symbol")]

def universe_status() -> Dict[str,Any]:
    d=get_state("universe_status",{}) or {}
    if not d:
        try:
            u=json.loads(UNIVERSE_PATH.read_text()) if UNIVERSE_PATH.exists() else refresh_universe()
            d={k:v for k,v in u.items() if k!="symbols"}
        except Exception as exc:
            d={"n":0,"error":str(exc)[:180]}
    breadth=get_state("full_breadth_discovery",{}) or {}
    daily_warm=get_state("daily_history_warm_status",{}) or {}
    intra_warm=get_state("last_intraday_history_warm",{}) or {}
    current_n=int(d.get("n") or 0); breadth_n=int(breadth.get("universe") or 0)
    breadth_current=bool(current_n and breadth_n==current_n and breadth.get("status")!="STALE_UNIVERSE")
    if breadth_current:
        daily_ready=breadth.get("daily_history_ready"); intraday_ready=breadth.get("intraday_history_ready")
        live_ready=breadth.get("live_prices"); evaluated=breadth.get("evaluated"); limited=breadth.get("new_or_limited_history")
        breadth_at=breadth.get("at"); breadth_status="CURRENT"
    else:
        daily_ready=((daily_warm.get("coverage") or {}).get("ready")); intraday_ready=intra_warm.get("ready")
        live_ready=None; evaluated=None; limited=None; breadth_at=None; breadth_status="AWAITING_CURRENT_UNIVERSE_PASS"
    ltp_status=get_state("live_price_cache_status",{}) or {}
    return {**d,
        "daily_ready":daily_ready,"intraday_ready":intraday_ready,"live_prices_ready":live_ready,
        "breadth_evaluated":evaluated,"new_or_limited_history":limited,"last_breadth_scan_at":breadth_at,
        "breadth_status":breadth_status,"live_price_refresh":ltp_status,
        "scan_policy":"FULL_BREADTH_DISCOVERY_NO_TOP_N_UNIVERSE_CAP"}

def full_breadth_discovery_snapshot(prices: Optional[Dict[str,float]]=None) -> Dict[str,Any]:
    """Cheap all-market pass over every NSE equity in the instrument master.

    This is intentionally not a top-N selector. Every discovered stock is evaluated for
    price displacement and data readiness; detailed strategy workers then use the richer
    history available for each name. New/limited-history listings remain visible and are
    prioritised for enrichment instead of disappearing from the universe.
    """
    syms=full_nse_symbols();prices=dict(prices or cached_live_prices(syms,max_age_seconds=600))
    evaluated=0;daily_ready=0;intra_ready=0;limited=0;moves=[];missing_price=0
    for sym in syms:
        evaluated+=1
        draw=_load_raw_candles(_history_path(sym,"1day"));iraw=_load_raw_candles(_history_path(sym,"5minute"))
        if len(draw)>=30:daily_ready+=1
        else:limited+=1
        if len(iraw)>=30:intra_ready+=1
        prev=None
        for row in reversed(draw):
            f=_candle_fields(row)
            if not f:continue
            prev=_number(f[4])
            if prev and prev>0:break
        px=prices.get(sym)
        if px is None:missing_price+=1
        elif prev and prev>0:
            mv=(float(px)/prev-1.0)*100;moves.append((mv,sym,len(draw),len(iraw)))
    moves.sort(key=lambda x:abs(x[0]),reverse=True)
    out={"at":now_iso(),"universe":len(syms),"evaluated":evaluated,"live_prices":len(prices),"missing_live_price":missing_price,
         "daily_history_ready":daily_ready,"intraday_history_ready":intra_ready,"new_or_limited_history":limited,
         "top_absolute_movers":[{"symbol":s,"move_pct":round(m,3),"daily_rows":dr,"intraday_rows":ir} for m,s,dr,ir in moves[:50]],
         "positive":sum(1 for m,_,_,_ in moves if m>0),"negative":sum(1 for m,_,_,_ in moves if m<0),
         "universe_source":"GROWW_NSE_EQUITY_SHARE_MASTER_V642","status":"CURRENT",
         "policy":"EVERY_GROWW_NSE_EQUITY_SHARE_EVALUATED_NO_MARKET_CAP_LIQUIDITY_CAP"}
    set_state("full_breadth_discovery",out);return out

def _activity_rank_full_breadth() -> List[str]:
    """Rank every discovered equity by live displacement from its last cached daily close.

    This is a priority queue for intraday-history enrichment only; it is not a research
    universe filter. Symbols without a daily cache are put first so new listings are learned.
    """
    syms=full_nse_symbols();prices=cached_live_prices(syms,max_age_seconds=600)
    scored=[]
    for sym in syms:
        p=_history_path(sym,"1day");raw=_load_raw_candles(p)
        prev=None
        for row in reversed(raw):
            f=_candle_fields(row)
            if not f:continue
            prev=_number(f[4])
            if prev and prev>0:break
        if prev and sym in prices:
            move=abs(float(prices[sym])/prev-1.0)*100
            scored.append((move,sym))
        # No-history names are prioritised explicitly by the warmers. Do not assign
        # them an artificial activity score that crowds out actual live movers.
    scored.sort(reverse=True)
    return [s for _,s in scored]

def liquidity_rank(limit: int=120, force: bool=False) -> List[str]:
    """Return a process-cached liquidity ranking.

    The ranking is refreshed at most once every five minutes and shared by all domain
    workers. The first build uses a direct JSON turnover calculation rather than the
    much slower DataFrame/date parsing path.
    """
    limit=max(1,int(limit))
    ttl=300.0
    now=time.time()
    with _LIQUIDITY_RANK_LOCK:
        cached=list(_LIQUIDITY_RANK_CACHE.get("symbols") or [])
        age=now-float(_LIQUIDITY_RANK_CACHE.get("at") or 0)
        if cached and not force and age<ttl:
            return cached[:limit]
        scored=[]
        for m in universe():
            p=_history_path(m["symbol"],"1day")
            if not p.exists():
                continue
            turn=_raw_turnover20(p)
            if turn is None:
                continue
            scored.append((float(turn),m["symbol"]))
        scored.sort(reverse=True)
        symbols=[sym for _,sym in scored]
        _LIQUIDITY_RANK_CACHE["at"]=now
        _LIQUIDITY_RANK_CACHE["symbols"]=symbols
        set_state("liquidity_rank_status",{
            "at":now_iso(),
            "symbols":len(symbols),
            "ttl_seconds":ttl,
            "method":"FAST_RAW_JSON_TURNOVER20_SHARED_CACHE",
        })
        return symbols[:limit]


def _active_nse_recommendation_symbols() -> List[str]:
    try:
        with db() as con:
            rows=con.execute("""
                SELECT DISTINCT symbol,
                  CASE book WHEN 'INTRADAY' THEN 0 WHEN 'WEEKLY' THEN 1 WHEN 'MONTHLY' THEN 2 WHEN 'CIRCUIT' THEN 3 WHEN 'ETF' THEN 4 ELSE 5 END p
                FROM recommendations
                WHERE state='LIVE' AND exchange='NSE'
                ORDER BY p, updated_at DESC
            """).fetchall()
        return [str(r[0]).upper() for r in rows if r and r[0]]
    except Exception:
        return []


def warm_intraday_history(max_symbols: int=24) -> Dict[str,Any]:
    """Rotate intraday history across full NSE breadth with useful-first hydration."""
    metas=universe(); syms=[str(x.get("symbol") or "").upper() for x in metas if x.get("symbol")]
    if not syms:return {"attempted":0,"ready":0,"cursor":0,"universe":0}
    symset=set(syms); n=max(1,min(int(max_symbols),len(syms)))
    cursor=int(get_state("intraday_history_warm_cursor",0) or 0)%len(syms)
    active=[s for s in _active_nse_recommendation_symbols() if s in symset]
    activity=_activity_rank_full_breadth()[:max(n*6,120)]
    need=[s for s in syms if len(_load_raw_candles(_history_path(s,"5minute")))<30]
    needset=set(need)
    anchor_need=[str(r.get("symbol") or "").upper() for r in metas
                 if str(r.get("industry") or "UNKNOWN").upper()!="UNKNOWN"
                 and str(r.get("symbol") or "").upper() in needset]
    ustate=get_state("universe_status",{}) or {}
    newly=[s for s in (ustate.get("new_since_last_refresh") or []) if s in symset]
    need_cursor=int(get_state("intraday_missing_cursor",0) or 0)%max(1,len(need) or 1)
    need_rot=[need[(need_cursor+i)%len(need)] for i in range(len(need))] if need else []
    rotating=[syms[(cursor+i)%len(syms)] for i in range(min(len(syms),n*4))]
    chosen=[]
    for s in active+newly+activity+anchor_need+need_rot+rotating:
        if s not in chosen:chosen.append(s)
        if len(chosen)>=n:break
    ready=0
    for sym in chosen:
        if len(history(sym,"5minute",allow_network=True))>=30:ready+=1
    set_state("intraday_history_warm_cursor",(cursor+n)%len(syms))
    if need:set_state("intraday_missing_cursor",(need_cursor+max(1,len(chosen)))%len(need))
    out={"attempted":len(chosen),"ready":ready,"cursor":cursor,"universe":len(syms),
         "priority_active":len(active),"priority_new":len(newly),"priority_movers":len(activity),
         "priority_industry_anchors":len(anchor_need),"missing_before":len(need),"at":now_iso(),
         "policy":"FULL_NSE_USEFUL_FIRST_ACTIVE_NEW_MOVERS_INDUSTRY_ANCHORS_THEN_ROTATION"}
    set_state("last_intraday_history_warm",out);return out


def bootstrap_history(max_symbols: int=80) -> Dict[str,Any]:
    syms=[x["symbol"] for x in universe()]
    if not syms:return {"attempted":0,"ready":0,"errors":0,"cursor":0}
    cursor=int(get_state("history_bootstrap_cursor",0) or 0)%len(syms)

    # Priority order: current live/frozen calls -> already-known liquid names -> rotating
    # NIFTY500 background population. This protects market/regime/scanner capacity from
    # low-priority warm-up traffic.
    active=[s for s in _active_nse_recommendation_symbols() if s in set(syms)]
    liquid=liquidity_rank(max(max_symbols*2,40))
    rotating=[syms[(cursor+i)%len(syms)] for i in range(min(len(syms),max_symbols*3))]
    batch=[]
    for s in active+liquid+rotating:
        if s not in batch:
            batch.append(s)
        if len(batch)>=min(max_symbols,len(syms)):
            break
    ok=0;err=0;quarantined=0
    for s in batch:
        meta=instrument(s) or {}; q=quarantine_status(meta.get("groww_symbol") or f"NSE-{s}","1day")
        if q.get("quarantined"):
            quarantined+=1
        df=history(s,"1day")
        if len(df)>=30:ok+=1
        else:err+=1
    set_state("history_bootstrap_cursor",(cursor+max(1,len(rotating[:len(batch)])))%max(1,len(syms)))
    result={"attempted":len(batch),"ready":ok,"errors":err,"quarantined":quarantined,"cursor":cursor,"priority_live":len(active),"priority_liquid":len(liquid)}
    set_state("last_history_bootstrap",result)
    return result



def cached_history_coverage(symbols: Iterable[str], interval: str="1day", minimum_rows: int=30) -> Dict[str,Any]:
    """Local-only cache coverage telemetry used by scanners and diagnostics."""
    interval=str(interval).lower(); minimum_rows=max(1,int(minimum_rows))
    total=0; files=0; ready=0; raw_rows=0; parsed_rows=0; short=[]
    for sym in [str(x).upper() for x in symbols if x]:
        total+=1; p=_history_path(sym,interval)
        if not p.exists():
            rr=0; pr=0
        else:
            files+=1
            raw=_load_raw_candles(p); rr=len(raw)
            # Do not construct thousands of empty DataFrames during a full-universe
            # telemetry pass. Parse only files that actually contain candle rows.
            pr=len(_parse_candles(raw)) if raw else 0
        raw_rows+=rr; parsed_rows+=pr
        if pr>=minimum_rows: ready+=1
        elif len(short)<12:
            shapes={}
            for row in raw[:50]:
                if isinstance(row,dict):
                    shape="dict"
                elif isinstance(row,(list,tuple)) and row:
                    shape=f"list:{type(row[0]).__name__}"
                else:
                    shape=type(row).__name__
                shapes[shape]=shapes.get(shape,0)+1
            short.append({"symbol":sym,"raw_rows":rr,"parsed_rows":pr,"parse_loss":max(0,rr-pr),"raw_shapes":shapes,"file":p.exists()})
    return {"interval":interval,"symbols":total,"files":files,"ready":ready,"minimum_rows":minimum_rows,"raw_rows":raw_rows,"parsed_rows":parsed_rows,"parse_loss":max(0,raw_rows-parsed_rows),"short_samples":short,"parser_policy":"V636_HLCV_VALID_OPEN_OPTIONAL_NO_FABRICATION","at":now_iso()}


def _fast_raw_history_coverage(symbols: Iterable[str], interval: str="1day", minimum_rows: int=30) -> Dict[str,Any]:
    """Cheap hydration telemetry: counts cached raw rows without pandas/full parsing."""
    total=files=ready=0
    for sym in [str(x).upper() for x in symbols if x]:
        total+=1; raw=_load_raw_candles(_history_path(sym,interval))
        if raw: files+=1
        if len(raw)>=minimum_rows: ready+=1
    return {"interval":interval,"symbols":total,"files":files,"ready":ready,"minimum_rows":minimum_rows,
            "mode":"FAST_RAW_CACHE_READINESS","at":now_iso()}


def warm_daily_history(max_symbols: int=24) -> Dict[str,Any]:
    """Populate daily history across every equity, hydrating representative evidence first."""
    metas=universe(); syms=[str(x.get("symbol") or "").upper() for x in metas if x.get("symbol")]
    if not syms:return {"attempted":0,"ready":0,"errors":0,"at":now_iso(),"universe":0}
    symset=set(syms); need=[];rest=[]
    for sym in syms:
        if len(_load_raw_candles(_history_path(sym,"1day")))<30:need.append(sym)
        else:rest.append(sym)
    needset=set(need)
    active=[s for s in _active_nse_recommendation_symbols() if s in symset]
    anchor_need=[str(r.get("symbol") or "").upper() for r in metas
                 if str(r.get("industry") or "UNKNOWN").upper()!="UNKNOWN"
                 and str(r.get("symbol") or "").upper() in needset]
    ustate=get_state("universe_status",{}) or {}
    newly=[s for s in (ustate.get("new_since_last_refresh") or []) if s in symset]
    missing_cursor=int(get_state("daily_missing_cursor",0) or 0)%max(1,len(need) or 1)
    need_rot=[need[(missing_cursor+i)%len(need)] for i in range(len(need))] if need else []
    refresh_cursor=int(get_state("daily_history_warm_cursor",0) or 0)%max(1,len(rest) or 1)
    rotated=[rest[(refresh_cursor+i)%len(rest)] for i in range(len(rest))] if rest else []
    ordered=active+newly+anchor_need+need_rot+rotated;chosen=[]
    for sym in ordered:
        if sym not in chosen:chosen.append(sym)
        if len(chosen)>=max(1,min(int(max_symbols),len(syms))):break
    ready=0;errors=0
    for sym in chosen:
        try:
            if len(history(sym,"1day",allow_network=True))>=30:ready+=1
            else:errors+=1
        except Exception:errors+=1
    if need:set_state("daily_missing_cursor",(missing_cursor+max(1,len(chosen)))%len(need))
    if rest:set_state("daily_history_warm_cursor",(refresh_cursor+max(1,len(chosen)))%len(rest))
    cov=_fast_raw_history_coverage(syms,"1day",30)
    out={"attempted":len(chosen),"ready":ready,"errors":errors,"coverage":cov,"universe":len(syms),
         "missing_before":len(need),"priority_active":len(active),"priority_new":len(newly),
         "priority_industry_anchors":len(anchor_need),"at":now_iso(),
         "policy":"FULL_NSE_DAILY_ACTIVE_NEW_INDUSTRY_ANCHORS_THEN_MISSING_ROTATION"}
    set_state("daily_history_warm_status",out);return out


def international_history(symbol: str, period: str="1y", interval: str="1d") -> pd.DataFrame:
    try:
        import yfinance as yf
        df=yf.download(symbol,period=period,interval=interval,auto_adjust=False,progress=False,threads=False)
        if df is None or df.empty:return pd.DataFrame()
        if isinstance(df.columns,pd.MultiIndex):
            # Single-ticker downloads may still carry a ticker level depending on yfinance version.
            if symbol in df.columns.get_level_values(0):
                df=df[symbol]
            elif symbol in df.columns.get_level_values(-1):
                df=df.xs(symbol,axis=1,level=-1)
        df.columns=[str(c).lower() for c in df.columns]
        keep=[c for c in ("open","high","low","close","volume") if c in df.columns]
        return df[keep].dropna(subset=["close"]).sort_index()
    except Exception as exc:
        health("international_data","WARN",f"{symbol}: {exc}");return pd.DataFrame()


def international_batch_history(symbols: Iterable[str], period: str="5d", interval: str="5m",
                                chunk_size: int=20, timeout_seconds: float=12.0) -> Dict[str,pd.DataFrame]:
    """Fetch International history in hard-bounded subprocess chunks.

    yfinance's own timeout does not always bound DNS/cookie/thread setup. v6.5.1 runs
    each chunk in a short-lived child Python process and kills that process on a hard
    deadline. Successful chunks are retained; timed-out chunks are skipped. No stale
    fallback is introduced and recommendation gates are unchanged.
    """
    syms=list(dict.fromkeys(str(s).upper() for s in symbols if s))
    if not syms:return {}
    size=max(1,min(int(chunk_size or 20),50))
    timeout=max(3.0,min(float(timeout_seconds or 12.0),30.0))
    chunks=[syms[i:i+size] for i in range(0,len(syms),size)]
    # Hard wall-clock budget for the whole call. This is intentionally generous enough
    # for partial success but finite even when Yahoo/yfinance hangs internally.
    total_budget=min(95.0,max(20.0,len(chunks)*(timeout+4.0)))
    deadline=time.monotonic()+total_budget
    out={};timeouts=0;errors=0;completed_chunks=0
    child_code=(
        "import json,sys,yfinance as yf;"
        "b=json.loads(sys.argv[1]);p=sys.argv[2];i=sys.argv[3];t=float(sys.argv[4]);o=sys.argv[5];"
        "d=yf.download(b,period=p,interval=i,auto_adjust=False,progress=False,threads=False,group_by='ticker',timeout=t);"
        "d.to_pickle(o)"
    )
    for off,batch in enumerate(chunks):
        remaining=deadline-time.monotonic()
        if remaining<=2.0:
            break
        tmp=tempfile.NamedTemporaryFile(prefix='psq_yf_',suffix='.pkl',delete=False)
        tmp_path=tmp.name;tmp.close()
        hard_timeout=max(2.0,min(timeout+4.0,remaining))
        try:
            cp=subprocess.run(
                [sys.executable,'-c',child_code,json.dumps(batch),str(period),str(interval),str(timeout),tmp_path],
                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=hard_timeout,check=False,
            )
            if cp.returncode!=0:
                errors+=1
                health('international_data','WARN',f'batch {interval} {off+1} child failed',
                       {'batch_size':len(batch),'returncode':cp.returncode,'stderr':(cp.stderr or '')[-220:]})
                continue
            try:
                df=pd.read_pickle(tmp_path)
            except Exception as exc:
                errors+=1
                health('international_data','WARN',f'batch {interval} {off+1} pickle: {exc}',
                       {'batch_size':len(batch)})
                continue
            completed_chunks+=1
            if df is None or df.empty:
                continue
            if not isinstance(df.columns,pd.MultiIndex):
                d=df.copy();d.columns=[str(c).lower() for c in d.columns]
                keep=[c for c in ('open','high','low','close','volume') if c in d.columns]
                if keep:
                    d=d[keep].dropna(subset=['close']).sort_index()
                    if not d.empty:out[batch[0]]=d
                continue
            lvl0=set(map(str,df.columns.get_level_values(0)))
            lvln=set(map(str,df.columns.get_level_values(-1)))
            for sym in batch:
                try:
                    if sym in lvl0:d=df[sym].copy()
                    elif sym in lvln:d=df.xs(sym,axis=1,level=-1).copy()
                    else:continue
                    d.columns=[str(c).lower() for c in d.columns]
                    keep=[c for c in ('open','high','low','close','volume') if c in d.columns]
                    if keep:
                        d=d[keep].dropna(subset=['close']).sort_index()
                        if not d.empty:out[sym]=d
                except Exception:
                    continue
        except subprocess.TimeoutExpired:
            timeouts+=1
            health('international_data','WARN',f'batch {interval} {off+1}: HARD_TIMEOUT',
                   {'batch_size':len(batch),'hard_timeout_seconds':round(hard_timeout,2)})
        except Exception as exc:
            errors+=1
            health('international_data','WARN',f'batch {interval} {off+1}: {exc}',
                   {'batch_size':len(batch),'hard_timeout_seconds':round(hard_timeout,2)})
        finally:
            try:os.unlink(tmp_path)
            except Exception:pass
    set_state('international_batch_transport',{
        'at':now_iso(),'requested':len(syms),'received':len(out),'interval':interval,'period':period,
        'chunk_size':size,'timeout_seconds':timeout,'hard_budget_seconds':total_budget,
        'chunks_total':len(chunks),'chunks_completed':completed_chunks,'hard_timeouts':timeouts,'errors':errors,
        'elapsed_seconds':round(max(0.0,total_budget-max(0.0,deadline-time.monotonic())),2),
        'policy':'BOUNDED_CHUNK_PARTIAL_SUCCESS_NO_STALE_FALLBACK_HARD_PROCESS_TIMEOUT_V651'
    })
    return out
