from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Iterable, Mapping

from .strategy_registry import StrategyDefinition, StrategyOutput


@dataclass(frozen=True)
class ReplayPoint:
    """
    One point-in-time decision snapshot.

    features is the only object passed to a strategy evaluator. All fields describing
    the next observation are reserved strictly for post-decision scoring, which prevents
    look-ahead leakage into the signal itself.
    """

    timestamp: str
    features: Mapping[str, float]
    next_price: float
    current_price: float
    next_timestamp: str | None = None
    interval_high: float | None = None
    interval_low: float | None = None
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    impact_bps: float = 0.0
    charges_bps: float | None = None


@dataclass(frozen=True)
class ReplayTrade:
    strategy_id: str
    family: str
    direction: str
    entry_timestamp: str
    exit_timestamp: str
    decision_price: float
    modeled_entry_price: float
    modeled_exit_price: float
    gross_pnl_bps: float
    spread_bps: float
    slippage_bps: float
    impact_bps: float
    charges_bps: float
    net_pnl_bps: float
    mfe_bps: float
    mae_bps: float
    time_to_mfe_seconds: float | None
    time_to_mae_seconds: float | None
    decision_score: float
    expected_return_bps: float
    reason_codes: tuple[str, ...]
    sample: str


@dataclass(frozen=True)
class StrategyReplayResult:
    strategy_id: str
    family: str
    trades: int
    gross_pnl_bps: float
    estimated_cost_bps: float
    net_pnl_bps: float
    win_rate_pct: float
    profit_factor: float
    max_drawdown_bps: float
    expectancy_bps: float
    out_of_sample_trades: int
    out_of_sample_net_pnl_bps: float
    out_of_sample_expectancy_bps: float
    trades_detail: tuple[ReplayTrade, ...]


