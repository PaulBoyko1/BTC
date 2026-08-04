from __future__ import annotations

import sqlite3

from app.research.engine import ExperimentEngine
from app.research.registry import build_default_registry
from app.research.types import (
    CostModelConfig,
    ExperimentCreate,
    MarketType,
    ValidationPolicy,
    WalkForwardConfig,
)


def make_config(dataset_id: str, candles) -> ExperimentCreate:
    return ExperimentCreate(
        strategy_id="simple_momentum",
        dataset_id=dataset_id,
        asset="BTCUSDT",
        market_type=MarketType.SPOT,
        source_timeframe_minutes=15,
        prediction_horizon_minutes=15,
        start_timestamp=candles[0].timestamp,
        end_timestamp=candles[-1].timestamp + 900,
        parameters={
            "lookback": 4,
            "minimum_return": 0.00001,
            "ema_period": 5,
            "atr_period": 5,
            "stop_atr": 1,
            "target_rr": 1,
            "max_holding_bars": 1,
        },
        parameter_sets=[
            {"lookback": 4, "minimum_return": 0.00001, "ema_period": 5, "atr_period": 5, "stop_atr": 1, "target_rr": 1, "max_holding_bars": 1},
            {"lookback": 6, "minimum_return": 0.00002, "ema_period": 5, "atr_period": 5, "stop_atr": 1, "target_rr": 1.5, "max_holding_bars": 1},
        ],
        walk_forward=WalkForwardConfig(train_days=2, validation_days=1, test_days=1, step_days=1, embargo_minutes=15),
        cost_model=CostModelConfig(taker_fee_bps=1, spread_bps=1, slippage_bps=1),
        validation_policy=ValidationPolicy(minimum_trades=1, minimum_profit_factor=0, minimum_positive_fold_ratio=0, maximum_drawdown_fraction=1, maximum_cost_to_gross_profit=10, maximum_bootstrap_loss_probability=1),
    )


def test_complete_experiment_run_is_stored(storage, deterministic_dataset) -> None:
    registry = build_default_registry()
    storage.sync_strategies(registry.definitions())
    dataset = storage.create_dataset(deterministic_dataset)
    config = make_config(dataset["dataset_id"], deterministic_dataset.candles)
    experiment = storage.create_experiment(config)
    storage.mark_running(experiment["experiment_id"])
    result = ExperimentEngine(registry).run(config, deterministic_dataset)
    storage.save_results(experiment["experiment_id"], result)
    saved = storage.get_experiment(experiment["experiment_id"])
    assert saved["status"] == "completed"
    assert saved["folds"]
    assert "out_of_sample" in saved["metrics"]
    assert saved["baselines"]
    assert len(saved["bootstrap"]) == 2


def test_completed_configuration_is_immutable(storage, deterministic_dataset) -> None:
    registry = build_default_registry()
    storage.sync_strategies(registry.definitions())
    dataset = storage.create_dataset(deterministic_dataset)
    config = make_config(dataset["dataset_id"], deterministic_dataset.candles)
    experiment = storage.create_experiment(config)
    storage.mark_running(experiment["experiment_id"])
    storage.save_results(experiment["experiment_id"], ExperimentEngine(registry).run(config, deterministic_dataset))
    with storage.connect() as connection:
        try:
            connection.execute(
                "UPDATE experiments SET configuration_json='{}' WHERE experiment_id=?",
                (experiment["experiment_id"],),
            )
        except sqlite3.IntegrityError as exc:
            assert "immutable" in str(exc)
        else:
            raise AssertionError("completed experiment configuration was mutable")
