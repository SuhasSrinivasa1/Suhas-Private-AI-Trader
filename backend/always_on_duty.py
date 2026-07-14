from __future__ import annotations

import asyncio
import os
import time as time_module
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable


OFF_HOURS_RESEARCH_INTERVAL_SECONDS = max(
    300, int(os.getenv("OFF_HOURS_RESEARCH_INTERVAL_SECONDS", "900"))
)
OFF_HOURS_LLM_INTERVAL_SECONDS = max(
    900, int(os.getenv("OFF_HOURS_LLM_INTERVAL_SECONDS", "1800"))
)
OFF_HOURS_CANDIDATE_VALID_SECONDS = max(
    900, int(os.getenv("OFF_HOURS_CANDIDATE_VALID_SECONDS", "21600"))
)
OFF_HOURS_DEEP_CANDIDATES = max(
    3, min(20, int(os.getenv("OFF_HOURS_DEEP_CANDIDATES", "8")))
)


class AlwaysOnDutyEngine:
    """Groww-backed off-hours research without creating actionable BUY calls."""

    def __init__(
        self,
        core: Any,
        runtime: Any,
        raw_mode_scan: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    ) -> None:
        self.core = core
        self.runtime = runtime
        self.raw_mode_scan = raw_mode_scan
        self._lock = asyncio.Lock()
        self._last_run_monotonic = 0.0
        self._last_llm_monotonic = 0.0
        self._last_top_signature = ""
        self._snapshot: dict[str, Any] = {
            "status": "starting",
            "mode": "off_hours_research",
            "market_open": False,
            "items": [],
            "last_run_at": None,
            "last_error": None,
            "llm_policy": "material changes or scheduled off-hours brief; never every tick",
            "data_policy": "Groww data only; no mock or synthetic prices",
            "execution_eligible": False,
        }

    def status(self) -> dict[str, Any]:
        market_open = bool(self.core._market_open_now())
        current_mode = "live_market_scan" if market_open else "off_hours_research"
        snapshot = dict(self._snapshot)
        snapshot.update(
            {
                "mode": current_mode,
                "market_open": market_open,
                "broker_configured": bool(self.core._broker_configured()),
                "live_execution_enabled": bool(
                    self.core.GROWW_LIVE_EXECUTION_ENABLED
                ),
                "buy_sell_execution_eligible": bool(
                    market_open and self.core.GROWW_LIVE_EXECUTION_ENABLED
                ),
                "off_hours_interval_seconds": OFF_HOURS_RESEARCH_INTERVAL_SECONDS,
                "off_hours_llm_interval_seconds": OFF_HOURS_LLM_INTERVAL_SECONDS,
            }
        )
        if market_open:
            snapshot["status"] = "live_market_scan"
        return snapshot

    @staticmethod
    def _as_watch_candidate(item: dict[str, Any], generated_at: str) -> dict[str, Any]:
        result = dict(item)
        model_state = str(result.get("state") or result.get("action") or "WAIT")
        if model_state in {"BUY", "WATCHING", "WATCH"}:
            result["state"] = "WATCHING"
            result["action"] = "WATCH"
        else:
            result["state"] = "WAIT"
            result["action"] = "WAIT"
        result["model_state_before_session_gate"] = model_state
        result["session_context"] = "off_hours_research"
        result["market_open"] = False
        result["execution_eligible"] = False
        result["paper_call_logged"] = False
        result["requires_live_revalidation"] = True
        result["price_context"] = "Groww latest available / prior-session market data"
        result["generated_at"] = generated_at
        result["valid_for_seconds"] = OFF_HOURS_CANDIDATE_VALID_SECONDS
        reasons = list(result.get("reasons") or [])
        reasons.append(
            "Off-hours research only. Recheck live price, spread, volume, MACD, news and risk after NSE opens."
        )
        result["reasons"] = list(dict.fromkeys(reasons))
        return result

    async def run_once(
        self, *, force: bool = False, reason: str = "scheduled"
    ) -> dict[str, Any]:
        if self.core._market_open_now():
            return self.status()
        if not self.core._broker_configured():
            self._snapshot.update(
                {
                    "status": "broker_not_configured",
                    "last_error": "Groww credentials are required.",
                }
            )
            return self.status()

        now_mono = time_module.monotonic()
        if (
            not force
            and self._last_run_monotonic
            and now_mono - self._last_run_monotonic
            < OFF_HOURS_RESEARCH_INTERVAL_SECONDS
        ):
            return self.status()

        async with self._lock:
            now_mono = time_module.monotonic()
            if (
                not force
                and self._last_run_monotonic
                and now_mono - self._last_run_monotonic
                < OFF_HOURS_RESEARCH_INTERVAL_SECONDS
            ):
                return self.status()

            started = time_module.monotonic()
            generated_at = datetime.now(timezone.utc).isoformat()
            try:
                self.core.latest_market_regime = (
                    await self.core._market_regime_score()
                )
                coarse = await self.core._coarse_scan()
                selected = coarse[:OFF_HOURS_DEEP_CANDIDATES]
                deep = await asyncio.gather(
                    *(self.raw_mode_scan(item) for item in selected),
                    return_exceptions=True,
                )
                items = [
                    self._as_watch_candidate(item, generated_at)
                    for item in deep
                    if isinstance(item, dict)
                ]
                items.sort(
                    key=lambda item: (
                        item.get("state") == "WATCHING",
                        float(item.get("rank_score") or item.get("confidence") or 0),
                    ),
                    reverse=True,
                )
                for item in items:
                    item["recommendation_id"] = self.core._signal_identity(item)
                    self.core.recommendation_cache[item["recommendation_id"]] = item

                self.core.latest_opportunities = {
                    f"{item.get('exchange', 'NSE')}:{item['symbol']}": item
                    for item in items
                    if item.get("symbol")
                }
                self.core.last_scan_at = generated_at
                self.core.last_scan_error = None
                self._last_run_monotonic = time_module.monotonic()

                top_signature = "|".join(
                    f"{item.get('symbol')}:{round(float(item.get('rank_score') or item.get('confidence') or 0), 1)}"
                    for item in items[:5]
                )
                should_brief = (
                    top_signature != self._last_top_signature
                    or self._last_llm_monotonic == 0
                    or self._last_run_monotonic - self._last_llm_monotonic
                    >= OFF_HOURS_LLM_INTERVAL_SECONDS
                )
                if should_brief and items:
                    bucket = int(
                        datetime.now(timezone.utc).timestamp()
                        // OFF_HOURS_LLM_INTERVAL_SECONDS
                    )
                    asyncio.create_task(
                        self.runtime.trigger_llm_analysis(
                            symbol="MARKET",
                            event_type="off_hours_market_research",
                            event_key=f"offhours:{bucket}:{top_signature}",
                            payload={
                                "reason": reason,
                                "market_regime": self.core.latest_market_regime,
                                "candidates": items[:5],
                                "execution_eligible": False,
                                "requires_live_revalidation": True,
                            },
                        )
                    )
                    self._last_llm_monotonic = self._last_run_monotonic
                    self._last_top_signature = top_signature

                self._snapshot = {
                    "status": "ready",
                    "mode": "off_hours_research",
                    "market_open": False,
                    "items": items,
                    "best_candidate": items[0] if items else None,
                    "last_run_at": generated_at,
                    "last_error": None,
                    "reason": reason,
                    "duration_seconds": round(
                        time_module.monotonic() - started, 2
                    ),
                    "rotation_batch_size": len(coarse),
                    "universe_size": len(self.core.SCANNER_UNIVERSE),
                    "llm_brief_requested": bool(should_brief and items),
                    "llm_policy": "material changes or every configured off-hours interval",
                    "data_policy": "Groww data only; no mock or synthetic prices",
                    "execution_eligible": False,
                }
                self.runtime.store.update_provider_health(
                    "off_hours_research",
                    ok=True,
                    latency_ms=(time_module.monotonic() - started) * 1000,
                    message=(
                        f"Always-on Groww research completed for {len(items)} "
                        "deep candidates; live confirmation remains mandatory."
                    ),
                )
                await self.core.broadcast(
                    {
                        "type": "opportunities",
                        "items": items,
                        "prices": self.core.latest_prices,
                        "market_regime": self.core.latest_market_regime,
                        "scan_at": generated_at,
                        "scan_mode": "off_hours_research",
                        "execution_eligible": False,
                        "ts": generated_at,
                    }
                )
                await self.core.broadcast(
                    {
                        "type": "duty_status",
                        "snapshot": self.status(),
                        "ts": generated_at,
                    }
                )
                return self.status()
            except Exception as exc:
                message = self.core._mask_error(exc)
                self.core.last_scan_error = message
                self._snapshot.update(
                    {
                        "status": "error",
                        "last_run_at": generated_at,
                        "last_error": message,
                        "items": self._snapshot.get("items", []),
                    }
                )
                self.runtime.store.update_provider_health(
                    "off_hours_research",
                    ok=False,
                    latency_ms=(time_module.monotonic() - started) * 1000,
                    message=f"{exc.__class__.__name__}: off-hours research failed",
                )
                return self.status()

    async def run_loop(self) -> None:
        while True:
            try:
                if (
                    self.core._broker_configured()
                    and not self.core._market_open_now()
                ):
                    await self.run_once(force=False, reason="scheduled")
            except Exception:
                pass
            await asyncio.sleep(30)
