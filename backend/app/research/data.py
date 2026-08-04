from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from .types import Candle, DatasetImport


@dataclass(frozen=True)
class DataIntegrityResult:
    passed: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    observation_count: int
    start_timestamp: int | None
    end_timestamp: int | None


def dataset_hash(dataset: DatasetImport) -> str:
    canonical = {
        "name": dataset.name,
        "asset": dataset.asset,
        "exchange": dataset.exchange,
        "market_type": dataset.market_type,
        "source_timeframe_minutes": dataset.source_timeframe_minutes,
        "feature_version": dataset.feature_version,
        "adapter_version": dataset.adapter_version,
        "candles": [c.model_dump(mode="json") for c in dataset.candles],
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_dataset(dataset: DatasetImport, required_features: Iterable[str] = ()) -> DataIntegrityResult:
    reasons: list[str] = []
    warnings: list[str] = []
    candles = dataset.candles
    interval = dataset.source_timeframe_minutes * 60

    timestamps = [c.timestamp for c in candles]
    if timestamps != sorted(timestamps):
        reasons.append("Candle timestamps are not strictly chronological")
    if len(set(timestamps)) != len(timestamps):
        reasons.append("Duplicate candle timestamps detected")
    if any(timestamp <= 0 for timestamp in timestamps):
        reasons.append("Invalid non-positive UTC timestamp")
    if any(timestamp % interval != 0 for timestamp in timestamps):
        reasons.append("One or more candle timestamps do not align to the configured UTC candle boundary")
    if any(not c.complete for c in candles):
        reasons.append("Incomplete candles are present in the requested dataset")

    for index, candle in enumerate(candles):
        availability = candle.availability_timestamp or candle.timestamp + interval
        if availability < candle.timestamp + interval:
            reasons.append(f"Candle {index} availability precedes candle close")
            break
        if candle.exchange_timestamp is not None and candle.exchange_timestamp < candle.timestamp:
            warnings.append(f"Candle {index} exchange timestamp precedes candle open")
        if candle.receipt_timestamp is not None and candle.exchange_timestamp is not None:
            if candle.receipt_timestamp < candle.exchange_timestamp:
                warnings.append(f"Candle {index} receipt timestamp precedes exchange timestamp")

    gaps = [
        timestamps[i] - timestamps[i - 1]
        for i in range(1, len(timestamps))
        if timestamps[i] - timestamps[i - 1] != interval
    ]
    if gaps:
        warnings.append(f"Detected {len(gaps)} non-contiguous candle gaps; experiments may reject folds with insufficient continuity")

    required = set(required_features)
    if "aggressive_trade_flow" in required or "aggressive_flow_percentile" in required:
        missing = sum(
            1 for c in candles
            if c.aggressive_buy_notional is None or c.aggressive_sell_notional is None
        )
        if missing:
            reasons.append(f"Aggressive buy/sell notional is missing for {missing} candles")
    if "order_book" in required or "liquidity_replenishment" in required:
        missing = sum(1 for c in candles if c.bid_replenishment is None or c.ask_replenishment is None)
        if missing:
            reasons.append(f"Bid/ask replenishment is missing for {missing} candles")
    if "cvd" in required:
        missing = sum(1 for c in candles if c.cvd is None)
        if missing:
            reasons.append(f"CVD is missing for {missing} candles")
    if "derivatives" in required:
        missing = sum(1 for c in candles if c.open_interest is None or c.funding_rate is None)
        if missing:
            reasons.append(f"Open interest or funding is missing for {missing} candles")

    return DataIntegrityResult(
        passed=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
        observation_count=len(candles),
        start_timestamp=min(timestamps) if timestamps else None,
        end_timestamp=max(timestamps) if timestamps else None,
    )


def slice_candles(candles: list[Candle], start: int, end: int) -> list[Candle]:
    return [c for c in candles if start <= c.timestamp < end]


def utc_iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
