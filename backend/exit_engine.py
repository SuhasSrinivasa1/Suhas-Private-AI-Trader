from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def evaluate_exit_signal(
    *,
    symbol: str,
    quantity: float,
    average_price: float,
    current_price: float,
    pattern: dict[str, Any] | None = None,
    news: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pattern = pattern or {}
    news = news or {}
    pnl_pct = ((current_price - average_price) / average_price * 100) if average_price > 0 else 0.0
    pattern_score = float(pattern.get("score") or 50.0)
    news_sentiment = float(news.get("sentiment") or 0.0)

    action = "HOLD"
    urgency = "normal"
    reasons: list[str] = []

    if news.get("available") and news_sentiment <= -0.65:
        action = "REVIEW_SELL"
        urgency = "high"
        reasons.append("Strongly negative recent news requires immediate exit review.")
    if pattern.get("available") and pattern_score < 35:
        action = "REVIEW_SELL"
        urgency = "high"
        reasons.append("Six-month pattern has deteriorated below the long-quality threshold.")
    if pnl_pct <= -2.2:
        action = "REVIEW_SELL"
        urgency = "high"
        reasons.append("Loss has moved beyond the default 2.2% hard review boundary.")
    elif pnl_pct >= 5.0 and action == "HOLD":
        action = "TRIM_15"
        urgency = "normal"
        reasons.append("Profit is at or above 5%; plan an approximately 15% quantity trim under the configured discipline.")
    elif pnl_pct >= 3.0 and action == "HOLD":
        action = "BOOK_PARTIAL_REVIEW"
        urgency = "normal"
        reasons.append("Profit is at or above the 3% base booking reference.")
    elif pnl_pct >= 1.0 and action == "HOLD":
        reasons.append("Position is in the configured acceptable-profit zone.")
    else:
        reasons.append("No configured exit trigger is active.")

    return {
        "symbol": symbol.upper(),
        "quantity": quantity,
        "average_price": round(average_price, 4),
        "current_price": round(current_price, 4),
        "pnl_pct": round(pnl_pct, 3),
        "pattern_score": round(pattern_score, 2),
        "news_sentiment": round(news_sentiment, 4),
        "action": action,
        "urgency": urgency,
        "reason": " ".join(reasons),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution": "human_confirmation_required",
    }
