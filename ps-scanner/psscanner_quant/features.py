from __future__ import annotations

import math
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


def _safe(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([
        (df["high"] - df["low"]).abs(),
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    a = atr(df, period).replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1/period, adjust=False).mean() / a
    minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False).mean() / a
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/period, adjust=False).mean().fillna(0.0)


def enrich(df: pd.DataFrame, benchmark: Optional[pd.Series] = None) -> pd.DataFrame:
    if df is None or len(df) < 5:
        return pd.DataFrame()
    x = df.copy()
    for c in ("open", "high", "low", "close", "volume"):
        x[c] = pd.to_numeric(x[c], errors="coerce")
    # Horizon histories may have a missing daily open while H/L/C/V remain valid.
    # Preserve those rows for return/trend/ATR calculations. Open-dependent features
    # are masked below rather than fabricated.
    x = x.dropna(subset=["high", "low", "close"])
    open_ok = x["open"].notna()
    x["open_observed"] = open_ok.astype(int)
    if "volume" not in x:
        x["volume"] = 0.0
    close = x["close"]
    x["ret1"] = close.pct_change() * 100
    for n in (3, 5, 10, 20, 60):
        x[f"ret{n}"] = close.pct_change(n) * 100
    for n in (5, 10, 20, 50, 100, 200):
        x[f"sma{n}"] = close.rolling(n, min_periods=max(3, n//3)).mean()
    x["ema12"] = close.ewm(span=12, adjust=False).mean()
    x["ema26"] = close.ewm(span=26, adjust=False).mean()
    x["macd"] = x["ema12"] - x["ema26"]
    x["macd_signal"] = x["macd"].ewm(span=9, adjust=False).mean()
    x["rsi14"] = rsi(close, 14)
    x["atr14"] = atr(x, 14)
    x["atr_pct"] = (x["atr14"] / close.replace(0, np.nan)) * 100
    x["adx14"] = adx(x, 14)
    x["vol20"] = x["volume"].rolling(20, min_periods=5).mean()
    x["volume_ratio"] = x["volume"] / x["vol20"].replace(0, np.nan)

    # Accumulation/distribution features. These measure price/volume behavior only; they
    # never claim the identity of the buyer/seller. Direct institutional disclosures are
    # joined separately by institutional_intelligence.py.
    direction=np.sign(close.diff()).fillna(0.0)
    x["obv"]=(direction*x["volume"].fillna(0.0)).cumsum()
    obv_denom=x["volume"].abs().rolling(5,min_periods=2).sum().replace(0,np.nan)
    x["obv_trend5"]=(x["obv"]-x["obv"].shift(5))/obv_denom
    typical=(x["high"]+x["low"]+x["close"])/3.0
    raw_flow=typical*x["volume"].fillna(0.0)
    tdir=typical.diff()
    pos_flow=raw_flow.where(tdir>0,0.0).rolling(14,min_periods=5).sum()
    neg_flow=raw_flow.where(tdir<0,0.0).rolling(14,min_periods=5).sum().abs()
    money_ratio=pos_flow/neg_flow.replace(0,np.nan)
    x["mfi14"]=(100.0-(100.0/(1.0+money_ratio))).fillna(50.0)
    mf_multiplier=((x["close"]-x["low"])-(x["high"]-x["close"]))/(x["high"]-x["low"]).replace(0,np.nan)
    mf_volume=mf_multiplier*x["volume"].fillna(0.0)
    x["cmf20"]=mf_volume.rolling(20,min_periods=5).sum()/x["volume"].rolling(20,min_periods=5).sum().replace(0,np.nan)

    x["std20"] = close.rolling(20, min_periods=8).std()
    x["z20"] = (close - x["sma20"]) / x["std20"].replace(0, np.nan)
    x["high20"] = x["high"].rolling(20, min_periods=5).max()
    x["low20"] = x["low"].rolling(20, min_periods=5).min()
    x["high55"] = x["high"].rolling(55, min_periods=15).max()
    x["low55"] = x["low"].rolling(55, min_periods=15).min()
    x["range20_pos"] = (close - x["low20"]) / (x["high20"] - x["low20"]).replace(0, np.nan)
    x["gap_pct"] = ((x["open"] / close.shift(1).replace(0, np.nan) - 1) * 100).where(open_ok)
    body = (x["close"] - x["open"]).abs().where(open_ok)
    full = (x["high"] - x["low"]).replace(0, np.nan)
    x["body_frac"] = (body / full).where(open_ok)
    upper = (x["high"] - x[["open", "close"]].max(axis=1)) / full
    lower = (x[["open", "close"]].min(axis=1) - x["low"]) / full
    x["upper_wick_frac"] = upper.where(open_ok)
    x["lower_wick_frac"] = lower.where(open_ok)
    prev_open = x["open"].shift(1)
    prev_close = x["close"].shift(1)
    prev_open_ok = open_ok.shift(1, fill_value=False)
    x["bull_engulf"] = (open_ok & prev_open_ok & (x["close"] > x["open"]) & (prev_close < prev_open) & (x["close"] >= prev_open) & (x["open"] <= prev_close)).astype(int)
    x["bear_engulf"] = (open_ok & prev_open_ok & (x["close"] < x["open"]) & (prev_close > prev_open) & (x["open"] >= prev_close) & (x["close"] <= prev_open)).astype(int)
    x["inside_bar"] = ((x["high"] < x["high"].shift(1)) & (x["low"] > x["low"].shift(1))).astype(int)
    x["trend"] = np.select(
        [
            (close > x["sma20"]) & (x["sma20"] > x["sma50"]),
            (close < x["sma20"]) & (x["sma20"] < x["sma50"]),
        ], [1, -1], default=0,
    )
    x["turnover"] = close * x["volume"]
    x["turnover20"] = x["turnover"].rolling(20, min_periods=5).mean()
    # Intraday VWAP and opening-range features are computed session-by-session.
    # Daily bars deliberately leave these as NaN rather than inventing intraday context.
    x["vwap"] = np.nan
    x["opening_range_high"] = np.nan
    x["opening_range_low"] = np.nan
    x["opening_range_position"] = np.nan
    try:
        if isinstance(x.index, pd.DatetimeIndex) and len(x) >= 3:
            diffs = x.index.to_series().diff().dropna().dt.total_seconds()
            intraday = bool(len(diffs) and float(diffs.median()) < 20 * 3600)
            if intraday:
                daykey = pd.Series(x.index.date, index=x.index)
                pv = ((x["high"] + x["low"] + x["close"]) / 3.0) * x["volume"]
                cum_pv = pv.groupby(daykey).cumsum()
                cum_vol = x["volume"].groupby(daykey).cumsum().replace(0, np.nan)
                x["vwap"] = cum_pv / cum_vol
                for _, idxs in daykey.groupby(daykey).groups.items():
                    loc = list(idxs)
                    first = x.loc[loc[:3]]
                    if first.empty:
                        continue
                    oh = float(first["high"].max()); ol = float(first["low"].min())
                    x.loc[loc, "opening_range_high"] = oh
                    x.loc[loc, "opening_range_low"] = ol
                    denom = max(1e-12, oh-ol)
                    x.loc[loc, "opening_range_position"] = (x.loc[loc, "close"] - ol) / denom
    except Exception:
        pass
    if benchmark is not None and len(benchmark):
        b = benchmark.reindex(x.index).ffill()
        x["benchmark_ret20"] = b.pct_change(20) * 100
        x["relative_strength20"] = x["ret20"] - x["benchmark_ret20"]
    else:
        x["relative_strength20"] = 0.0
    return x.replace([np.inf, -np.inf], np.nan)


def latest_features(df: pd.DataFrame, fundamentals: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    x = enrich(df)
    if x.empty:
        return {}
    r = x.iloc[-1]
    keys = [
        "open","high","low","close","volume","ret1","ret3","ret5","ret10","ret20","ret60",
        "sma5","sma10","sma20","sma50","sma100","sma200","macd","macd_signal","rsi14","atr14","atr_pct","adx14",
        "volume_ratio","z20","high20","low20","high55","low55","range20_pos","gap_pct","body_frac","upper_wick_frac",
        "lower_wick_frac","bull_engulf","bear_engulf","inside_bar","trend","turnover20","relative_strength20",
        "vwap","opening_range_high","opening_range_low","opening_range_position",
        "obv","obv_trend5","mfi14","cmf20",
    ]
    out = {k: _safe(r.get(k), 0.0) for k in keys}
    out["open_observed"] = bool(pd.notna(r.get("open")))
    out["open_coverage_pct"] = round(100.0 * float(pd.to_numeric(x["open"], errors="coerce").notna().mean()), 2) if len(x) else 0.0
    out["asof"] = str(x.index[-1])
    if fundamentals:
        out["fundamentals"] = fundamentals
    return out
