from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.research.types import Candle, MarketType

SUPPORTED_ASSETS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT",
)


class Horizon(StrEnum):
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR = "1h"

    @property
    def minutes(self) -> int:
        return 15 if self is Horizon.FIFTEEN_MINUTES else 60


class ProbabilityState(StrEnum):
    CALIBRATED = "calibrated"
    HEURISTIC = "heuristic"
    INSUFFICIENT_DATA = "insufficient_data"
    STALE = "stale"


class BiasStatus(StrEnum):
    STRONG_UP = "Strong Up Bias"
    UP = "Up Bias"
    SLIGHT_UP = "Slight Up Bias"
    NEUTRAL = "Neutral"
    SLIGHT_DOWN = "Slight Down Bias"
    DOWN = "Down Bias"
    STRONG_DOWN = "Strong Down Bias"
    NO_TRADE = "No Trade"
    INSUFFICIENT_DATA = "Insufficient Data"
    DATA_STALE = "Data Stale"


class DataStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    connected: bool
    stale: bool
    last_trade_timestamp: int | None = None
    last_candle_timestamp: int | None = None
    latency_ms: int | None = None
    missing_candles: int = 0
    duplicate_events: int = 0
    sequence_gaps: int = 0
    crossed_book: bool = False
    score: float = Field(ge=0, le=100)
    reasons: tuple[str, ...] = ()


class IntervalWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    horizon: Horizon
    start_timestamp: int
    expiry_timestamp: int
    reference_price: float
    reference_source: str

    @model_validator(mode="after")
    def validate_window(self) -> "IntervalWindow":
        if self.expiry_timestamp <= self.start_timestamp:
            raise ValueError("expiry must be after start")
        if self.reference_price <= 0:
            raise ValueError("reference price must be positive")
        if self.expiry_timestamp - self.start_timestamp != self.horizon.minutes * 60:
            raise ValueError("interval duration does not match horizon")
        return self


class Factor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    value: float | str | None = None
    direction: Literal["supporting", "opposing", "neutral"] = "neutral"
    explanation: str


class IntervalAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prediction_id: str
    asset: str
    exchange: str
    market_type: MarketType
    horizon: Horizon
    generated_timestamp: int
    interval_start_timestamp: int
    expiry_timestamp: int
    reference_price: float
    current_price: float
    difference: float
    difference_percent: float
    seconds_remaining: int
    probability_state: ProbabilityState
    up_probability: float | None = Field(default=None, ge=0, le=1)
    down_probability: float | None = Field(default=None, ge=0, le=1)
    raw_direction_score: float = Field(ge=-1, le=1)
    expected_close: float | None = None
    expected_signed_return: float | None = None
    expected_absolute_return: float | None = None
    expected_low: float | None = None
    expected_high: float | None = None
    upper_touch_probability: float | None = Field(default=None, ge=0, le=1)
    lower_touch_probability: float | None = Field(default=None, ge=0, le=1)
    reference_retouch_probability: float | None = Field(default=None, ge=0, le=1)
    vwap_touch_probability: float | None = Field(default=None, ge=0, le=1)
    regression_center_touch_probability: float | None = Field(default=None, ge=0, le=1)
    reversion_score: float = Field(ge=0, le=1)
    continuation_score: float = Field(ge=0, le=1)
    uncertainty_score: float = Field(ge=0, le=1)
    reversion_label: str
    continuation_label: str
    status: BiasStatus
    current_regime: str
    data_status: DataStatus
    model_version: str
    feature_version: str
    calibrated_model_id: str | None = None
    supporting_factors: tuple[Factor, ...] = ()
    opposing_factors: tuple[Factor, ...] = ()
    no_trade_reasons: tuple[str, ...] = ()
    feature_snapshot: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_probabilities(self) -> "IntervalAnalysis":
        if self.probability_state == ProbabilityState.CALIBRATED:
            if self.up_probability is None or self.down_probability is None:
                raise ValueError("calibrated output requires probabilities")
            if abs((self.up_probability + self.down_probability) - 1.0) > 1e-6:
                raise ValueError("calibrated direction probabilities must sum to one")
            if not self.calibrated_model_id:
                raise ValueError("calibrated output requires model id")
        elif self.calibrated_model_id is not None:
            raise ValueError("uncalibrated output cannot reference calibrated model")
        return self


class PredictionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prediction_id: str
    resolved_timestamp: int
    expiry_price: float
    finished_above_reference: bool
    signed_return: float
    correct: bool | None = None


class OrderBlockDefinition(StrEnum):
    DISPLACEMENT = "displacement"
    IMBALANCE_CONFIRMED = "imbalance_confirmed"


class OrderBlockConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    definition: OrderBlockDefinition = OrderBlockDefinition.DISPLACEMENT
    lookback_structure: int = Field(default=20, ge=3, le=500)
    displacement_atr: float = Field(default=1.5, ge=0.1, le=10)
    imbalance_fraction: float = Field(default=0.10, ge=0, le=1)
    zone_mode: Literal["body", "full"] = "full"
    entry_depths: tuple[float, ...] = (1.0, 0.75, 0.5, 0.25, 0.0)
    stop_buffer_atr: float = Field(default=0.2, ge=0, le=5)
    target_rr: float = Field(default=2.0, ge=0.25, le=20)
    confirmation: Literal["touch", "confirmation_close", "reclaim", "break"] = "touch"
    max_holding_bars: int = Field(default=15, ge=1, le=1000)


class OrderBlockZone(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    zone_id: str
    side: Literal["bullish", "bearish"]
    formed_timestamp: int
    source_candle_index: int
    lower: float
    upper: float
    displacement_atr: float
    structure_break_price: float
    definition: OrderBlockDefinition
    feature_snapshot: dict[str, Any]

    def price_at_depth(self, depth: float) -> float:
        if not 0 <= depth <= 1:
            raise ValueError("depth must be in [0,1]")
        return self.lower + (self.upper - self.lower) * depth


class NullModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: int = 42
    simulations: int = Field(default=1000, ge=100, le=100_000)
    model: Literal["random_timing", "random_depth", "matched_market", "random_days"]


class ResearchTrade(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    setup_id: str
    entry_timestamp: int
    exit_timestamp: int
    side: Literal["long", "short"]
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    r_multiple: float
    pnl: float
    day_key: str
    regime: str = "unknown"


class NullModelResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    seed: int
    simulations: int
    observed_mean_r: float | None
    null_mean_r: float | None
    difference: float | None
    percentile: float | None
    empirical_p_value: float | None
    confidence_interval: tuple[float, float] | None
    status: str


class BootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: str
    seed: int
    simulations: int
    statistic: str
    observed: float | None
    lower: float | None
    upper: float | None
    includes_zero: bool | None
    interpretation: str


class LiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str = "BTCUSDT"
    market_type: MarketType = MarketType.SPOT
    horizon: Horizon = Horizon.FIFTEEN_MINUTES
    timezone: str = "America/Los_Angeles"

    @model_validator(mode="after")
    def validate_asset(self) -> "LiveRequest":
        if self.asset not in SUPPORTED_ASSETS:
            raise ValueError(f"unsupported asset {self.asset}")
        return self


class CandleBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset: str
    exchange: str
    market_type: MarketType
    timeframe_minutes: int
    candles: tuple[Candle, ...]
    fetched_timestamp: int
    data_status: DataStatus
