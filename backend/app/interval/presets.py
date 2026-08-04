from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean
from typing import Any

from app.research.types import Candle

from .features import feature_snapshot
from .types import Horizon, IntervalAnalysis


@dataclass(frozen=True)
class PresetDefinition:
    preset_id: str
    name: str
    category: str
    description: str
    minimum_score: float = 0.08


PRESETS: tuple[PresetDefinition, ...] = (
    PresetDefinition("balanced", "Balanced Composite", "Composite", "Blends reference distance, VWAP, trend, regression and available aggressive flow."),
    PresetDefinition("fast_momentum", "Fast Momentum", "Continuation", "Follows reference/VWAP direction when trend efficiency and regression slope agree."),
    PresetDefinition("breakout_hold", "Breakout Hold", "Continuation", "Follows a move away from the fixed interval reference when the path is efficient."),
    PresetDefinition("trend_pullback", "Trend Pullback", "Continuation", "Trades with the broader trend after a temporary regression or VWAP pullback."),
    PresetDefinition("vwap_reversion", "VWAP Reversion", "Reversion", "Fades statistically large VWAP extension when trend efficiency is weak."),
    PresetDefinition("regression_extreme", "Regression Extreme", "Reversion", "Fades large regression residuals, with trend strength reducing the signal."),
    PresetDefinition("reference_reversion", "Reference Reversion", "Reversion", "Looks for a return toward the interval opening reference after an outsized move."),
    PresetDefinition("flow_follow", "Aggressive Flow Follow", "Order Flow", "Follows taker buy/sell imbalance when price direction agrees."),
    PresetDefinition("flow_absorption_fade", "Flow Absorption Fade", "Order Flow", "Fades aggressive flow when price displacement does not confirm it."),
    PresetDefinition("late_interval_hold", "Late Interval Hold", "Expiry", "Late in the interval, favors the side already holding above or below the reference."),
)


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


