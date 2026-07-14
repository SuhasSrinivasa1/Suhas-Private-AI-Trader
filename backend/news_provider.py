from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
GOOGLE_NEWS_RSS_ENDPOINT = "https://news.google.com/rss/search"
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


def _aggregate(symbol: str, provider: str, articles: list[dict[str, Any]], *, provider_chain: list[str] | None = None) -> dict[str, Any]:
    seen_urls: set[str] = set()
    source_domains: set[str] = set()
    deduped: list[dict[str, Any]] = []
    scores: list[float] = []
    for item in articles:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        source = str(item.get("source") or "").strip()
        if not title or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        if source:
            source_domains.add(source.lower())
        sentiment = _headline_sentiment(title)
        scores.append(sentiment)
        deduped.append({
            "title": title,
            "url": url,
            "source": source or provider,
            "published": item.get("published") or "",
            "sentiment": sentiment,
            "fingerprint": hashlib.sha256(f"{title}|{url}".encode("utf-8")).hexdigest()[:24],
        })
    sentiment = sum(scores) / len(scores) if scores else 0.0
    return {
        "provider": provider,
        "provider_chain": provider_chain or [provider],
        "available": True,
        "status": "ok" if deduped else "no_recent_headlines",
        "symbol": symbol.upper(),
        "article_count": len(deduped),
        "source_count": len(source_domains),
        "sentiment": round(max(-1.0, min(1.0, sentiment)), 4),
        "headlines": deduped[:12],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def parse_gdelt_payload(payload: Any, symbol: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("GDELT response was not a JSON object")
    raw_articles = payload.get("articles", [])
    if not isinstance(raw_articles, list):
        raw_articles = []
    articles = [
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "source": item.get("domain") or "GDELT source",
            "published": item.get("seendate") or item.get("date") or "",
        }
        for item in raw_articles if isinstance(item, dict)
    ]
    return _aggregate(symbol, "gdelt_doc_2", articles)


def parse_google_news_rss(xml_bytes: bytes, symbol: str) -> dict[str, Any]:
    root = ET.fromstring(xml_bytes)
    articles: list[dict[str, Any]] = []
    for node in root.findall("./channel/item")[:DEFAULT_MAX_RECORDS]:
        source_node = node.find("source")
        articles.append({
            "title": node.findtext("title") or "",
            "url": node.findtext("link") or "",
            "source": (source_node.text if source_node is not None else "Google News RSS") or "Google News RSS",
            "published": node.findtext("pubDate") or "",
        })
    return _aggregate(symbol, "google_news_rss", articles)


def _fetch_gdelt_sync(symbol: str, timeout: float) -> dict[str, Any]:
    alias = ALIASES.get(symbol.upper(), symbol.upper())
    params = urllib.parse.urlencode({
        "query": f'"{alias}"', "mode": "ArtList", "maxrecords": str(DEFAULT_MAX_RECORDS),
        "timespan": DEFAULT_LOOKBACK, "sort": "DateDesc", "format": "json",
    })
    request = urllib.request.Request(f"{GDELT_ENDPOINT}?{params}", headers={"User-Agent": "SuhasPrivateAITrader/2.0 (+local-only)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return parse_gdelt_payload(payload, symbol)


def _fetch_google_news_rss_sync(symbol: str, timeout: float) -> dict[str, Any]:
    alias = ALIASES.get(symbol.upper(), symbol.upper())
    params = urllib.parse.urlencode({"q": f'"{alias}" when:3d', "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    request = urllib.request.Request(f"{GOOGLE_NEWS_RSS_ENDPOINT}?{params}", headers={"User-Agent": "Mozilla/5.0 SuhasPrivateAITrader/2.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return parse_google_news_rss(payload, symbol)


def fetch_free_news_sync(symbol: str, *, timeout: float = 8.0) -> dict[str, Any]:
    errors: list[str] = []
    try:
        result = _fetch_gdelt_sync(symbol, timeout)
        result["provider_chain"] = ["gdelt_doc_2"]
        return result
    except Exception as exc:
        errors.append(f"gdelt_doc_2={exc.__class__.__name__}: {str(exc)[:120]}")
    try:
        result = _fetch_google_news_rss_sync(symbol, timeout)
        result["provider_chain"] = ["gdelt_doc_2_failed", "google_news_rss"]
        result["fallback_used"] = True
        result["primary_error"] = errors[0]
        return result
    except Exception as exc:
        errors.append(f"google_news_rss={exc.__class__.__name__}: {str(exc)[:120]}")
    return {
        "provider": "free_news_failover",
        "provider_chain": ["gdelt_doc_2_failed", "google_news_rss_failed"],
        "available": False,
        "status": "providers_unavailable",
        "symbol": symbol.upper(),
        "article_count": 0,
        "source_count": 0,
        "sentiment": 0.0,
        "headlines": [],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "error": " | ".join(errors),
    }
