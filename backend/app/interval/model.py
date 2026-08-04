from __future__ import annotations

import math
from dataclasses import dataclass
from time import time
from typing import Any
from uuid import uuid4

from app.research.types import MarketType

from .features import feature_snapshot
from .types import (
    BiasStatus,
    DataStatus,
    Factor,
    Horizon,
    IntervalAnalysis,
    IntervalWindow,
    ProbabilityState,
)


@dataclass(frozen=True)
class Calibration:
    model_id: str
    sample_count: int
    intercept: float
    coefficient: float
    brier_skill: float
    validation_end_timestamp: int

    @property
    def usable(self) -> bool:
        return self.sample_count >= 200 and self.brier_skill > 0


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


def _logistic(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))


def _bias(score: float, no_trade: bool, stale: bool, enough: bool) -> BiasStatus:
    if stale:
        return BiasStatus.DATA_STALE
    if not enough:
        return BiasStatus.INSUFFICIENT_DATA
    if no_trade:
        return BiasStatus.NO_TRADE
    if score >= 0.65:
        return BiasStatus.STRONG_UP
    if score >= 0.35:
        return BiasStatus.UP
    if score >= 0.12:
        return BiasStatus.SLIGHT_UP
    if score <= -0.65:
        return BiasStatus.STRONG_DOWN
    if score <= -0.35:
        return BiasStatus.DOWN
    if score <= -0.12:
        return BiasStatus.SLIGHT_DOWN
    return BiasStatus.NEUTRAL


def _regime(features: dict[str, Any]) -> str:
    regression = features.get("regression") or {}
    slope = float(regression.get("slope") or 0.0)
    r_squared = float(regression.get("r_squared") or 0.0)
    atr = float(features.get("atr") or 0.0)
    price = float(features.get("current_price") or 1.0)
    normalized_slope = slope / max(atr, price * 1e-6)
    efficiency = float(features.get("directional_efficiency") or 0.0)
    if r_squared >= 0.55 and efficiency >= 0.45:
        if normalized_slope > 0.08:
            return "Strong Bullish Trend"
        if normalized_slope < -0.08:
            return "Strong Bearish Trend"
        if normalized_slope > 0:
            return "Moderate Bullish Trend"
        if normalized_slope < 0:
            return "Moderate Bearish Trend"
    rv = float(features.get("realized_volatility") or 0.0)
    if efficiency < 0.25:
        return "High-Volatility Range" if rv > 0.002 else "Low-Volatility Range"
    return "Uncertain Transition"


