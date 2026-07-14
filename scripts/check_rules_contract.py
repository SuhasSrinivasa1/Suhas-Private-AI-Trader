#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "config" / "trading_rules.json"
ENV_EXAMPLE = ROOT / "backend" / ".env.example"
REQUIREMENTS = ROOT / "backend" / "requirements.txt"


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"rules contract failed: {message}")


def main() -> None:
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    env = parse_env(ENV_EXAMPLE)
    requirements = REQUIREMENTS.read_text(encoding="utf-8")

    require(rules["timezone"] == "Asia/Kolkata", "timezone must remain Asia/Kolkata")
    execution = rules["execution"]
    require(execution["paper_mode_default"] is True, "paper mode must default to true")
    require(execution["live_execution_default"] is False, "live execution must default to false")
    require(execution["human_confirmation_required"] is True, "human confirmation is mandatory")
    require(execution["server_side_revalidation_required"] is True, "server-side revalidation is mandatory")
    require(execution["fresh_live_quote_required"] is True, "fresh live quotes are mandatory")
    require(execution["live_time_check_required"] is True, "current market-time checks are mandatory")
    require(execution["never_auto_execute_from_llm"] is True, "LLM must never auto-execute")

    risk = rules["risk"]
    require(risk["max_risk_per_trade_pct"] <= 1.0, "max risk per trade cannot exceed 1% by default")
    require(risk["min_reward_risk_ratio"] >= 2.0, "minimum reward/risk cannot be below 2.0")
    require(risk["max_chase_pct"] <= 1.5, "anti-chase limit cannot exceed 1.5% by default")
    require(risk["max_spread_pct"] <= 0.35, "default maximum spread cannot exceed 0.35%")
    require(risk["max_intraday_range_pct"] <= 7.0, "default maximum intraday range cannot exceed 7%")
    require(risk["min_independent_confirmation_sources"] >= 2, "at least two confirmation sources are required")

    required_checks = {"news", "technical_setup", "portfolio_exposure", "six_month_pattern"}
    require(required_checks.issubset(set(rules["mandatory_checks"])), "mandatory checks are incomplete")

    scanner = rules["scanner"]
    require(scanner["dynamic_universe"] is True, "scanner must remain dynamic")
    require(scanner["fixed_watchlist_only"] is False, "scanner must not be fixed-watchlist-only")
    require("six_month_pattern" in scanner["agents"], "six-month pattern agent is required")
    require("risk_veto" in scanner["agents"], "risk veto agent is required")

    daily = rules["daily_recommendations"]
    require(daily["enabled"] is True, "daily recommendation engine must remain enabled")
    require(int(daily["historical_window_days"]) == 180, "daily pattern window must remain 180 days")
    require(daily["premarket_watch_not_live_buy"] is True, "premarket daily list must never be an automatic BUY list")
    require(daily["free_news_risk_check"] is True, "free news-risk check must remain enabled")
    require(daily["local_llm_advisory_brief"] is True, "local LLM daily brief must remain advisory")
    require(daily["live_revalidation_required_for_buy"] is True, "live revalidation is mandatory before BUY")

    profit = rules["profit_discipline"]
    require(profit["one_pct_profit_is_acceptable"] is True, "1% acceptable-profit preference must remain recorded")
    require(float(profit["base_profit_booking_pct"]) == 3.0, "base profit-booking reference must remain 3%")
    require(float(profit["trim_trigger_profit_pct"]) == 5.0, "trim trigger must remain 5%")
    require(float(profit["trim_quantity_pct_at_five_pct_profit"]) == 15.0, "5% trim preference must remain 15% of quantity")
    require(profit["automatic_exit_orders_enabled"] is False, "automatic exit orders must remain disabled")

    missed_trade = rules["missed_trade_postmortem"]
    require(missed_trade["enabled"] is True, "missed-trade postmortem must remain enabled")
    require(
        missed_trade["never_relax_anti_chase_rule_only_because_a_trade_was_missed"] is True,
        "missed trades must never weaken the anti-chase rule",
    )

    news = rules["news_policy"]
    require(news["free_provider_enabled"] is True, "free news provider must remain enabled")
    require(news["fail_closed_for_new_buy_when_unavailable"] is True, "news unavailability must fail closed for new BUYs")
    require(news["never_invent_headlines_or_sentiment"] is True, "news data must never be fabricated")

    privacy = rules["privacy"]
    require(privacy["frontend_must_not_store_secrets"] is True, "frontend secret storage must be forbidden")
    require(privacy["macos_keychain_for_groww_secrets"] is True, "Groww secrets must use macOS Keychain in production")
    require(privacy["local_llm_advisory_only"] is True, "local LLM must remain advisory only")
    require(privacy["local_llm_must_not_receive_broker_secrets"] is True, "local LLM must never receive broker secrets")

    expected_env = {
        "MAX_RISK_PER_TRADE_PCT": risk["max_risk_per_trade_pct"],
        "MIN_REWARD_RISK_RATIO": risk["min_reward_risk_ratio"],
        "MAX_CHASE_PCT": risk["max_chase_pct"],
        "MAX_PRICE_AGE_SECONDS": execution["max_quote_age_seconds"],
        "MIN_CONFIRMATION_SOURCES": risk["min_independent_confirmation_sources"],
        "MAX_POSITION_VALUE_PCT": risk["max_position_value_pct"],
        "MIN_BUY_CONFIDENCE": risk["min_buy_confidence"],
        "MIN_WATCH_CONFIDENCE": risk["min_watch_confidence"],
        "MAX_SPREAD_PCT": risk["max_spread_pct"],
        "MAX_INTRADAY_RANGE_PCT": risk["max_intraday_range_pct"],
        "SCAN_INTERVAL_SECONDS": scanner["scan_interval_seconds"],
        "DEEP_SCAN_CANDIDATES": scanner["deep_scan_candidates"],
        "MAX_DISPLAY_OPPORTUNITIES": scanner["max_display_opportunities"],
        "SIGNAL_VALID_SECONDS": execution["signal_valid_seconds"],
        "FREE_NEWS_ENABLED": True,
        "NEWS_REQUIRED_FOR_BUY": True,
    }
    for key, expected in expected_env.items():
        actual = env.get(key)
        require(actual is not None, f"{key} is missing from backend/.env.example")
        if isinstance(expected, bool):
            require((actual.lower() in {"1", "true", "yes", "on"}) == expected, f"{key} does not match the rules contract")
        else:
            require(float(actual) == float(expected), f"{key}={actual} does not match rules contract value {expected}")

    require(env.get("APP_ENV") == "production", "example environment must default to production")
    require(env.get("GROWW_CREDENTIAL_SOURCE") == "keychain", "production Groww credential source must be Keychain")
    require(env.get("TRADING_PROFILE_ENABLED", "false").lower() in {"1", "true", "yes", "on"}, "trading profile should be enabled")
    require(env.get("GROWW_LIVE_EXECUTION_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}, "Groww live execution must be disabled by default")
    require(env.get("GROWW_API_KEY", "") == "", "Groww API key must be blank in the example environment")
    require(env.get("GROWW_API_SECRET", "") == "", "Groww API secret must be blank in the example environment")

    groww_requirement = re.search(r"(?m)^growwapi==([0-9.]+)$", requirements)
    require(groww_requirement is not None, "runtime requirements must pin the tested growwapi SDK")
    require(tuple(map(int, groww_requirement.group(1).split("."))) >= (1, 5, 0), "growwapi must be at least 1.5.0")

    print("rules contract passed")


if __name__ == "__main__":
    main()
