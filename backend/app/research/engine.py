from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from collections import defaultdict
from statistics import mean
from typing import Any, Callable

from .costs import calculate_execution_cost
from .data import slice_candles, validate_dataset
from .metrics import calculate_metrics, degradation
from .multiple_testing import deflated_sharpe_ratio, probability_of_backtest_overfitting
from .registry import StrategyRegistry
from .robustness import block_bootstrap, ordinary_bootstrap, parameter_neighborhood
from .splits import annotate_fold_counts, build_walk_forward_folds
from .strategies import RegressionChannelStrategy, ResearchStrategy, _ema_series, _linear_regression, _rolling_vwap
from .types import (
    Candle,
    DatasetImport,
    ExperimentCreate,
    ExperimentStatus,
    MarketType,
    Signal,
    StrategyStatus,
    Trade,
)


class ExperimentCancelled(RuntimeError):
    pass


def expand_grid(search_space: dict[str, list[Any]]) -> list[dict[str, Any]]:
    keys = sorted(search_space)
    return [dict(zip(keys, values, strict=True)) for values in itertools.product(*(search_space[key] for key in keys))]


def _slice_with_warmup(candles: list[Candle], start: int, end: int, warmup_bars: int = 2000) -> tuple[list[Candle], int]:
    first = next((i for i, candle in enumerate(candles) if candle.timestamp >= start), len(candles))
    last = next((i for i, candle in enumerate(candles[first:], start=first) if candle.timestamp >= end), len(candles))
    warm_start = max(0, first - warmup_bars)
    return candles[warm_start:last], first - warm_start


def _trade_from_signal(
    candles: list[Candle],
    signal: Signal,
    config: ExperimentCreate,
    equity: float,
    horizon_bars: int,
) -> tuple[Trade | None, int]:
    entry_index = signal.entry_index
    if entry_index >= len(candles):
        return None, entry_index
    entry_candle = candles[entry_index]
    entry_price = entry_candle.open
    stop_price = signal.stop_price
    target_price = signal.target_price
    risk_per_unit = abs(entry_price - stop_price)
    if risk_per_unit <= 0:
        return None, entry_index
    if config.position_sizing == "fixed_fractional_risk":
        risk_capital = max(0.0, equity) * config.risk_fraction
        quantity = risk_capital / risk_per_unit
        maximum_quantity = max(0.0, equity) * config.maximum_leverage / entry_price
        quantity = min(quantity, maximum_quantity)
    else:
        quantity = max(0.0, equity) * config.maximum_leverage / entry_price
    if quantity <= 0:
        return None, entry_index

    max_bars = max(1, min(signal.max_holding_bars, horizon_bars))
    exit_index = min(len(candles) - 1, entry_index + max_bars - 1)
    exit_price = candles[exit_index].close
    exit_reason = "time"
    target_before_stop = False
    favorable = 0.0
    adverse = 0.0

    for index in range(entry_index, exit_index + 1):
        candle = candles[index]
        if signal.side == "long":
            favorable = max(favorable, candle.high - entry_price)
            adverse = min(adverse, candle.low - entry_price)
            hit_stop = candle.low <= stop_price
            hit_target = candle.high >= target_price
        else:
            favorable = max(favorable, entry_price - candle.low)
            adverse = min(adverse, entry_price - candle.high)
            hit_stop = candle.high >= stop_price
            hit_target = candle.low <= target_price

        if hit_stop and hit_target:
            # Intrabar ordering is unknowable from OHLC; use conservative stop-first handling.
            exit_index = index
            exit_price = stop_price
            exit_reason = "stop"
            target_before_stop = False
            break
        if hit_stop:
            exit_index = index
            exit_price = stop_price
            exit_reason = "stop"
            break
        if hit_target:
            exit_index = index
            exit_price = target_price
            exit_reason = "target"
            target_before_stop = True
            break

    direction = 1.0 if signal.side == "long" else -1.0
    gross_pnl = direction * (exit_price - entry_price) * quantity
    gross_return = direction * (exit_price / entry_price - 1.0)
    entry_notional = entry_price * quantity
    exit_notional = exit_price * quantity
    holding_seconds = max(0, candles[exit_index].timestamp - entry_candle.timestamp)
    costs = calculate_execution_cost(
        config.cost_model,
        entry_notional,
        exit_notional,
        holding_seconds,
        config.market_type,
    )
    net_pnl = gross_pnl - costs.total
    net_return = net_pnl / entry_notional if entry_notional else 0.0
    trade = Trade(
        signal_timestamp=signal.timestamp,
        entry_timestamp=entry_candle.timestamp,
        exit_timestamp=candles[exit_index].timestamp,
        side=signal.side,
        entry_price=entry_price,
        exit_price=exit_price,
        stop_price=stop_price,
        target_price=target_price,
        quantity=quantity,
        gross_pnl=gross_pnl,
        fee_cost=costs.fee_cost,
        spread_cost=costs.spread_cost,
        slippage_cost=costs.slippage_cost,
        funding_cost=costs.funding_cost,
        net_pnl=net_pnl,
        gross_return=gross_return,
        net_return=net_return,
        mfe=favorable / entry_price,
        mae=adverse / entry_price,
        bars_held=exit_index - entry_index + 1,
        exit_reason=exit_reason,
        target_before_stop=target_before_stop,
        feature_snapshot=signal.feature_snapshot,
    )
    return trade, exit_index


