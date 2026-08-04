from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.research.types import Candle, MarketType

from .clock import current_fixed_window
from .data import ResilientPublicAdapter
from .model import analyze_interval
from .storage import IntervalStorage
from .types import Horizon, IntervalAnalysis, IntervalWindow, PredictionOutcome, SUPPORTED_ASSETS


@dataclass
class CacheEntry:
    timestamp: float
    value: Any


class IntervalService:
    def __init__(
        self,
        storage: IntervalStorage,
        adapter: Any | None = None,
        cache_seconds: float = 3.0,
    ) -> None:
        self.storage = storage
        self.adapter = adapter or ResilientPublicAdapter()
        self.cache_seconds = cache_seconds
        self._cache: dict[tuple[str, str, str], CacheEntry] = {}

    def assets(self) -> list[dict[str, Any]]:
        return [
            {
                "symbol": asset,
                "base": asset.removesuffix("USDT"),
                "quote": "USDT",
                "normal_confidence_enabled": asset in {"BTCUSDT", "ETHUSDT"},
                "status": "enabled" if asset in {"BTCUSDT", "ETHUSDT"} else "experimental_liquidity_gate",
            }
            for asset in SUPPORTED_ASSETS
        ]

    @staticmethod
    def _reference(candles: list[Candle], start_timestamp: int, exchange: str = "binance") -> tuple[float, str]:
        exact = next((candle for candle in candles if candle.timestamp == start_timestamp), None)
        if exact:
            return exact.open, f"{exchange}_one_minute_interval_open"
        prior = [candle for candle in candles if candle.timestamp < start_timestamp]
        if prior:
            return prior[-1].close, f"{exchange}_last_completed_candle_before_interval"
        raise ValueError("interval reference price is unavailable")

    def live(
        self,
        asset: str,
        market_type: MarketType,
        horizon: Horizon,
        *,
        now_timestamp: int | None = None,
        persist: bool = True,
    ) -> IntervalAnalysis:
        if asset not in SUPPORTED_ASSETS:
            raise ValueError(f"unsupported asset {asset}")
        now = int(time.time()) if now_timestamp is None else now_timestamp
        key = (asset, market_type.value, horizon.value)
        cached = self._cache.get(key)
        if now_timestamp is None and cached and time.monotonic() - cached.timestamp < self.cache_seconds:
            return cached.value
        batch = self.adapter.candles(asset, market_type, limit=500, end_timestamp=now)
        if not batch.candles:
            raise RuntimeError("market data unavailable: " + "; ".join(batch.data_status.reasons))
        candles = list(batch.candles)
        exchange = batch.exchange
        if persist:
            self.resolve_expired(asset, market_type, candles, now, exchange=exchange)
        fixed = current_fixed_window(now, horizon)
        reference, source = self._reference(candles, fixed.start_timestamp, exchange)
        window = IntervalWindow(
            horizon=horizon,
            start_timestamp=fixed.start_timestamp,
            expiry_timestamp=fixed.expiry_timestamp,
            reference_price=reference,
            reference_source=source,
        )
        try:
            ticker, _ = self.adapter.ticker(asset, market_type)
        except Exception:
            ticker = candles[-1].close

        # Existing calibration records are Binance-specific. Never apply one to
        # Coinbase proxy data merely because the asset and horizon match.
        calibration = (
            self.storage.active_calibration(asset, market_type, horizon)
            if exchange == "binance"
            else None
        )
        analysis = analyze_interval(
            asset=asset,
            exchange=exchange,
            market_type=market_type,
            candles=candles,
            window=window,
            data_status=batch.data_status,
            generated_timestamp=now,
            calibration=calibration,
            current_price_override=ticker,
        )
        if persist:
            reference_id = self.storage.get_or_create_reference(
                asset=asset, exchange=exchange, market_type=market_type, window=window
            )
            self.storage.insert_prediction(reference_id, analysis)
            self.storage.data_quality_event(
                asset=asset, exchange=exchange, market_type=market_type,
                timestamp=now, status="stale" if batch.data_status.stale else "healthy",
                score=batch.data_status.score,
                details=batch.data_status.model_dump(mode="json"),
            )
        if now_timestamp is None:
            self._cache[key] = CacheEntry(time.monotonic(), analysis)
        return analysis

    def resolve_expired(
        self,
        asset: str,
        market_type: MarketType,
        candles: list[Candle],
        now_timestamp: int,
        *,
        exchange: str = "binance",
    ) -> int:
        resolved = 0
        for prediction in self.storage.unresolved_predictions(now_timestamp):
            if prediction["asset"] != asset or prediction["market_type"] != market_type.value:
                continue
            prediction_exchange = prediction.get("exchange")
            if prediction_exchange is not None and prediction_exchange != exchange:
                continue
            expiry = int(prediction["expiry_timestamp"])
            expiry_candle = next((candle for candle in candles if candle.timestamp == expiry), None)
            if expiry_candle is None:
                continue
            expiry_price = expiry_candle.open
            reference = float(prediction["reference_price"])
            finished_above = expiry_price > reference
            correct: bool | None = None
            if prediction["up_probability"] is not None and prediction["down_probability"] is not None:
                predicted_up = float(prediction["up_probability"]) >= float(prediction["down_probability"])
                correct = predicted_up == finished_above
            elif abs(float(prediction["raw_direction_score"])) >= 0.08:
                correct = (float(prediction["raw_direction_score"]) > 0) == finished_above
            self.storage.insert_outcome(PredictionOutcome(
                prediction_id=str(prediction["prediction_id"]),
                resolved_timestamp=now_timestamp,
                expiry_price=expiry_price,
                finished_above_reference=finished_above,
                signed_return=expiry_price / reference - 1.0,
                correct=correct,
            ))
            resolved += 1
        return resolved

    def chart(self, asset: str, market_type: MarketType, limit: int = 500) -> dict[str, Any]:
        batch = self.adapter.candles(asset, market_type, limit=limit)
        return {
            "asset": asset,
            "exchange": batch.exchange,
            "market_type": market_type.value,
            "timeframe_minutes": 1,
            "candles": [candle.model_dump(mode="json") for candle in batch.candles],
            "data_status": batch.data_status.model_dump(mode="json"),
            "expiry_boundaries": [
                {
                    "timestamp": candle.timestamp,
                    "kind": "hour" if candle.timestamp % 3600 == 0 else "quarter_hour",
                }
                for candle in batch.candles
                if candle.timestamp % 900 == 0
            ],
        }
