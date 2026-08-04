from __future__ import annotations

import math

import pytest

from app.interval.clock import current_fixed_window
from app.interval.contracts import compare_contracts, indicative_probability
from app.interval.model import analyze_interval
from app.interval.presets import PRESETS, backtest_preset, current_preset_rows, score_preset
from app.interval.types import DataStatus, Horizon, IntervalWindow
from app.research.types import Candle, MarketType


def candles(count: int = 1080, start: int = 1_700_000_000) -> list[Candle]:
    aligned_start = start - start % 60
    result: list[Candle] = []
    price = 100.0
    for index in range(count):
        cycle = math.sin(index / 11.0) * 0.08
        drift = 0.025 if (index // 120) % 2 == 0 else -0.018
        open_price = price
        close = max(1.0, open_price + drift + cycle)
        high = max(open_price, close) + 0.12
        low = min(open_price, close) - 0.12
        volume = 20.0 + index % 7
        quote = volume * ((open_price + close) / 2.0)
        buy_ratio = 0.56 if close >= open_price else 0.44
        result.append(Candle(
            timestamp=aligned_start + index * 60,
            availability_timestamp=aligned_start + (index + 1) * 60,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            quote_volume=quote,
            aggressive_buy_notional=quote * buy_ratio,
            aggressive_sell_notional=quote * (1.0 - buy_ratio),
            complete=True,
        ))
        price = close
    return result


def analysis() -> object:
    series = candles(240)
    now = series[-1].timestamp + 30
    fixed = current_fixed_window(now, Horizon.FIFTEEN_MINUTES)
    reference = next((candle.open for candle in series if candle.timestamp == fixed.start_timestamp), series[-15].open)
    window = IntervalWindow(
        horizon=Horizon.FIFTEEN_MINUTES,
        start_timestamp=fixed.start_timestamp,
        expiry_timestamp=fixed.expiry_timestamp,
        reference_price=reference,
        reference_source="test",
    )
    return analyze_interval(
        asset="BTCUSDT",
        exchange="binance",
        market_type=MarketType.SPOT,
        candles=series,
        window=window,
        data_status=DataStatus(provider="test", connected=True, stale=False, score=100),
        generated_timestamp=now,
    )


def test_indicative_probability_matches_small_negative_composite() -> None:
    assert indicative_probability(-0.018) == pytest.approx(0.4838057, rel=1e-5)


def test_contract_comparison_shows_both_sides_without_fees() -> None:
    result = compare_contracts(
        analysis(),
        {
            "provider": "polymarket",
            "available": True,
            "up": {"ask": 0.47, "bid": 0.46, "midpoint": 0.465},
            "down": {"ask": 0.54, "bid": 0.53, "midpoint": 0.535},
        },
    )
    assert result["no_fee_assumption"] is True
    assert result["up"]["market_price"] == pytest.approx(0.47)
    assert result["down"]["market_price"] == pytest.approx(0.54)
    assert result["up"]["edge"] == pytest.approx(result["up"]["fair_value"] - 0.47)
    assert result["fair_value_state"] == "indicative_uncalibrated"


def test_presets_are_distinct_and_clickable() -> None:
    current = analysis()
    rows = current_preset_rows(current)
    assert len(rows) == len(PRESETS)
    assert len({row["preset_id"] for row in rows}) == len(PRESETS)
    assert {row["category"] for row in rows}.issuperset({"Continuation", "Reversion", "Order Flow"})
    scores = {round(float(row["score"]), 6) for row in rows}
    assert len(scores) > 3


def test_score_preset_rejects_unknown_definition() -> None:
    with pytest.raises(KeyError):
        score_preset("does-not-exist", {}, 0.5)


def test_backtest_uses_fixed_clock_intervals_and_same_elapsed_minute() -> None:
    result = backtest_preset(
        candles(),
        horizon=Horizon.FIFTEEN_MINUTES,
        preset_id="balanced",
        elapsed_seconds=7 * 60 + 22,
        minimum_score=0.0,
    )
    assert result["elapsed_minutes"] == 7
    assert result["samples"] > 10
    assert result["wins"] + result["losses"] == result["samples"]
    assert result["contract_pnl_tested"] is False
    assert result["costs_included"] is False
    assert result["cases_by_regime"]