def simulate_signals(
    candles: list[Candle],
    signals: list[Signal],
    config: ExperimentCreate,
) -> list[Trade]:
    horizon_bars = max(1, math.ceil(config.prediction_horizon_minutes / config.source_timeframe_minutes))
    trades: list[Trade] = []
    equity = config.initial_capital
    last_exit_index = -1
    for signal in signals:
        if signal.entry_index <= last_exit_index:
            continue
        trade, exit_index = _trade_from_signal(candles, signal, config, equity, horizon_bars)
        if trade is None:
            continue
        trades.append(trade)
        equity += trade.net_pnl
        last_exit_index = exit_index
    return trades


def run_strategy(
    strategy: ResearchStrategy,
    candles: list[Candle],
    parameters: dict[str, Any],
    config: ExperimentCreate,
) -> tuple[list[Trade], list[Signal]]:
    validated = strategy.validate_parameters(parameters)
    signals = strategy.generate_signals(candles, validated, config.prediction_horizon_minutes)
    return simulate_signals(candles, signals, config), signals


def _periodic_baseline(
    baseline_id: str,
    candles: list[Candle],
    config: ExperimentCreate,
    side_function: Callable[[int], str],
) -> dict[str, Any]:
    horizon_bars = max(1, math.ceil(config.prediction_horizon_minutes / config.source_timeframe_minutes))
    trades: list[Trade] = []
    equity = config.initial_capital
    for entry_index in range(1, len(candles) - horizon_bars, horizon_bars):
        side = side_function(entry_index)
        entry = candles[entry_index]
        exit_candle = candles[entry_index + horizon_bars]
        entry_price = entry.open
        exit_price = exit_candle.close
        quantity = max(0.0, equity) * config.maximum_leverage / entry_price
        direction = 1.0 if side == "long" else -1.0
        gross_pnl = direction * (exit_price - entry_price) * quantity
        entry_notional = entry_price * quantity
        exit_notional = exit_price * quantity
        costs = calculate_execution_cost(
            config.cost_model,
            entry_notional,
            exit_notional,
            exit_candle.timestamp - entry.timestamp,
            config.market_type,
        )
        net_pnl = gross_pnl - costs.total
        trades.append(Trade(
            signal_timestamp=candles[entry_index - 1].timestamp,
            entry_timestamp=entry.timestamp,
            exit_timestamp=exit_candle.timestamp,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            stop_price=entry_price,
            target_price=entry_price,
            quantity=quantity,
            gross_pnl=gross_pnl,
            fee_cost=costs.fee_cost,
            spread_cost=costs.spread_cost,
            slippage_cost=costs.slippage_cost,
            funding_cost=costs.funding_cost,
            net_pnl=net_pnl,
            gross_return=direction * (exit_price / entry_price - 1.0),
            net_return=net_pnl / entry_notional if entry_notional else 0.0,
            mfe=0.0,
            mae=0.0,
            bars_held=horizon_bars,
            exit_reason="time",
            target_before_stop=False,
            feature_snapshot={"baseline": baseline_id},
        ))
        equity += net_pnl
    return calculate_metrics(trades, config.initial_capital)


