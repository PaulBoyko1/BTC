from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MarketType(StrEnum):
    SPOT = "spot"
    PERPETUAL = "perpetual"


class StrategyFamily(StrEnum):
    MEAN_REVERSION = "mean_reversion"
    MOMENTUM = "momentum"
    BREAKOUT = "breakout"
    ORDER_FLOW = "order_flow"
    COMPOSITE = "composite"


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED_DATA_INTEGRITY = "failed_data_integrity"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StrategyStatus(StrEnum):
    DRAFT = "Draft"
    EXPERIMENTAL = "Experimental"
    INSUFFICIENT_DATA = "Insufficient Data"
    DATA_INTEGRITY_FAILED = "Data Integrity Failed"
    IN_SAMPLE_ONLY = "In-Sample Only"
    VALIDATION_FAILED = "Validation Failed"
    OVERFIT = "Overfit"
    COST_INFEASIBLE = "Cost-Infeasible"
    OUT_OF_SAMPLE_CANDIDATE = "Out-of-Sample Candidate"
    ROBUSTNESS_CANDIDATE = "Robustness Candidate"
    PAPER_TRADING_CANDIDATE = "Paper-Trading Candidate"
    FORWARD_VALIDATED = "Forward Validated"
    DEPLOYMENT_ELIGIBLE = "Deployment Eligible"
    PERFORMANCE_DECAY_WARNING = "Performance Decay Warning"
    SUSPENDED = "Suspended"
    RETIRED = "Retired"


class CostPreset(StrEnum):
    OPTIMISTIC = "optimistic"
    REALISTIC = "realistic"
    CONSERVATIVE = "conservative"


class ParameterSearchMethod(StrEnum):
    MANUAL = "manual"
    GRID = "grid"
    RANDOM = "random"


