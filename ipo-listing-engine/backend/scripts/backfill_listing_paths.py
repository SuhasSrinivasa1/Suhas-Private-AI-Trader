from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import fmean
from typing import Any

from app.groww_session import GrowwSession


@dataclass(frozen=True)
class Listing:
    symbol: str
    company_name: str
    listing_date: date
    issue_price: float
    is_sme: bool


def load_listings(path: Path) -> list[Listing]:
    rows: list[Listing] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            rows.append(
                Listing(
                    symbol=str(raw["symbol"]).upper().strip(),
                    company_name=str(raw.get("company_name") or raw["symbol"]).strip(),
                    listing_date=date.fromisoformat(raw["listing_date"]),
                    issue_price=float(raw["issue_price"]),
                    is_sme=str(raw.get("is_sme", "")).strip().lower() in {"1", "true", "yes", "y"},
                )
            )
    return rows


def candles(payload: dict[str, Any]) -> list[list[Any]]:
    source = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    values = source.get("candles", []) if isinstance(source, dict) else []
    return [row for row in values if isinstance(row, list) and len(row) >= 6]


def pct(a: float, b: float) -> float | None:
    return None if b == 0 else (a / b - 1.0) * 100.0


def round_or_none(value: float | None, places: int = 4) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, places)


def analyze(listing: Listing, minute_rows: list[list[Any]], daily_rows: list[list[Any]]) -> dict[str, Any]:
    if not minute_rows:
        return {
            "symbol": listing.symbol,
            "listing_date": listing.listing_date.isoformat(),
            "status": "NO_D0_MINUTE_DATA",
        }

    first = minute_rows[0]
    first_tradable = float(first[1])
    d0_high = max(float(row[2]) for row in minute_rows)
    d0_low = min(float(row[3]) for row in minute_rows)
    d0_close = float(minute_rows[-1][4])
    total_volume = sum(float(row[5]) for row in minute_rows)

    closes = [float(row[4]) for row in daily_rows if len(row) >= 5]
    d5_close = closes[min(5, len(closes) - 1)] if closes else None

    returns = []
    for row in minute_rows:
        close = float(row[4])
        value = pct(close, first_tradable)
        if value is not None:
            returns.append(value)

    return {
        "symbol": listing.symbol,
        "company_name": listing.company_name,
        "listing_date": listing.listing_date.isoformat(),
        "is_sme": listing.is_sme,
        "issue_price": listing.issue_price,
        "first_continuous_price": first_tradable,
        "listing_gain_vs_issue_pct": round_or_none(pct(first_tradable, listing.issue_price)),
        "d0_close": d0_close,
        "d0_open_to_close_pct": round_or_none(pct(d0_close, first_tradable)),
        "d0_mfe_pct": round_or_none(pct(d0_high, first_tradable)),
        "d0_mae_pct": round_or_none(pct(d0_low, first_tradable)),
        "d0_volume": int(total_volume),
        "d5_close": d5_close,
        "d5_return_from_first_continuous_pct": round_or_none(pct(d5_close, first_tradable)) if d5_close else None,
        "mean_1m_close_return_pct": round(fmean(returns), 4) if returns else None,
        "minute_candle_count": len(minute_rows),
        "daily_candle_count": len(daily_rows),
        "status": "OK",
    }


def backfill_one(groww: GrowwSession, listing: Listing) -> dict[str, Any]:
    d0 = listing.listing_date
    minute_payload = groww.historical(
        symbol=listing.symbol,
        start_time=f"{d0.isoformat()} 10:00:00",
        end_time=f"{d0.isoformat()} 15:30:00",
        interval=groww.api.CANDLE_INTERVAL_MIN_1,
    )
    daily_payload = groww.historical(
        symbol=listing.symbol,
        start_time=f"{d0.isoformat()} 00:00:00",
        end_time=f"{(d0 + timedelta(days=14)).isoformat()} 23:59:59",
        interval=groww.api.CANDLE_INTERVAL_DAY,
    )
    return analyze(listing, candles(minute_payload), candles(daily_payload))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill IPO listing-day and first-week paths from Groww.")
    parser.add_argument("--input", type=Path, required=True, help="CSV: symbol,company_name,listing_date,issue_price,is_sme")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    listings = load_listings(args.input)
    groww = GrowwSession.from_totp_env()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", encoding="utf-8") as handle:
        for listing in listings:
            record = backfill_one(groww, listing)
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(json.dumps({"symbol": listing.symbol, "status": record["status"]}))


if __name__ == "__main__":
    main()