def run_baselines(candles: list[Candle], config: ExperimentCreate) -> dict[str, dict[str, Any]]:
    if len(candles) < 10:
        return {}
    closes = [c.close for c in candles]
    ema = _ema_series(closes, 20)
    rng = random.Random(config.random_seed)
    random_sides = [rng.choice(["long", "short"]) for _ in candles]

    def previous(index: int) -> str:
        return "long" if candles[index - 1].close >= candles[index - 1].open else "short"

    def ema_side(index: int) -> str:
        return "long" if ema[index - 1] >= ema[max(0, index - 2)] else "short"

    def vwap_side(index: int) -> str:
        vwap = _rolling_vwap(candles, index - 1, min(96, index))
        return "long" if vwap is not None and candles[index - 1].close >= vwap else "short"

    def regression_fade(index: int) -> str:
        lookback = min(55, index)
        window = closes[index - lookback : index]
        slope, intercept, _, _ = _linear_regression(window)
        center = intercept + slope * (lookback - 1)
        return "short" if candles[index - 1].close > center else "long"

    def regression_breakout(index: int) -> str:
        lookback = min(55, index)
        window = closes[index - lookback : index]
        slope, intercept, _, _ = _linear_regression(window)
        center = intercept + slope * (lookback - 1)
        return "long" if candles[index - 1].close > center else "short"

    return {
        "random_direction": _periodic_baseline("random_direction", candles, config, lambda index: random_sides[index]),
        "always_long": _periodic_baseline("always_long", candles, config, lambda _: "long"),
        "always_short": _periodic_baseline("always_short", candles, config, lambda _: "short"),
        "previous_candle_direction": _periodic_baseline("previous_candle_direction", candles, config, previous),
        "ema_slope": _periodic_baseline("ema_slope", candles, config, ema_side),
        "above_below_vwap": _periodic_baseline("above_below_vwap", candles, config, vwap_side),
        "simple_regression_fade": _periodic_baseline("simple_regression_fade", candles, config, regression_fade),
        "simple_regression_breakout": _periodic_baseline("simple_regression_breakout", candles, config, regression_breakout),
    }


def _aggregate_metrics(trade_groups: list[list[Trade]], initial_capital: float) -> dict[str, Any]:
    return calculate_metrics([trade for group in trade_groups for trade in group], initial_capital)


def _select_parameters(parameter_metrics: list[tuple[int, dict[str, Any], dict[str, Any]]]) -> tuple[int, dict[str, Any]]:
    def rank(item: tuple[int, dict[str, Any], dict[str, Any]]) -> tuple[float, float, int]:
        _, _, metrics = item
        expectancy = float(metrics.get("expectancy") or -1e100)
        profit_factor = float(metrics.get("profit_factor") or 0.0)
        trade_count = int(metrics.get("trade_count") or 0)
        return expectancy, profit_factor, trade_count

    best = max(parameter_metrics, key=rank)
    return best[0], best[1]


