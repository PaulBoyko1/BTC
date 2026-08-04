from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from statistics import mean
from typing import Iterable
from uuid import uuid4

from app.research.types import Candle

from .features import atr
from .types import OrderBlockConfig, OrderBlockDefinition, OrderBlockZone, ResearchTrade


def _zone_bounds(candle: Candle, mode: str) -> tuple[float, float]:
    if mode == "body":
        return min(candle.open, candle.close), max(candle.open, candle.close)
    return candle.low, candle.high


def detect_order_blocks(candles: list[Candle], config: OrderBlockConfig) -> list[OrderBlockZone]:
    """Detect mathematically defined displacement or imbalance order blocks.

    A bullish block is the final bearish candle before an upward displacement
    that closes above the previous `lookback_structure` high. A bearish block
    is symmetric. Imbalance-confirmed blocks additionally require a gap between
    the source candle and the second candle after it of at least the configured
    fraction of ATR.
    """
    zones: list[OrderBlockZone] = []
    for index in range(max(config.lookback_structure, 14), len(candles) - 2):
        source = candles[index]
        next_one = candles[index + 1]
        next_two = candles[index + 2]
        local_atr = atr(candles[: index + 3], 14)
        if not local_atr or local_atr <= 0:
            continue
        previous = candles[index - config.lookback_structure : index]
        prior_high = max(c.high for c in previous)
        prior_low = min(c.low for c in previous)
        up_displacement = next_two.close - source.close
        down_displacement = source.close - next_two.close
        side: str | None = None
        structure_break = 0.0
        displacement = 0.0
        if source.close < source.open and next_two.close > prior_high and up_displacement / local_atr >= config.displacement_atr:
            side = "bullish"
            structure_break = prior_high
            displacement = up_displacement / local_atr
            if config.definition == OrderBlockDefinition.IMBALANCE_CONFIRMED:
                gap = next_two.low - source.high
                if gap / local_atr < config.imbalance_fraction:
                    continue
        elif source.close > source.open and next_two.close < prior_low and down_displacement / local_atr >= config.displacement_atr:
            side = "bearish"
            structure_break = prior_low
            displacement = down_displacement / local_atr
            if config.definition == OrderBlockDefinition.IMBALANCE_CONFIRMED:
                gap = source.low - next_two.high
                if gap / local_atr < config.imbalance_fraction:
                    continue
        if side is None:
            continue
        lower, upper = _zone_bounds(source, config.zone_mode)
        zones.append(OrderBlockZone(
            zone_id=str(uuid4()),
            side=side,
            formed_timestamp=next_two.availability_timestamp or next_two.timestamp + 60,
            source_candle_index=index,
            lower=lower,
            upper=upper,
            displacement_atr=displacement,
            structure_break_price=structure_break,
            definition=config.definition,
            feature_snapshot={
                "source_timestamp": source.timestamp,
                "source_availability_timestamp": source.availability_timestamp or source.timestamp + 60,
                "atr": local_atr,
                "prior_high": prior_high,
                "prior_low": prior_low,
                "displacement_close_timestamp": next_two.timestamp,
                "zone_mode": config.zone_mode,
            },
        ))
    return zones


def backtest_order_blocks(
    candles: list[Candle],
    zones: Iterable[OrderBlockZone],
    config: OrderBlockConfig,
    *,
    entry_depth: float,
    notional: float = 1000.0,
) -> list[ResearchTrade]:
    if not 0 <= entry_depth <= 1:
        raise ValueError("entry_depth must be in [0,1]")
    trades: list[ResearchTrade] = []
    last_exit = -1
    for zone in zones:
        start = zone.source_candle_index + 3
        if start <= last_exit:
            continue
        entry_price = zone.price_at_depth(entry_depth)
        entry_index: int | None = None
        for index in range(start, min(len(candles), start + config.max_holding_bars * 4)):
            candle = candles[index]
            touched = candle.low <= entry_price <= candle.high
            if not touched:
                continue
            if config.confirmation == "confirmation_close":
                confirmed = candle.close > entry_price if zone.side == "bullish" else candle.close < entry_price
                if not confirmed:
                    continue
            entry_index = index
            break
        if entry_index is None:
            continue
        local_atr = float(zone.feature_snapshot["atr"])
        if zone.side == "bullish":
            side = "long"
            stop = zone.lower - config.stop_buffer_atr * local_atr
            risk = entry_price - stop
            target = entry_price + config.target_rr * risk
        else:
            side = "short"
            stop = zone.upper + config.stop_buffer_atr * local_atr
            risk = stop - entry_price
            target = entry_price - config.target_rr * risk
        if risk <= 0:
            continue
        exit_index = min(len(candles) - 1, entry_index + config.max_holding_bars - 1)
        exit_price = candles[exit_index].close
        for index in range(entry_index, exit_index + 1):
            candle = candles[index]
            hit_stop = candle.low <= stop if side == "long" else candle.high >= stop
            hit_target = candle.high >= target if side == "long" else candle.low <= target
            if hit_stop and hit_target:
                exit_index, exit_price = index, stop
                break
            if hit_stop:
                exit_index, exit_price = index, stop
                break
            if hit_target:
                exit_index, exit_price = index, target
                break
        direction = 1.0 if side == "long" else -1.0
        r_multiple = direction * (exit_price - entry_price) / risk
        pnl = notional * direction * (exit_price / entry_price - 1.0)
        entry_dt = datetime.fromtimestamp(candles[entry_index].timestamp, tz=timezone.utc)
        trades.append(ResearchTrade(
            setup_id=zone.zone_id,
            entry_timestamp=candles[entry_index].timestamp,
            exit_timestamp=candles[exit_index].timestamp,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            stop_price=stop,
            target_price=target,
            r_multiple=r_multiple,
            pnl=pnl,
            day_key=entry_dt.strftime("%Y-%m-%d"),
            regime="unknown",
        ))
        last_exit = exit_index
    return trades


