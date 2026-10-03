from __future__ import annotations

import csv
import hashlib
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


def _norm_company(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    for suffix in ("privatelimited", "pvtltd", "limited", "ltd"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _official_issue_id(raw: dict[str, Any]) -> str | None:
    value = _first(
        raw,
        "issueId",
        "issue_id",
        "issueIdentifier",
        "issueCode",
        "offerId",
        "offerDocumentId",
    )
    return str(value).strip() if value not in (None, "") else None


def _candidate_identity(raw: dict[str, Any]) -> str | None:
    """Stable research identity. A trading symbol is deliberately the last fallback."""
    issue_id = _official_issue_id(raw)
    if issue_id:
        return "ISSUE:" + issue_id

    isin = str(_first(raw, "isin", "isinCode") or "").upper().strip()
    if isin:
        return "ISIN:" + isin

    company = _norm_company(
        _first(raw, "companyName", "company", "issuerName", "securityName", "name")
    )
    start = _parse_date(
        _first(raw, "issueStartDate", "startDate", "openDate", "issueOpenDate")
    )
    end = _parse_date(
        _first(raw, "issueEndDate", "endDate", "closeDate", "issueCloseDate")
    )
    if company and (start or end):
        seed = f"{company}|{start.isoformat() if start else ''}|{end.isoformat() if end else ''}"
        return "COMPANY_DATES:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]

    symbol = str(_first(raw, "symbol", "trading_symbol", "issue_symbol") or "").upper().strip()
    if symbol:
        return "SYMBOL:" + symbol
    return None


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    """
    NSE changes response envelopes from time to time. An IPO is a valid research record
    before a final trading symbol exists, so discovery never requires a symbol.
    """
    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            flat = _flat_keys(node)
            has_company = any(
                _norm_key(k) in flat
                for k in ("companyName", "company", "issuerName", "securityName")
            )
            has_issue_fact = any(
                _norm_key(k) in flat
                for k in (
                    "symbol",
                    "tradingSymbol",
                    "issue_symbol",
                    "issueStartDate",
                    "issueEndDate",
                    "listingDate",
                    "tentativeListingDate",
                    "dateOfListing",
                    "issuePrice",
                    "issueSize",
                    "status",
                )
            )
            if has_company and has_issue_fact and _candidate_identity(node):
                out.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)

    unique: dict[str, dict[str, Any]] = {}
    for item in out:
        key = _candidate_identity(item)
        if not key:
            continue
        merged = dict(unique.get(key, {}))
        merged.update(item)
        unique[key] = merged
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
    candidate_id: str
    lifecycle_state: str
    symbol: str | None
    company_name: str
    listing_date: str | None
    issue_start_date: str | None
    issue_end_date: str | None
    official_issue_id: str | None
    isin: str | None
    board: str | None
    is_sme: bool
    issue_status: str | None
    issue_price_text: str | None
    issue_size: str | None
    subscription_multiple: float | None
    nse_source: str
    nse_listing_confirmed: bool
    groww_symbol: str | None
    groww_exchange_token: str | None
    groww_series: str | None
    groww_instrument_type: str | None
    groww_lot_size: int | None
    groww_tick_size: float | None
    groww_freeze_quantity: int | None
    buy_allowed: bool
    sell_allowed: bool
    symbol_resolved: bool
    groww_resolution_status: str
    resolution_status: str
    trading_day_number: int | None = None


@dataclass(frozen=True)
class GrowwResolution:
    status: str
    row: dict[str, str] | None = None


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
        records: list[tuple[dict[str, Any], str]] = []

        def merge_research(item: dict[str, Any], source: str) -> None:
            key = _candidate_identity(item)
            if not key:
                return
            for index, (prior, prior_source) in enumerate(records):
                if _candidate_identity(prior) == key:
                    merged = dict(prior)
                    merged.update(item)
                    records[index] = (merged, source or prior_source)
                    return
            records.append((dict(item), source))

        for path, source in (
            (NSE_UPCOMING, "NSE_UPCOMING_ISSUES"),
            (NSE_CURRENT, "NSE_CURRENT_ISSUES"),
        ):
            payload = self.json(path)
            for item in _extract_records(payload):
                merge_research(item, source)

        # Final exchange identity may arrive after research was already created without
        # a symbol. Link only by exact identifiers (ISIN, exact symbol, or exact normalized
        # company identity). Fuzzy company-name matching is never used for live identity.
        try:
            payload = self.json(NSE_FORTHCOMING)
            self.forthcoming_ready = True
            for final_item in _extract_forthcoming_records(payload):
                final_symbol = str(
                    _first(final_item, "symbol", "tradingSymbol", "securitySymbol") or ""
                ).upper().strip()
                final_isin = str(_first(final_item, "isin", "isinCode") or "").upper().strip()
                final_company = _norm_company(
                    _first(final_item, "companyName", "company", "issuerName", "securityName", "name")
                )
                matches: list[int] = []
                for index, (prior, _) in enumerate(records):
                    prior_symbol = str(
                        _first(prior, "symbol", "trading_symbol", "issue_symbol") or ""
                    ).upper().strip()
                    prior_isin = str(_first(prior, "isin", "isinCode") or "").upper().strip()
                    prior_company = _norm_company(
                        _first(prior, "companyName", "company", "issuerName", "securityName", "name")
                    )
                    exact = bool(
                        (final_isin and prior_isin and final_isin == prior_isin)
                        or (final_symbol and prior_symbol and final_symbol == prior_symbol)
                        or (final_company and prior_company and final_company == prior_company)
                    )
                    if exact:
                        matches.append(index)

                if len(matches) == 1:
                    index = matches[0]
                    merged = dict(records[index][0])
                    merged.update(final_item)
                    records[index] = (merged, "NSE_FORTHCOMING_LISTING")
                else:
                    records.append((dict(final_item), "NSE_FORTHCOMING_LISTING"))
        except Exception:
            self.forthcoming_ready = False
            # Research remains useful. Live execution must stay blocked until this source
            # becomes authoritative again.
            pass

        return records

    def trading_holidays(self) -> set[date]:
        payload = self.json(NSE_HOLIDAYS)
        if not isinstance(payload, dict) or not isinstance(payload.get("CM"), list):
            raise RuntimeError("NSE cash-market holiday calendar (CM) is unavailable")

        holidays: set[date] = set()
        for item in payload["CM"]:
            if not isinstance(item, dict):
                continue
            parsed = _parse_date(_first(item, "tradingDate", "date", "holidayDate"))
            if parsed:
                holidays.add(parsed)
        if not holidays:
            raise RuntimeError("NSE cash-market holiday calendar (CM) is empty")
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
    def resolve_detailed(
        instruments: list[dict[str, str]],
        *,
        official_symbol: str | None,
        isin: str | None,
    ) -> GrowwResolution:
        symbol = str(official_symbol or "").upper().strip()
        official_isin = str(isin or "").upper().strip()
        if not symbol:
            return GrowwResolution("WAIT_NSE_IDENTITY")

        nse_cash = [
            row
            for row in instruments
            if str(row.get("exchange") or "").upper() == "NSE"
            and str(row.get("segment") or "").upper() == "CASH"
        ]
        by_symbol = [
            row
            for row in nse_cash
            if str(row.get("trading_symbol") or "").upper().strip() == symbol
        ]
        if official_isin:
            by_isin = [
                row
                for row in nse_cash
                if str(row.get("isin") or "").upper().strip() == official_isin
            ]
            exact = [
                row
                for row in by_symbol
                if str(row.get("isin") or "").upper().strip() == official_isin
            ]
            if len(exact) > 1:
                return GrowwResolution("BLOCK_MULTIPLE_EXACT_ROWS")
            if len(exact) == 1:
                return GrowwResolution("RESOLVED", exact[0])
            if by_isin or by_symbol:
                return GrowwResolution("BLOCK_IDENTIFIER_DISAGREEMENT")
            return GrowwResolution("WAIT_GROWW_INSTRUMENT")

        if len(by_symbol) > 1:
            return GrowwResolution("BLOCK_MULTIPLE_SYMBOL_ROWS")
        if len(by_symbol) == 1:
            return GrowwResolution("RESOLVED", by_symbol[0])
        return GrowwResolution("WAIT_GROWW_INSTRUMENT")

    @staticmethod
    def resolve(
        instruments: list[dict[str, str]],
        *,
        official_symbol: str,
        isin: str | None,
    ) -> dict[str, str] | None:
        return GrowwInstrumentMaster.resolve_detailed(
            instruments,
            official_symbol=official_symbol,
            isin=isin,
        ).row


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
        symbol = str(_first(item, "symbol", "trading_symbol", "issue_symbol") or "").upper().strip() or None
        company = str(
            _first(item, "companyName", "company", "issuerName", "securityName", "name")
            or symbol
            or "Unknown issuer"
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
        board = str(board_raw).strip() if board_raw else None
        multiple_raw = _first(item, "noOfTime", "subscriptionMultiple", "subscription")
        try:
            subscription_multiple = float(multiple_raw) if multiple_raw not in (None, "") else None
        except (TypeError, ValueError):
            subscription_multiple = None

        candidate_id = _candidate_identity(item)
        if not candidate_id:
            seed = f"{_norm_company(company)}|{start}|{end}|{symbol or ''}"
            candidate_id = "RESEARCH:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]

        return {
            "candidate_id": candidate_id,
            "symbol": symbol,
            "company_name": company,
            "listing_date": listing,
            "issue_start_date": start,
            "issue_end_date": end,
            "official_issue_id": _official_issue_id(item),
            "isin": str(isin_raw).upper().strip() if isin_raw else None,
            "board": board,
            "is_sme": str(board or "").upper() in {"SME", "ST", "SM"},
            "issue_status": str(_first(item, "status", "issueStatus") or "").strip() or None,
            "issue_price_text": str(_first(item, "issuePrice", "priceBand") or "").strip() or None,
            "issue_size": str(_first(item, "issueSize", "noOfSharesOffered") or "").strip() or None,
            "subscription_multiple": subscription_multiple,
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

                normalized = [self._candidate(item, source) for item, source in raw_issues]

                next_trading_day = (
                    self.calendar.next_trading_day(now.date())
                    if self.calendar.source_ready
                    else None
                )
                week_end = (next_trading_day + timedelta(days=6)) if next_trading_day else None

                candidates: list[ResearchCandidate] = []
                for item in normalized:
                    final_listing_confirmed = bool(
                        item["nse_source"] == "NSE_FORTHCOMING_LISTING"
                        and item["symbol"]
                        and item["listing_date"]
                    )
                    resolution = GrowwResolution("WAIT_NSE_IDENTITY")
                    if final_listing_confirmed and instruments:
                        resolution = GrowwInstrumentMaster.resolve_detailed(
                            instruments,
                            official_symbol=item["symbol"],
                            isin=item["isin"],
                        )
                    row = resolution.row

                    def allowed(name: str) -> bool:
                        return str((row or {}).get(name) or "").strip().lower() in {"1", "true", "yes"}

                    trading_day_no: int | None = None
                    if item["listing_date"] and self.calendar.source_ready and item["listing_date"] <= now.date():
                        cursor = item["listing_date"]
                        count = 0
                        while cursor <= now.date():
                            if self.calendar.is_trading_day(cursor):
                                count += 1
                            cursor += timedelta(days=1)
                        trading_day_no = count

                    if not item["symbol"]:
                        lifecycle = "RESEARCHED_NO_SYMBOL"
                        status = "RESEARCH_CONTINUES_SYMBOL_PENDING"
                    elif item["listing_date"] is None:
                        lifecycle = "RESEARCHING"
                        status = "WAIT_OFFICIAL_LISTING_DATE"
                    elif not final_listing_confirmed:
                        lifecycle = "LISTING_DATE_CONFIRMED"
                        status = "WAIT_NSE_IDENTITY_CONFIRMATION"
                    elif resolution.status != "RESOLVED":
                        lifecycle = "GROWW_INSTRUMENT_PENDING"
                        status = resolution.status
                    elif item["listing_date"] == now.date():
                        lifecycle = "LISTING_DAY_WATCH"
                        status = "WAIT_LISTING_SESSION_AND_LIVE_DATA"
                    elif item["listing_date"] < now.date():
                        if trading_day_no is None:
                            lifecycle = "D1_D30_MONITOR"
                            status = "WAIT_OFFICIAL_TRADING_DAY_COUNT"
                        elif trading_day_no <= 30:
                            lifecycle = "D1_D30_MONITOR"
                            status = f"POST_LISTING_MONITOR_D{trading_day_no}"
                        else:
                            lifecycle = "COMPLETE"
                            status = "D30_WINDOW_COMPLETE"
                    else:
                        lifecycle = "GROWW_INSTRUMENT_RESOLVED"
                        status = "RESOLVED_PRE_LISTING"

                    candidates.append(
                        ResearchCandidate(
                            candidate_id=item["candidate_id"],
                            lifecycle_state=lifecycle,
                            symbol=item["symbol"],
                            company_name=item["company_name"],
                            listing_date=item["listing_date"].isoformat() if item["listing_date"] else None,
                            issue_start_date=item["issue_start_date"].isoformat() if item["issue_start_date"] else None,
                            issue_end_date=item["issue_end_date"].isoformat() if item["issue_end_date"] else None,
                            official_issue_id=item["official_issue_id"],
                            isin=item["isin"],
                            board=item["board"],
                            is_sme=item["is_sme"],
                            issue_status=item["issue_status"],
                            issue_price_text=item["issue_price_text"],
                            issue_size=item["issue_size"],
                            subscription_multiple=item["subscription_multiple"],
                            nse_source=item["nse_source"],
                            nse_listing_confirmed=final_listing_confirmed,
                            groww_symbol=str((row or {}).get("groww_symbol") or "").strip() or None,
                            groww_exchange_token=str((row or {}).get("exchange_token") or "").strip() or None,
                            groww_series=str((row or {}).get("series") or "").strip() or None,
                            groww_instrument_type=str((row or {}).get("instrument_type") or "").strip() or None,
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
                            groww_freeze_quantity=(
                                int(float((row or {}).get("freeze_quantity") or 0))
                                if str((row or {}).get("freeze_quantity") or "").strip()
                                else None
                            ),
                            buy_allowed=allowed("buy_allowed"),
                            sell_allowed=allowed("sell_allowed"),
                            symbol_resolved=final_listing_confirmed and resolution.status == "RESOLVED",
                            groww_resolution_status=resolution.status,
                            resolution_status=status,
                            trading_day_number=trading_day_no,
                        )
                    )

                # Preserve recently researched candidates that have disappeared from the
                # current issue feed so the D1-D30 universe is not erased after listing.
                current_ids = {c.candidate_id for c in candidates}
                prior = self.store.load() or {}
                for saved in prior.get("all_known_candidates", []):
                    if not isinstance(saved, dict):
                        continue
                    saved_id = str(saved.get("candidate_id") or "").strip()
                    if not saved_id or saved_id in current_ids:
                        continue
                    listing_text = saved.get("listing_date")
                    issue_end_text = saved.get("issue_end_date")
                    keep = False
                    for text_value in (listing_text, issue_end_text):
                        try:
                            parsed = date.fromisoformat(str(text_value))
                            keep = keep or (now.date() - timedelta(days=60) <= parsed <= now.date() + timedelta(days=60))
                        except (TypeError, ValueError):
                            pass
                    if keep:
                        try:
                            restored = dict(saved)
                            listing_date_value = None
                            try:
                                listing_date_value = date.fromisoformat(str(restored.get("listing_date")))
                            except (TypeError, ValueError):
                                pass
                            if listing_date_value and listing_date_value < now.date() and self.calendar.source_ready:
                                cursor = listing_date_value
                                count = 0
                                while cursor <= now.date():
                                    if self.calendar.is_trading_day(cursor):
                                        count += 1
                                    cursor += timedelta(days=1)
                                restored["trading_day_number"] = count
                                if count <= 30:
                                    restored["lifecycle_state"] = "D1_D30_MONITOR"
                                    restored["resolution_status"] = f"POST_LISTING_MONITOR_D{count}"
                                else:
                                    restored["lifecycle_state"] = "COMPLETE"
                                    restored["resolution_status"] = "D30_WINDOW_COMPLETE"
                            candidates.append(ResearchCandidate(**restored))
                            current_ids.add(saved_id)
                        except TypeError:
                            pass

                next_candidates = [
                    candidate
                    for candidate in candidates
                    if next_trading_day and candidate.listing_date == next_trading_day.isoformat()
                ]
                week_candidates = [
                    candidate
                    for candidate in candidates
                    if (
                        next_trading_day
                        and week_end
                        and candidate.listing_date
                        and next_trading_day <= date.fromisoformat(candidate.listing_date) <= week_end
                    )
                ]
                source_ready = not any(err.startswith("NSE_ISSUE_SOURCE") for err in errors)
                research_health = (
                    "FAILED"
                    if not source_ready
                    else "DEGRADED"
                    if errors
                    else "OK"
                )
                candidate_dicts = [asdict(candidate) for candidate in candidates]
                payload = {
                    "generated_at": now.isoformat(),
                    "trigger": trigger,
                    "source_ready": source_ready,
                    "nse_identity_source_ready": nse.forthcoming_ready,
                    "research_health": research_health,
                    "calendar_ready": self.calendar.source_ready,
                    "calendar_holidays": sorted(day.isoformat() for day in self.calendar.holidays),
                    "next_trading_day": next_trading_day.isoformat() if next_trading_day else None,
                    "candidate_count": len(candidates),
                    "nse_identity_confirmed_count": sum(1 for c in candidates if c.nse_listing_confirmed),
                    "groww_resolved_count": sum(1 for c in candidates if c.symbol_resolved),
                    "groww_pending_count": sum(
                        1 for c in candidates if c.nse_listing_confirmed and not c.symbol_resolved
                    ),
                    "next_trading_day_candidates": [asdict(c) for c in next_candidates],
                    "week_candidates": [
                        asdict(c)
                        for c in sorted(
                            week_candidates,
                            key=lambda c: (c.listing_date or "", c.symbol or "", c.company_name),
                        )
                    ],
                    "all_known_candidates": candidate_dicts,
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