def _validation_decision(
    out_metrics: dict[str, Any],
    stability: dict[str, Any],
    robustness: dict[str, Any],
    config: ExperimentCreate,
    bootstrap_loss_probability: float,
    multiple_testing: dict[str, Any],
) -> tuple[StrategyStatus, str, list[str]]:
    policy = config.validation_policy
    failures: list[str] = []
    if int(out_metrics.get("trade_count") or 0) < policy.minimum_trades:
        failures.append(f"minimum trade count {policy.minimum_trades} not met")
    if float(out_metrics.get("expectancy") or 0.0) <= 0:
        failures.append("out-of-sample net expectancy is not positive")
    if float(out_metrics.get("profit_factor") or 0.0) < policy.minimum_profit_factor:
        failures.append(f"profit factor is below {policy.minimum_profit_factor}")
    if float(out_metrics.get("max_drawdown_fraction") or 0.0) > policy.maximum_drawdown_fraction:
        failures.append("maximum drawdown exceeds policy")
    if float(stability.get("positive_fold_ratio") or 0.0) < policy.minimum_positive_fold_ratio:
        failures.append("insufficient positive walk-forward folds")
    cost_fraction = out_metrics.get("costs_as_fraction_of_gross_profit")
    if isinstance(cost_fraction, (int, float)) and cost_fraction > policy.maximum_cost_to_gross_profit:
        failures.append("execution costs consume too much gross profit")
    if bootstrap_loss_probability > policy.maximum_bootstrap_loss_probability:
        failures.append("block-bootstrap loss probability exceeds policy")
    if robustness.get("parameter_stability", {}).get("classification") == "fragile_optimum":
        failures.append("selected parameters form a fragile optimum")
    dsr = multiple_testing.get("deflated_sharpe", {})
    if dsr.get("label") == "failed":
        failures.append("deflated Sharpe failed")

    if failures:
        if int(out_metrics.get("trade_count") or 0) < policy.minimum_trades:
            return StrategyStatus.INSUFFICIENT_DATA, "; ".join(failures), failures
        if float(out_metrics.get("net_profit") or 0.0) > 0 and float(out_metrics.get("gross_profit") or 0.0) > 0:
            cost_fraction = out_metrics.get("costs_as_fraction_of_gross_profit")
            if isinstance(cost_fraction, (int, float)) and cost_fraction > policy.maximum_cost_to_gross_profit:
                return StrategyStatus.COST_INFEASIBLE, "; ".join(failures), failures
        if robustness.get("parameter_stability", {}).get("classification") == "fragile_optimum" or dsr.get("label") == "failed":
            return StrategyStatus.OVERFIT, "; ".join(failures), failures
        return StrategyStatus.VALIDATION_FAILED, "; ".join(failures), failures
    if robustness.get("parameter_stability", {}).get("classification") == "robust_plateau":
        return StrategyStatus.ROBUSTNESS_CANDIDATE, "Historical validation and robustness policy passed; forward paper trading is still required", []
    return StrategyStatus.OUT_OF_SAMPLE_CANDIDATE, "Historical out-of-sample policy passed; parameter robustness or forward testing remains", []


def _rank_prior(values: list[float], value: float) -> float | None:
    if not values:
        return None
    return sum(item <= value for item in values) / len(values) * 100.0


