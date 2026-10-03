from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Iterable


@dataclass(frozen=True)
class StrategyFamily:
    family_id: str
    name: str
    phase: str
    description: str


@dataclass(frozen=True)
class FamilyEvidence:
    family_id: str
    trades: int = 0
    wins: int = 0
    net_pnl_bps: float = 0.0
    gross_profit_bps: float = 0.0
    gross_loss_bps: float = 0.0
    max_drawdown_bps: float = 0.0
    last_20_net_bps: float = 0.0

    @property
    def win_rate_pct(self) -> float:
        return round(self.wins / self.trades * 100.0, 2) if self.trades else 0.0

    @property
    def expectancy_bps(self) -> float:
        return round(self.net_pnl_bps / self.trades, 3) if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss_bps < 0:
            return round(self.gross_profit_bps / abs(self.gross_loss_bps), 3)
        return 0.0 if self.gross_profit_bps <= 0 else 99.0


STRATEGY_FAMILIES: tuple[StrategyFamily, ...] = (
    StrategyFamily("preopen_equilibrium", "Pre-open Equilibrium", "LISTING_DAY", "Price discovery stability and auction imbalance."),
    StrategyFamily("opening_drive", "Opening Drive", "LISTING_DAY", "Strong early directional expansion after continuous trading opens."),
    StrategyFamily("orb_5m", "5m Opening Range Breakout", "LISTING_DAY", "Break and hold outside the first five-minute range."),
    StrategyFamily("orb_15m", "15m Opening Range Breakout", "LISTING_DAY", "Break and hold outside the first fifteen-minute range."),
    StrategyFamily("gap_go_fade", "Gap Continuation / Fade", "LISTING_DAY", "Continuation or rejection of the listing premium/discount."),
    StrategyFamily("vwap_hold_reclaim", "VWAP Hold / Reclaim", "ALL", "Acceptance, pullback and reclaim around VWAP."),
    StrategyFamily("breakout_retest", "Breakout Retest", "ALL", "Breakout followed by successful retest and continuation."),
    StrategyFamily("failed_breakout", "Failed Breakout / Breakdown", "ALL", "Failure at an obvious level followed by reversal."),
    StrategyFamily("liquidity_sweep", "Liquidity Sweep", "ALL", "Sweep of visible liquidity followed by rejection or continuation."),
    StrategyFamily("exhaustion_reversal", "Exhaustion Reversal", "ALL", "Volume/velocity exhaustion near an extreme."),
    StrategyFamily("orderflow_tape", "Order Flow + Tape Acceleration", "ALL", "Depth imbalance and trade-rate acceleration."),
    StrategyFamily("relative_strength", "Relative Strength", "ALL", "Outperformance/underperformance versus NIFTY and sector."),
    StrategyFamily("circuit_pressure", "Circuit Pressure", "LISTING_DAY", "Queue pressure, fill probability and circuit proximity."),
    StrategyFamily("avwap_reclaim", "Listing AVWAP Reclaim", "D1_D30", "Reclaim/hold around listing-anchored VWAP."),
    StrategyFamily("healthy_pullback", "Healthy Pullback", "D2_D10", "Controlled retracement with structure intact."),
    StrategyFamily("post_ipo_base", "Post-IPO Base Breakout", "D5_D30", "Breakout from a multi-session post-listing base."),
    StrategyFamily("volume_revival", "Volume Revival", "D5_D30", "Renewed participation after a quiet digestion period."),
    StrategyFamily("intraday_fade", "Post-listing Intraday Fade", "D1_D30", "Eligible intraday short after structural weakness is confirmed."),
    StrategyFamily("closing_continuation", "Closing Strength Continuation", "D0_D30", "Late-session strength used for delivery hold/next-day continuation."),
)


class StrategyEvidenceStore:
    """
    Small append/update store for aggregated family-level replay evidence.

    The replay pipeline can update it after each session. It contains aggregate
    statistics only; the detailed immutable replay ledger remains the source of truth.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._path = Path(os.getenv("IPO_SENTINEL_STRATEGY_EVIDENCE_FILE", ".runtime/strategy-evidence.json"))

    def _read(self) -> dict[str, FamilyEvidence]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        out: dict[str, FamilyEvidence] = {}
        for item in raw.get("families", []):
            try:
                evidence = FamilyEvidence(**item)
                out[evidence.family_id] = evidence
            except Exception:
                continue
        return out

    def all(self) -> dict[str, FamilyEvidence]:
        with self._lock:
            return self._read()

    def replace(self, evidence: Iterable[FamilyEvidence]) -> None:
        payload = {"families": [asdict(item) for item in evidence]}
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self._path)


def promotion_status(e: FamilyEvidence) -> str:
    if e.trades < 10:
        return "RESEARCH"
    if e.trades < 30:
        return "CHALLENGER"
    if (
        e.expectancy_bps > 0
        and e.profit_factor >= 1.15
        and e.max_drawdown_bps <= 900
        and e.last_20_net_bps >= 0
    ):
        return "CHAMPION"
    return "CHALLENGER"


def ranking_score(e: FamilyEvidence) -> float:
    """
    Conservative family score: expectancy and profit factor matter, but evidence is
    discounted when sample size is small. Recent negative evidence is penalized.
    """
    if e.trades <= 0:
        return float("-inf")
    sample_weight = min(1.0, e.trades / 40.0)
    pf_component = min(2.0, e.profit_factor) * 12.0
    expectancy_component = max(-100.0, min(100.0, e.expectancy_bps)) * 0.7
    win_component = (e.win_rate_pct - 50.0) * 0.25
    recency_penalty = -12.0 if e.last_20_net_bps < 0 else 0.0
    dd_penalty = min(20.0, max(0.0, e.max_drawdown_bps - 500.0) / 50.0)
    return round(sample_weight * (pf_component + expectancy_component + win_component) + recency_penalty - dd_penalty, 3)


def strategy_summary(store: StrategyEvidenceStore) -> dict:
    evidence = store.all()
    rows = []
    tested = 0
    champions = 0
    challengers = 0

    for family in STRATEGY_FAMILIES:
        e = evidence.get(family.family_id, FamilyEvidence(family_id=family.family_id))
        status = promotion_status(e)
        if e.trades > 0:
            tested += 1
        if status == "CHAMPION":
            champions += 1
        elif status == "CHALLENGER":
            challengers += 1

        rows.append(
            {
                "family_id": family.family_id,
                "name": family.name,
                "phase": family.phase,
                "description": family.description,
                "trades": e.trades,
                "win_rate_pct": e.win_rate_pct,
                "expectancy_bps": e.expectancy_bps,
                "profit_factor": e.profit_factor,
                "max_drawdown_bps": round(e.max_drawdown_bps, 2),
                "last_20_net_bps": round(e.last_20_net_bps, 2),
                "status": status,
                "ranking_score": ranking_score(e),
            }
        )

    eligible = [row for row in rows if row["trades"] > 0]
    top_five = sorted(
        eligible,
        key=lambda row: (row["ranking_score"], row["trades"]),
        reverse=True,
    )[:5]

    return {
        "total_strategy_families": len(STRATEGY_FAMILIES),
        "tested_families": tested,
        "champions": champions,
        "challengers": challengers,
        "untested_families": len(STRATEGY_FAMILIES) - tested,
        "top_five": top_five,
        "families": rows,
        "ranking_note": "Top families are ranked only from recorded replay evidence after costs; untested families are never presented as working.",
    }