class Candle(BaseModel):
    """A completed market candle with explicit event and availability times.

    Timestamps are Unix seconds in UTC. Optional microstructure fields remain
    nullable so candle-only strategies can be tested without fabricating them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: int = Field(description="Candle open timestamp, UTC epoch seconds")
    availability_timestamp: int | None = Field(
        default=None,
        description="Earliest timestamp at which the completed candle was available",
    )
    exchange_timestamp: int | None = None
    receipt_timestamp: int | None = None
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    quote_volume: float = 0.0
    vwap: float | None = None
    complete: bool = True
    aggressive_buy_notional: float | None = None
    aggressive_sell_notional: float | None = None
    bid_replenishment: float | None = None
    ask_replenishment: float | None = None
    cvd: float | None = None
    open_interest: float | None = None
    funding_rate: float | None = None
    liquidation_long_notional: float | None = None
    liquidation_short_notional: float | None = None

    @model_validator(mode="after")
    def validate_ohlc(self) -> "Candle":
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be >= open, close and low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be <= open, close and high")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("prices must be positive")
        if self.volume < 0 or self.quote_volume < 0:
            raise ValueError("volumes cannot be negative")
        return self


class DatasetImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    asset: Literal["BTCUSDT", "ETHUSDT"]
    exchange: Literal["binance"] = "binance"
    market_type: MarketType
    source_timeframe_minutes: int = Field(default=1, ge=1, le=60)
    candles: list[Candle] = Field(min_length=1)
    feature_version: str = "research-v1"
    adapter_version: str = "manual-import-v1"


class CostModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    preset: CostPreset = CostPreset.REALISTIC
    maker_fee_bps: float = Field(default=2.0, ge=0, le=100)
    taker_fee_bps: float = Field(default=5.0, ge=0, le=100)
    spread_bps: float = Field(default=2.0, ge=0, le=500)
    slippage_bps: float = Field(default=2.0, ge=0, le=500)
    latency_ms: int = Field(default=250, ge=0, le=60_000)
    partial_fill_probability: float = Field(default=0.0, ge=0, le=1)
    funding_bps_per_8h: float = Field(default=0.0, ge=-100, le=100)
    entry_order_type: Literal["market", "limit"] = "market"
    exit_order_type: Literal["market", "limit"] = "market"


class WalkForwardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["rolling", "expanding"] = "rolling"
    train_days: int = Field(default=90, ge=1, le=3650)
    validation_days: int = Field(default=30, ge=1, le=3650)
    test_days: int = Field(default=30, ge=1, le=3650)
    step_days: int = Field(default=30, ge=1, le=3650)
    embargo_minutes: int | None = Field(default=None, ge=0, le=7 * 24 * 60)


class ValidationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = "research-default"
    minimum_trades: int = Field(default=30, ge=1)
    minimum_profit_factor: float = Field(default=1.05, ge=0)
    minimum_positive_fold_ratio: float = Field(default=0.50, ge=0, le=1)
    maximum_drawdown_fraction: float = Field(default=0.35, gt=0, le=1)
    maximum_cost_to_gross_profit: float = Field(default=0.80, ge=0)
    maximum_sharpe_degradation: float = Field(default=0.80, ge=-10, le=10)
    maximum_bootstrap_loss_probability: float = Field(default=0.50, ge=0, le=1)


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str
    strategy_version: str = "1.0.0"
    dataset_id: str
    asset: Literal["BTCUSDT", "ETHUSDT"]
    exchange: Literal["binance"] = "binance"
    market_type: MarketType
    source_timeframe_minutes: int = Field(default=1, ge=1, le=60)
    prediction_horizon_minutes: Literal[15, 60]
    start_timestamp: int
    end_timestamp: int
    parameters: dict[str, Any] = Field(default_factory=dict)
    parameter_sets: list[dict[str, Any]] = Field(default_factory=list)
    search_method: ParameterSearchMethod = ParameterSearchMethod.MANUAL
    walk_forward: WalkForwardConfig = Field(default_factory=WalkForwardConfig)
    cost_model: CostModelConfig = Field(default_factory=CostModelConfig)
    validation_policy: ValidationPolicy = Field(default_factory=ValidationPolicy)
    initial_capital: float = Field(default=100_000.0, gt=0)
    maximum_leverage: float = Field(default=1.0, gt=0, le=20)
    position_sizing: Literal["fixed_notional", "fixed_fractional_risk"] = "fixed_fractional_risk"
    risk_fraction: float = Field(default=0.005, gt=0, le=0.10)
    random_seed: int = 42
    code_commit_hash: str = "unknown"
    feature_version: str = "research-v1"
    dataset_version: str = "1"

    @model_validator(mode="after")
    def validate_range(self) -> "ExperimentCreate":
        if self.end_timestamp <= self.start_timestamp:
            raise ValueError("end_timestamp must be after start_timestamp")
        return self


class StrategyDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str
    strategy_version: str
    family: StrategyFamily
    name: str
    description: str
    required_data_feeds: tuple[str, ...]
    required_features: tuple[str, ...]
    supported_assets: tuple[str, ...]
    supported_market_types: tuple[MarketType, ...]
    supported_source_timeframes: tuple[int, ...]
    supported_prediction_horizons: tuple[int, ...]
    parameter_schema: dict[str, Any]
    entry_rules: tuple[str, ...]
    invalidation_rules: tuple[str, ...]
    stop_rules: tuple[str, ...]
    target_rules: tuple[str, ...]
    position_sizing_rules: tuple[str, ...]
    maximum_holding_period_minutes: int
    cost_assumptions: tuple[str, ...]
    regime_restrictions: tuple[str, ...]
    data_quality_requirements: tuple[str, ...]
    enabled: bool = True


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: int
    availability_timestamp: int
    side: Literal["long", "short"]
    entry_index: int
    signal_price: float
    stop_price: float
    target_price: float
    max_holding_bars: int
    feature_snapshot: dict[str, float | int | str | bool | None]
    reason: str


class Trade(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_timestamp: int
    entry_timestamp: int
    exit_timestamp: int
    side: Literal["long", "short"]
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    quantity: float
    gross_pnl: float
    fee_cost: float
    spread_cost: float
    slippage_cost: float
    funding_cost: float
    net_pnl: float
    gross_return: float
    net_return: float
    mfe: float
    mae: float
    bars_held: int
    exit_reason: Literal["target", "stop", "time"]
    target_before_stop: bool
    feature_snapshot: dict[str, Any]


class FoldDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fold_index: int
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int
    test_start: int
    test_end: int
    purged_observations: int = 0
    embargoed_observations: int = 0


class JobView(BaseModel):
    id: str
    experiment_id: str
    status: str
    progress: float = 0.0
    message: str = ""
    created_at: str
    updated_at: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"