def run_absorption_ablation_suite(
    candles: list[Candle],
    config: ExperimentCreate,
    full_parameters: dict[str, Any],
    registry: StrategyRegistry,
) -> dict[str, dict[str, Any]]:
    if config.strategy_id != "regression_extreme_absorption":
        return {}
    regression = RegressionChannelStrategy()
    common = {
        "lookback": full_parameters["lookback"],
        "channel_width": full_parameters["channel_width"],
        "atr_period": full_parameters["atr_period"],
        "minimum_atr_extension": full_parameters["minimum_atr_extension"],
        "confirmation": "none",
        "stop_atr": full_parameters["stop_atr"],
        "target_rr": full_parameters["target_rr"],
        "max_holding_bars": full_parameters["max_holding_bars"],
    }
    regression_signals = regression.generate_signals(candles, common, config.prediction_horizon_minutes)
    index_by_timestamp = {candle.timestamp: index for index, candle in enumerate(candles)}
    flow_lookback = int(full_parameters["flow_lookback"])
    flow_threshold = float(full_parameters["flow_percentile"])
    absorption_threshold = float(full_parameters["absorption_percentile"])

    raw_flow_signals: list[Signal] = []
    impact_signals: list[Signal] = []
    absorption_signals: list[Signal] = []
    cvd_signals: list[Signal] = []
    for signal in regression_signals:
        index = index_by_timestamp[signal.timestamp]
        if index < flow_lookback:
            continue
        candle = candles[index]
        flow = candle.aggressive_sell_notional if signal.side == "long" else candle.aggressive_buy_notional
        if flow is None:
            continue
        history: list[float] = []
        impact_history: list[float] = []
        for prior in candles[index - flow_lookback : index]:
            prior_flow = prior.aggressive_sell_notional if signal.side == "long" else prior.aggressive_buy_notional
            if prior_flow is None:
                continue
            displacement = max(abs(prior.close - prior.open), prior.high - prior.low, 1e-9)
            history.append(prior_flow)
            impact_history.append(prior_flow / displacement)
        flow_rank = _rank_prior(history, flow)
        impact = flow / max(abs(candle.close - candle.open), candle.high - candle.low, 1e-9)
        impact_rank = _rank_prior(impact_history, impact)
        if flow_rank is not None and flow_rank >= flow_threshold:
            raw_flow_signals.append(signal.model_copy(update={
                "feature_snapshot": {**signal.feature_snapshot, "ablation": "raw_flow", "flow_percentile": flow_rank}
            }))
        if impact_rank is not None and impact_rank >= absorption_threshold:
            impact_signals.append(signal.model_copy(update={
                "feature_snapshot": {**signal.feature_snapshot, "ablation": "price_impact", "impact_percentile": impact_rank}
            }))
        if flow_rank is not None and impact_rank is not None and flow_rank >= flow_threshold and impact_rank >= absorption_threshold:
            enriched = signal.model_copy(update={
                "feature_snapshot": {**signal.feature_snapshot, "ablation": "absorption", "flow_percentile": flow_rank, "impact_percentile": impact_rank}
            })
            absorption_signals.append(enriched)
            prior_cvd = [item.cvd for item in candles[max(0, index - 20):index] if item.cvd is not None]
            if candle.cvd is not None and prior_cvd:
                divergence = candle.cvd > min(prior_cvd) if signal.side == "long" else candle.cvd < max(prior_cvd)
                if divergence:
                    cvd_signals.append(enriched.model_copy(update={
                        "feature_snapshot": {**enriched.feature_snapshot, "cvd_divergence": True}
                    }))

    full_strategy = registry.get("regression_extreme_absorption")
    variants: dict[str, tuple[list[Signal], dict[str, Any]]] = {
        "A_regression_channel_only": (regression_signals, {"definition": "Regression extension without order flow"}),
        "B_plus_raw_aggressive_volume": (raw_flow_signals, {"definition": "Regression extension plus prior-only aggressive-flow percentile"}),
        "C_plus_price_impact": (impact_signals, {"definition": "Regression extension plus notional-per-displacement percentile"}),
        "D_plus_absorption": (absorption_signals, {"definition": "Regression extension plus both flow and impact thresholds"}),
        "G_plus_cvd_divergence": (cvd_signals, {"definition": "Absorption subset with exact prior-window CVD divergence rule"}),
    }
    results: dict[str, dict[str, Any]] = {}
    for name, (signals, definition) in variants.items():
        results[name] = {**definition, "status": "completed", "metrics": calculate_metrics(simulate_signals(candles, signals, config), config.initial_capital)}

    for name, confirmation in (
        ("E_plus_absorption_and_reclaim", "channel_reclaim"),
        ("F_plus_liquidity_replenishment", "liquidity_replenishment"),
    ):
        parameters = dict(full_parameters)
        parameters["confirmation"] = confirmation
        trades, _ = run_strategy(full_strategy, candles, parameters, config)
        results[name] = {
            "definition": f"Full absorption conditions with {confirmation}",
            "status": "completed",
            "metrics": calculate_metrics(trades, config.initial_capital),
        }
    results["H_full_system"] = {
        "status": "not_run",
        "reason": "Higher-timeframe, derivatives and independent cross-exchange confirmation are not all present in the imported single-market dataset; no result was fabricated.",
        "metrics": None,
    }
    return results


