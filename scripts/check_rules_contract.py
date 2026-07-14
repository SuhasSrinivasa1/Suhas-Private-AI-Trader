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

    require(rules.get("schema_version") == "2.3.0", "rules schema must be Production 2.3")
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

    required_checks = {"news", "technical_setup", "portfolio_exposure", "six_month_pattern", "macd", "rsi", "mode_specific_timeframe"}
    require(required_checks.issubset(set(rules["mandatory_checks"])), "mandatory checks are incomplete")

    modes = rules["trading_modes"]
    require(modes["user_must_select_on_ui_entry"] is True, "the UI must ask the user to choose Intraday or Delivery")
    require(set(modes["available"]) == {"intraday", "delivery"}, "exactly Intraday and Delivery modes are required")
    require(modes["available"]["intraday"]["broker_product"] == "MIS", "Intraday mode must use Groww MIS")
    require(modes["available"]["delivery"]["broker_product"] == "CNC", "Delivery mode must use Groww CNC")
    require(modes["broker_product_must_match_selected_mode"] is True, "broker product must match the selected mode")

    indicators = rules["technical_indicators"]
    macd = indicators["macd"]
    require(macd["enabled"] is True, "MACD must remain enabled")
    require(macd["mandatory_for_buy_evaluation"] is True, "MACD must be checked before BUY evaluation")
    require([macd["fast_period"], macd["slow_period"], macd["signal_period"]] == [12, 26, 9], "MACD must use the 12/26/9 baseline")
    require(indicators["rsi"]["enabled"] is True, "RSI agent must remain enabled")
    require(indicators["atr"]["enabled"] is True, "ATR agent must remain enabled")

    universe = rules["market_universe"]
    require(universe["scope"] == "all tradable NSE CASH equities", "scanner scope must cover all tradable NSE cash equities")
    require(universe["include_penny_stocks_for_discovery"] is True, "penny stocks must remain included for discovery")
    require(universe["include_sme_equities_for_discovery"] is True, "SME equities must remain included for discovery")
    require(universe["full_universe_rotation_enabled"] is True, "full NSE universe rotation must remain enabled")
    require(int(universe["rest_batch_size"]) <= 50, "REST batches must respect Groww's 50-instrument call size")
    require(int(universe["feed_priority_subscription_cap"]) <= 1000, "feed priority cap must respect Groww's 1000-subscription limit")
    require(universe["coarse_prediction_is_not_actionable_buy"] is True, "coarse full-universe predictions must not become blind BUY instructions")
    require(universe["deep_revalidation_required_before_actionable_signal"] is True, "deep revalidation is required before actionable signals")

    objective = rules["capital_objective"]
    require(int(objective["current_starting_capital_inr"]) == 20000, "current starting capital objective must be ₹20,000")
    require(int(objective["stretch_target_inr"]) == 100000, "stretch target must be ₹1,00,000")
    require(int(objective["target_horizon_calendar_days"]) == 30, "stretch target horizon must remain 30 calendar days")
    require(objective["target_is_guarantee"] is False, "the stretch target must never be represented as guaranteed")
    require(objective["no_loss_guarantee"] is False, "the system must not promise zero losses")
    require(objective["capital_preservation_has_priority_over_target"] is True, "capital preservation must outrank the stretch target")
    require(objective["never_relax_risk_rules_to_hit_target"] is True, "risk rules must never be weakened to chase the target")

    legal = rules["legal_information_policy"]
    require(legal["public_lawful_information_only"] is True, "only lawful public information may be used")
    require(legal["reject_unpublished_price_sensitive_information"] is True, "UPSI must be rejected")
    require(legal["no_insider_trading"] is True, "insider trading must be prohibited")
    require(legal["no_market_manipulation"] is True, "market manipulation must be prohibited")

    scanner = rules["scanner"]
    require(scanner["dynamic_universe"] is True, "scanner must remain dynamic")
    require(scanner["event_driven_live_feed"] is True, "event-driven live feed is required")
    required_specialists = {"macd", "rsi_momentum", "trend_ema", "volume_confirmation", "volatility_atr", "liquidity", "order_flow", "market_regime", "news", "six_month_pattern", "portfolio_exposure", "risk_veto"}
    require(required_specialists.issubset(set(scanner["agents"])), "specialist agent set is incomplete")
    require(int(scanner["specialist_agent_count"]) >= 12, "at least 12 specialist agents are required")
    require(scanner["mode_specific_agent_weights"] is True, "agent weights must vary by trading mode")

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
    require("paper_calls" in memory["stores"], "paper-call ledger must be stored locally")

    learning = rules["learning"]
    require(learning["recommendation_outcome_tracking"] is True, "recommendation outcome tracking is required")
    require(learning["adaptive_agent_weights"] is True, "bounded adaptive agent weights are required")
    require(learning["weight_multiplier_bounds"] == [0.75, 1.25], "adaptive weights must stay bounded")
    require(learning["risk_rules_never_adapt_automatically"] is True, "risk rules must never self-modify")

    calls = rules["calls_and_results"]
    require(calls["enabled"] is True, "Calls & Results must remain enabled")
    require(int(calls["paper_observation_days"]) == 7, "the initial paper-observation phase must remain seven days")
    require(calls["predictions_are_not_trades"] is True, "paper calls must not be represented as real trades")
    require(calls["live_orders_blocked_during_observation"] is True, "live orders must remain blocked during the observation phase")
    require(calls["store_predicted_buy_and_sell_prices"] is True, "predicted buy and sell prices must be stored")
    require(calls["visual_accuracy_dashboard"] is True, "correct/wrong accuracy visuals are required")
    require(calls["automatic_result_resolution"] is True, "paper calls must resolve automatically")
    require(calls["automatic_precision_calibration"] is True, "automatic precision calibration is required")
    require(float(calls["target_precision"]) == 0.99, "the aspirational precision target must remain 99%")
    require(calls["target_precision_is_guaranteed"] is False, "99% accuracy must never be guaranteed")
    require(int(calls["minimum_resolved_calls_before_calibration"]) >= 50, "calibration requires enough resolved calls")
    require(calls["confidence_threshold_bounds"] == [72, 95], "confidence calibration must remain bounded")
    require(calls["risk_rules_may_only_tighten"] is True, "learning may only tighten risk filters")
    require(calls["no_live_execution_from_training"] is True, "training may never auto-execute orders")

    exits = rules["sell_exit_management"]
    require(exits["automatic_sell_orders"] is False, "automatic SELL orders must remain disabled")
    require(exits["human_confirmation_required"] is True, "SELL requires human confirmation")
    require(exits["fresh_groww_price_required_before_order"] is True, "SELL requires a fresh Groww price")

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
        "BROAD_SCAN_BATCH_SIZE": universe["broad_scan_batch_size"],
        "STARTING_CAPITAL_INR": objective["current_starting_capital_inr"],
        "STRETCH_TARGET_INR": objective["stretch_target_inr"],
        "TARGET_HORIZON_DAYS": objective["target_horizon_calendar_days"],
        "NEWS_PRIORITY_INTERVAL_SECONDS": continuous["priority_news_interval_seconds"],
        "NEWS_BROAD_INTERVAL_SECONDS": continuous["broad_news_rotation_interval_seconds"],
        "MATERIAL_PRICE_MOVE_PCT": continuous["material_price_move_trigger_pct"],
        "PAPER_OBSERVATION_DAYS": calls["paper_observation_days"],
        "CALL_TARGET_PRECISION": calls["target_precision"],
        "CALL_MIN_CALIBRATION_SAMPLES": calls["minimum_resolved_calls_before_calibration"],
        "CALL_CONFIDENCE_MIN": calls["confidence_threshold_bounds"][0],
        "CALL_CONFIDENCE_MAX": calls["confidence_threshold_bounds"][1],
    }
    for key, expected in numeric_env.items():
        actual = env.get(key)
        require(actual is not None, f"{key} is missing from backend/.env.example")
        require(float(actual) == float(expected), f"{key}={actual} does not match rules contract value {expected}")

    for key in ("ENABLE_GROWW_FEED", "ENABLE_AUTO_LLM", "ENABLE_SEMANTIC_MEMORY", "FREE_NEWS_ENABLED", "NEWS_REQUIRED_FOR_BUY"):
        require(env_bool(env, key), f"{key} must remain enabled in the production example")

    require(env.get("APP_ENV") == "production", "example environment must default to production")
    require(env.get("SCANNER_UNIVERSE_MODE") == "full_nse_equity", "production example must default to the full NSE equity universe")
    require(env.get("DEFAULT_TRADING_MODE") == "intraday", "backend default mode must be intraday until the UI selection is made")
    require(int(env.get("MACD_FAST_PERIOD", "0")) == 12, "MACD fast period must be 12")
    require(int(env.get("MACD_SLOW_PERIOD", "0")) == 26, "MACD slow period must be 26")
    require(int(env.get("MACD_SIGNAL_PERIOD", "0")) == 9, "MACD signal period must be 9")
    require(float(env.get("DEFAULT_PORTFOLIO_VALUE", "0")) == 20000.0, "default portfolio value must reflect the current ₹20,000 Groww balance")
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
