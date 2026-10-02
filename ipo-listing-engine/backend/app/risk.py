from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionSnapshot:
    auth_ok: bool
    calendar_ready: bool
    market_data_fresh: bool
    position_reconciled: bool
    order_state_certain: bool
    spread_bps: float
    estimated_impact_bps: float
    circuit_distance_pct: float | None
    shortable: bool
    side: str


@dataclass(frozen=True)
class RiskResult:
    allowed: bool
    reasons: tuple[str, ...]


class ImmutableRiskEngine:
    """Operational veto layer. Strategies cannot override these checks."""

    def __init__(
        self,
        *,
        max_spread_bps: float = 85.0,
        max_impact_bps: float = 75.0,
        min_circuit_distance_pct: float = 1.0,
    ) -> None:
        self.max_spread_bps = max_spread_bps
        self.max_impact_bps = max_impact_bps
        self.min_circuit_distance_pct = min_circuit_distance_pct

    def validate(self, s: ExecutionSnapshot) -> RiskResult:
        reasons: list[str] = []
        if not s.auth_ok:
            reasons.append("AUTH_UNCERTAIN")
        if not s.calendar_ready:
            reasons.append("EXCHANGE_CALENDAR_NOT_READY")
        if not s.market_data_fresh:
            reasons.append("STALE_MARKET_DATA")
        if not s.position_reconciled:
            reasons.append("POSITION_MISMATCH")
        if not s.order_state_certain:
            reasons.append("ORDER_STATE_UNCERTAIN")
        if s.spread_bps > self.max_spread_bps:
            reasons.append("SPREAD_TOO_WIDE")
        if s.estimated_impact_bps > self.max_impact_bps:
            reasons.append("MARKET_IMPACT_TOO_HIGH")
        if s.circuit_distance_pct is not None and s.circuit_distance_pct <= self.min_circuit_distance_pct:
            reasons.append("CIRCUIT_TRAP_RISK")
        if s.side.upper() == "SELL_SHORT" and not s.shortable:
            reasons.append("SHORT_NOT_ELIGIBLE")
        return RiskResult(not reasons, tuple(reasons))