def _num(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else default


def _nested(features: dict[str, Any], key: str) -> dict[str, Any]:
    value = features.get(key)
    return value if isinstance(value, dict) else {}


def score_to_probability(score: float) -> float:
    probability = 1.0 / (1.0 + math.exp(-3.6 * _clip(score)))
    return min(0.99, max(0.01, probability))


def score_preset(preset_id: str, features: dict[str, Any], elapsed_fraction: float) -> tuple[float, tuple[str, ...]]:
    reference_distance = _num(features.get("reference_distance"))
    vwap_distance = _num(features.get("vwap_distance"))
    atr_distance = _num(features.get("atr_distance_from_reference"))
    ema_alignment = _num(features.get("ema_alignment"))
    efficiency = _num(features.get("directional_efficiency"))
    regression = _nested(features, "regression")
    residual_z = _num(regression.get("residual_z"))
    slope = _num(regression.get("slope"))
    r_squared = _num(regression.get("r_squared"))
    atr = max(_num(features.get("atr")), _num(features.get("current_price"), 1.0) * 1e-6)
    slope_normalized = _clip(slope / atr * 6.0)
    flow = _nested(features, "flow")
    buy_ratio = flow.get("buy_ratio")
    flow_score = _clip((float(buy_ratio) - 0.5) * 3.0) if isinstance(buy_ratio, (int, float)) else 0.0

    reference_signal = _clip(reference_distance * 220.0)
    vwap_signal = _clip(vwap_distance * 260.0)
    atr_signal = _clip(atr_distance / 2.5)
    residual_signal = _clip(residual_z / 3.0)
    trend_signal = _clip(0.48 * ema_alignment + 0.34 * slope_normalized + 0.18 * reference_signal)
    reasons: list[str] = []

    if preset_id == "balanced":
        score = 0.24 * reference_signal + 0.18 * vwap_signal + 0.20 * ema_alignment + 0.16 * slope_normalized + 0.10 * residual_signal + 0.12 * flow_score
        reasons.extend(("reference/VWAP blend", "EMA and regression trend", "available taker-flow confirmation"))
    elif preset_id == "fast_momentum":
        score = (0.30 * reference_signal + 0.22 * vwap_signal + 0.23 * trend_signal + 0.15 * flow_score) * (0.55 + 0.45 * efficiency)
        reasons.extend(("price direction from fixed reference", "trend efficiency", "flow confirmation"))
    elif preset_id == "breakout_hold":
        score = 0.55 * reference_signal + 0.25 * trend_signal + 0.20 * flow_score
        score *= 0.45 + 0.55 * efficiency
        reasons.extend(("distance from interval open", "efficient path", "trend alignment"))
    elif preset_id == "trend_pullback":
        pullback = -0.55 * residual_signal - 0.45 * vwap_signal
        trend_direction = 1.0 if trend_signal > 0.15 else -1.0 if trend_signal < -0.15 else 0.0
        pullback_quality = max(0.0, -pullback * trend_direction)
        score = trend_direction * (0.45 * abs(trend_signal) + 0.35 * pullback_quality + 0.20 * r_squared)
        reasons.extend(("broader trend direction", "temporary pullback", "regression fit"))
    elif preset_id == "vwap_reversion":
        score = -vwap_signal * (0.70 + 0.30 * max(0.0, 1.0 - efficiency)) - 0.15 * trend_signal
        reasons.extend(("VWAP extension", "lower path efficiency", "trend penalty"))
    elif preset_id == "regression_extreme":
        score = -0.72 * residual_signal - 0.18 * atr_signal - 0.10 * trend_signal
        score *= 0.65 + 0.35 * max(0.0, 1.0 - r_squared)
        reasons.extend(("regression residual extreme", "ATR-normalized extension", "trend-strength penalty"))
    elif preset_id == "reference_reversion":
        score = -0.66 * reference_signal - 0.20 * atr_signal - 0.14 * trend_signal
        score *= 0.60 + 0.40 * max(0.0, 1.0 - efficiency)
        reasons.extend(("extension from fixed reference", "ATR normalization", "choppy-path preference"))
    elif preset_id == "flow_follow":
        price_confirmation = 1.0 if flow_score * reference_signal > 0 else 0.35
        score = (0.62 * flow_score + 0.24 * reference_signal + 0.14 * trend_signal) * price_confirmation
        reasons.extend(("aggressive buy/sell ratio", "price confirmation", "trend context"))
    elif preset_id == "flow_absorption_fade":
        mismatch = abs(flow_score) * max(0.0, 1.0 - abs(reference_signal))
        score = -math.copysign(mismatch, flow_score) if flow_score else 0.0
        score += -0.18 * residual_signal
        reasons.extend(("large flow with weak displacement", "fade of unconfirmed flow", "regression context"))
    elif preset_id == "late_interval_hold":
        time_weight = max(0.0, min(1.0, (elapsed_fraction - 0.45) / 0.55))
        score = time_weight * (0.58 * reference_signal + 0.22 * trend_signal + 0.20 * flow_score)
        reasons.extend(("late-interval time weight", "current side of reference", "continuation confirmation"))
    else:
        raise KeyError(f"unknown preset {preset_id}")
    return _clip(score), tuple(reasons)


def _market_edge(fair_up: float, contract: dict[str, Any] | None) -> dict[str, float | None]:
    if not contract:
        return {"up_edge": None, "down_edge": None, "best_edge": None}
    up_market = contract.get("up", {}).get("market_price") if isinstance(contract.get("up"), dict) else None
    down_market = contract.get("down", {}).get("market_price") if isinstance(contract.get("down"), dict) else None
    up_edge = fair_up - float(up_market) if isinstance(up_market, (int, float)) else None
    fair_down = 1.0 - fair_up
    down_edge = fair_down - float(down_market) if isinstance(down_market, (int, float)) else None
    values = [value for value in (up_edge, down_edge) if value is not None]
    return {"up_edge": up_edge, "down_edge": down_edge, "best_edge": max(values) if values else None}


def current_preset_rows(analysis: IntervalAnalysis, contract: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    elapsed = max(0, analysis.generated_timestamp - analysis.interval_start_timestamp)
    duration = max(1, analysis.expiry_timestamp - analysis.interval_start_timestamp)
    elapsed_fraction = min(1.0, elapsed / duration)
    rows: list[dict[str, Any]] = []
    for definition in PRESETS:
        score, reasons = score_preset(definition.preset_id, analysis.feature_snapshot, elapsed_fraction)
        fair_up = score_to_probability(score)
        side = "up" if score >= definition.minimum_score else "down" if score <= -definition.minimum_score else "watch"
        edges = _market_edge(fair_up, contract)
        rows.append({
            "preset_id": definition.preset_id,
            "name": definition.name,
            "category": definition.category,
            "description": definition.description,
            "minimum_score": definition.minimum_score,
            "score": score,
            "strength": abs(score),
            "side": side,
            "fair_up": fair_up,
            "fair_down": 1.0 - fair_up,
            "fair_value_state": "indicative_uncalibrated",
            "reasons": reasons,
            **edges,
        })
    return rows


def _regime(features: dict[str, Any]) -> str:
    regression = _nested(features, "regression")
    efficiency = _num(features.get("directional_efficiency"))
    r_squared = _num(regression.get("r_squared"))
    ema_alignment = _num(features.get("ema_alignment"))
    if efficiency >= 0.45 and r_squared >= 0.45:
        return "bull trend" if ema_alignment > 0 else "bear trend" if ema_alignment < 0 else "trend"
    if efficiency <= 0.25:
        return "range"
    return "transition"


def backtest_preset(
    candles: list[Candle],
    *,
    horizon: Horizon,
    preset_id: str,
    elapsed_seconds: int,
    minimum_score: float | None = None,
) -> dict[str, Any]:
    definition = next((item for item in PRESETS if item.preset_id == preset_id), None)
    if definition is None:
        raise KeyError(f"unknown preset {preset_id}")
    threshold = definition.minimum_score if minimum_score is None else minimum_score
    period = horizon.minutes * 60
    elapsed = max(60, min(period - 60, elapsed_seconds - elapsed_seconds % 60))
    by_timestamp = {candle.timestamp: candle for candle in candles}
    index_by_timestamp = {candle.timestamp: index for index, candle in enumerate(candles)}
    starts = [timestamp for timestamp in by_timestamp if timestamp % period == 0]
    results: list[dict[str, Any]] = []
    for start in sorted(starts):
        expiry = start + period
        evaluation_close_timestamp = start + elapsed - 60
        start_candle = by_timestamp.get(start)
        expiry_candle = by_timestamp.get(expiry)
        evaluation_index = index_by_timestamp.get(evaluation_close_timestamp)
        if start_candle is None or expiry_candle is None or evaluation_index is None or evaluation_index < 60:
            continue
        subset = candles[: evaluation_index + 1]
        features = feature_snapshot(subset, start_candle.open, horizon.minutes)
        score, _ = score_preset(preset_id, features, elapsed / period)
        if abs(score) < threshold:
            continue
        fair_up = score_to_probability(score)
        finished_up = expiry_candle.open >= start_candle.open
        predicted_up = score > 0
        correct = predicted_up == finished_up
        probability_for_outcome = fair_up if finished_up else 1.0 - fair_up
        brier = (fair_up - (1.0 if finished_up else 0.0)) ** 2
        strength = "strong" if abs(score) >= 0.55 else "medium" if abs(score) >= 0.28 else "light"
        results.append({
            "interval_start": start,
            "expiry": expiry,
            "score": score,
            "fair_up": fair_up,
            "finished_up": finished_up,
            "correct": correct,
            "brier": brier,
            "probability_for_outcome": probability_for_outcome,
            "regime": _regime(features),
            "strength": strength,
            "signed_return": expiry_candle.open / start_candle.open - 1.0,
        })
    wins = sum(1 for result in results if result["correct"])
    total = len(results)

    def breakdown(key: str) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for result in results:
            groups.setdefault(str(result[key]), []).append(result)
        return [
            {
                "case": case,
                "trades": len(group),
                "win_rate": sum(1 for item in group if item["correct"]) / len(group),
                "average_score": mean(abs(float(item["score"])) for item in group),
                "average_signed_return": mean(float(item["signed_return"]) for item in group),
            }
            for case, group in sorted(groups.items())
        ]

    return {
        "preset_id": definition.preset_id,
        "name": definition.name,
        "category": definition.category,
        "horizon": horizon.value,
        "elapsed_seconds": elapsed,
        "elapsed_minutes": elapsed // 60,
        "minimum_score": threshold,
        "source_candles": len(candles),
        "samples": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate": wins / total if total else None,
        "average_brier": mean(float(result["brier"]) for result in results) if results else None,
        "average_probability_on_realized_outcome": mean(float(result["probability_for_outcome"]) for result in results) if results else None,
        "average_absolute_score": mean(abs(float(result["score"])) for result in results) if results else None,
        "cases_by_regime": breakdown("regime"),
        "cases_by_strength": breakdown("strength"),
        "contract_pnl_tested": False,
        "costs_included": False,
        "interpretation": (
            "This is a same-minute-of-interval directional backtest using completed one-minute candles. "
            "It does not include historical prediction-market quotes, fees, spread, or slippage."
        ),
    }
