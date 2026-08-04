from __future__ import annotations

import random
from statistics import mean

from app.research.types import Candle

from .order_blocks import backtest_order_blocks
from .types import NullModelRequest, NullModelResult, OrderBlockConfig, OrderBlockZone


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = probability * (len(ordered) - 1)
    low = int(index)
    high = min(len(ordered) - 1, low + 1)
    weight = index - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _randomized_zones(
    zones: list[OrderBlockZone], candles: list[Candle], rng: random.Random, mode: str
) -> list[OrderBlockZone]:
    output: list[OrderBlockZone] = []
    if not candles:
        return output
    day_bars = 24 * 60
    for zone in zones:
        source_index = zone.source_candle_index
        if mode == "random_timing":
            source_index = min(len(candles) - 4, source_index + rng.randint(0, 60))
        elif mode == "matched_market":
            hour = (candles[source_index].timestamp // 3600) % 24
            candidates = [
                index for index in range(20, len(candles) - 4)
                if (candles[index].timestamp // 3600) % 24 == hour
            ]
            if candidates:
                source_index = rng.choice(candidates)
        elif mode == "random_days":
            shift_days = rng.randint(-7, 7)
            source_index = min(len(candles) - 4, max(20, source_index + shift_days * day_bars))
        output.append(zone.model_copy(update={"source_candle_index": source_index}))
    return output


def run_order_block_null_model(
    candles: list[Candle],
    zones: list[OrderBlockZone],
    config: OrderBlockConfig,
    request: NullModelRequest,
    *,
    observed_depth: float = 0.5,
) -> NullModelResult:
    observed_trades = backtest_order_blocks(candles, zones, config, entry_depth=observed_depth)
    observed = mean([trade.r_multiple for trade in observed_trades]) if observed_trades else None
    if observed is None or not zones:
        return NullModelResult(
            model=request.model, seed=request.seed, simulations=request.simulations,
            observed_mean_r=observed, null_mean_r=None, difference=None,
            percentile=None, empirical_p_value=None, confidence_interval=None,
            status="INSUFFICIENT DATA",
        )
    rng = random.Random(request.seed)
    null_means: list[float] = []
    for _ in range(request.simulations):
        depth = rng.random() if request.model == "random_depth" else observed_depth
        randomized = zones if request.model == "random_depth" else _randomized_zones(zones, candles, rng, request.model)
        trades = backtest_order_blocks(candles, randomized, config, entry_depth=depth)
        null_means.append(mean([trade.r_multiple for trade in trades]) if trades else 0.0)
    null_mean = mean(null_means)
    percentile = sum(value <= observed for value in null_means) / len(null_means)
    p_value = (1 + sum(value >= observed for value in null_means)) / (len(null_means) + 1)
    interval = (_quantile(null_means, 0.025), _quantile(null_means, 0.975))
    return NullModelResult(
        model=request.model,
        seed=request.seed,
        simulations=request.simulations,
        observed_mean_r=observed,
        null_mean_r=null_mean,
        difference=observed - null_mean,
        percentile=percentile,
        empirical_p_value=p_value,
        confidence_interval=interval,
        status="EXPERIMENTAL — MULTIPLE-TESTING CONTROL STILL REQUIRED",
    )
