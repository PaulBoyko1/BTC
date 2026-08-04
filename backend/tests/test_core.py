from __future__ import annotations

import pytest

from app.research.costs import calculate_execution_cost
from app.research.data import validate_dataset
from app.research.metrics import calculate_metrics, max_drawdown
from app.research.registry import build_default_registry
from app.research.splits import build_walk_forward_folds, purge_and_embargo_indices
from app.research.types import CostModelConfig, MarketType, Trade, WalkForwardConfig


def test_registry_has_initial_five_strategies() -> None:
    registry = build_default_registry()
    ids = {definition.strategy_id for definition in registry.definitions()}
    assert ids == {
        "regression_channel_reversion",
        "regression_extreme_absorption",
        "vwap_reversion",
        "simple_momentum",
        "breakout_retest",
    }


def test_data_integrity_detects_duplicates(deterministic_dataset) -> None:
    duplicate = deterministic_dataset.model_copy(update={
        "candles": deterministic_dataset.candles + [deterministic_dataset.candles[-1]]
    })
    result = validate_dataset(duplicate)
    assert not result.passed
    assert any("Duplicate" in reason for reason in result.reasons)


def test_walk_forward_is_chronological(deterministic_candles) -> None:
    start = deterministic_candles[0].timestamp
    end = deterministic_candles[-1].timestamp + 900
    folds = build_walk_forward_folds(
        start,
        end,
        WalkForwardConfig(train_days=2, validation_days=1, test_days=1, step_days=1),
        maximum_horizon_minutes=60,
    )
    assert folds
    for fold in folds:
        assert fold.train_end == fold.validation_start
        assert fold.validation_end == fold.test_start
        assert fold.train_start < fold.train_end < fold.validation_end < fold.test_end


def test_purge_removes_overlapping_labels(deterministic_candles) -> None:
    test_start = deterministic_candles[100].timestamp
    test_end = deterministic_candles[110].timestamp
    kept, purged, embargoed = purge_and_embargo_indices(
        deterministic_candles,
        deterministic_candles[0].timestamp,
        test_start,
        test_start,
        test_end,
        prediction_horizon_minutes=60,
        maximum_holding_minutes=60,
        embargo_minutes=60,
    )
    assert purged > 0
    assert all(deterministic_candles[index].timestamp < test_start for index in kept)
    assert embargoed == 0  # training ends after test, but the explicit overlap rule removes these first


def test_cost_model_includes_spread_slippage_and_fees() -> None:
    cost = calculate_execution_cost(
        CostModelConfig(),
        entry_notional=100_000,
        exit_notional=101_000,
        holding_seconds=3600,
        market_type=MarketType.SPOT,
    )
    assert cost.fee_cost > 0
    assert cost.spread_cost > 0
    assert cost.slippage_cost > 0
    assert cost.funding_cost == 0
    assert cost.total == cost.fee_cost + cost.spread_cost + cost.slippage_cost


def test_drawdown_and_metrics_are_deterministic() -> None:
    _, fraction, duration = max_drawdown([100, -50, -100, 40], 1000)
    assert fraction == 150 / 1100
    assert duration == 2
    base = dict(
        signal_timestamp=1,
        entry_timestamp=2,
        exit_timestamp=3,
        side="long",
        entry_price=100,
        exit_price=101,
        stop_price=99,
        target_price=102,
        quantity=1,
        gross_pnl=1,
        fee_cost=0.1,
        spread_cost=0.1,
        slippage_cost=0.1,
        funding_cost=0,
        gross_return=0.01,
        mfe=0.02,
        mae=-0.01,
        bars_held=1,
        exit_reason="time",
        target_before_stop=False,
        feature_snapshot={},
    )
    trades = [
        Trade(**base, net_pnl=0.7, net_return=0.007),
        Trade(**{**base, "exit_price": 99, "gross_pnl": -1, "gross_return": -0.01}, net_pnl=-1.3, net_return=-0.013),
    ]
    metrics = calculate_metrics(trades, 1000)
    assert metrics["trade_count"] == 2
    assert metrics["expectancy"] == pytest.approx(-0.3)
    assert metrics["max_consecutive_losses"] == 1
