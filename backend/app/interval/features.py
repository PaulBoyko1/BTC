from __future__ import annotations

from math import sqrt
from statistics import mean
from typing import Any

from app.research.types import Candle


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])
    return result


def atr(candles: list[Candle], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    ranges: list[float] = []
    for index in range(len(candles) - period, len(candles)):
        candle = candles[index]
        previous = candles[index - 1].close
        ranges.append(max(candle.high - candle.low, abs(candle.high - previous), abs(candle.low - previous)))
    return mean(ranges)


def rolling_vwap(candles: list[Candle], lookback: int = 60) -> float | None:
    subset = candles[-lookback:]
    if not subset:
        return None
    quote = sum(c.quote_volume for c in subset)
    base = sum(c.volume for c in subset)
    if quote > 0 and base > 0:
        return quote / base
    weights = [max(c.volume, 1.0) for c in subset]
    prices = [c.vwap or ((c.high + c.low + c.close) / 3.0) for c in subset]
    total = sum(weights)
    return sum(price * weight for price, weight in zip(prices, weights, strict=True)) / total if total else None


def linear_regression_channel(candles: list[Candle], lookback: int = 55, width: float = 3.0) -> dict[str, float] | None:
    if len(candles) < lookback:
        return None
    values = [c.close for c in candles[-lookback:]]
    n = len(values)
    x_mean = (n - 1) / 2.0
    y_mean = mean(values)
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    slope = sum((i - x_mean) * (value - y_mean) for i, value in enumerate(values)) / denominator if denominator else 0.0
    intercept = y_mean - slope * x_mean
    fitted = [intercept + slope * i for i in range(n)]
    residuals = [value - fit for value, fit in zip(values, fitted, strict=True)]
    sigma = sqrt(sum(value * value for value in residuals) / max(1, n - 2))
    center = fitted[-1]
    ss_total = sum((value - y_mean) ** 2 for value in values)
    ss_residual = sum(value * value for value in residuals)
    r_squared = 1.0 - ss_residual / ss_total if ss_total > 0 else 0.0
    residual_z = residuals[-1] / sigma if sigma > 0 else 0.0
    return {
        "center": center,
        "upper": center + width * sigma,
        "lower": center - width * sigma,
        "slope": slope,
        "r_squared": r_squared,
        "sigma": sigma,
        "residual_z": residual_z,
    }


def realized_volatility(candles: list[Candle], lookback: int = 60) -> float | None:
    subset = candles[-(lookback + 1):]
    if len(subset) < 3:
        return None
    returns = [subset[i].close / subset[i - 1].close - 1.0 for i in range(1, len(subset))]
    avg = mean(returns)
    variance = sum((value - avg) ** 2 for value in returns) / max(1, len(returns) - 1)
    return sqrt(variance)


def efficiency_ratio(candles: list[Candle], lookback: int = 20) -> float | None:
    subset = candles[-(lookback + 1):]
    if len(subset) < lookback + 1:
        return None
    displacement = abs(subset[-1].close - subset[0].close)
    path = sum(abs(subset[i].close - subset[i - 1].close) for i in range(1, len(subset)))
    return displacement / path if path > 0 else 0.0


def flow_features(candles: list[Candle], lookback: int = 60) -> dict[str, float | None]:
    subset = candles[-lookback:]
    buy = sum(c.aggressive_buy_notional or 0.0 for c in subset)
    sell = sum(c.aggressive_sell_notional or 0.0 for c in subset)
    total = buy + sell
    delta = buy - sell
    buy_ratio = buy / total if total > 0 else None
    sell_ratio = sell / total if total > 0 else None
    price_change = subset[-1].close - subset[0].open if subset else 0.0
    upward = max(price_change, 0.0)
    downward = max(-price_change, 0.0)
    epsilon = 1e-9
    return {
        "aggressive_buy_notional": buy if total > 0 else None,
        "aggressive_sell_notional": sell if total > 0 else None,
        "aggressive_delta": delta if total > 0 else None,
        "buy_ratio": buy_ratio,
        "sell_ratio": sell_ratio,
        "upward_flow_efficiency": upward / max(buy, epsilon) if buy > 0 else None,
        "downward_flow_efficiency": downward / max(sell, epsilon) if sell > 0 else None,
        "buy_absorption": buy / max(upward, epsilon) if buy > 0 else None,
        "sell_absorption": sell / max(downward, epsilon) if sell > 0 else None,
    }


def feature_snapshot(candles: list[Candle], reference_price: float, horizon_minutes: int) -> dict[str, Any]:
    closes = [c.close for c in candles]
    latest = candles[-1]
    ema9 = ema(closes, 9)[-1] if len(closes) >= 9 else latest.close
    ema20 = ema(closes, 20)[-1] if len(closes) >= 20 else latest.close
    ema50 = ema(closes, 50)[-1] if len(closes) >= 50 else latest.close
    current_atr = atr(candles, 14)
    vwap = rolling_vwap(candles, max(15, horizon_minutes))
    regression = linear_regression_channel(candles)
    rv = realized_volatility(candles, max(30, horizon_minutes))
    efficiency = efficiency_ratio(candles)
    flow = flow_features(candles)
    reference_distance = latest.close / reference_price - 1.0
    vwap_distance = latest.close / vwap - 1.0 if vwap else None
    atr_distance = (latest.close - reference_price) / current_atr if current_atr else None
    return {
        "current_price": latest.close,
        "reference_price": reference_price,
        "reference_distance": reference_distance,
        "vwap": vwap,
        "vwap_distance": vwap_distance,
        "ema9": ema9,
        "ema20": ema20,
        "ema50": ema50,
        "ema_alignment": 1 if ema9 > ema20 > ema50 else -1 if ema9 < ema20 < ema50 else 0,
        "atr": current_atr,
        "atr_distance_from_reference": atr_distance,
        "realized_volatility": rv,
        "directional_efficiency": efficiency,
        "regression": regression,
        "flow": flow,
        "open_interest": latest.open_interest,
        "funding_rate": latest.funding_rate,
        "cvd": latest.cvd,
        "bid_replenishment": latest.bid_replenishment,
        "ask_replenishment": latest.ask_replenishment,
        "liquidation_long_notional": latest.liquidation_long_notional,
        "liquidation_short_notional": latest.liquidation_short_notional,
        "feature_source_timestamp": latest.timestamp,
        "feature_availability_timestamp": latest.availability_timestamp or latest.timestamp + 60,
        "feature_calculation_timestamp": latest.availability_timestamp or latest.timestamp + 60,
        "feature_version": "interval-features-v1",
    }
