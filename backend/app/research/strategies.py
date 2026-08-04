from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import sqrt
from statistics import mean
from typing import Any, Iterable

from .types import Candle, MarketType, Signal, StrategyDefinition, StrategyFamily


def _sma(values: list[float], end: int, lookback: int) -> float | None:
    start = end - lookback + 1
    if start < 0:
        return None
    return sum(values[start : end + 1]) / lookback


def _ema_series(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1.0)
    out: list[float] = []
    current = values[0]
    for value in values:
        current = value if not out else alpha * value + (1.0 - alpha) * current
        out.append(current)
    return out


def _atr(candles: list[Candle], end: int, period: int) -> float | None:
    if end < period:
        return None
    trs: list[float] = []
    for i in range(end - period + 1, end + 1):
        previous_close = candles[i - 1].close if i > 0 else candles[i].open
        trs.append(max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - previous_close),
            abs(candles[i].low - previous_close),
        ))
    return sum(trs) / len(trs)


def _rolling_vwap(candles: list[Candle], end: int, lookback: int) -> float | None:
    start = end - lookback + 1
    if start < 0:
        return None
    subset = candles[start : end + 1]
    total_quote = sum(c.quote_volume for c in subset)
    total_base = sum(c.volume for c in subset)
    if total_quote > 0 and total_base > 0:
        return total_quote / total_base
    weighted = sum((c.vwap or ((c.high + c.low + c.close) / 3.0)) * max(c.volume, 1.0) for c in subset)
    weight = sum(max(c.volume, 1.0) for c in subset)
    return weighted / weight if weight else None


def _linear_regression(values: list[float]) -> tuple[float, float, float, float]:
    n = len(values)
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    slope = sum((i - x_mean) * (value - y_mean) for i, value in enumerate(values)) / denominator if denominator else 0.0
    intercept = y_mean - slope * x_mean
    residuals = [value - (intercept + slope * i) for i, value in enumerate(values)]
    sigma = sqrt(sum(r * r for r in residuals) / max(1, n - 2))
    fitted = [intercept + slope * i for i in range(n)]
    ss_total = sum((v - y_mean) ** 2 for v in values)
    ss_residual = sum((v - f) ** 2 for v, f in zip(values, fitted, strict=True))
    r_squared = 1.0 - ss_residual / ss_total if ss_total > 0 else 0.0
    return slope, intercept, sigma, r_squared


def _percentile_rank(history: list[float], value: float) -> float | None:
    if not history:
        return None
    return sum(1 for item in history if item <= value) / len(history) * 100.0


def _conservative_levels(candle: Candle, side: str, atr: float, stop_atr: float, target_rr: float) -> tuple[float, float]:
    if side == "long":
        stop = min(candle.low, candle.close - stop_atr * atr)
        risk = max(candle.close - stop, atr * 0.05)
        return stop, candle.close + target_rr * risk
    stop = max(candle.high, candle.close + stop_atr * atr)
    risk = max(stop - candle.close, atr * 0.05)
    return stop, candle.close - target_rr * risk


