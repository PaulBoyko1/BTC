from __future__ import annotations

import math
from pathlib import Path

import pytest

from app.research.storage import ResearchStorage
from app.research.types import Candle, DatasetImport, MarketType


@pytest.fixture
def deterministic_candles() -> list[Candle]:
    start = 1_735_689_600  # 2025-01-01 00:00:00 UTC, aligned to 15m
    candles: list[Candle] = []
    price = 100_000.0
    for index in range(800):
        trend = 8.0 if (index // 96) % 2 == 0 else -6.0
        cycle = math.sin(index / 8.0) * 35.0
        open_price = price
        close = max(100.0, open_price + trend + cycle * 0.08)
        high = max(open_price, close) + 25.0 + abs(math.sin(index)) * 10
        low = min(open_price, close) - 25.0 - abs(math.cos(index)) * 10
        volume = 10.0 + abs(math.sin(index / 3.0)) * 4
        quote = volume * ((open_price + close) / 2)
        sell = quote * (0.65 if close < open_price else 0.35)
        buy = quote - sell
        candles.append(Candle(
            timestamp=start + index * 900,
            availability_timestamp=start + (index + 1) * 900,
            exchange_timestamp=start + (index + 1) * 900 - 1,
            receipt_timestamp=start + (index + 1) * 900,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            quote_volume=quote,
            vwap=(open_price + close) / 2,
            aggressive_buy_notional=buy,
            aggressive_sell_notional=sell,
            bid_replenishment=100_000 + index,
            ask_replenishment=100_000 + index,
            cvd=float(index),
            open_interest=1_000_000 + index * 100,
            funding_rate=0.0001,
        ))
        price = close
    return candles


@pytest.fixture
def deterministic_dataset(deterministic_candles: list[Candle]) -> DatasetImport:
    return DatasetImport(
        name="DEMO DATA — NOT MARKET RESULTS",
        asset="BTCUSDT",
        exchange="binance",
        market_type=MarketType.SPOT,
        source_timeframe_minutes=15,
        candles=deterministic_candles,
    )


@pytest.fixture
def storage(tmp_path: Path) -> ResearchStorage:
    migration = Path(__file__).parents[1] / "migrations" / "001_research_lab.sql"
    return ResearchStorage(tmp_path / "research.sqlite3", migration)
