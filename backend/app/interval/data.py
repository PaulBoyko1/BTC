from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
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
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "crypto-interval-analyzer/2.1",
                "Accept": "application/json",
            },
        )
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
        missing = _missing_candle_count(candles)
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


class CoinbaseExchangePublicAdapter:
    """Public Coinbase Exchange spot adapter used when Binance is unavailable.

    Coinbase products are USD quoted. The fallback therefore acts as a clearly
    labelled spot-price proxy for the requested USDT symbol; it is never used
    for a perpetual-futures request and it does not fabricate taker-side flow.
    """

    rest = "https://api.exchange.coinbase.com"
    max_candles_per_request = 300

    def __init__(self, timeout_seconds: float = 8.0) -> None:
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def product_id(asset: str) -> str:
        if asset not in SUPPORTED_ASSETS:
            raise ValueError(f"unsupported asset {asset}")
        return f"{asset.removesuffix('USDT')}-USD"

    def _get_json(self, url: str) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "crypto-interval-analyzer/2.1",
                "Accept": "application/json",
                "Cache-Control": "no-cache",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _iso_timestamp(timestamp: int) -> str:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    def ticker(self, asset: str, market_type: MarketType) -> tuple[float, int]:
        if market_type != MarketType.SPOT:
            raise ValueError("Coinbase fallback is spot-only and cannot substitute for perpetual market data")
        product = self.product_id(asset)
        payload = self._get_json(f"{self.rest}/products/{urllib.parse.quote(product)}/ticker")
        timestamp = int(time.time())
        raw_time = payload.get("time") if isinstance(payload, dict) else None
        if isinstance(raw_time, str):
            try:
                timestamp = int(datetime.fromisoformat(raw_time.replace("Z", "+00:00")).timestamp())
            except ValueError:
                pass
        return float(payload["price"]), timestamp

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
        fetched = int(time.time())
        if market_type != MarketType.SPOT:
            return _empty_batch(
                asset,
                market_type,
                provider="coinbase",
                exchange="coinbase",
                fetched=fetched,
                reason="Coinbase fallback is spot-only and cannot substitute for perpetual market data",
            )

        started = time.monotonic()
        product = self.product_id(asset)
        cursor_end = ((end_timestamp or fetched) // 60) * 60
        rows_by_timestamp: dict[int, list[Any]] = {}
        request_errors: list[str] = []

        # Coinbase returns at most 300 candles. Page backward until the requested
        # completed history is assembled, allowing for an omitted no-trade bucket.
        for _ in range(6):
            if len(rows_by_timestamp) >= limit:
                break
            remaining = limit - len(rows_by_timestamp)
            request_size = min(self.max_candles_per_request, max(20, remaining + 3))
            start_timestamp = cursor_end - request_size * 60
            params = urllib.parse.urlencode({
                "granularity": 60,
                "start": self._iso_timestamp(start_timestamp),
                "end": self._iso_timestamp(cursor_end),
            })
            url = f"{self.rest}/products/{urllib.parse.quote(product)}/candles?{params}"
            try:
                payload = self._get_json(url)
                if not isinstance(payload, list):
                    raise ValueError(f"unexpected candle response: {payload!r}")
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
                request_errors.append(str(exc))
                break

            oldest: int | None = None
            for row in payload:
                if not isinstance(row, list) or len(row) < 6:
                    continue
                timestamp = int(row[0])
                oldest = timestamp if oldest is None else min(oldest, timestamp)
                if timestamp + 60 > fetched:
                    continue
                rows_by_timestamp[timestamp] = row
            if oldest is None or oldest >= cursor_end:
                break
            cursor_end = oldest

        if not rows_by_timestamp:
            reason = "Coinbase market-data request failed"
            if request_errors:
                reason += ": " + "; ".join(request_errors)
            return _empty_batch(
                asset,
                market_type,
                provider="coinbase",
                exchange="coinbase",
                fetched=fetched,
                reason=reason,
            )

        candles: list[Candle] = []
        for timestamp in sorted(rows_by_timestamp)[-limit:]:
            row = rows_by_timestamp[timestamp]
            volume = float(row[5])
            candles.append(Candle(
                timestamp=timestamp,
                availability_timestamp=timestamp + 61,
                exchange_timestamp=timestamp + 60,
                receipt_timestamp=fetched,
                open=float(row[3]),
                high=float(row[2]),
                low=float(row[1]),
                close=float(row[4]),
                volume=volume,
                quote_volume=0.0,
                vwap=None,
                complete=True,
                aggressive_buy_notional=None,
                aggressive_sell_notional=None,
            ))

        missing = _missing_candle_count(candles)
        last = candles[-1].timestamp if candles else None
        stale = last is None or fetched - last > 180
        score = 92.0
        reasons = [
            f"using Coinbase Exchange {product} spot as a USD proxy for {asset}",
            "Coinbase candle data does not provide taker-side order-flow fields",
        ]
        if stale:
            score -= 60
            reasons.append("last completed candle is stale")
        if missing:
            score -= min(30, missing * 2)
            reasons.append(f"{missing} missing one-minute candles")
        if request_errors:
            score -= 10
            reasons.append("one or more Coinbase history pages failed")
        status = DataStatus(
            provider="coinbase_exchange",
            connected=True,
            stale=stale,
            last_candle_timestamp=last,
            latency_ms=int((time.monotonic() - started) * 1000),
            missing_candles=missing,
            score=max(0.0, score),
            reasons=tuple(reasons),
        )
        return CandleBatch(
            asset=asset,
            exchange="coinbase",
            market_type=market_type,
            timeframe_minutes=1,
            candles=tuple(candles),
            fetched_timestamp=fetched,
            data_status=status,
        )


class ResilientPublicAdapter:
    """Prefer Binance and automatically fall back to Coinbase spot data."""

    def __init__(
        self,
        timeout_seconds: float = 8.0,
        *,
        binance: BinancePublicAdapter | None = None,
        coinbase: CoinbaseExchangePublicAdapter | None = None,
    ) -> None:
        self.binance = binance or BinancePublicAdapter(timeout_seconds)
        self.coinbase = coinbase or CoinbaseExchangePublicAdapter(timeout_seconds)
        self._last_source: dict[tuple[str, str], str] = {}

    def candles(
        self,
        asset: str,
        market_type: MarketType,
        *,
        limit: int = 500,
        end_timestamp: int | None = None,
    ) -> CandleBatch:
        primary = self.binance.candles(
            asset,
            market_type,
            limit=limit,
            end_timestamp=end_timestamp,
        )
        key = (asset, market_type.value)
        if primary.candles:
            self._last_source[key] = "binance"
            return primary

        if market_type != MarketType.SPOT:
            reason = "Coinbase fallback was not used because perpetual and spot markets are not interchangeable"
            status = primary.data_status.model_copy(update={
                "reasons": primary.data_status.reasons + (reason,),
            })
            return primary.model_copy(update={"data_status": status})

        fallback = self.coinbase.candles(
            asset,
            market_type,
            limit=limit,
            end_timestamp=end_timestamp,
        )
        if fallback.candles:
            primary_reason = "; ".join(primary.data_status.reasons) or "Binance returned no candles"
            status = fallback.data_status.model_copy(update={
                "reasons": (f"Binance unavailable ({primary_reason}); automatic fallback active",)
                + fallback.data_status.reasons,
            })
            self._last_source[key] = "coinbase"
            return fallback.model_copy(update={"data_status": status})

        combined = DataStatus(
            provider="binance+coinbase_exchange",
            connected=False,
            stale=True,
            score=0,
            reasons=primary.data_status.reasons + fallback.data_status.reasons,
        )
        return primary.model_copy(update={"data_status": combined})

    def ticker(self, asset: str, market_type: MarketType) -> tuple[float, int]:
        key = (asset, market_type.value)
        if self._last_source.get(key) == "coinbase":
            return self.coinbase.ticker(asset, market_type)
        try:
            return self.binance.ticker(asset, market_type)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            if market_type == MarketType.SPOT:
                return self.coinbase.ticker(asset, market_type)
            raise


def _empty_batch(
    asset: str,
    market_type: MarketType,
    *,
    provider: str,
    exchange: str,
    fetched: int,
    reason: str,
) -> CandleBatch:
    return CandleBatch(
        asset=asset,
        exchange=exchange,
        market_type=market_type,
        timeframe_minutes=1,
        candles=(),
        fetched_timestamp=fetched,
        data_status=DataStatus(
            provider=provider,
            connected=False,
            stale=True,
            score=0,
            reasons=(reason,),
        ),
    )


def _missing_candle_count(candles: list[Candle]) -> int:
    missing = 0
    for left, right in zip(candles, candles[1:]):
        gap = (right.timestamp - left.timestamp) // 60 - 1
        if gap > 0:
            missing += gap
    return missing
