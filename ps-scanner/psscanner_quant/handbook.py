from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from .paths import ROOT

CATALOG_PATH = ROOT / "research" / "handbook_catalog.json"
SOURCE_ID = "COMPLETE_TRADING_SYSTEM_MASTER_HANDBOOK_2026-09-24"

# Only map concepts that can be represented by the local, audited cash-equity feature stack.
# Everything else remains visible in research/reference status rather than being faked.
EXECUTABLE_MAP: Dict[int, str] = {
    1: "QUALITY_MOMENTUM", 3: "RELATIVE_STRENGTH", 4: "VALUE_QUALITY",
    7: "LOW_VOL_QUALITY", 9: "VALUE_QUALITY", 11: "EARNINGS_EVENT",
    12: "EARNINGS_EVENT", 13: "RELATIVE_STRENGTH", 15: "QUALITY_MOMENTUM",
    16: "MEAN_REVERSION", 21: "MOMENTUM", 22: "MOMENTUM",
    23: "DONCHIAN_BREAKOUT", 24: "TREND_BREAKOUT", 25: "TREND_BREAKOUT",
    26: "TREND_PULLBACK", 27: "VOLATILITY_COMPRESSION", 28: "MOMENTUM",
    29: "RELATIVE_STRENGTH", 36: "VALUE_QUALITY", 37: "VALUE_QUALITY",
    38: "VALUE_QUALITY", 39: "VALUE_QUALITY", 42: "VALUE_QUALITY",
    43: "VALUE_QUALITY", 44: "VALUE_QUALITY", 45: "VALUE_QUALITY",
    46: "LOW_VOL_QUALITY", 47: "LOW_VOL_QUALITY", 48: "LOW_VOL_QUALITY",
    49: "LOW_VOL_QUALITY", 50: "QUALITY_MOMENTUM", 71: "MEAN_REVERSION",
    72: "VWAP_MEAN_REVERSION", 78: "GAP_CONTINUATION", 79: "EARNINGS_EVENT",
    82: "QUALITY_MOMENTUM", 95: "OPENING_RANGE_BREAKOUT",
    96: "MEAN_REVERSION", 97: "NEWS_MOMENTUM",
}

META_STRATEGIES = {98, 99, 100}


@lru_cache(maxsize=1)
def catalog() -> Dict[str, Any]:
    try:
        d = json.loads(CATALOG_PATH.read_text())
        if not isinstance(d, dict):
            raise ValueError("catalog root is not an object")
        return d
    except Exception:
        return {"source": SOURCE_ID, "strategies": [], "candlesticks": [], "filters": []}


def strategy_catalog() -> List[Dict[str, Any]]:
    out = []
    for row in catalog().get("strategies") or []:
        d = dict(row)
        rank = int(d.get("rank") or 0)
        d["source_id"] = SOURCE_ID
        d["mapped_local_family"] = EXECUTABLE_MAP.get(rank)
        if rank in META_STRATEGIES:
            d["implementation_status"] = "ARCHITECTURE_META_STRATEGY"
        elif rank in EXECUTABLE_MAP:
            d["implementation_status"] = "MAPPED_TO_AUDITED_LOCAL_TEMPLATE"
        else:
            d["implementation_status"] = "RESEARCH_REFERENCE_ONLY"
        out.append(d)
    return out


def candlestick_catalog() -> List[Dict[str, Any]]:
    return [dict(x, source_id=SOURCE_ID) for x in (catalog().get("candlesticks") or [])]


def filter_catalog() -> List[Dict[str, Any]]:
    return [dict(x, source_id=SOURCE_ID) for x in (catalog().get("filters") or [])]


def status() -> Dict[str, Any]:
    s = strategy_catalog()
    return {
        "source": SOURCE_ID,
        "strategy_families": len(s),
        "candlestick_patterns": len(candlestick_catalog()),
        "intelligence_filters": len(filter_catalog()),
        "mapped_to_local_templates": sum(1 for x in s if x.get("mapped_local_family")),
        "research_reference_only": sum(1 for x in s if x.get("implementation_status") == "RESEARCH_REFERENCE_ONLY"),
        "meta_strategies": [x for x in s if int(x.get("rank") or 0) in META_STRATEGIES],
        "principle": "The handbook is used as strategy research, numeric candle context, and a 50-filter decision layer; unsupported institutional concepts are never pretended to be executable cash-equity strategies.",
    }


def family_evidence_grade(local_family: str) -> str:
    """Return the strongest handbook evidence grade mapped to a local family.

    This is a research prior only. Live promotion still requires PS Scanner's own
    chronological walk-forward, holdout and live-shadow evidence.
    """
    fam=str(local_family or '').upper()
    grades=[str(x.get('evidence') or '').upper() for x in strategy_catalog() if str(x.get('mapped_local_family') or '').upper()==fam]
    order={'A':3,'B':2,'C':1}
    return max(grades,key=lambda g:order.get(g,0)) if grades else 'UNRATED'
