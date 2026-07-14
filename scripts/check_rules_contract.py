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


def env_bool(env: dict[str, str], key: str) -> bool:
    return env.get(key, "false").lower() in {"1", "true", "yes", "on"}


def main() -> None:
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    env = parse_env(ENV_EXAMPLE)
    requirements = REQUIREMENTS.read_text(encoding="utf-8")

    require(rules.get("schema_version") == "2.0.0", "rules schema must be Production 2.0")
    require(rules["timezone"] == "Asia/Kolkata", "timezone must remain Asia/Kolkata")

    execution = rules["execution"]
    require(execution["paper_mode_default"] is True, "paper mode must default to true")
    require(execution["live_execution_default"] is False, "live execution must default to false")
    require(execution["human_confirmation_required"] is True, "human confirmation is mandatory")
    require(execution["server_side_revalidation_required"] is True, "server-side revalidation is mandatory")
    require(execution["fresh_live_quote_required"] is True, "fresh live quotes are mandatory")
    require(execution["never_auto_execute_from_llm"] is True, "LLM must never auto-execute")

    risk = rules["risk"]
    require(risk["max_risk_per_trade_pct"] <= 1.0, "max risk per trade cannot exceed 1% by default")
    require(risk["min_reward_risk_ratio"] >= 2.0, "minimum reward/risk cannot be below 2.0")
    require(risk["max_chase_pct"] <= 1.5, "anti-chase cannot exceed 1.5% by default")
    require(risk["min_independent_confirmation_sources"] >= 2, "at least two confirmation sources are required")

    required_checks = {"news", "technical_setup", "portfolio_exposure", "six_month_pattern"}
    require(required_checks.issubset(set(rules["mandatory_checks"])), "mandatory checks are incomplete")

    scanner = rules["scanner"]
    require(scanner["dynamic_universe"] is True, "scanner must remain dynamic")
    require(scanner["event_driven_live_feed"] is True, "event-driven live feed is required")
    require("risk_veto" in scanner["agents"], "risk veto agent is required")
    require("outcome_learning" in scanner["agents"], "outcome learning agent is required")
    require("exit_management" in scanner["agents"], "exit management agent is required")

    continuous = rules["continuous_intelligence"]
    require(continuous["enabled"] is True, "continuous intelligence must remain enabled")
    require(continuous["browser_refresh_required"] is False, "browser refresh must not be required")
    require(continuous["groww_callback_feed"] is True, "Groww callback feed must remain enabled")
    require(continuous["automatic_local_llm_on_material_events"] is True, "automatic local LLM material-event analysis is required")
    require(continuous["llm_not_called_on_every_tick"] is True, "LLM must not run on every market tick")
    require(int(continuous["max_feed_subscriptions"]) <= 1000, "feed subscription cap must respect the supported limit")

    daily = rules["daily_recommendations"]
    require(int(daily["historical_window_days"]) == 180, "daily pattern window must remain 180 days")
    require(daily["premarket_watch_not_live_buy"] is True, "premarket list must not be an automatic BUY list")
    require(daily["free_news_risk_check"] is True, "free news-risk check must remain enabled")
    require(daily["live_revalidation_required_for_buy"] is True, "live revalidation is mandatory before BUY")

    memory = rules["local_memory"]
    require(memory["enabled"] is True, "local SQLite memory must remain enabled")
    require(memory["semantic_memory"] is True, "local semantic memory must remain enabled")
    require(memory["embedding_provider"] == "local Ollama", "embeddings must remain local by default")
    require(memory["embedding_model_default"] == "embeddinggemma", "default local embedding model must remain embeddinggemma")
    require(int(memory["price_retention_days"]) == 30, "price sample retention must remain bounded")

    learning = rules["learning"]
    require(learning["recommendation_outcome_tracking"] is True, "recommendation outcome tracking is required")
    require(learning["adaptive_agent_weights"] is True, "bounded adaptive agent weights are required")
    require(learning["weight_multiplier_bounds"] == [0.75, 1.25], "adaptive weights must stay bounded")
    require(learning["risk_rules_never_adapt_automatically"] is True, "risk rules must never self-modify")

    exits = rules["sell_exit_management"]
    require(exits["automatic_sell_orders"] is False, "automatic SELL orders must remain disabled")
    require(exits["human_confirmation_required"] is True, "SELL requires human confirmation")
    require(exits["fresh_groww_price_required_before_order"] is True, "SELL requires a fresh Groww price")
    require(float(exits["five_pct_trim_planning_pct"]) == 15.0, "5% trim planning must remain 15%")

    news = rules["news_policy"]
    require(news["free_provider_enabled"] is True, "free news provider must remain enabled")
    require(news["fail_closed_for_new_buy_when_unavailable"] is True, "news unavailability must fail closed for BUY")
    require(news["never_invent_headlines_or_sentiment"] is True, "news must never be fabricated")

    privacy = rules["privacy"]
    require(privacy["frontend_must_not_store_secrets"] is True, "frontend secret storage must be forbidden")
    require(privacy["macos_keychain_for_groww_secrets"] is True, "Groww secrets must use macOS Keychain")
    require(privacy["local_llm_advisory_only"] is True, "local LLM must remain advisory only")

    provider_health = rules["provider_health"]
    require(provider_health["enabled"] is True, "provider health monitoring must remain enabled")
    require(provider_health["fail_closed_for_missing_buy_dependencies"] is True, "missing BUY dependencies must fail closed")

    numeric_env = {
        "MAX_RISK_PER_TRADE_PCT": risk["max_risk_per_trade_pct"],
        "MIN_REWARD_RISK_RATIO": risk["min_reward_risk_ratio"],
        "MAX_CHASE_PCT": risk["max_chase_pct"],
        "MAX_PRICE_AGE_SECONDS": execution["max_quote_age_seconds"],
        "MIN_CONFIRMATION_SOURCES": risk["min_independent_confirmation_sources"],
        "SCAN_INTERVAL_SECONDS": scanner["scan_interval_seconds"],
        "DEEP_SCAN_CANDIDATES": scanner["deep_scan_candidates"],
        "MAX_DISPLAY_OPPORTUNITIES": scanner["max_display_opportunities"],
        "SIGNAL_VALID_SECONDS": execution["signal_valid_seconds"],
        "NEWS_PRIORITY_INTERVAL_SECONDS": continuous["priority_news_interval_seconds"],
        "NEWS_BROAD_INTERVAL_SECONDS": continuous["broad_news_rotation_interval_seconds"],
        "MATERIAL_PRICE_MOVE_PCT": continuous["material_price_move_trigger_pct"],
    }
    for key, expected in numeric_env.items():
        actual = env.get(key)
        require(actual is not None, f"{key} is missing from backend/.env.example")
        require(float(actual) == float(expected), f"{key}={actual} does not match rules contract value {expected}")

    for key in ("ENABLE_GROWW_FEED", "ENABLE_AUTO_LLM", "ENABLE_SEMANTIC_MEMORY", "FREE_NEWS_ENABLED", "NEWS_REQUIRED_FOR_BUY"):
        require(env_bool(env, key), f"{key} must remain enabled in the production example")

    require(env.get("APP_ENV") == "production", "example environment must default to production")
    require(env.get("OLLAMA_EMBEDDING_MODEL") == "embeddinggemma", "default embedding model must remain local embeddinggemma")
    require(env.get("GROWW_CREDENTIAL_SOURCE") == "keychain", "production Groww credential source must be Keychain")
    require(env_bool(env, "TRADING_PROFILE_ENABLED"), "trading profile should be enabled")
    require(not env_bool(env, "GROWW_LIVE_EXECUTION_ENABLED"), "Groww live execution must be disabled by default")
    require(env.get("GROWW_API_KEY", "") == "", "Groww API key must be blank in the example environment")
    require(env.get("GROWW_API_SECRET", "") == "", "Groww API secret must be blank in the example environment")

    groww_requirement = re.search(r"(?m)^growwapi==([0-9.]+)$", requirements)
    require(groww_requirement is not None, "runtime requirements must pin the tested growwapi SDK")
    require(tuple(map(int, groww_requirement.group(1).split("."))) >= (1, 5, 0), "growwapi must be at least 1.5.0")

    print("rules contract passed")


if __name__ == "__main__":
    main()
