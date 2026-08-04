from __future__ import annotations

from collections.abc import Iterable

from .strategies import DEFAULT_STRATEGIES, ResearchStrategy
from .types import MarketType, StrategyDefinition


class StrategyRegistry:
    def __init__(self, strategies: Iterable[ResearchStrategy] = ()) -> None:
        self._strategies: dict[tuple[str, str], ResearchStrategy] = {}
        for strategy in strategies:
            self.register(strategy)

    def register(self, strategy: ResearchStrategy) -> None:
        key = (strategy.definition.strategy_id, strategy.definition.strategy_version)
        if key in self._strategies:
            raise ValueError(f"Strategy already registered: {key[0]}@{key[1]}")
        self._strategies[key] = strategy

    def get(self, strategy_id: str, version: str = "1.0.0") -> ResearchStrategy:
        try:
            return self._strategies[(strategy_id, version)]
        except KeyError as exc:
            raise KeyError(f"Unknown strategy: {strategy_id}@{version}") from exc

    def definitions(self) -> list[StrategyDefinition]:
        return sorted(
            (strategy.definition for strategy in self._strategies.values()),
            key=lambda definition: (definition.family, definition.name),
        )

    def validate_compatibility(
        self,
        strategy_id: str,
        version: str,
        asset: str,
        market_type: MarketType,
        source_timeframe_minutes: int,
        prediction_horizon_minutes: int,
    ) -> None:
        definition = self.get(strategy_id, version).definition
        failures: list[str] = []
        if not definition.enabled:
            failures.append("strategy is disabled")
        if asset not in definition.supported_assets:
            failures.append(f"unsupported asset {asset}")
        if market_type not in definition.supported_market_types:
            failures.append(f"unsupported market type {market_type}")
        if source_timeframe_minutes not in definition.supported_source_timeframes:
            failures.append(f"unsupported source timeframe {source_timeframe_minutes}m")
        if prediction_horizon_minutes not in definition.supported_prediction_horizons:
            failures.append(f"unsupported prediction horizon {prediction_horizon_minutes}m")
        if failures:
            raise ValueError("; ".join(failures))


def build_default_registry() -> StrategyRegistry:
    return StrategyRegistry(DEFAULT_STRATEGIES)
