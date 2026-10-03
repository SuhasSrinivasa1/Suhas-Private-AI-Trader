from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping


@dataclass(frozen=True)
class StrategyOutput:
    strategy_id: str
    direction: str
    score: float
    expected_return_bps: float
    expected_risk_bps: float
    reason_codes: tuple[str, ...]
    metadata: Mapping[str, float | str | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    family: str
    version: str
    source: str
    required_features: tuple[str, ...]
    evaluator: Callable[[Mapping[str, float]], StrategyOutput]


class StrategyRegistry:
    """
    Versioned registry for live, shadow and book-derived strategies.

    A strategy may be added to the registry as SHADOW_ONLY before it is eligible for
    execution. Replay can evaluate every registered strategy on the exact same stored
    point-in-time feature tape.
    """

    def __init__(self) -> None:
        self._strategies: dict[str, StrategyDefinition] = {}
        self._live_enabled: set[str] = set()

    def register(self, strategy: StrategyDefinition, *, live_enabled: bool = False) -> None:
        self._strategies[strategy.strategy_id] = strategy
        if live_enabled:
            self._live_enabled.add(strategy.strategy_id)

    def all(self) -> tuple[StrategyDefinition, ...]:
        return tuple(self._strategies.values())

    def live(self) -> tuple[StrategyDefinition, ...]:
        return tuple(s for s in self._strategies.values() if s.strategy_id in self._live_enabled)

    def set_live(self, strategy_id: str, enabled: bool) -> None:
        if strategy_id not in self._strategies:
            raise KeyError(strategy_id)
        if enabled:
            self._live_enabled.add(strategy_id)
        else:
            self._live_enabled.discard(strategy_id)
