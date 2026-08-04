from __future__ import annotations

import random
from collections import defaultdict
from statistics import mean, median
from typing import Callable

from .types import BootstrapResult, ResearchTrade


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("values required")
    ordered = sorted(values)
    index = probability * (len(ordered) - 1)
    lower = int(index)
    upper = min(len(ordered) - 1, lower + 1)
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _statistic(trades: list[ResearchTrade], statistic: str) -> float:
    rs = [trade.r_multiple for trade in trades]
    if not rs:
        return 0.0
    if statistic == "mean_r":
        return mean(rs)
    if statistic == "median_r":
        return median(rs)
    if statistic == "win_rate":
        return sum(value > 0 for value in rs) / len(rs)
    if statistic == "net_pnl":
        return sum(trade.pnl for trade in trades)
    if statistic == "profit_factor":
        gross_win = sum(max(0.0, trade.pnl) for trade in trades)
        gross_loss = abs(sum(min(0.0, trade.pnl) for trade in trades))
        return gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    raise ValueError(f"unsupported statistic {statistic}")


def bootstrap_confidence_interval(
    trades: list[ResearchTrade],
    *,
    method: str = "day",
    statistic: str = "mean_r",
    simulations: int = 1000,
    seed: int = 42,
    block_size: int | None = None,
) -> BootstrapResult:
    if simulations < 100:
        raise ValueError("at least 100 simulations required")
    if not trades:
        return BootstrapResult(
            method=method, seed=seed, simulations=simulations, statistic=statistic,
            observed=None, lower=None, upper=None, includes_zero=None,
            interpretation="INSUFFICIENT DATA",
        )
    rng = random.Random(seed)
    samples: list[float] = []
    if method == "trade":
        for _ in range(simulations):
            sample = [rng.choice(trades) for _ in trades]
            samples.append(_statistic(sample, statistic))
    elif method in {"day", "week", "regime"}:
        groups: dict[str, list[ResearchTrade]] = defaultdict(list)
        for trade in trades:
            if method == "day":
                key = trade.day_key
            elif method == "week":
                key = trade.day_key[:7] + f"-w{int(trade.day_key[-2:]) // 7}"
            else:
                key = trade.regime
            groups[key].append(trade)
        keys = list(groups)
        for _ in range(simulations):
            sample: list[ResearchTrade] = []
            for _ in keys:
                sample.extend(groups[rng.choice(keys)])
            samples.append(_statistic(sample, statistic))
    elif method == "block":
        size = block_size or max(2, round(len(trades) ** 0.5))
        for _ in range(simulations):
            sample: list[ResearchTrade] = []
            while len(sample) < len(trades):
                start = rng.randrange(len(trades))
                for offset in range(size):
                    sample.append(trades[(start + offset) % len(trades)])
                    if len(sample) >= len(trades):
                        break
            samples.append(_statistic(sample, statistic))
    else:
        raise ValueError("method must be trade, day, week, regime or block")
    lower = _quantile(samples, 0.025)
    upper = _quantile(samples, 0.975)
    includes_zero = lower <= 0 <= upper
    return BootstrapResult(
        method=method,
        seed=seed,
        simulations=simulations,
        statistic=statistic,
        observed=_statistic(trades, statistic),
        lower=lower,
        upper=upper,
        includes_zero=includes_zero,
        interpretation="INCONCLUSIVE — interval includes zero" if includes_zero else (
            "POSITIVE OUT-OF-SAMPLE ESTIMATE" if lower > 0 else "NEGATIVE OUT-OF-SAMPLE ESTIMATE"
        ),
    )
