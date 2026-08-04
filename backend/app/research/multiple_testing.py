from __future__ import annotations

from math import erf, exp, log, pi, sqrt
from statistics import mean, pstdev


def benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> list[bool]:
    if not p_values:
        return []
    indexed = sorted(enumerate(p_values), key=lambda pair: pair[1])
    largest_rank = 0
    count = len(p_values)
    for rank, (_, value) in enumerate(indexed, start=1):
        if value <= alpha * rank / count:
            largest_rank = rank
    passed = [False] * count
    for rank, (original_index, _) in enumerate(indexed, start=1):
        passed[original_index] = rank <= largest_rank
    return passed


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def deflated_sharpe_ratio(
    returns: list[float],
    raw_sharpe: float | None,
    trials: int,
) -> dict[str, float | int | None | str]:
    """Bailey/Lopez-de-Prado-style DSR approximation.

    The expected selected Sharpe uses an extreme-value normal approximation.
    The result is explicitly labeled approximate because finite-sample trial
    dependence is generally unknown.
    """
    if raw_sharpe is None or len(returns) < 3 or trials < 1:
        return {
            "raw_sharpe": raw_sharpe,
            "trials": trials,
            "expected_maximum_sharpe": None,
            "deflated_sharpe_probability": None,
            "label": "insufficient_data",
        }
    n = len(returns)
    average = mean(returns)
    sigma = pstdev(returns)
    if sigma == 0:
        return {
            "raw_sharpe": raw_sharpe,
            "trials": trials,
            "expected_maximum_sharpe": None,
            "deflated_sharpe_probability": None,
            "label": "insufficient_data",
        }
    centered = [(value - average) / sigma for value in returns]
    skew = mean([value ** 3 for value in centered])
    kurtosis = mean([value ** 4 for value in centered])
    if trials == 1:
        expected_max = 0.0
    else:
        # Expected maximum of approximately independent standard normals.
        expected_max = sqrt(max(0.0, 2.0 * log(trials))) - (
            log(max(log(trials), 1e-12)) + log(4.0 * pi)
        ) / (2.0 * sqrt(max(2.0 * log(trials), 1e-12)))
    denominator = sqrt(max(1e-12, (1.0 - skew * raw_sharpe + ((kurtosis - 1.0) / 4.0) * raw_sharpe ** 2) / (n - 1)))
    statistic = (raw_sharpe - expected_max) / denominator
    probability = _normal_cdf(statistic)
    return {
        "raw_sharpe": raw_sharpe,
        "trials": trials,
        "return_skewness": skew,
        "return_kurtosis": kurtosis,
        "expected_maximum_sharpe": expected_max,
        "deflated_sharpe_probability": probability,
        "label": "passed" if probability >= 0.95 else "failed",
    }


def probability_of_backtest_overfitting(
    fold_scores: list[list[float]],
) -> dict[str, float | int | None | str]:
    """Estimate PBO from per-fold configuration scores.

    Each inner list contains scores for all configurations in one chronological
    fold in the same configuration order. For every split of folds into an
    earlier selection segment and later evaluation segment, the best selection
    configuration is checked against the median evaluation rank.
    """
    if len(fold_scores) < 4 or any(not fold for fold in fold_scores):
        return {"estimated_pbo": None, "label": "insufficient_data", "splits": 0}
    config_count = len(fold_scores[0])
    if config_count < 2 or any(len(fold) != config_count for fold in fold_scores):
        return {"estimated_pbo": None, "label": "insufficient_data", "splits": 0}
    failures = 0
    correlations: list[float] = []
    degradations: list[float] = []
    splits = 0
    for cut in range(2, len(fold_scores) - 1):
        train = fold_scores[:cut]
        test = fold_scores[cut:]
        in_scores = [mean([fold[index] for fold in train]) for index in range(config_count)]
        out_scores = [mean([fold[index] for fold in test]) for index in range(config_count)]
        selected = max(range(config_count), key=in_scores.__getitem__)
        sorted_out = sorted(range(config_count), key=out_scores.__getitem__)
        out_rank = sorted_out.index(selected) + 1
        if out_rank <= config_count / 2:
            failures += 1
        degradations.append(in_scores[selected] - out_scores[selected])
        in_mean = mean(in_scores)
        out_mean = mean(out_scores)
        numerator = sum((a - in_mean) * (b - out_mean) for a, b in zip(in_scores, out_scores, strict=True))
        denominator = sqrt(sum((a - in_mean) ** 2 for a in in_scores) * sum((b - out_mean) ** 2 for b in out_scores))
        correlations.append(numerator / denominator if denominator else 0.0)
        splits += 1
    pbo = failures / splits if splits else None
    label = (
        "insufficient_data" if pbo is None
        else "low apparent overfitting risk" if pbo < 0.20
        else "moderate overfitting risk" if pbo < 0.50
        else "high overfitting risk"
    )
    return {
        "estimated_pbo": pbo,
        "label": label,
        "splits": splits,
        "in_sample_out_of_sample_correlation": mean(correlations) if correlations else None,
        "selected_model_degradation": mean(degradations) if degradations else None,
    }
