from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .strategy_registry import StrategyDefinition, StrategyOutput


@dataclass(frozen=True)
class ReplayPoint:
    timestamp: str
    features: Mapping[str, float]
    next_price: float
    current_price: float


@dataclass(frozen=True)
class StrategyReplayResult:
    strategy_id: str
    trades: int
    gross_pnl_bps: float
    estimated_cost_bps: float
    net_pnl_bps: float
    win_rate_pct: float


class ReplayTournament:
    """
    Runs all registered strategies over the same historical point-in-time tape.

    This is intentionally a tournament, not an optimizer that keeps searching until
    something wins. Every strategy version gets identical data, cost assumptions and
    timestamps. Results are stored even when all strategies lose.
    """

    def __init__(self, estimated_round_trip_cost_bps: float = 25.0) -> None:
        self.estimated_round_trip_cost_bps = estimated_round_trip_cost_bps

    def run(
        self,
        strategies: Iterable[StrategyDefinition],
        tape: Iterable[ReplayPoint],
    ) -> tuple[StrategyReplayResult, ...]:
        points = tuple(tape)
        results: list[StrategyReplayResult] = []

        for strategy in strategies:
            gross = 0.0
            wins = 0
            trades = 0

            for point in points:
                output: StrategyOutput = strategy.evaluator(point.features)
                direction = output.direction.upper()
                if direction not in {"LONG", "SHORT"}:
                    continue
                if point.current_price <= 0:
                    continue

                realized_bps = (point.next_price / point.current_price - 1.0) * 10_000.0
                if direction == "SHORT":
                    realized_bps *= -1.0

                gross += realized_bps
                trades += 1
                if realized_bps > self.estimated_round_trip_cost_bps:
                    wins += 1

            cost = trades * self.estimated_round_trip_cost_bps
            net = gross - cost
            win_rate = wins / trades * 100.0 if trades else 0.0
            results.append(
                StrategyReplayResult(
                    strategy_id=strategy.strategy_id,
                    trades=trades,
                    gross_pnl_bps=round(gross, 3),
                    estimated_cost_bps=round(cost, 3),
                    net_pnl_bps=round(net, 3),
                    win_rate_pct=round(win_rate, 3),
                )
            )

        return tuple(sorted(results, key=lambda x: x.net_pnl_bps, reverse=True))
