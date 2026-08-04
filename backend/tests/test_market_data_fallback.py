from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

from app.interval.data import CoinbaseExchangePublicAdapter, ResilientPublicAdapter
from app.interval.types import CandleBatch, DataStatus
from app.research.types import Candle, MarketType


def _candles(exchange: str, market_type: MarketType) -> CandleBatch:
    now = int(time.time()) // 60 * 60
    rows = tuple(
        Candle(
            timestamp=now - (10 - index) * 60,
            availability_timestamp=now - (9 - index) * 60 + 1,
            exchange_timestamp=now - (9 - index) * 60,
            receipt_timestamp=now,
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.5 + index,
            volume=1.0,
        )
        for index in range(10)
    )
    return CandleBatch(
        asset="BTCUSDT",
        exchange=exchange,
        market_type=market_type,
        timeframe_minutes=1,
        candles=rows,
        fetched_timestamp=now,
        data_status=DataStatus(
            provider=exchange,
            connected=True,
            stale=False,
            last_candle_timestamp=rows[-1].timestamp,
            score=90,
        ),
    )


class UnavailableBinance:
    def candles(self, asset: str, market_type: MarketType, **_: object) -> CandleBatch:
        return CandleBatch(
            asset=asset,
            exchange="binance",
            market_type=market_type,
            timeframe_minutes=1,
            candles=(),
            fetched_timestamp=int(time.time()),
            data_status=DataStatus(
                provider="binance",
                connected=False,
                stale=True,
                score=0,
                reasons=("market-data request failed: HTTP Error 451",),
            ),
        )

    def ticker(self, asset: str, market_type: MarketType) -> tuple[float, int]:
        raise RuntimeError("Binance ticker should not be used after fallback")


class AvailableCoinbase:
    def __init__(self) -> None:
        self.candle_calls = 0
        self.ticker_calls = 0

    def candles(self, asset: str, market_type: MarketType, **_: object) -> CandleBatch:
        self.candle_calls += 1
        return _candles("coinbase", market_type)

    def ticker(self, asset: str, market_type: MarketType) -> tuple[float, int]:
        self.ticker_calls += 1
        return 123.45, int(time.time())


def test_resilient_adapter_falls_back_after_binance_451() -> None:
    coinbase = AvailableCoinbase()
    adapter = ResilientPublicAdapter(binance=UnavailableBinance(), coinbase=coinbase)

    batch = adapter.candles("BTCUSDT", MarketType.SPOT, limit=10)
    ticker, _ = adapter.ticker("BTCUSDT", MarketType.SPOT)

    assert batch.exchange == "coinbase"
    assert batch.data_status.provider == "coinbase"
    assert any("HTTP Error 451" in reason for reason in batch.data_status.reasons)
    assert any("automatic fallback active" in reason for reason in batch.data_status.reasons)
    assert ticker == 123.45
    assert coinbase.candle_calls == 1
    assert coinbase.ticker_calls == 1


def test_resilient_adapter_does_not_replace_perpetual_with_spot() -> None:
    coinbase = AvailableCoinbase()
    adapter = ResilientPublicAdapter(binance=UnavailableBinance(), coinbase=coinbase)

    batch = adapter.candles("BTCUSDT", MarketType.PERPETUAL, limit=10)

    assert not batch.candles
    assert coinbase.candle_calls == 0
    assert any("not interchangeable" in reason for reason in batch.data_status.reasons)


class PagedCoinbase(CoinbaseExchangePublicAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def _get_json(self, url: str) -> list[list[float]]:
        self.urls.append(url)
        query = parse_qs(urlparse(url).query)
        start = int(self._parse_iso(query["start"][0]))
        end = int(self._parse_iso(query["end"][0]))
        rows: list[list[float]] = []
        for timestamp in range(start, end, 60):
            minute = timestamp // 60
            open_price = 100.0 + minute % 20
            rows.append([
                timestamp,
                open_price - 1.0,
                open_price + 2.0,
                open_price,
                open_price + 0.5,
                2.0,
            ])
        rows.reverse()
        return rows

    @staticmethod
    def _parse_iso(value: str) -> float:
        from datetime import datetime

        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def test_coinbase_fallback_pages_to_preserve_500_candles() -> None:
    adapter = PagedCoinbase()
    end = (int(time.time()) // 60 - 10) * 60

    batch = adapter.candles(
        "BTCUSDT",
        MarketType.SPOT,
        limit=500,
        end_timestamp=end,
    )

    assert len(batch.candles) == 500
    assert len(adapter.urls) >= 2
    assert batch.exchange == "coinbase"
    assert batch.data_status.provider == "coinbase_exchange"
    assert batch.candles == tuple(sorted(batch.candles, key=lambda candle: candle.timestamp))
    first = batch.candles[0]
    assert first.low < first.open < first.high
    assert first.close > first.open
    assert first.aggressive_buy_notional is None
    assert first.aggressive_sell_notional is None