def analyze_interval(
    *,
    asset: str,
    exchange: str,
    market_type: MarketType,
    candles: list,
    window: IntervalWindow,
    data_status: DataStatus,
    generated_timestamp: int | None = None,
    calibration: Calibration | None = None,
    current_price_override: float | None = None,
) -> IntervalAnalysis:
    generated = int(time()) if generated_timestamp is None else generated_timestamp
    current_price = current_price_override or candles[-1].close
    remaining = max(0, window.expiry_timestamp - generated)
    features = feature_snapshot(candles, window.reference_price, window.horizon.minutes)
    features["current_price"] = current_price
    features["reference_distance"] = current_price / window.reference_price - 1.0
    if features.get("vwap"):
        features["vwap_distance"] = current_price / float(features["vwap"]) - 1.0
    if features.get("atr"):
        features["atr_distance_from_reference"] = (current_price - window.reference_price) / float(features["atr"])
    regression = features.get("regression") or {}
    flow = features.get("flow") or {}

    reference_distance = float(features.get("reference_distance") or 0.0)
    vwap_distance = float(features.get("vwap_distance") or 0.0)
    ema_alignment = float(features.get("ema_alignment") or 0.0)
    efficiency = float(features.get("directional_efficiency") or 0.0)
    residual_z = float(regression.get("residual_z") or 0.0)
    slope = float(regression.get("slope") or 0.0)
    atr = float(features.get("atr") or 0.0)
    flow_delta = flow.get("aggressive_delta")
    buy_ratio = flow.get("buy_ratio")

    score_terms = [
        max(-1.0, min(1.0, reference_distance * 150.0)) * 0.22,
        max(-1.0, min(1.0, vwap_distance * 180.0)) * 0.18,
        ema_alignment * 0.18,
        max(-1.0, min(1.0, slope / max(atr, current_price * 1e-6) * 7.0)) * 0.16,
        max(-1.0, min(1.0, residual_z / 3.0)) * 0.10,
    ]
    if isinstance(buy_ratio, (int, float)):
        score_terms.append((float(buy_ratio) - 0.5) * 0.32)
    raw_score = max(-1.0, min(1.0, sum(score_terms)))

    extension = min(1.0, abs(residual_z) / 3.5)
    reference_extension = min(1.0, abs(reference_distance) / max(0.0005, float(features.get("realized_volatility") or 0.0005) * 2.5))
    trend_strength = min(1.0, abs(ema_alignment) * 0.35 + efficiency * 0.65)
    flow_continuation = 0.0
    flow_absorption = 0.0
    if isinstance(flow_delta, (int, float)) and isinstance(buy_ratio, (int, float)):
        aligned = (raw_score >= 0 and float(flow_delta) > 0) or (raw_score < 0 and float(flow_delta) < 0)
        flow_continuation = abs(float(buy_ratio) - 0.5) * 2.0 if aligned else 0.0
        flow_absorption = abs(float(buy_ratio) - 0.5) * 2.0 if not aligned else 0.0

    reversion = _clip(0.15 + 0.38 * extension + 0.24 * reference_extension + 0.18 * flow_absorption - 0.35 * trend_strength)
    continuation = _clip(0.12 + 0.42 * trend_strength + 0.24 * efficiency + 0.20 * flow_continuation - 0.24 * extension)
    uncertainty = _clip(1.0 - max(reversion, continuation) + (0.12 if abs(reversion - continuation) < 0.10 else 0.0))

    rv = float(features.get("realized_volatility") or 0.0)
    remaining_bars = max(1.0, remaining / 60.0)
    expected_sigma = rv * math.sqrt(remaining_bars)
    signed_return = raw_score * expected_sigma * 0.75
    expected_absolute = expected_sigma * 0.8 if rv > 0 else None
    expected_close = current_price * (1.0 + signed_return) if rv > 0 else None
    expected_low = current_price * (1.0 - expected_sigma * 1.28) if rv > 0 else None
    expected_high = current_price * (1.0 + expected_sigma * 1.28) if rv > 0 else None

    probability_state = ProbabilityState.HEURISTIC
    up_probability = None
    down_probability = None
    model_id = None
    if data_status.stale:
        probability_state = ProbabilityState.STALE
    elif len(candles) < 120:
        probability_state = ProbabilityState.INSUFFICIENT_DATA
    elif calibration and calibration.usable and calibration.validation_end_timestamp <= window.start_timestamp:
        probability_state = ProbabilityState.CALIBRATED
        up_probability = _clip(_logistic(calibration.intercept + calibration.coefficient * raw_score), 0.01, 0.99)
        down_probability = 1.0 - up_probability
        model_id = calibration.model_id

    supporting: list[Factor] = []
    opposing: list[Factor] = []
    def add_factor(name: str, value: float | str | None, positive: bool, explanation: str) -> None:
        factor = Factor(name=name, value=value, direction="supporting" if positive else "opposing", explanation=explanation)
        (supporting if positive else opposing).append(factor)

    if ema_alignment:
        add_factor("EMA alignment", ema_alignment, ema_alignment * raw_score >= 0, "EMA 9, 20 and 50 alignment is evaluated from completed candles.")
    if vwap_distance:
        add_factor("VWAP position", vwap_distance, vwap_distance * raw_score >= 0, "Current price is compared with rolling interval VWAP.")
    if residual_z:
        add_factor("Regression extension", residual_z, abs(residual_z) < 2.5 or residual_z * raw_score >= 0, "Residual z-score measures frozen current extension from the rolling regression center.")
    if isinstance(buy_ratio, (int, float)):
        add_factor("Aggressive buy ratio", float(buy_ratio), (float(buy_ratio) - 0.5) * raw_score >= 0, "Aggressive flow is included only when the source candles contain classified flow.")
    add_factor("Directional efficiency", efficiency, efficiency >= 0.35, "Efficiency compares net displacement with the full recent price path.")

    reasons: list[str] = []
    if data_status.stale:
        reasons.append("Required market data is stale")
    if data_status.score < 70:
        reasons.append("Data-quality score is below 70")
    if remaining <= 10:
        reasons.append("Interval is within ten seconds of expiry")
    if abs(raw_score) < 0.08:
        reasons.append("Directional evidence is too weak")
    if reversion >= 0.65 and continuation >= 0.65:
        reasons.append("Reversion and continuation evidence conflict")
    no_trade = bool(reasons)

    return IntervalAnalysis(
        prediction_id=str(uuid4()),
        asset=asset,
        exchange=exchange,
        market_type=market_type,
        horizon=window.horizon,
        generated_timestamp=generated,
        interval_start_timestamp=window.start_timestamp,
        expiry_timestamp=window.expiry_timestamp,
        reference_price=window.reference_price,
        current_price=current_price,
        difference=current_price - window.reference_price,
        difference_percent=current_price / window.reference_price - 1.0,
        seconds_remaining=remaining,
        probability_state=probability_state,
        up_probability=up_probability,
        down_probability=down_probability,
        raw_direction_score=raw_score,
        expected_close=expected_close,
        expected_signed_return=signed_return if rv > 0 else None,
        expected_absolute_return=expected_absolute,
        expected_low=expected_low,
        expected_high=expected_high,
        upper_touch_probability=None,
        lower_touch_probability=None,
        reference_retouch_probability=None,
        vwap_touch_probability=None,
        regression_center_touch_probability=None,
        reversion_score=reversion,
        continuation_score=continuation,
        uncertainty_score=uncertainty,
        reversion_label="REVERSION SCORE — NOT A VALIDATED PROBABILITY",
        continuation_label="CONTINUATION SCORE — NOT A VALIDATED PROBABILITY",
        status=_bias(raw_score, no_trade, data_status.stale, len(candles) >= 120),
        current_regime=_regime(features),
        data_status=data_status,
        model_version="interval-direction-v1",
        feature_version="interval-features-v1",
        calibrated_model_id=model_id,
        supporting_factors=tuple(supporting[:6]),
        opposing_factors=tuple(opposing[:6]),
        no_trade_reasons=tuple(reasons),
        feature_snapshot=features,
    )