class ResearchStrategy(ABC):
    definition: StrategyDefinition

    @abstractmethod
    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def generate_signals(self, candles: list[Candle], parameters: dict[str, Any], horizon_minutes: int) -> list[Signal]:
        raise NotImplementedError

    def default_parameters(self) -> dict[str, Any]:
        return {name: schema["default"] for name, schema in self.definition.parameter_schema.items()}

    @staticmethod
    def _coerce(parameters: dict[str, Any], schema: dict[str, dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        unknown = set(parameters) - set(schema)
        if unknown:
            raise ValueError(f"Unknown parameters: {', '.join(sorted(unknown))}")
        for name, spec in schema.items():
            value = parameters.get(name, spec["default"])
            kind = spec["type"]
            if kind == "integer":
                value = int(value)
            elif kind == "number":
                value = float(value)
            elif kind == "boolean":
                value = bool(value)
            elif kind == "string":
                value = str(value)
            if "enum" in spec and value not in spec["enum"]:
                raise ValueError(f"{name} must be one of {spec['enum']}")
            if "minimum" in spec and value < spec["minimum"]:
                raise ValueError(f"{name} must be >= {spec['minimum']}")
            if "maximum" in spec and value > spec["maximum"]:
                raise ValueError(f"{name} must be <= {spec['maximum']}")
            result[name] = value
        return result


class RegressionChannelStrategy(ResearchStrategy):
    definition = StrategyDefinition(
        strategy_id="regression_channel_reversion",
        strategy_version="1.0.0",
        family=StrategyFamily.MEAN_REVERSION,
        name="Regression Channel Reversion",
        description="Fade a completed-candle close beyond a rolling least-squares regression channel by a minimum ATR extension.",
        required_data_feeds=("completed_candles",),
        required_features=("atr", "rolling_regression"),
        supported_assets=("BTCUSDT", "ETHUSDT"),
        supported_market_types=(MarketType.SPOT, MarketType.PERPETUAL),
        supported_source_timeframes=(1, 15, 60),
        supported_prediction_horizons=(15, 60),
        parameter_schema={
            "lookback": {"type": "integer", "default": 55, "minimum": 20, "maximum": 240},
            "channel_width": {"type": "number", "default": 3.0, "minimum": 1.0, "maximum": 5.0},
            "atr_period": {"type": "integer", "default": 14, "minimum": 5, "maximum": 100},
            "minimum_atr_extension": {"type": "number", "default": 0.20, "minimum": 0.0, "maximum": 3.0},
            "confirmation": {"type": "string", "default": "none", "enum": ["none", "channel_reclaim"]},
            "stop_atr": {"type": "number", "default": 0.20, "minimum": 0.05, "maximum": 3.0},
            "target_rr": {"type": "number", "default": 1.5, "minimum": 0.25, "maximum": 10.0},
            "max_holding_bars": {"type": "integer", "default": 15, "minimum": 1, "maximum": 240},
        },
        entry_rules=(
            "Long when a completed candle closes below the lower regression band by the configured ATR extension.",
            "Short when a completed candle closes above the upper regression band by the configured ATR extension.",
            "If channel_reclaim is selected, require the next completed candle to close back inside the frozen signal-time band.",
        ),
        invalidation_rules=("Reject incomplete candles and unavailable future observations.",),
        stop_rules=("Stop at the signal extreme or configured ATR distance, whichever is farther from entry.",),
        target_rules=("Target a fixed reward-to-risk multiple from the frozen entry and stop.",),
        position_sizing_rules=("Sizing is delegated to the experiment execution model.",),
        maximum_holding_period_minutes=240,
        cost_assumptions=("Uses experiment fee, spread, slippage, latency and funding model.",),
        regime_restrictions=(),
        data_quality_requirements=("Chronological complete candles", "Frozen rolling regression values"),
    )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return self._coerce(parameters, self.definition.parameter_schema)

    def generate_signals(self, candles: list[Candle], parameters: dict[str, Any], horizon_minutes: int) -> list[Signal]:
        p = self.validate_parameters(parameters)
        closes = [c.close for c in candles]
        signals: list[Signal] = []
        minimum_index = max(p["lookback"] - 1, p["atr_period"])
        for index in range(minimum_index, len(candles) - 1):
            candle = candles[index]
            if not candle.complete:
                continue
            window = closes[index - p["lookback"] + 1 : index + 1]
            slope, intercept, sigma, r_squared = _linear_regression(window)
            center = intercept + slope * (p["lookback"] - 1)
            upper = center + p["channel_width"] * sigma
            lower = center - p["channel_width"] * sigma
            atr = _atr(candles, index, p["atr_period"])
            if atr is None or atr <= 0:
                continue
            side: str | None = None
            extension = 0.0
            if candle.close < lower:
                extension = (lower - candle.close) / atr
                if extension >= p["minimum_atr_extension"]:
                    side = "long"
            elif candle.close > upper:
                extension = (candle.close - upper) / atr
                if extension >= p["minimum_atr_extension"]:
                    side = "short"
            if side is None:
                continue
            entry_index = index + 1
            if p["confirmation"] == "channel_reclaim":
                confirmation = candles[index + 1]
                reclaimed = confirmation.close >= lower if side == "long" else confirmation.close <= upper
                if not reclaimed or index + 2 >= len(candles):
                    continue
                entry_index = index + 2
            stop, target = _conservative_levels(candle, side, atr, p["stop_atr"], p["target_rr"])
            signals.append(Signal(
                timestamp=candle.timestamp,
                availability_timestamp=candle.availability_timestamp or candle.timestamp,
                side=side,
                entry_index=entry_index,
                signal_price=candle.close,
                stop_price=stop,
                target_price=target,
                max_holding_bars=min(p["max_holding_bars"], max(1, horizon_minutes)),
                feature_snapshot={
                    "lookback": p["lookback"],
                    "channel_width": p["channel_width"],
                    "regression_center": center,
                    "upper_band": upper,
                    "lower_band": lower,
                    "regression_slope": slope,
                    "regression_r_squared": r_squared,
                    "residual_sigma": sigma,
                    "atr": atr,
                    "atr_extension": extension,
                    "confirmation": p["confirmation"],
                },
                reason=f"{side} regression-channel extension {extension:.3f} ATR",
            ))
        return signals


class RegressionExtremeAbsorptionStrategy(RegressionChannelStrategy):
    definition = StrategyDefinition(
        strategy_id="regression_extreme_absorption",
        strategy_version="1.0.0",
        family=StrategyFamily.COMPOSITE,
        name="Regression Extreme Absorption",
        description="Regression extension plus extreme opposing aggressive flow, weak price impact, and optional reclaim/liquidity confirmation.",
        required_data_feeds=("completed_candles", "aggressive_trade_flow"),
        required_features=("atr", "rolling_regression", "aggressive_flow_percentile", "price_impact", "absorption_percentile"),
        supported_assets=("BTCUSDT", "ETHUSDT"),
        supported_market_types=(MarketType.SPOT, MarketType.PERPETUAL),
        supported_source_timeframes=(1,),
        supported_prediction_horizons=(15, 60),
        parameter_schema={
            "lookback": {"type": "integer", "default": 55, "minimum": 20, "maximum": 240},
            "channel_width": {"type": "number", "default": 3.0, "minimum": 1.0, "maximum": 5.0},
            "atr_period": {"type": "integer", "default": 14, "minimum": 5, "maximum": 100},
            "minimum_atr_extension": {"type": "number", "default": 0.20, "minimum": 0.0, "maximum": 3.0},
            "flow_lookback": {"type": "integer", "default": 1440, "minimum": 100, "maximum": 10080},
            "flow_percentile": {"type": "number", "default": 97.5, "minimum": 50.0, "maximum": 100.0},
            "absorption_percentile": {"type": "number", "default": 95.0, "minimum": 50.0, "maximum": 100.0},
            "confirmation": {"type": "string", "default": "channel_reclaim", "enum": ["none", "channel_reclaim", "liquidity_replenishment"]},
            "replenishment_threshold": {"type": "number", "default": 0.0, "minimum": 0.0, "maximum": 1e12},
            "stop_atr": {"type": "number", "default": 0.20, "minimum": 0.05, "maximum": 3.0},
            "target_rr": {"type": "number", "default": 1.5, "minimum": 0.25, "maximum": 10.0},
            "max_holding_bars": {"type": "integer", "default": 15, "minimum": 1, "maximum": 240},
        },
        entry_rules=(
            "Require a completed close beyond the regression band by the configured ATR extension.",
            "Require opposing aggressive quote notional to meet its rolling percentile using only prior completed intervals.",
            "Require high notional per unit of directional displacement (absorption percentile).",
            "Apply the configured reclaim or same-side replenishment confirmation.",
        ),
        invalidation_rules=("Reject when aggressive-flow history is unavailable or required L2 fields are absent.",),
        stop_rules=("Freeze stop from the signal extreme and configured ATR buffer.",),
        target_rules=("Freeze target as a reward-to-risk multiple; later bands do not repaint it.",),
        position_sizing_rules=("Sizing is delegated to the experiment execution model.",),
        maximum_holding_period_minutes=240,
        cost_assumptions=("Uses experiment fee, spread, slippage, latency and funding model.",),
        regime_restrictions=(),
        data_quality_requirements=("Chronological complete candles", "Aggressive-side notional", "No future percentile observations"),
    )

    def generate_signals(self, candles: list[Candle], parameters: dict[str, Any], horizon_minutes: int) -> list[Signal]:
        p = self.validate_parameters(parameters)
        closes = [c.close for c in candles]
        signals: list[Signal] = []
        minimum_index = max(p["lookback"] - 1, p["atr_period"], p["flow_lookback"])
        for index in range(minimum_index, len(candles) - 1):
            candle = candles[index]
            window = closes[index - p["lookback"] + 1 : index + 1]
            slope, intercept, sigma, r_squared = _linear_regression(window)
            center = intercept + slope * (p["lookback"] - 1)
            upper = center + p["channel_width"] * sigma
            lower = center - p["channel_width"] * sigma
            atr = _atr(candles, index, p["atr_period"])
            if atr is None or atr <= 0:
                continue
            side: str | None = None
            extension = 0.0
            flow = None
            displacement = None
            if candle.close < lower:
                extension = (lower - candle.close) / atr
                side = "long" if extension >= p["minimum_atr_extension"] else None
                flow = candle.aggressive_sell_notional
                displacement = max(candle.open - candle.close, candle.high - candle.low, atr * 1e-6)
            elif candle.close > upper:
                extension = (candle.close - upper) / atr
                side = "short" if extension >= p["minimum_atr_extension"] else None
                flow = candle.aggressive_buy_notional
                displacement = max(candle.close - candle.open, candle.high - candle.low, atr * 1e-6)
            if side is None or flow is None or displacement is None:
                continue
            history: list[float] = []
            absorption_history: list[float] = []
            for prior in candles[index - p["flow_lookback"] : index]:
                prior_flow = prior.aggressive_sell_notional if side == "long" else prior.aggressive_buy_notional
                if prior_flow is None:
                    continue
                prior_disp = max(abs(prior.close - prior.open), prior.high - prior.low, atr * 1e-6)
                history.append(prior_flow)
                absorption_history.append(prior_flow / prior_disp)
            flow_rank = _percentile_rank(history, flow)
            absorption = flow / displacement
            absorption_rank = _percentile_rank(absorption_history, absorption)
            if flow_rank is None or absorption_rank is None:
                continue
            if flow_rank < p["flow_percentile"] or absorption_rank < p["absorption_percentile"]:
                continue
            entry_index = index + 1
            confirmation_passed = True
            if p["confirmation"] == "channel_reclaim":
                confirmation = candles[index + 1]
                confirmation_passed = confirmation.close >= lower if side == "long" else confirmation.close <= upper
                entry_index = index + 2
            elif p["confirmation"] == "liquidity_replenishment":
                replenishment = candle.bid_replenishment if side == "long" else candle.ask_replenishment
                confirmation_passed = replenishment is not None and replenishment >= p["replenishment_threshold"]
            if not confirmation_passed or entry_index >= len(candles):
                continue
            stop, target = _conservative_levels(candle, side, atr, p["stop_atr"], p["target_rr"])
            signals.append(Signal(
                timestamp=candle.timestamp,
                availability_timestamp=candle.availability_timestamp or candle.timestamp,
                side=side,
                entry_index=entry_index,
                signal_price=candle.close,
                stop_price=stop,
                target_price=target,
                max_holding_bars=min(p["max_holding_bars"], max(1, horizon_minutes)),
                feature_snapshot={
                    "regression_center": center,
                    "upper_band": upper,
                    "lower_band": lower,
                    "regression_slope": slope,
                    "regression_r_squared": r_squared,
                    "residual_sigma": sigma,
                    "atr": atr,
                    "atr_extension": extension,
                    "aggressive_flow_notional": flow,
                    "aggressive_flow_percentile": flow_rank,
                    "price_displacement": displacement,
                    "absorption_ratio": absorption,
                    "absorption_percentile": absorption_rank,
                    "confirmation": p["confirmation"],
                    "bid_replenishment": candle.bid_replenishment,
                    "ask_replenishment": candle.ask_replenishment,
                },
                reason=f"{side} extension with flow p{flow_rank:.1f} and absorption p{absorption_rank:.1f}",
            ))
        return signals


class VwapReversionStrategy(ResearchStrategy):
    definition = StrategyDefinition(
        strategy_id="vwap_reversion",
        strategy_version="1.0.0",
        family=StrategyFamily.MEAN_REVERSION,
        name="VWAP Reversion",
        description="Fade a completed close a configured ATR distance from a rolling volume-weighted average price.",
        required_data_feeds=("completed_candles",),
        required_features=("rolling_vwap", "atr"),
        supported_assets=("BTCUSDT", "ETHUSDT"),
        supported_market_types=(MarketType.SPOT, MarketType.PERPETUAL),
        supported_source_timeframes=(1, 15, 60),
        supported_prediction_horizons=(15, 60),
        parameter_schema={
            "vwap_lookback": {"type": "integer", "default": 96, "minimum": 10, "maximum": 1440},
            "atr_period": {"type": "integer", "default": 14, "minimum": 5, "maximum": 100},
            "minimum_atr_deviation": {"type": "number", "default": 1.0, "minimum": 0.1, "maximum": 10.0},
            "stop_atr": {"type": "number", "default": 0.75, "minimum": 0.05, "maximum": 5.0},
            "target_mode": {"type": "string", "default": "vwap", "enum": ["vwap", "fixed_rr"]},
            "target_rr": {"type": "number", "default": 1.5, "minimum": 0.25, "maximum": 10.0},
            "max_holding_bars": {"type": "integer", "default": 15, "minimum": 1, "maximum": 240},
        },
        entry_rules=("Enter opposite the deviation after the completed signal candle; no intrabar future values are used.",),
        invalidation_rules=("Reject when rolling VWAP or ATR is unavailable.",),
        stop_rules=("Stop beyond the signal extreme by configured ATR distance.",),
        target_rules=("Target frozen signal-time VWAP or fixed reward-to-risk.",),
        position_sizing_rules=("Sizing is delegated to the experiment execution model.",),
        maximum_holding_period_minutes=240,
        cost_assumptions=("Uses experiment execution-cost model.",),
        regime_restrictions=(),
        data_quality_requirements=("Chronological completed candles",),
    )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return self._coerce(parameters, self.definition.parameter_schema)

    def generate_signals(self, candles: list[Candle], parameters: dict[str, Any], horizon_minutes: int) -> list[Signal]:
        p = self.validate_parameters(parameters)
        signals: list[Signal] = []
        start = max(p["vwap_lookback"] - 1, p["atr_period"])
        for index in range(start, len(candles) - 1):
            candle = candles[index]
            atr = _atr(candles, index, p["atr_period"])
            vwap = _rolling_vwap(candles, index, p["vwap_lookback"])
            if atr is None or vwap is None or atr <= 0:
                continue
            deviation = (candle.close - vwap) / atr
            side = "short" if deviation >= p["minimum_atr_deviation"] else "long" if deviation <= -p["minimum_atr_deviation"] else None
            if side is None:
                continue
            stop, rr_target = _conservative_levels(candle, side, atr, p["stop_atr"], p["target_rr"])
            target = vwap if p["target_mode"] == "vwap" else rr_target
            if side == "long" and target <= candle.close:
                continue
            if side == "short" and target >= candle.close:
                continue
            signals.append(Signal(
                timestamp=candle.timestamp,
                availability_timestamp=candle.availability_timestamp or candle.timestamp,
                side=side,
                entry_index=index + 1,
                signal_price=candle.close,
                stop_price=stop,
                target_price=target,
                max_holding_bars=min(p["max_holding_bars"], max(1, horizon_minutes)),
                feature_snapshot={"rolling_vwap": vwap, "atr": atr, "atr_deviation": deviation},
                reason=f"{side} VWAP deviation {deviation:.3f} ATR",
            ))
        return signals


class SimpleMomentumStrategy(ResearchStrategy):
    definition = StrategyDefinition(
        strategy_id="simple_momentum",
        strategy_version="1.0.0",
        family=StrategyFamily.MOMENTUM,
        name="Simple Momentum",
        description="Trade in the direction of a completed lookback return when it exceeds a configured threshold and EMA slope agrees.",
        required_data_feeds=("completed_candles",),
        required_features=("lookback_return", "ema_slope", "atr"),
        supported_assets=("BTCUSDT", "ETHUSDT"),
        supported_market_types=(MarketType.SPOT, MarketType.PERPETUAL),
        supported_source_timeframes=(1, 15, 60),
        supported_prediction_horizons=(15, 60),
        parameter_schema={
            "lookback": {"type": "integer", "default": 12, "minimum": 2, "maximum": 240},
            "minimum_return": {"type": "number", "default": 0.003, "minimum": 0.0, "maximum": 0.50},
            "ema_period": {"type": "integer", "default": 20, "minimum": 2, "maximum": 240},
            "atr_period": {"type": "integer", "default": 14, "minimum": 5, "maximum": 100},
            "stop_atr": {"type": "number", "default": 1.0, "minimum": 0.05, "maximum": 10.0},
            "target_rr": {"type": "number", "default": 1.5, "minimum": 0.25, "maximum": 10.0},
            "max_holding_bars": {"type": "integer", "default": 15, "minimum": 1, "maximum": 240},
        },
        entry_rules=("Long when completed lookback return exceeds threshold and EMA slope is positive; short symmetrically.",),
        invalidation_rules=("Reject when the lookback or ATR is incomplete.",),
        stop_rules=("ATR stop frozen at signal time.",),
        target_rules=("Fixed reward-to-risk target frozen at signal time.",),
        position_sizing_rules=("Sizing is delegated to the experiment execution model.",),
        maximum_holding_period_minutes=240,
        cost_assumptions=("Uses experiment execution-cost model.",),
        regime_restrictions=(),
        data_quality_requirements=("Chronological completed candles",),
    )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return self._coerce(parameters, self.definition.parameter_schema)

    def generate_signals(self, candles: list[Candle], parameters: dict[str, Any], horizon_minutes: int) -> list[Signal]:
        p = self.validate_parameters(parameters)
        closes = [c.close for c in candles]
        ema = _ema_series(closes, p["ema_period"])
        signals: list[Signal] = []
        start = max(p["lookback"], p["atr_period"], p["ema_period"])
        for index in range(start, len(candles) - 1):
            candle = candles[index]
            momentum = candle.close / candles[index - p["lookback"]].close - 1.0
            ema_slope = ema[index] / ema[index - 1] - 1.0
            side = "long" if momentum >= p["minimum_return"] and ema_slope > 0 else "short" if momentum <= -p["minimum_return"] and ema_slope < 0 else None
            if side is None:
                continue
            atr = _atr(candles, index, p["atr_period"])
            if atr is None or atr <= 0:
                continue
            stop, target = _conservative_levels(candle, side, atr, p["stop_atr"], p["target_rr"])
            signals.append(Signal(
                timestamp=candle.timestamp,
                availability_timestamp=candle.availability_timestamp or candle.timestamp,
                side=side,
                entry_index=index + 1,
                signal_price=candle.close,
                stop_price=stop,
                target_price=target,
                max_holding_bars=min(p["max_holding_bars"], max(1, horizon_minutes)),
                feature_snapshot={"lookback_return": momentum, "ema": ema[index], "ema_slope": ema_slope, "atr": atr},
                reason=f"{side} momentum {momentum:.5f} with EMA slope {ema_slope:.6f}",
            ))
        return signals


class BreakoutRetestStrategy(ResearchStrategy):
    definition = StrategyDefinition(
        strategy_id="breakout_retest",
        strategy_version="1.0.0",
        family=StrategyFamily.BREAKOUT,
        name="Breakout and Retest",
        description="Enter after a prior completed close breaks a rolling range and the current completed candle retests and closes beyond the frozen breakout level.",
        required_data_feeds=("completed_candles",),
        required_features=("rolling_range", "atr"),
        supported_assets=("BTCUSDT", "ETHUSDT"),
        supported_market_types=(MarketType.SPOT, MarketType.PERPETUAL),
        supported_source_timeframes=(1, 15, 60),
        supported_prediction_horizons=(15, 60),
        parameter_schema={
            "lookback": {"type": "integer", "default": 20, "minimum": 5, "maximum": 240},
            "breakout_buffer": {"type": "number", "default": 0.0005, "minimum": 0.0, "maximum": 0.10},
            "retest_tolerance": {"type": "number", "default": 0.0015, "minimum": 0.0, "maximum": 0.10},
            "atr_period": {"type": "integer", "default": 14, "minimum": 5, "maximum": 100},
            "stop_atr": {"type": "number", "default": 0.50, "minimum": 0.05, "maximum": 10.0},
            "target_rr": {"type": "number", "default": 2.0, "minimum": 0.25, "maximum": 10.0},
            "max_holding_bars": {"type": "integer", "default": 15, "minimum": 1, "maximum": 240},
        },
        entry_rules=("Use the range ending two candles before the retest; require a prior breakout close and a current retest close beyond the frozen level.",),
        invalidation_rules=("Reject retests that close back inside the prior range.",),
        stop_rules=("Stop beyond the retest candle extreme by configured ATR distance.",),
        target_rules=("Fixed reward-to-risk target frozen at signal time.",),
        position_sizing_rules=("Sizing is delegated to the experiment execution model.",),
        maximum_holding_period_minutes=240,
        cost_assumptions=("Uses experiment execution-cost model.",),
        regime_restrictions=(),
        data_quality_requirements=("Chronological completed candles",),
    )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return self._coerce(parameters, self.definition.parameter_schema)

    def generate_signals(self, candles: list[Candle], parameters: dict[str, Any], horizon_minutes: int) -> list[Signal]:
        p = self.validate_parameters(parameters)
        signals: list[Signal] = []
        start = max(p["lookback"] + 1, p["atr_period"])
        for index in range(start, len(candles) - 1):
            prior = candles[index - 1]
            retest = candles[index]
            range_slice = candles[index - p["lookback"] - 1 : index - 1]
            resistance = max(c.high for c in range_slice)
            support = min(c.low for c in range_slice)
            long_breakout = prior.close >= resistance * (1.0 + p["breakout_buffer"])
            short_breakout = prior.close <= support * (1.0 - p["breakout_buffer"])
            long_retest = retest.low <= resistance * (1.0 + p["retest_tolerance"]) and retest.close > resistance
            short_retest = retest.high >= support * (1.0 - p["retest_tolerance"]) and retest.close < support
            side = "long" if long_breakout and long_retest else "short" if short_breakout and short_retest else None
            if side is None:
                continue
            atr = _atr(candles, index, p["atr_period"])
            if atr is None or atr <= 0:
                continue
            stop, target = _conservative_levels(retest, side, atr, p["stop_atr"], p["target_rr"])
            signals.append(Signal(
                timestamp=retest.timestamp,
                availability_timestamp=retest.availability_timestamp or retest.timestamp,
                side=side,
                entry_index=index + 1,
                signal_price=retest.close,
                stop_price=stop,
                target_price=target,
                max_holding_bars=min(p["max_holding_bars"], max(1, horizon_minutes)),
                feature_snapshot={"resistance": resistance, "support": support, "atr": atr, "retest_tolerance": p["retest_tolerance"]},
                reason=f"{side} breakout and retest",
            ))
        return signals


DEFAULT_STRATEGIES: tuple[ResearchStrategy, ...] = (
    RegressionChannelStrategy(),
    RegressionExtremeAbsorptionStrategy(),
    VwapReversionStrategy(),
    SimpleMomentumStrategy(),
    BreakoutRetestStrategy(),
)
