from __future__ import annotations

"""Central page/book lifecycle contracts for PS Scanner v6.6.0.

This module is intentionally declarative. Runtime functions still own market-calendar
calculations, but every UI page can now describe the same active-period, freeze,
expiry, recovery and learning semantics from one source instead of stale page copy.
"""

from copy import deepcopy
from typing import Any, Dict, Optional

POLICY_VERSION = "V672_BOUNDED_SANITY_AND_DEEP_DB_VERIFICATION"

BOOK_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "INTRADAY": {
        "page": "INTRADAY",
        "horizon": "SAME_NSE_SESSION",
        "worker": "intraday",
        "scan_function": "engine.run_intraday_cycle -> engine.scan_equities",
        "db_table": "recommendations",
        "api_endpoint": "/api/book/INTRADAY",
        "active_period": "session_date=today (period_key=YYYY-MM-DD)",
        "publication": "NSE session, 09:15-15:00 IST",
        "freeze": "not a frozen portfolio; each published identity is immutable",
        "expiry": "SHORT at 15:00 IST; unresolved LONG at NSE session end; missed close is resolved on next startup",
        "recovery": "zero-live deterministic rotating cached-ready bootstrap, then full breadth; no gate relaxation",
        "learning": "all valid CLOSED outcomes remain in the ledger; VOID/STALE_DATA are excluded from trading P/L evidence",
        "default_ui": "current session LIVE + CLOSED only",
        "history_ui": "older sessions only through History/Performance",
        "target_count": None,
    },
    "WEEKLY": {
        "page": "WEEKLY",
        "horizon": "NSE_TRADING_WEEK",
        "worker": "weekly",
        "scan_function": "engine.run_single_horizon_cycle('WEEKLY')",
        "db_table": "recommendations + candidate_observations",
        "api_endpoint": "/api/book/WEEKLY",
        "active_period": "current relevant NSE week (period_key=Monday)",
        "publication": "pre-period after prior close when possible; otherwise first/missing-session recovery",
        "freeze": "09:00-09:12 IST preferred; deterministic recovery through 15:25 and later sessions while the period remains valid",
        "expiry": "period end, target, or stop/thesis invalidation",
        "recovery": "staged deterministic cached-ready universe expansion; target 5 is a target, never a quota",
        "learning": "valid CLOSED outcomes remain available after the week leaves the active UI",
        "default_ui": "active period only",
        "history_ui": "older weeks only through History/Performance",
        "target_count": 5,
    },
    "MONTHLY": {
        "page": "MONTHLY",
        "horizon": "NSE_TRADING_MONTH",
        "worker": "monthly",
        "scan_function": "engine.run_single_horizon_cycle('MONTHLY')",
        "db_table": "recommendations + candidate_observations",
        "api_endpoint": "/api/book/MONTHLY",
        "active_period": "current relevant month (period_key=YYYY-MM)",
        "publication": "prefer pre-month publication after the prior month closes",
        "freeze": "same preferred morning window as WEEKLY when recovery is needed",
        "expiry": "month end, target, or stop/thesis invalidation",
        "recovery": "never reconstruct an effectively expired month with hindsight; prepare the next period instead",
        "learning": "valid CLOSED outcomes remain available after the month leaves the active UI",
        "default_ui": "active period only",
        "history_ui": "older months only through History/Performance",
        "target_count": 5,
        "cross_book_constraint": "symbol-level mutually exclusive with WEEKLY for overlapping frozen periods, even after early close",
    },
    "ETF": {
        "page": "ETF",
        "horizon": "NSE_TRADING_WEEK",
        "worker": "etf",
        "scan_function": "specialized.run_etf_cycle -> specialized.scan_etfs",
        "db_table": "recommendations + candidate_observations",
        "api_endpoint": "/api/book/ETF",
        "active_period": "current relevant NSE week",
        "publication": "weekly frozen ETF book",
        "freeze": "preferred 09:00-09:12 IST; current-period cached missed-freeze recovery remains allowed after the legacy window",
        "expiry": "week end, target, or stop/thesis invalidation",
        "recovery": "cached-first, deterministic, no stale fallback and no gate relaxation",
        "learning": "valid CLOSED outcomes remain in History/Performance and learning",
        "default_ui": "active week only",
        "history_ui": "older weeks only through History/Performance",
        "target_count": 5,
    },
    "CIRCUIT": {
        "page": "CIRCUIT",
        "horizon": "SAME_NSE_SESSION_TO_15_00",
        "worker": "circuit",
        "scan_function": "specialized.run_circuit_cycle",
        "db_table": "recommendations",
        "api_endpoint": "/api/circuit/board",
        "active_period": "today's NSE session",
        "publication": "09:15-15:00 IST after verified band/deadline/freshness/liquidity/execution evidence",
        "freeze": "not a multi-day frozen book",
        "expiry": "15:00 IST; missed close is resolved on next startup",
        "recovery": "no hindsight reconstruction after the session",
        "learning": "WIN/LOSS/MISS are trading evidence; VOID/data errors are reported separately",
        "default_ui": "today only",
        "history_ui": "older sessions only through History/Performance",
        "target_count": None,
    },
    "CIRCUIT_NEXTDAY": {
        "page": "CIRCUIT",
        "horizon": "NEXT_NSE_SESSION",
        "worker": "circuit_nextday",
        "scan_function": "specialized.run_circuit_nextday_cycle",
        "db_table": "recommendations",
        "api_endpoint": "/api/circuit/board",
        "active_period": "next/current forecast session",
        "publication": "prepared 14:40-close, frozen from 15:00 IST",
        "freeze": "identity/entry/target frozen for target session",
        "expiry": "target session 15:00 IST",
        "recovery": "do not reconstruct a missed freeze after source-session close",
        "learning": "separate next-session Circuit evidence",
        "default_ui": "current target session only",
        "history_ui": "older forecasts only through History/Performance",
        "target_count": 5,
    },
    "INTERNATIONAL": {
        "page": "INTERNATIONAL",
        "horizon": "US_TRADING_WEEK",
        "worker": "international",
        "scan_function": "specialized.run_international_cycle",
        "db_table": "recommendations",
        "api_endpoint": "/api/international/board",
        "active_period": "current relevant New York trading week",
        "publication": "prefer after Friday close/weekend/Monday pre-open",
        "freeze": "weekly frozen LONG-only research book",
        "expiry": "US week end, target, or stop/thesis invalidation",
        "recovery": "bounded subprocess data transport with graceful partial failure; current-week recovery, never stale substitution",
        "learning": "valid CLOSED weekly outcomes remain historical evidence",
        "default_ui": "active US week only",
        "history_ui": "older US weeks only through History/Performance",
        "target_count": 5,
    },
    "GLOBAL_INDIA_LONG": {
        "page": "INTERNATIONAL",
        "horizon": "NEXT_NSE_SESSION",
        "worker": "global_india",
        "scan_function": "cross_market.run_global_india_cycle",
        "db_table": "recommendations",
        "api_endpoint": "/api/international/board",
        "active_period": "current/next NSE forecast session",
        "publication": "overnight/global-context preparation",
        "freeze": "next-session identity",
        "expiry": "target NSE session 15:00 IST",
        "recovery": "no hindsight backfill",
        "learning": "valid CLOSED forecast outcomes remain historical evidence",
        "default_ui": "current target session only",
        "history_ui": "older sessions through History/Performance",
        "target_count": None,
    },
    "GLOBAL_INDIA_SHORT": {
        "page": "INTERNATIONAL",
        "horizon": "NEXT_NSE_SESSION_SAME_DAY_SHORT",
        "worker": "global_india",
        "scan_function": "cross_market.run_global_india_cycle",
        "db_table": "recommendations",
        "api_endpoint": "/api/international/board",
        "active_period": "current/next NSE forecast session",
        "publication": "overnight/global-context preparation",
        "freeze": "next-session identity",
        "expiry": "target NSE session 15:00 IST",
        "recovery": "no hindsight backfill",
        "learning": "valid CLOSED forecast outcomes remain historical evidence",
        "default_ui": "current target session only",
        "history_ui": "older sessions through History/Performance",
        "target_count": None,
    },
}

