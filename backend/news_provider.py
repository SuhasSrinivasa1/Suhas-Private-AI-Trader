from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_LOOKBACK = os.getenv("FREE_NEWS_LOOKBACK", "3d")
DEFAULT_MAX_RECORDS = max(5, min(50, int(os.getenv("FREE_NEWS_MAX_RECORDS", "20"))))
ROOT = Path(__file__).resolve().parents[1]
ALIASES_PATH = ROOT / "config" / "symbol_aliases.json"

NEGATIVE_TERMS = {
    "fraud", "probe", "raid", "default", "downgrade", "lawsuit", "ban", "penalty",
    "insolvency", "bankruptcy", "warning", "slump", "decline", "weak", "loss", "miss",
    "cyberattack", "fire", "accident", "recall", "investigation", "fine", "cut guidance",
}
POSITIVE_TERMS = {
    "upgrade", "record profit", "order win", "contract win", "approval", "buyback", "dividend",
    "expansion", "beat estimates", "strong growth", "launch", "partnership", "acquisition", "profit rises",
}


def _load_aliases() -> dict[str, str]:
    try:
        payload = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
        return {str(k).upper(): str(v) for k, v in payload.items() if str(v).strip()}
    except (OSError, json.JSONDecodeError):
        return {}


ALIASES = _load_aliases()


def _headline_sentiment(title: str) -> float:
    text = title.lower()
    negative = sum(1 for term in NEGATIVE_TERMS if term in text)
    positive = sum(1 for term in POSITIVE_TERMS if term in text)
    if positive == negative:
        return 0.0
    return max(-1.0, min(1.0, (positive - negative) / max(1, positive + negative)))


def parse_gdelt_payload(payload: Any, symbol: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("GDELT response was not a JSON object")
    raw_articles = payload.get("articles", [])
    if not isinstance(raw_articles, list):
        raw_articles = []

    articles: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    source_domains: set[str] = set()
    scores: list[float] = []
    for item in raw_articles:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        domain = str(item.get("domain") or "").strip().lower()
        if not title or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        if domain:
            source_domains.add(domain)
        score = _headline_sentiment(title)
        scores.append(score)
        articles.append(
            {
                "title": title,
                "url": url,
                "source": domain or "GDELT source",
                "published": item.get("seendate") or item.get("date") or "",
            }
        )

    sentiment = sum(scores) / len(scores) if scores else 0.0
    return {
        "provider": "gdelt_doc_2",
        "available": True,
        "status": "ok" if articles else "no_recent_headlines",
        "symbol": symbol.upper(),
        "article_count": len(articles),
        "source_count": len(source_domains),
        "sentiment": round(max(-1.0, min(1.0, sentiment)), 4),
        "headlines": articles[:12],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_free_news_sync(symbol: str, *, timeout: float = 8.0) -> dict[str, Any]:
    alias = ALIASES.get(symbol.upper(), symbol.upper())
    query = f'"{alias}"'
    params = urllib.parse.urlencode(
        {
            "query": query,
            "mode": "ArtList",
            "maxrecords": str(DEFAULT_MAX_RECORDS),
            "timespan": DEFAULT_LOOKBACK,
            "sort": "DateDesc",
            "format": "json",
        }
    )
    request = urllib.request.Request(
        f"{GDELT_ENDPOINT}?{params}",
        headers={"User-Agent": "SuhasPrivateAITrader/1.0 (+local-only)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
        return parse_gdelt_payload(payload, symbol)
    except Exception as exc:  # network/provider errors must fail closed for BUY decisions
        return {
            "provider": "gdelt_doc_2",
            "available": False,
            "status": "provider_unavailable",
            "symbol": symbol.upper(),
            "article_count": 0,
            "source_count": 0,
            "sentiment": 0.0,
            "headlines": [],
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": f"{exc.__class__.__name__}: {str(exc)[:180]}",
        }
