from __future__ import annotations

from dataclasses import dataclass

from .domain import Action, Decision, LiveFeatures


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class EngineConfig:
    min_live_budget: int = 10_000
    max_live_budget: int = 100_000
    max_spread_bps: float = 85.0
    min_rvol_for_momentum: float = 1.6
    circuit_buffer_pct: float = 1.0


class ListingDecisionEngine:
    """
    Bootstrap scorer.

    Production versions will replace fixed weights with versioned, replay-validated
    champion/challenger weights. Candles/patterns remain features, not standalone commands.
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()

    def decide(self, f: LiveFeatures, requested_budget: int) -> Decision:
        budget = max(self.config.min_live_budget, min(self.config.max_live_budget, int(requested_budget)))
        reasons: list[str] = []

        if not f.data_fresh:
            return Decision(Action.HALTED, 0.0, 100.0, 0, ("STALE_MARKET_DATA",))
        if f.ltp <= 0 or f.vwap <= 0:
            return Decision(Action.WAIT, 0.0, 100.0, 0, ("MISSING_PRICE_OR_VWAP",))
        if f.spread_bps > self.config.max_spread_bps:
            return Decision(Action.WAIT, 0.0, 95.0, 0, ("SPREAD_TOO_WIDE",))
        if f.circuit_distance_pct is not None and f.circuit_distance_pct <= self.config.circuit_buffer_pct:
            return Decision(Action.WAIT, 0.0, 95.0, 0, ("CIRCUIT_TRAP_RISK",))

        trend = 50.0 + (18.0 if f.ltp > f.vwap else -18.0)
        volume = _clamp(35.0 + min(f.rvol, 5.0) * 14.0)
        order_flow = _clamp(50.0 + f.depth_imbalance * 45.0)
        market = _clamp(50.0 + f.nifty_return_pct * 8.0 + f.sector_return_pct * 10.0)

        opening = 50.0
        if f.first_5m_high and f.ltp > f.first_5m_high:
            opening += 22.0
            reasons.append("ABOVE_5M_ORB")
        if f.first_5m_low and f.ltp < f.first_5m_low:
            opening -= 22.0
            reasons.append("BELOW_5M_ORB")

        premium = 50.0
        if f.listing_price and f.issue_price and f.issue_price > 0:
            listing_gain = (f.listing_price / f.issue_price - 1.0) * 100.0
            if listing_gain > 60:
                premium -= 12
                reasons.append("EXTREME_LISTING_PREMIUM")
            elif 5 <= listing_gain <= 35:
                premium += 8

        score = _clamp(
            trend * 0.24
            + volume * 0.22
            + order_flow * 0.20
            + opening * 0.18
            + market * 0.10
            + premium * 0.06
        )

        if f.rvol >= self.config.min_rvol_for_momentum:
            reasons.append("RVOL_CONFIRMED")
        if f.depth_imbalance > 0.18:
            reasons.append("BUY_DEPTH_IMBALANCE")
        elif f.depth_imbalance < -0.18:
            reasons.append("SELL_DEPTH_IMBALANCE")

        confidence = _clamp(50 + abs(score - 50) * 1.4)

        if score >= 72 and f.rvol >= self.config.min_rvol_for_momentum:
            action = Action.BUILD_LONG if score >= 82 else Action.PROBE_LONG
        elif score <= 28 and f.rvol >= self.config.min_rvol_for_momentum and f.shortable:
            action = Action.BUILD_SHORT if score <= 18 else Action.PROBE_SHORT
        elif score <= 28 and not f.shortable:
            action = Action.WAIT
            reasons.append("SHORT_NOT_ELIGIBLE")
        else:
            action = Action.WAIT
            reasons.append("NO_CONFIRMED_EDGE")

        return Decision(action, round(score, 2), round(confidence, 2), budget, tuple(reasons))