PAGE_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "INTRADAY": {"kind": "book", "books": ["INTRADAY"]},
    "WEEKLY": {"kind": "book", "books": ["WEEKLY"]},
    "MONTHLY": {"kind": "book", "books": ["MONTHLY"]},
    "ETF": {"kind": "book", "books": ["ETF"]},
    "CIRCUIT": {"kind": "book", "books": ["CIRCUIT", "CIRCUIT_NEXTDAY"]},
    "INTERNATIONAL": {"kind": "book", "books": ["INTERNATIONAL", "GLOBAL_INDIA_LONG", "GLOBAL_INDIA_SHORT"]},
    "STRATEGY": {"kind": "research", "api_endpoint": "/api/strategy-lab", "contract": "Champion/Challenger + shadow learning; no direct trade publication"},
    "REGIME": {"kind": "context", "api_endpoint": "/api/regime", "contract": "current market-regime context"},
    "INTELLIGENCE": {"kind": "audit", "api_endpoint": "/api/trade-decisions", "contract": "recent candidate decision evidence, including rejects"},
    "PERFORMANCE": {"kind": "history", "api_endpoint": "/api/performance", "contract": "historical outcomes and statistical performance; never mixed into active-book payloads"},
    "PORTFOLIO": {"kind": "risk", "api_endpoint": "/api/portfolio", "contract": "current broker/risk state; not a signal generator"},
    "HEALTH": {"kind": "operations", "api_endpoint": "/api/health", "contract": "cached operational status; no long blocking aggregation"},
    "SETTINGS": {"kind": "configuration", "api_endpoint": "/api/settings", "contract": "execution/configuration controls"},
}


def book_contract(book: str) -> Dict[str, Any]:
    return deepcopy(BOOK_CONTRACTS.get(str(book or "").upper(), {}))


def lifecycle_payload(page: Optional[str] = None) -> Dict[str, Any]:
    if page:
        p = str(page).upper()
        page_info = deepcopy(PAGE_CONTRACTS.get(p, {}))
        books = {b: deepcopy(BOOK_CONTRACTS[b]) for b in page_info.get("books", []) if b in BOOK_CONTRACTS}
        return {"policy_version": POLICY_VERSION, "page": p, "page_contract": page_info, "books": books}
    return {
        "policy_version": POLICY_VERSION,
        "principles": {
            "active_ui": "current actionable/current-period records only",
            "history": "historical rows remain immutable learning/performance evidence",
            "target_count": "a target is never a quota; shortages are explicit and never fabricated",
            "strategy_combinations": "family diversity is advisory/shadow evidence until statistically validated",
            "hard_gates": "freshness, liquidity, data quality, risk and execution safety remain fail-closed",
        },
        "pages": deepcopy(PAGE_CONTRACTS),
        "books": deepcopy(BOOK_CONTRACTS),
    }
