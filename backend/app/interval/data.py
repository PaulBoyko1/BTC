from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.research.types import Candle, MarketType

from .types import CandleBatch, DataStatus, SUPPORTED_ASSETS


@dataclass(frozen=True)
class BinanceEndpoints:
    rest: str
    klines_path: str = "/api/v3/klines"
    ticker_path: str = "/api/v3/ticker/price"


class BinancePublicAdapter:
    """Public unauthenticated Binance REST adapter.

    The adapter intentionally uses completed one-minute candles for model
    features. The current ticker is fetched separately and never used to
    rewrite a completed candle.
    """

    def __init__(self, timeout_seconds: float = 8.0) -> None:
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def endpoints(market_type: MarketType) -> BinanceEndpoints:
        if market_type == MarketType.PERPETUAL:
            return BinanceEndpoints(
                rest="https://fapi.binance.com",
                klines_path="/fapi/v1/klines",
                ticker_path="/fapi/v1/ticker/price",
            )
        return BinanceEndpoints(rest="https://api.binance.com")

    def _get_json(self, url: str) -> Any:
        request = urllib.request.Request(url, headers={"User-Agent": "crypto-interval-analyzer/1.0"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def ticker(self, asset: str, market_type: MarketType) -> tuple[float, int]:
        if asset not in SUPPORTED_ASSETS:
            raise ValueError(f"unsupported asset {asset}")
        endpoints = self.endpoints(market_type)
        query = urllib.parse.urlencode({"symbol": asset})
        payload = self._get_json(f"{endpoints.rest}{endpoints.ticker_path}?{query}")
        return float(payload["price"]), int(time.time())

    def candles(
        self,
        asset: str,
        market_type: MarketType,
        *,
        limit: int = 500,
        end_timestamp: int | None = None,
    ) -> CandleBatch:
        if asset not in SUPPORTED_ASSETS:
            raise ValueError(f"unsupported asset {asset}")
        if not 10 <= limit <= 1000:
            raise ValueError("limit must be between 10 and 1000")
        endpoints = self.endpoints(market_type)
        params: dict[str, Any] = {"symbol": asset, "interval": "1m", "limit": limit}
        if end_timestamp is not None:
            params["endTime"] = end_timestamp * 1000
        started = time.monotonic()
        fetched = int(time.time())
        try:
            payload = self._get_json(f"{endpoints.rest}{endpoints.klines_path}?{urllib.parse.urlencode(params)}")
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            status = DataStatus(
                provider="binance",
                connected=False,
                stale=True,
                score=0,
                reasons=(f"market-data request failed: {exc}",),
            )
            return CandleBatch(
                asset=asset,
                exchange="binance",
                market_type=market_type,
                timeframe_minutes=1,
                candles=(),
                fetched_timestamp=fetched,
                data_status=status,
            )

        now_ms = int(time.time() * 1000)
        candles: list[Candle] = []
        duplicates = 0
        seen: set[int] = set()
        for row in payload:
            open_time_ms = int(row[0])
            close_time_ms = int(row[6])
            timestamp = open_time_ms // 1000
            if timestamp in seen:
                duplicates += 1
                continue
            seen.add(timestamp)
            complete = close_time_ms < now_ms
            if not complete:
                continue
            base_volume = float(row[5])
            quote_volume = float(row[7])
            taker_buy_base = float(row[9])
            taker_buy_quote = float(row[10])
            aggressive_sell_quote = max(0.0, quote_volume - taker_buy_quote)
            candles.append(Candle(
                timestamp=timestamp,
                availability_timestamp=close_time_ms // 1000 + 1,
                exchange_timestamp=close_time_ms // 1000,
                receipt_timestamp=fetched,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=base_volume,
                quote_volume=quote_volume,
                vwap=quote_volume / base_volume if base_volume > 0 else None,
                complete=True,
                aggressive_buy_notional=taker_buy_quote,
                aggressive_sell_notional=aggressive_sell_quote,
            ))
        candles.sort(key=lambda candle: candle.timestamp)
        missing = 0
        for left, right in zip(candles, candles[1:]):
            gap = (right.timestamp - left.timestamp) // 60 - 1
            if gap > 0:
                missing += gap
        last = candles[-1].timestamp if candles else None
        stale = last is None or fetched - last > 180
        latency = int((time.monotonic() - started) * 1000)
        score = 100.0
        reasons: list[str] = []
        if stale:
            score -= 60
            reasons.append("last completed candle is stale")
        if missing:
            score -= min(30, missing * 2)
            reasons.append(f"{missing} missing one-minute candles")
        if duplicates:
            score -= min(10, duplicates)
            reasons.append(f"{duplicates} duplicate candles discarded")
        status = DataStatus(
            provider="binance",
            connected=True,
            stale=stale,
            last_candle_timestamp=last,
            latency_ms=latency,
            missing_candles=missing,
            duplicate_events=duplicates,
            score=max(0.0, score),
            reasons=tuple(reasons),
        )
        return CandleBatch(
            asset=asset,
            exchange="binance",
            market_type=market_type,
            timeframe_minutes=1,
            candles=tuple(candles),
            fetched_timestamp=fetched,
            data_status=status,
        )