class ReplayTournament:
    """
    Runs every registered strategy on the same immutable point-in-time tape.

    The evaluator sees only information available at the decision timestamp. Future
    prices/highs/lows are consumed only after the strategy has emitted a direction and
    are used to score modeled fills, MFE/MAE and exit quality. The tape is split in time
    order so ranking evidence includes a held-out out-of-sample segment.
    """

    def __init__(
        self,
        estimated_round_trip_cost_bps: float = 25.0,
        *,
        training_fraction: float = 0.70,
    ) -> None:
        if estimated_round_trip_cost_bps < 0:
            raise ValueError("estimated_round_trip_cost_bps must be non-negative")
        if not 0.5 <= training_fraction < 1.0:
            raise ValueError("training_fraction must be between 0.5 and 1.0")
        self.estimated_round_trip_cost_bps = float(estimated_round_trip_cost_bps)
        self.training_fraction = float(training_fraction)

    @staticmethod
    def _seconds(start: str, end: str | None) -> float | None:
        if not end:
            return None
        try:
            left = datetime.fromisoformat(start.replace("Z", "+00:00"))
            right = datetime.fromisoformat(end.replace("Z", "+00:00"))
            return max(0.0, (right - left).total_seconds())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bounded(value: float, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if isfinite(parsed) else default

    def _trade(
        self,
        strategy: StrategyDefinition,
        output: StrategyOutput,
        point: ReplayPoint,
        *,
        sample: str,
    ) -> ReplayTrade | None:
        direction = output.direction.upper().strip()
        if direction not in {"LONG", "SHORT"}:
            return None
        if point.current_price <= 0 or point.next_price <= 0:
            return None

        spread = max(0.0, self._bounded(point.spread_bps))
        slippage = max(0.0, self._bounded(point.slippage_bps))
        impact = max(0.0, self._bounded(point.impact_bps))
        explicit_charges = point.charges_bps
        if explicit_charges is None:
            charges = max(0.0, self.estimated_round_trip_cost_bps - spread - slippage - impact)
        else:
            charges = max(0.0, self._bounded(explicit_charges))

        entry_penalty = (spread / 2.0 + slippage / 2.0 + impact / 2.0) / 10_000.0
        exit_penalty = entry_penalty
        if direction == "LONG":
            entry = point.current_price * (1.0 + entry_penalty)
            exit_price = point.next_price * (1.0 - exit_penalty)
            gross_bps = (point.next_price / point.current_price - 1.0) * 10_000.0
            net_bps = (exit_price / entry - 1.0) * 10_000.0 - charges
            high = point.interval_high if point.interval_high and point.interval_high > 0 else max(point.current_price, point.next_price)
            low = point.interval_low if point.interval_low and point.interval_low > 0 else min(point.current_price, point.next_price)
            mfe_bps = (high / point.current_price - 1.0) * 10_000.0
            mae_bps = (low / point.current_price - 1.0) * 10_000.0
        else:
            entry = point.current_price * (1.0 - entry_penalty)
            exit_price = point.next_price * (1.0 + exit_penalty)
            gross_bps = (point.current_price / point.next_price - 1.0) * 10_000.0
            net_bps = (entry / exit_price - 1.0) * 10_000.0 - charges
            high = point.interval_high if point.interval_high and point.interval_high > 0 else max(point.current_price, point.next_price)
            low = point.interval_low if point.interval_low and point.interval_low > 0 else min(point.current_price, point.next_price)
            mfe_bps = (point.current_price / low - 1.0) * 10_000.0
            mae_bps = (point.current_price / high - 1.0) * 10_000.0

        elapsed = self._seconds(point.timestamp, point.next_timestamp)
        time_to_mfe = elapsed if elapsed is not None and abs(mfe_bps) > 0 else None
        time_to_mae = elapsed if elapsed is not None and abs(mae_bps) > 0 else None

        return ReplayTrade(
            strategy_id=strategy.strategy_id,
            family=strategy.family,
            direction=direction,
            entry_timestamp=point.timestamp,
            exit_timestamp=point.next_timestamp or point.timestamp,
            decision_price=round(point.current_price, 6),
            modeled_entry_price=round(entry, 6),
            modeled_exit_price=round(exit_price, 6),
            gross_pnl_bps=round(gross_bps, 3),
            spread_bps=round(spread, 3),
            slippage_bps=round(slippage, 3),
            impact_bps=round(impact, 3),
            charges_bps=round(charges, 3),
            net_pnl_bps=round(net_bps, 3),
            mfe_bps=round(mfe_bps, 3),
            mae_bps=round(mae_bps, 3),
            time_to_mfe_seconds=time_to_mfe,
            time_to_mae_seconds=time_to_mae,
            decision_score=round(float(output.score), 6),
            expected_return_bps=round(float(output.expected_return_bps), 3),
            reason_codes=tuple(output.reason_codes),
            sample=sample,
        )

    @staticmethod
    def _max_drawdown(net_returns: Iterable[float]) -> float:
        equity = 0.0
        peak = 0.0
        worst = 0.0
        for value in net_returns:
            equity += value
            peak = max(peak, equity)
            worst = max(worst, peak - equity)
        return worst

    def run(
        self,
        strategies: Iterable[StrategyDefinition],
        tape: Iterable[ReplayPoint],
    ) -> tuple[StrategyReplayResult, ...]:
        points = tuple(tape)
        if len(points) <= 1:
            split = len(points)
        else:
            split = min(len(points) - 1, max(1, int(len(points) * self.training_fraction)))

        results: list[StrategyReplayResult] = []
        for strategy in strategies:
            trades: list[ReplayTrade] = []
            for index, point in enumerate(points):
                output = strategy.evaluator(point.features)
                trade = self._trade(
                    strategy,
                    output,
                    point,
                    sample="IN_SAMPLE" if index < split else "OUT_OF_SAMPLE",
                )
                if trade is not None:
                    trades.append(trade)

            gross = sum(t.gross_pnl_bps for t in trades)
            net = sum(t.net_pnl_bps for t in trades)
            costs = sum(t.gross_pnl_bps - t.net_pnl_bps for t in trades)
            wins = sum(1 for t in trades if t.net_pnl_bps > 0)
            gross_profit = sum(t.net_pnl_bps for t in trades if t.net_pnl_bps > 0)
            gross_loss = sum(t.net_pnl_bps for t in trades if t.net_pnl_bps < 0)
            profit_factor = (
                gross_profit / abs(gross_loss)
                if gross_loss < 0
                else (99.0 if gross_profit > 0 else 0.0)
            )
            out = [t for t in trades if t.sample == "OUT_OF_SAMPLE"]
            out_net = sum(t.net_pnl_bps for t in out)

            results.append(
                StrategyReplayResult(
                    strategy_id=strategy.strategy_id,
                    family=strategy.family,
                    trades=len(trades),
                    gross_pnl_bps=round(gross, 3),
                    estimated_cost_bps=round(costs, 3),
                    net_pnl_bps=round(net, 3),
                    win_rate_pct=round(wins / len(trades) * 100.0, 3) if trades else 0.0,
                    profit_factor=round(profit_factor, 3),
                    max_drawdown_bps=round(self._max_drawdown(t.net_pnl_bps for t in trades), 3),
                    expectancy_bps=round(net / len(trades), 3) if trades else 0.0,
                    out_of_sample_trades=len(out),
                    out_of_sample_net_pnl_bps=round(out_net, 3),
                    out_of_sample_expectancy_bps=round(out_net / len(out), 3) if out else 0.0,
                    trades_detail=tuple(trades),
                )
            )

        return tuple(
            sorted(
                results,
                key=lambda value: (
                    value.out_of_sample_expectancy_bps,
                    value.net_pnl_bps,
                    value.trades,
                ),
                reverse=True,
            )
        )
