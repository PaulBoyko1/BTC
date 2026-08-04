from __future__ import annotations

import random
from dataclasses import dataclass
from math import ceil
from statistics import mean, median
from typing import Iterable

from .metrics import max_drawdown


@dataclass(frozen=True)
class BootstrapSummary:
    method: str
    simulations: int
    median_terminal_equity: float
    fifth_percentile_terminal_equity: float
    ninety_fifth_percentile_drawdown: float
    worst_simulated_drawdown: float
    median_maximum_losing_streak: float
    ninety_fifth_percentile_losing_streak: float
    probability_of_net_loss: float
    probability_of_exceeding_risk_limit: float
    risk_of_ruin_estimate: float

    def as_dict(self) -> dict[str, float | int | str]:
        return self.__dict__.copy()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, ceil(percentile / 100.0 * len(ordered)) - 1))
    return ordered[index]


def _losing_streak(pnls: list[float]) -> int:
    best = current = 0
    for pnl in pnls:
        if pnl < 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _summarize(paths: list[list[float]], initial_capital: float, risk_limit_fraction: float, method: str) -> BootstrapSummary:
    terminals: list[float] = []
    drawdowns: list[float] = []
    streaks: list[float] = []
    ruined = 0
    loss = 0
    exceeded = 0
    for path in paths:
        terminal = initial_capital + sum(path)
        _, dd_fraction, _ = max_drawdown(path, initial_capital)
        terminals.append(terminal)
        drawdowns.append(dd_fraction)
        streaks.append(float(_losing_streak(path)))
        if terminal < initial_capital:
            loss += 1
        if dd_fraction >= risk_limit_fraction:
            exceeded += 1
        if terminal <= 0:
            ruined += 1
    count = max(1, len(paths))
    return BootstrapSummary(
        method=method,
        simulations=len(paths),
        median_terminal_equity=median(terminals) if terminals else initial_capital,
        fifth_percentile_terminal_equity=_percentile(terminals, 5),
        ninety_fifth_percentile_drawdown=_percentile(drawdowns, 95),
        worst_simulated_drawdown=max(drawdowns, default=0.0),
        median_maximum_losing_streak=median(streaks) if streaks else 0.0,
        ninety_fifth_percentile_losing_streak=_percentile(streaks, 95),
        probability_of_net_loss=loss / count,
        probability_of_exceeding_risk_limit=exceeded / count,
        risk_of_ruin_estimate=ruined / count,
    )


def ordinary_bootstrap(
    pnls: list[float],
    initial_capital: float,
    simulations: int = 1000,
    seed: int = 42,
    risk_limit_fraction: float = 0.35,
) -> BootstrapSummary:
    if not pnls:
        return _summarize([], initial_capital, risk_limit_fraction, "ordinary")
    rng = random.Random(seed)
    paths = [[rng.choice(pnls) for _ in pnls] for _ in range(simulations)]
    return _summarize(paths, initial_capital, risk_limit_fraction, "ordinary")


def block_bootstrap(
    pnls: list[float],
    initial_capital: float,
    simulations: int = 1000,
    block_size: int | None = None,
    seed: int = 42,
    risk_limit_fraction: float = 0.35,
) -> BootstrapSummary:
    if not pnls:
        return _summarize([], initial_capital, risk_limit_fraction, "block")
    rng = random.Random(seed)
    size = block_size or max(2, int(round(len(pnls) ** 0.5)))
    paths: list[list[float]] = []
    for _ in range(simulations):
        sampled: list[float] = []
        while len(sampled) < len(pnls):
            start = rng.randrange(0, len(pnls))
            block = [pnls[(start + offset) % len(pnls)] for offset in range(size)]
            sampled.extend(block)
        paths.append(sampled[: len(pnls)])
    return _summarize(paths, initial_capital, risk_limit_fraction, "block")


def parameter_neighborhood(
    parameter_results: list[dict[str, object]],
    selected_parameters: dict[str, object],
    metric: str = "expectancy",
) -> dict[str, object]:
    """Classify the selected point using one-step neighborhoods in tested space."""
    if not parameter_results:
        return {"classification": "insufficient_data", "neighbors": [], "positive_neighbor_ratio": None}
    dimensions = [key for key, value in selected_parameters.items() if isinstance(value, (int, float))]
    unique_values: dict[str, list[float]] = {}
    for dimension in dimensions:
        unique_values[dimension] = sorted({
            float(item["parameters"][dimension])
            for item in parameter_results
            if isinstance(item.get("parameters"), dict) and dimension in item["parameters"]
        })
    neighbors: list[dict[str, object]] = []
    for item in parameter_results:
        params = item.get("parameters")
        if not isinstance(params, dict) or params == selected_parameters:
            continue
        distance = 0
        comparable = True
        for dimension in dimensions:
            values = unique_values[dimension]
            try:
                selected_index = values.index(float(selected_parameters[dimension]))
                candidate_index = values.index(float(params[dimension]))
            except (ValueError, KeyError):
                comparable = False
                break
            distance += abs(selected_index - candidate_index)
        for key, value in selected_parameters.items():
            if key not in dimensions and params.get(key) != value:
                comparable = False
                break
        if comparable and distance == 1:
            neighbors.append(item)
    metric_values = [
        float(item.get("metrics", {}).get(metric, 0.0))
        for item in neighbors
        if isinstance(item.get("metrics"), dict)
    ]
    if not metric_values:
        classification = "insufficient_data"
        ratio = None
    else:
        ratio = sum(value > 0 for value in metric_values) / len(metric_values)
        selected_metric = next(
            (
                float(item.get("metrics", {}).get(metric, 0.0))
                for item in parameter_results
                if item.get("parameters") == selected_parameters and isinstance(item.get("metrics"), dict)
            ),
            0.0,
        )
        neighbor_median = median(metric_values)
        if ratio >= 0.70 and neighbor_median > 0 and selected_metric <= max(metric_values) * 2.0:
            classification = "robust_plateau"
        elif selected_metric > 0 and ratio < 0.50:
            classification = "fragile_optimum"
        else:
            classification = "unstable"
    return {
        "classification": classification,
        "positive_neighbor_ratio": ratio,
        "neighbors": neighbors,
    }
