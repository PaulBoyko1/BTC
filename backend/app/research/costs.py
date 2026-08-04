from __future__ import annotations

from dataclasses import dataclass

from .types import CostModelConfig, CostPreset, MarketType


@dataclass(frozen=True)
class ExecutionCost:
    fee_cost: float
    spread_cost: float
    slippage_cost: float
    funding_cost: float

    @property
    def total(self) -> float:
        return self.fee_cost + self.spread_cost + self.slippage_cost + self.funding_cost


def preset_cost_model(preset: CostPreset) -> CostModelConfig:
    if preset == CostPreset.OPTIMISTIC:
        return CostModelConfig(
            preset=preset,
            maker_fee_bps=1.0,
            taker_fee_bps=3.0,
            spread_bps=1.0,
            slippage_bps=0.5,
            latency_ms=50,
            partial_fill_probability=0.02,
            entry_order_type="limit",
            exit_order_type="market",
        )
    if preset == CostPreset.CONSERVATIVE:
        return CostModelConfig(
            preset=preset,
            maker_fee_bps=3.0,
            taker_fee_bps=7.0,
            spread_bps=5.0,
            slippage_bps=8.0,
            latency_ms=750,
            partial_fill_probability=0.20,
            entry_order_type="market",
            exit_order_type="market",
        )
    return CostModelConfig()


def calculate_execution_cost(
    config: CostModelConfig,
    entry_notional: float,
    exit_notional: float,
    holding_seconds: int,
    market_type: MarketType,
) -> ExecutionCost:
    entry_fee_bps = config.maker_fee_bps if config.entry_order_type == "limit" else config.taker_fee_bps
    exit_fee_bps = config.maker_fee_bps if config.exit_order_type == "limit" else config.taker_fee_bps
    fee_cost = entry_notional * entry_fee_bps / 10_000.0 + exit_notional * exit_fee_bps / 10_000.0

    # Crossing the book is charged at half-spread on entry and half-spread on exit.
    spread_cost = (entry_notional + exit_notional) * config.spread_bps / 20_000.0
    slippage_cost = (entry_notional + exit_notional) * config.slippage_bps / 10_000.0

    funding_cost = 0.0
    if market_type == MarketType.PERPETUAL and holding_seconds > 0:
        eight_hours = 8 * 60 * 60
        funding_cost = entry_notional * config.funding_bps_per_8h / 10_000.0 * (holding_seconds / eight_hours)

    return ExecutionCost(
        fee_cost=fee_cost,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        funding_cost=funding_cost,
    )