class ExperimentEngine:
    def __init__(self, registry: StrategyRegistry) -> None:
        self.registry = registry

    def run(
        self,
        config: ExperimentCreate,
        dataset: DatasetImport,
        progress: Callable[[float, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        progress = progress or (lambda _value, _message: None)
        cancelled = cancelled or (lambda: False)

        self.registry.validate_compatibility(
            config.strategy_id,
            config.strategy_version,
            config.asset,
            config.market_type,
            config.source_timeframe_minutes,
            config.prediction_horizon_minutes,
        )
        strategy = self.registry.get(config.strategy_id, config.strategy_version)
        required = set(strategy.definition.required_features) | set(strategy.definition.required_data_feeds)
        integrity = validate_dataset(dataset, required)
        if not integrity.passed:
            raise ValueError("FAILED — DATA INTEGRITY: " + "; ".join(integrity.reasons))
        candles = [c for c in dataset.candles if config.start_timestamp <= c.timestamp < config.end_timestamp]
        if len(candles) < 50:
            raise ValueError("Insufficient history in requested experiment range")

        parameter_sets = config.parameter_sets or [config.parameters or strategy.default_parameters()]
        parameter_sets = [strategy.validate_parameters(parameters) for parameters in parameter_sets]
        if not parameter_sets:
            raise ValueError("At least one parameter set is required")

        embargo = config.walk_forward.embargo_minutes
        if embargo is None:
            embargo = max(config.prediction_horizon_minutes, strategy.definition.maximum_holding_period_minutes)
        raw_folds = build_walk_forward_folds(
            config.start_timestamp,
            config.end_timestamp,
            config.walk_forward,
            strategy.definition.maximum_holding_period_minutes,
        )
        folds = [
            annotate_fold_counts(
                fold,
                candles,
                config.prediction_horizon_minutes,
                strategy.definition.maximum_holding_period_minutes,
                embargo,
            )
            for fold in raw_folds
        ]
        if not folds:
            raise ValueError("Requested range is too short for the configured walk-forward windows")

        progress(0.05, f"Running {len(folds)} chronological walk-forward folds")
        fold_results: list[dict[str, Any]] = []
        fold_config_scores: list[list[float]] = []
        all_test_trades: list[list[Trade]] = []
        all_validation_trades: list[list[Trade]] = []
        aggregated_parameter_results: dict[int, list[dict[str, Any]]] = defaultdict(list)

        for fold_index, fold in enumerate(folds):
            if cancelled():
                raise ExperimentCancelled("Experiment cancelled")
            train_candles = slice_candles(candles, fold.train_start, fold.train_end)
            validation_candles = slice_candles(candles, fold.validation_start, fold.validation_end)
            test_candles = slice_candles(candles, fold.test_start, fold.test_end)
            if min(len(train_candles), len(validation_candles), len(test_candles)) < 20:
                continue

            parameter_metrics: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
            parameter_records: list[dict[str, Any]] = []
            fold_scores: list[float] = []
            for parameter_index, parameters in enumerate(parameter_sets):
                validation_trades, _ = run_strategy(strategy, validation_candles, parameters, config)
                validation_metrics = calculate_metrics(validation_trades, config.initial_capital)
                parameter_metrics.append((parameter_index, parameters, validation_metrics))
                fold_scores.append(float(validation_metrics.get("expectancy") or -1e12))
                parameter_records.append({
                    "parameter_set_index": parameter_index,
                    "partition": "validation",
                    "parameters": parameters,
                    "metrics": validation_metrics,
                })
                aggregated_parameter_results[parameter_index].append(validation_metrics)
            selected_index, selected_parameters = _select_parameters(parameter_metrics)
            train_trades, _ = run_strategy(strategy, train_candles, selected_parameters, config)
            validation_trades, _ = run_strategy(strategy, validation_candles, selected_parameters, config)
            test_trades, _ = run_strategy(strategy, test_candles, selected_parameters, config)
            train_metrics = calculate_metrics(train_trades, config.initial_capital)
            validation_metrics = calculate_metrics(validation_trades, config.initial_capital)
            test_metrics = calculate_metrics(test_trades, config.initial_capital)
            fold_results.append({
                "definition": fold.model_dump(mode="json"),
                "selected_parameter_set_index": selected_index,
                "selected_parameters": selected_parameters,
                "train_metrics": train_metrics,
                "validation_metrics": validation_metrics,
                "test_metrics": test_metrics,
                "data_quality": {"passed": True, "warnings": integrity.warnings},
                "parameter_results": parameter_records,
                "trades": {
                    "train": [trade.model_dump(mode="json") for trade in train_trades],
                    "validation": [trade.model_dump(mode="json") for trade in validation_trades],
                    "test": [trade.model_dump(mode="json") for trade in test_trades],
                },
            })
            all_test_trades.append(test_trades)
            all_validation_trades.append(validation_trades)
            fold_config_scores.append(fold_scores)
            progress(0.10 + 0.55 * (fold_index + 1) / len(folds), f"Completed walk-forward fold {fold_index + 1}/{len(folds)}")

        if not fold_results:
            raise ValueError("No walk-forward folds had sufficient observations")

        in_sample_metrics = _aggregate_metrics(all_validation_trades, config.initial_capital)
        out_sample_metrics = _aggregate_metrics(all_test_trades, config.initial_capital)
        fold_returns = [float(fold["test_metrics"].get("net_return") or 0.0) for fold in fold_results]
        fold_expectancies = [float(fold["test_metrics"].get("expectancy") or 0.0) for fold in fold_results]
        stability = {
            "fold_count": len(fold_results),
            "positive_fold_ratio": sum(value > 0 for value in fold_returns) / len(fold_returns),
            "positive_expectancy_fold_ratio": sum(value > 0 for value in fold_expectancies) / len(fold_expectancies),
            "median_fold_return": sorted(fold_returns)[len(fold_returns) // 2],
            "worst_fold_return": min(fold_returns),
            "best_fold_return": max(fold_returns),
            "fold_return_dispersion": max(fold_returns) - min(fold_returns),
            "selected_parameter_changes": sum(
                fold_results[index]["selected_parameters"] != fold_results[index - 1]["selected_parameters"]
                for index in range(1, len(fold_results))
            ),
        }

        parameter_summary: list[dict[str, Any]] = []
        for index, parameters in enumerate(parameter_sets):
            metrics_list = aggregated_parameter_results.get(index, [])
            mean_expectancy = mean(float(item.get("expectancy") or 0.0) for item in metrics_list) if metrics_list else 0.0
            mean_pf_values = [float(item["profit_factor"]) for item in metrics_list if isinstance(item.get("profit_factor"), (int, float))]
            parameter_summary.append({
                "parameter_set_index": index,
                "parameters": parameters,
                "metrics": {
                    "expectancy": mean_expectancy,
                    "profit_factor": mean(mean_pf_values) if mean_pf_values else None,
                    "positive_fold_ratio": sum(float(item.get("expectancy") or 0.0) > 0 for item in metrics_list) / len(metrics_list) if metrics_list else 0.0,
                    "folds": len(metrics_list),
                },
            })
        most_selected_index = max(
            range(len(parameter_sets)),
            key=lambda index: sum(fold["selected_parameter_set_index"] == index for fold in fold_results),
        )
        selected_parameters = parameter_sets[most_selected_index]
        stability_map = parameter_neighborhood(parameter_summary, selected_parameters)
        robustness = {"parameter_stability": stability_map}

        progress(0.70, "Running baseline comparisons and robustness simulations")
        full_oos_candles = [c for fold in folds for c in slice_candles(candles, fold.test_start, fold.test_end)]
        # Deduplicate overlapping test windows if step < test period.
        full_oos_candles = list({c.timestamp: c for c in full_oos_candles}.values())
        full_oos_candles.sort(key=lambda c: c.timestamp)
        baselines = run_baselines(full_oos_candles, config)
        ablations = run_absorption_ablation_suite(
            full_oos_candles, config, selected_parameters, self.registry
        )

        test_trades_flat = [trade for group in all_test_trades for trade in group]
        pnls = [trade.net_pnl for trade in test_trades_flat]
        ordinary = ordinary_bootstrap(
            pnls,
            config.initial_capital,
            simulations=500,
            seed=config.random_seed,
            risk_limit_fraction=config.validation_policy.maximum_drawdown_fraction,
        )
        block = block_bootstrap(
            pnls,
            config.initial_capital,
            simulations=500,
            seed=config.random_seed,
            risk_limit_fraction=config.validation_policy.maximum_drawdown_fraction,
        )

        returns = [trade.net_return for trade in test_trades_flat]
        dsr = deflated_sharpe_ratio(returns, out_sample_metrics.get("sharpe"), len(parameter_sets))
        pbo = probability_of_backtest_overfitting(fold_config_scores)
        multiple_testing = {
            "total_trials": len(parameter_sets),
            "deflated_sharpe": dsr,
            "probability_of_backtest_overfitting": pbo,
            "warnings": [
                warning
                for warning, condition in (
                    ("MULTIPLE-TESTING RISK", len(parameter_sets) >= 100),
                    ("DEFLATED SHARPE FAILED", dsr.get("label") == "failed"),
                    ("HIGH PROBABILITY OF OVERFITTING", isinstance(pbo.get("estimated_pbo"), (int, float)) and float(pbo["estimated_pbo"]) >= 0.50),
                )
                if condition
            ],
        }

        degradation_metrics = degradation(in_sample_metrics, out_sample_metrics)
        metrics = {
            "in_sample": in_sample_metrics,
            "out_of_sample": out_sample_metrics,
            "degradation": degradation_metrics,
            "stability": stability,
            "robustness": robustness,
        }

        status, reason, failures = _validation_decision(
            out_sample_metrics,
            stability,
            robustness,
            config,
            block.probability_of_net_loss,
            multiple_testing,
        )
        progress(0.95, "Applying validation policy")

        return {
            "strategy_status": status,
            "metrics": metrics,
            "folds": fold_results,
            "baselines": baselines,
            "ablations": ablations,
            "bootstrap": [
                {
                    "method": "ordinary",
                    "seed": config.random_seed,
                    "simulations": ordinary.simulations,
                    "configuration": {"resampling": "trades_with_replacement"},
                    "statistics": ordinary.as_dict(),
                },
                {
                    "method": "block",
                    "seed": config.random_seed,
                    "simulations": block.simulations,
                    "configuration": {"block_size": max(2, int(round(max(1, len(pnls)) ** 0.5)))},
                    "statistics": block.as_dict(),
                },
            ],
            "multiple_testing": multiple_testing,
            "parameter_search": {
                "method": config.search_method,
                "total_configurations": len(parameter_sets),
                "search_space": parameter_sets,
                "result": {
                    "most_selected_parameter_set_index": most_selected_index,
                    "selected_parameters": selected_parameters,
                    "parameter_stability": stability_map,
                },
            },
            "validation": {
                "passed": not failures,
                "reason": reason,
                "failures": failures,
                "active_policy": config.validation_policy.model_dump(mode="json"),
            },
            "data_integrity": integrity.__dict__,
            "reproducibility": {
                "configuration_hash": hashlib.sha256(config.model_dump_json().encode()).hexdigest(),
                "dataset_hash": hashlib.sha256(
                    json.dumps([c.model_dump(mode="json") for c in dataset.candles], sort_keys=True).encode()
                ).hexdigest(),
                "random_seed": config.random_seed,
                "code_commit_hash": config.code_commit_hash,
                "feature_version": config.feature_version,
                "timezone": "UTC",
                "exchange_adapter": dataset.adapter_version,
            },
        }
