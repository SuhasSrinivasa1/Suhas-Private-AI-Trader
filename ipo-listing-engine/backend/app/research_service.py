from __future__ import annotations

import csv
import io
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any

import httpx

from .audit import audit_log
from .services import ExchangeCalendar
from .scheduler import IST

NSE_BASE = "https://www.nseindia.com"
NSE_UPCOMING = "/api/all-upcoming-issues?category=ipo"
NSE_CURRENT = "/api/ipo-current-issue"
NSE_HOLIDAYS = "/api/holiday-master?type=trading"
NSE_FORTHCOMING = "/api/new-listing-today?index=ForthListing"
GROWW_INSTRUMENT_CSV = "https://growwapi-assets.groww.in/instruments/instrument.csv"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
}


def _norm_key(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _flat_keys(raw: dict[str, Any]) -> dict[str, Any]:
    return {_norm_key(k): v for k, v in raw.items()}


def _first(raw: dict[str, Any], *names: str) -> Any:
    flat = _flat_keys(raw)
    for name in names:
        value = flat.get(_norm_key(name))
        if value not in (None, "", [], {}):
            return value
    return None


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    for fmt in (
        "%d-%b-%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    """
    NSE changes response envelopes from time to time. Walk the JSON tree and retain
    dictionary nodes that look like public-issue records rather than binding the engine
    to one undocumented envelope.
    """
    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            flat = _flat_keys(node)
            looks_like_issue = (
                any(_norm_key(k) in flat for k in ("symbol", "tradingSymbol", "issue_symbol"))
                and any(
                    _norm_key(k) in flat
                    for k in (
                        "companyName",
                        "company",
                        "issuerName",
                        "issueStartDate",
                        "issueEndDate",
                        "listingDate",
                        "tentativeListingDate",
                        "dateOfListing",
                    )
                )
            )
            if looks_like_issue:
                out.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)

    unique: dict[str, dict[str, Any]] = {}
    for item in out:
        symbol = str(_first(item, "symbol", "trading_symbol", "issue_symbol") or "").upper().strip()
        if symbol:
            unique[symbol] = item
    return list(unique.values())


def _extract_forthcoming_records(payload: Any) -> list[dict[str, Any]]:
    """
    Parse NSE's Forthcoming Listing endpoint defensively. The endpoint's envelope
    and column spelling have changed historically, so identify rows by exact exchange
    identifiers rather than by a fixed top-level JSON key.
    """
    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            symbol = str(_first(node, "symbol", "tradingSymbol", "securitySymbol") or "").upper().strip()
            listing = _parse_date(
                _first(
                    node,
                    "listingDate",
                    "dateOfListing",
                    "date_of_listing",
                    "date",
                    "listing_date",
                )
            )
            isin = _first(node, "isin", "isinCode")
            if symbol and (listing or isin):
                out.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    unique: dict[str, dict[str, Any]] = {}
    for item in out:
        symbol = str(_first(item, "symbol", "tradingSymbol", "securitySymbol") or "").upper().strip()
        if symbol:
            unique[symbol] = item
    return list(unique.values())


@dataclass(frozen=True)
class ResearchCandidate:
    symbol: str
    company_name: str
    listing_date: str | None
    issue_start_date: str | None
    issue_end_date: str | None
    isin: str | None
    board: str | None
    nse_source: str
    nse_listing_confirmed: bool
    groww_symbol: str | None
    groww_exchange_token: str | None
    groww_series: str | None
    groww_lot_size: int | None
    groww_tick_size: float | None
    buy_allowed: bool
    sell_allowed: bool
    symbol_resolved: bool
    resolution_status: str


class NseOfficialClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=httpx.Timeout(12.0),
            follow_redirects=True,
            headers=_BROWSER_HEADERS,
        )
        self._primed = False
        self.forthcoming_ready = False

    def close(self) -> None:
        self._client.close()

    def _prime(self) -> None:
        if self._primed:
            return
        response = self._client.get(NSE_BASE + "/market-data/all-upcoming-issues-ipo")
        response.raise_for_status()
        self._primed = True

    def json(self, path: str) -> Any:
        self._prime()
        response = self._client.get(NSE_BASE + path)
        if response.status_code in (401, 403):
            self._primed = False
            self._prime()
            response = self._client.get(NSE_BASE + path)
        response.raise_for_status()
        return response.json()

    def issue_records(self) -> list[tuple[dict[str, Any], str]]:
        records: dict[str, tuple[dict[str, Any], str]] = {}
        for path, source in (
            (NSE_UPCOMING, "NSE_UPCOMING_ISSUES"),
            (NSE_CURRENT, "NSE_CURRENT_ISSUES"),
        ):
            payload = self.json(path)
            for item in _extract_records(payload):
                symbol = str(_first(item, "symbol", "trading_symbol", "issue_symbol") or "").upper().strip()
                if symbol:
                    prior = records.get(symbol)
                    merged = dict(prior[0]) if prior else {}
                    merged.update(item)
                    records[symbol] = (merged, source)

        # Final/near-final exchange listing rows override tentative issue metadata for
        # symbol, ISIN, series and listing date. This is the authoritative pre-listing gate.
        try:
            payload = self.json(NSE_FORTHCOMING)
            self.forthcoming_ready = True
            for item in _extract_forthcoming_records(payload):
                symbol = str(
                    _first(item, "symbol", "tradingSymbol", "securitySymbol") or ""
                ).upper().strip()
                if not symbol:
                    continue
                prior = records.get(symbol)
                merged = dict(prior[0]) if prior else {}
                merged.update(item)
                records[symbol] = (merged, "NSE_FORTHCOMING_LISTING")
        except Exception:
            self.forthcoming_ready = False
            # Issue feeds remain useful for research, but final listing confirmation
            # stays false and therefore live execution remains blocked.
            pass

        return list(records.values())

    def trading_holidays(self) -> set[date]:
        payload = self.json(NSE_HOLIDAYS)
        holidays: set[date] = set()

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                raw = _first(node, "tradingDate", "date", "holidayDate")
                parsed = _parse_date(raw)
                if parsed:
                    holidays.add(parsed)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)
        return holidays


class GrowwInstrumentMaster:
    def __init__(self) -> None:
        self._client = httpx.Client(timeout=httpx.Timeout(15.0), follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def records(self) -> list[dict[str, str]]:
        response = self._client.get(GROWW_INSTRUMENT_CSV)
        response.raise_for_status()
        return list(csv.DictReader(io.StringIO(response.text)))

    @staticmethod
    def resolve(
        instruments: list[dict[str, str]],
        *,
        official_symbol: str,
        isin: str | None,
    ) -> dict[str, str] | None:
        symbol = official_symbol.upper().strip()
        nse_cash = [
            row
            for row in instruments
            if str(row.get("exchange") or "").upper() == "NSE"
            and str(row.get("segment") or "").upper() == "CASH"
        ]
        exact: list[dict[str, str]] = []
        if isin:
            exact = [row for row in nse_cash if str(row.get("isin") or "").upper().strip() == isin.upper().strip()]
        if not exact:
            exact = [
                row
                for row in nse_cash
                if str(row.get("trading_symbol") or "").upper().strip() == symbol
            ]
        if len(exact) != 1:
            return None
        row = exact[0]
        # If both identifiers exist they must agree. Never fuzzy-match a company name into live execution.
        if isin and str(row.get("isin") or "").strip() and str(row.get("isin")).upper().strip() != isin.upper().strip():
            return None
        if str(row.get("trading_symbol") or "").upper().strip() != symbol:
            return None
        return row


class ResearchPlanStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._path = Path(os.getenv("IPO_SENTINEL_RESEARCH_PLAN_FILE", ".runtime/research-plan.json"))

    def save(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path)

    def load(self) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        with self._lock:
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                return None


class DailyResearchService:
    def __init__(self, calendar: ExchangeCalendar) -> None:
        self.calendar = calendar
        self.store = ResearchPlanStore()
        self._lock = RLock()

    @staticmethod
    def _candidate(item: dict[str, Any], source: str) -> dict[str, Any]:
        symbol = str(_first(item, "symbol", "trading_symbol", "issue_symbol") or "").upper().strip()
        company = str(
            _first(item, "companyName", "company", "issuerName", "securityName", "name") or symbol
        ).strip()
        listing = _parse_date(
            _first(
                item,
                "listingDate",
                "dateOfListing",
                "date_of_listing",
                "listing_date",
                "tentativeListingDate",
                "date",
            )
        )
        start = _parse_date(_first(item, "issueStartDate", "startDate", "openDate", "issueOpenDate"))
        end = _parse_date(_first(item, "issueEndDate", "endDate", "closeDate", "issueCloseDate"))
        isin_raw = _first(item, "isin", "isinCode")
        board_raw = _first(item, "series", "board", "category", "issueType")
        return {
            "symbol": symbol,
            "company_name": company,
            "listing_date": listing,
            "issue_start_date": start,
            "issue_end_date": end,
            "isin": str(isin_raw).upper().strip() if isin_raw else None,
            "board": str(board_raw).strip() if board_raw else None,
            "nse_source": source,
        }

    def refresh(self, *, trigger: str = "scheduled") -> dict[str, Any]:
        now = datetime.now(IST)
        with self._lock:
            nse = NseOfficialClient()
            groww_master = GrowwInstrumentMaster()
            errors: list[str] = []
            try:
                try:
                    holidays = nse.trading_holidays()
                    self.calendar.holidays = holidays
                    self.calendar.source_ready = True
                except Exception as exc:
                    errors.append("NSE_HOLIDAY_SOURCE:" + exc.__class__.__name__)
                    self.calendar.source_ready = False

                raw_issues: list[tuple[dict[str, Any], str]] = []
                try:
                    raw_issues = nse.issue_records()
                    if not nse.forthcoming_ready:
                        errors.append("NSE_FORTHCOMING_LISTING:UNAVAILABLE")
                except Exception as exc:
                    errors.append("NSE_ISSUE_SOURCE:" + exc.__class__.__name__)

                instruments: list[dict[str, str]] = []
                try:
                    instruments = groww_master.records()
                except Exception as exc:
                    errors.append("GROWW_INSTRUMENT_MASTER:" + exc.__class__.__name__)

                normalized = [
                    self._candidate(item, source)
                    for item, source in raw_issues
                ]
                normalized = [item for item in normalized if item["symbol"]]

                next_trading_day = (
                    self.calendar.next_trading_day(now.date())
                    if self.calendar.source_ready
                    else None
                )
                week_end = (next_trading_day + timedelta(days=6)) if next_trading_day else None

                candidates: list[ResearchCandidate] = []
                for item in normalized:
                    row = None
                    if instruments:
                        row = GrowwInstrumentMaster.resolve(
                            instruments,
                            official_symbol=item["symbol"],
                            isin=item["isin"],
                        )

                    buy_allowed = str((row or {}).get("buy_allowed") or "").strip() in {"1", "true", "True"}
                    sell_allowed = str((row or {}).get("sell_allowed") or "").strip() in {"1", "true", "True"}
                    final_listing_confirmed = item["nse_source"] == "NSE_FORTHCOMING_LISTING"
                    groww_resolved = row is not None
                    resolved = final_listing_confirmed and groww_resolved

                    if item["listing_date"] is None:
                        status = "WAIT_OFFICIAL_LISTING_DATE"
                    elif not final_listing_confirmed:
                        status = "WAIT_NSE_LISTING_CONFIRMATION"
                    elif not groww_resolved:
                        status = "WAIT_GROWW_INSTRUMENT"
                    else:
                        status = "RESOLVED"

                    candidates.append(
                        ResearchCandidate(
                            symbol=item["symbol"],
                            company_name=item["company_name"],
                            listing_date=item["listing_date"].isoformat() if item["listing_date"] else None,
                            issue_start_date=item["issue_start_date"].isoformat() if item["issue_start_date"] else None,
                            issue_end_date=item["issue_end_date"].isoformat() if item["issue_end_date"] else None,
                            isin=item["isin"],
                            board=item["board"],
                            nse_source=item["nse_source"],
                            nse_listing_confirmed=final_listing_confirmed,
                            groww_symbol=str((row or {}).get("groww_symbol") or "").strip() or None,
                            groww_exchange_token=str((row or {}).get("exchange_token") or "").strip() or None,
                            groww_series=str((row or {}).get("series") or "").strip() or None,
                            groww_lot_size=(
                                int(float((row or {}).get("lot_size") or 0))
                                if str((row or {}).get("lot_size") or "").strip()
                                else None
                            ),
                            groww_tick_size=(
                                float((row or {}).get("tick_size"))
                                if str((row or {}).get("tick_size") or "").strip()
                                else None
                            ),
                            buy_allowed=buy_allowed,
                            sell_allowed=sell_allowed,
                            symbol_resolved=resolved,
                            resolution_status=status,
                        )
                    )

                next_candidates = [
                    c for c in candidates
                    if next_trading_day and c.listing_date == next_trading_day.isoformat()
                ]
                week_candidates = [
                    c for c in candidates
                    if (
                        next_trading_day
                        and week_end
                        and c.listing_date
                        and next_trading_day <= date.fromisoformat(c.listing_date) <= week_end
                    )
                ]

                payload = {
                    "generated_at": now.isoformat(),
                    "trigger": trigger,
                    "source_ready": not any(err.startswith("NSE_ISSUE_SOURCE") for err in errors),
                    "calendar_ready": self.calendar.source_ready,
                    "next_trading_day": next_trading_day.isoformat() if next_trading_day else None,
                    "next_trading_day_candidates": [asdict(c) for c in next_candidates],
                    "week_candidates": [asdict(c) for c in sorted(week_candidates, key=lambda c: (c.listing_date or "", c.symbol))],
                    "all_known_candidates": [asdict(c) for c in candidates],
                    "errors": errors,
                    "trade_gate": {
                        "special_preopen_order_entry": "09:00-09:45 IST; limit orders only",
                        "special_preopen_matching": "09:45-09:55 IST",
                        "buffer": "09:55-10:00 IST",
                        "continuous_market": "from 10:00 IST, subject to live exchange/broker confirmation",
                        "auto_execution_rule": (
                            "No order until official NSE symbol/date and Groww instrument resolve exactly; "
                            "listing-day live quote/depth must also be available."
                        ),
                    },
                }
                self.store.save(payload)
                audit_log.append(
                    "DAILY_IPO_RESEARCH_REFRESH",
                    trigger=trigger,
                    next_trading_day=payload["next_trading_day"],
                    next_candidate_count=len(next_candidates),
                    week_candidate_count=len(week_candidates),
                    errors=errors,
                )
                return payload
            finally:
                nse.close()
                groww_master.close()


research_service: DailyResearchService | None = None


def bind_research_service(calendar: ExchangeCalendar) -> DailyResearchService:
    global research_service
    research_service = DailyResearchService(calendar)
    return research_service