def order_block_metrics(trades: list[ResearchTrade]) -> dict[str, float | int | None]:
    if not trades:
        return {"trades": 0, "mean_r": None, "median_r": None, "net_pnl": 0.0, "win_rate": None, "profit_factor": None}
    rs = sorted(trade.r_multiple for trade in trades)
    gross_win = sum(max(0.0, trade.pnl) for trade in trades)
    gross_loss = abs(sum(min(0.0, trade.pnl) for trade in trades))
    return {
        "trades": len(trades),
        "mean_r": mean(rs),
        "median_r": rs[len(rs) // 2],
        "net_pnl": sum(trade.pnl for trade in trades),
        "win_rate": sum(value > 0 for value in rs) / len(rs),
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else None,
    }


def chronological_order_block_validation(
    candles: list[Candle],
    config: OrderBlockConfig,
    *,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
) -> dict[str, object]:
    """Select entry depth chronologically, then evaluate once on final data.

    All candidate depths are recorded. The final test partition is never used
    to select the depth. Detection is rerun independently inside each
    partition so future zones cannot leak backward.
    """
    if not 0.3 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be in [0.3,0.8]")
    if not 0.1 <= validation_fraction <= 0.4:
        raise ValueError("validation_fraction must be in [0.1,0.4]")
    if train_fraction + validation_fraction >= 0.95:
        raise ValueError("final test partition must contain at least 5%")
    n = len(candles)
    train_end = int(n * train_fraction)
    validation_end = int(n * (train_fraction + validation_fraction))
    train = candles[:train_end]
    validation = candles[train_end:validation_end]
    test = candles[validation_end:]
    partitions = {"train": train, "validation": validation, "test": test}
    if min(map(len, partitions.values())) < max(config.lookback_structure + 20, 50):
        raise ValueError("insufficient candles for chronological order-block partitions")

    depth_records: list[dict[str, object]] = []
    for depth in config.entry_depths:
        record: dict[str, object] = {"entry_depth": depth}
        for name in ("train", "validation"):
            partition = partitions[name]
            zones = detect_order_blocks(partition, config)
            trades = backtest_order_blocks(partition, zones, config, entry_depth=depth)
            record[name] = {
                "zones": len(zones),
                "metrics": order_block_metrics(trades),
            }
        depth_records.append(record)

    eligible = [
        record for record in depth_records
        if int((record["validation"] if isinstance(record["validation"], dict) else {}).get("metrics", {}).get("trades", 0)) > 0
    ]
    if eligible:
        selected = max(
            eligible,
            key=lambda record: float(
                ((record["validation"] if isinstance(record["validation"], dict) else {}).get("metrics", {}).get("mean_r") or -1e12)
            ),
        )
        selected_depth = float(selected["entry_depth"])
    else:
        selected_depth = 0.5

    test_zones = detect_order_blocks(test, config)
    test_trades = backtest_order_blocks(test, test_zones, config, entry_depth=selected_depth)
    return {
        "partition_boundaries": {
            "train_start": train[0].timestamp,
            "train_end": train[-1].timestamp,
            "validation_start": validation[0].timestamp,
            "validation_end": validation[-1].timestamp,
            "test_start": test[0].timestamp,
            "test_end": test[-1].timestamp,
        },
        "parameter_results": depth_records,
        "selected_entry_depth": selected_depth,
        "selection_partition": "validation",
        "test_zones": test_zones,
        "test_trades": test_trades,
        "test_metrics": order_block_metrics(test_trades),
        "status": "completed" if test_trades else "insufficient_test_trades",
    }
