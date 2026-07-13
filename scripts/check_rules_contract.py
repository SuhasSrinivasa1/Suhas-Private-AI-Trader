#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "config" / "trading_rules.json"
ENV_EXAMPLE = ROOT / "backend" / ".env.example"


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

    require(rules["timezone"] == "Asia/Kolkata", "timezone must remain Asia/Kolkata")
    require(rules["execution"]["paper_mode_default"] is True, "paper mode must default to true")
    require(rules["execution"]["live_execution_default"] is False, "live execution must default to false")
    require(rules["execution"]["human_confirmation_required"] is True, "human confirmation is mandatory")
    require(rules["execution"]["server_side_revalidation_required"] is True, "server-side revalidation is mandatory")
    require(rules["execution"]["never_auto_execute_from_llm"] is True, "LLM must never auto-execute")

    risk = rules["risk"]
    require(risk["max_risk_per_trade_pct"] <= 1.0, "max risk per trade cannot exceed 1% by default")
    require(risk["min_reward_risk_ratio"] >= 2.0, "minimum reward/risk cannot be below 2.0")
    require(risk["max_chase_pct"] <= 1.5, "anti-chase limit cannot exceed 1.5% by default")
    require(risk["min_independent_confirmation_sources"] >= 2, "at least two confirmation sources are required")

    required_checks = {"news", "technical_setup", "portfolio_exposure"}
    require(required_checks.issubset(set(rules["mandatory_checks"])), "mandatory checks are incomplete")

    scanner = rules["scanner"]
    require(scanner["dynamic_universe"] is True, "scanner must remain dynamic")
    require(scanner["fixed_watchlist_only"] is False, "scanner must not be fixed-watchlist-only")
    require("risk_veto" in scanner["agents"], "risk veto agent is required")

    privacy = rules["privacy"]
    require(privacy["frontend_must_not_store_secrets"] is True, "frontend secret storage must be forbidden")
    require(privacy["local_llm_advisory_only"] is True, "local LLM must remain advisory only")

    expected_env = {
        "MAX_RISK_PER_TRADE_PCT": str(risk["max_risk_per_trade_pct"]),
        "MIN_REWARD_RISK_RATIO": str(risk["min_reward_risk_ratio"]),
        "MAX_CHASE_PCT": str(risk["max_chase_pct"]),
        "MAX_PRICE_AGE_SECONDS": str(rules["execution"]["max_quote_age_seconds"]),
        "MIN_CONFIRMATION_SOURCES": str(risk["min_independent_confirmation_sources"]),
        "MAX_POSITION_VALUE_PCT": str(risk["max_position_value_pct"]),
        "MIN_BUY_CONFIDENCE": str(risk["min_buy_confidence"]),
        "MIN_WATCH_CONFIDENCE": str(risk["min_watch_confidence"]),
        "SCAN_INTERVAL_SECONDS": str(scanner["scan_interval_seconds"]),
        "DEEP_SCAN_CANDIDATES": str(scanner["deep_scan_candidates"]),
        "MAX_DISPLAY_OPPORTUNITIES": str(scanner["max_display_opportunities"]),
        "SIGNAL_VALID_SECONDS": str(rules["execution"]["signal_valid_seconds"]),
    }

    for key, expected in expected_env.items():
        actual = env.get(key)
        require(actual is not None, f"{key} is missing from backend/.env.example")
        require(float(actual) == float(expected), f"{key}={actual} does not match rules contract value {expected}")

    require(env.get("GROWW_LIVE_EXECUTION_ENABLED", "false").lower() not in {"1", "true", "yes", "on"},
            "Groww live execution must be disabled in the example environment")

    print("rules contract passed")


if __name__ == "__main__":
    main()
