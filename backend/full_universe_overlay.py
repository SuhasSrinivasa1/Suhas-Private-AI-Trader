from __future__ import annotations

import os
from typing import Any

from nse_universe import build_full_nse_universe


def install_full_nse_universe(core: Any) -> None:
    """Upgrade the core scanner to full tradable NSE cash-equity rotating discovery."""
    seed_universe = list(dict.fromkeys(str(symbol).upper() for symbol in core.SCANNER_UNIVERSE if symbol))
    mode = os.getenv("SCANNER_UNIVERSE_MODE", "seed").strip().lower()
    custom = [item.strip().upper() for item in os.getenv("SCANNER_UNIVERSE", "").split(",") if item.strip()]
    if custom:
        universe = list(dict.fromkeys(custom))
    elif mode == "full_nse_equity":
        universe = build_full_nse_universe(seed_universe)
    else:
        universe = seed_universe

    core.SCANNER_UNIVERSE = universe
    core.latest_universe_predictions = {}
    core._full_universe_scan_cursor = 0
    batch_size = max(50, min(500, int(os.getenv("BROAD_SCAN_BATCH_SIZE", "250"))))

    async def rotating_coarse_scan() -> list[dict]:
        if not core.SCANNER_UNIVERSE:
            return []
        size = min(batch_size, len(core.SCANNER_UNIVERSE))
        start_index = core._full_universe_scan_cursor % len(core.SCANNER_UNIVERSE)
        end_index = start_index + size
        if end_index <= len(core.SCANNER_UNIVERSE):
            scan_symbols = core.SCANNER_UNIVERSE[start_index:end_index]
        else:
            scan_symbols = core.SCANNER_UNIVERSE[start_index:] + core.SCANNER_UNIVERSE[: end_index - len(core.SCANNER_UNIVERSE)]
        core._full_universe_scan_cursor = end_index % len(core.SCANNER_UNIVERSE)

        candidates: list[dict] = []
        scanned_at = core._now().isoformat()
        for start in range(0, len(scan_symbols), 50):
            chunk = scan_symbols[start : start + 50]
            ltps, ohlc = await core.asyncio.gather(core._get_ltp_batch(chunk), core._get_ohlc_batch(chunk))
            for symbol, last in ltps.items():
                ranked = core.coarse_rank(
                    symbol=symbol,
                    exchange="NSE",
                    last_price=last,
                    ohlc=ohlc.get(symbol),
                    market_regime_score=core._f(core.latest_market_regime.get("score"), 50),
                )
                score = core._f(ranked.get("coarse_score"), 0)
                ranked["prediction"] = "BULLISH_CANDIDATE" if score >= 70 else "WATCH" if score >= 55 else "LOW_PRIORITY"
                ranked["prediction_is_actionable"] = False
                ranked["scanned_at"] = scanned_at
                core.latest_universe_predictions[f"NSE:{symbol}"] = dict(ranked)
                candidates.append(ranked)
        candidates.sort(key=lambda item: core._f(item.get("coarse_score")), reverse=True)
        return candidates[: core.DEEP_SCAN_CANDIDATES]

    core._coarse_scan = rotating_coarse_scan
