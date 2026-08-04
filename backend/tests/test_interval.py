from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.interval.bootstrap import bootstrap_confidence_interval
from app.interval.clock import current_fixed_window, is_fixed_boundary
from app.interval.model import Calibration, analyze_interval
from app.interval.null_models import run_order_block_null_model
from app.interval.order_blocks import backtest_order_blocks, detect_order_blocks
from app.interval.router import router
from app.interval.storage import IntervalStorage
from app.interval.types import (
    DataStatus,
    Horizon,
    IntervalWindow,
    NullModelRequest,
    OrderBlockConfig,
    ProbabilityState,
    ResearchTrade,
)
from app.research.types import Candle, MarketType


def candles(count: int = 180, start: int = 1_700_000_000) -> list[Candle]:
    result: list[Candle] = []
    price = 100.0
    for index in range(count):
        change = 0.03 + (0.02 if index % 7 < 4 else -0.01)
        open_price = price
        close = price + change
        high = max(open_price, close) + 0.08
        low = min(open_price, close) - 0.08
        result.append(Candle(
            timestamp=start + index * 60,
            availability_timestamp=start + (index + 1) * 60,
            open=open_price, high=high, low=low, close=close,
            volume=10 + index % 5,
            quote_volume=(10 + index % 5) * ((open_price + close) / 2),
            aggressive_buy_notional=700 + index,
            aggressive_sell_notional=500 + index / 2,
            complete=True,
        ))
        price = close
    return result


def order_block_candles() -> list[Candle]:
    result: list[Candle] = []
    start = 1_700_100_000
    for index in range(80):
        base = 100 + (index % 4) * 0.02
        result.append(Candle(
            timestamp=start + index * 60,
            availability_timestamp=start + (index + 1) * 60,
            open=base, high=base + 0.15, low=base - 0.15, close=base + 0.01,
            volume=20, quote_volume=2000, complete=True,
        ))
    result[20] = result[20].model_copy(update={"open": 100.2, "high": 100.3, "low": 99.7, "close": 99.8})
    result[21] = result[21].model_copy(update={"open": 99.8, "high": 102.0, "low": 99.75, "close": 101.8})
    result[22] = result[22].model_copy(update={"open": 101.8, "high": 105.2, "low": 101.7, "close": 105.0})
    result[23] = result[23].model_copy(update={"open": 101.0, "high": 101.2, "low": 99.8, "close": 100.4})
    result[24] = result[24].model_copy(update={"open": 100.4, "high": 103.0, "low": 100.3, "close": 102.8})
    return result


def test_fixed_utc_boundaries() -> None:
    timestamp = 1_700_000_777
    fifteen = current_fixed_window(timestamp, Horizon.FIFTEEN_MINUTES)
    hour = current_fixed_window(timestamp, Horizon.ONE_HOUR)
    assert fifteen.start_timestamp % 900 == 0
    assert fifteen.expiry_timestamp - fifteen.start_timestamp == 900
    assert hour.start_timestamp % 3600 == 0
    assert hour.expiry_timestamp - hour.start_timestamp == 3600
    assert is_fixed_boundary(fifteen.start_timestamp, Horizon.FIFTEEN_MINUTES)


def test_heuristic_scores_do_not_become_probabilities() -> None:
    series = candles()
    now = series[-1].timestamp + 30
    fixed = current_fixed_window(now, Horizon.FIFTEEN_MINUTES)
    window = IntervalWindow(
        horizon=Horizon.FIFTEEN_MINUTES,
        start_timestamp=fixed.start_timestamp,
        expiry_timestamp=fixed.expiry_timestamp,
        reference_price=series[-15].open,
        reference_source="test",
    )
    status = DataStatus(provider="test", connected=True, stale=False, score=100)
    result = analyze_interval(
        asset="BTCUSDT", exchange="binance", market_type=MarketType.SPOT,
        candles=series, window=window, data_status=status, generated_timestamp=now,
    )
    assert result.probability_state == ProbabilityState.HEURISTIC
    assert result.up_probability is None
    assert result.down_probability is None
    assert 0 <= result.reversion_score <= 1
    assert 0 <= result.continuation_score <= 1
    assert abs(result.reversion_score + result.continuation_score - 1) > 1e-4


def test_calibration_gate_requires_prior_validation() -> None:
    series = candles()
    now = series[-1].timestamp + 30
    fixed = current_fixed_window(now, Horizon.FIFTEEN_MINUTES)
    window = IntervalWindow(horizon=Horizon.FIFTEEN_MINUTES, start_timestamp=fixed.start_timestamp, expiry_timestamp=fixed.expiry_timestamp, reference_price=series[-15].open, reference_source="test")
    status = DataStatus(provider="test", connected=True, stale=False, score=100)
    calibration = Calibration(model_id="cal-1", sample_count=500, intercept=0.0, coefficient=1.2, brier_skill=0.05, validation_end_timestamp=window.start_timestamp - 1)
    result = analyze_interval(asset="BTCUSDT", exchange="binance", market_type=MarketType.SPOT, candles=series, window=window, data_status=status, generated_timestamp=now, calibration=calibration)
    assert result.probability_state == ProbabilityState.CALIBRATED
    assert result.up_probability is not None
    assert result.down_probability is not None
    assert result.up_probability + result.down_probability == pytest.approx(1.0)


def test_prediction_and_reference_are_immutable(tmp_path: Path) -> None:
    migration = Path(__file__).parents[1] / "migrations" / "002_crypto_interval_analyzer.sql"
    storage = IntervalStorage(tmp_path / "interval.sqlite3", migration)
    series = candles()
    now = series[-1].timestamp + 30
    fixed = current_fixed_window(now, Horizon.FIFTEEN_MINUTES)
    window = IntervalWindow(horizon=Horizon.FIFTEEN_MINUTES, start_timestamp=fixed.start_timestamp, expiry_timestamp=fixed.expiry_timestamp, reference_price=series[-15].open, reference_source="test")
    reference_id = storage.get_or_create_reference(asset="BTCUSDT", exchange="binance", market_type=MarketType.SPOT, window=window)
    analysis = analyze_interval(asset="BTCUSDT", exchange="binance", market_type=MarketType.SPOT, candles=series, window=window, data_status=DataStatus(provider="test", connected=True, stale=False, score=100), generated_timestamp=now)
    storage.insert_prediction(reference_id, analysis)
    storage.insert_prediction(reference_id, analysis)
    changed = analysis.model_copy(update={"current_price": analysis.current_price + 1})
    with pytest.raises(ValueError, match="immutable"):
        storage.insert_prediction(reference_id, changed)
    altered_window = window.model_copy(update={"reference_price": window.reference_price + 1})
    with pytest.raises(ValueError, match="immutable"):
        storage.get_or_create_reference(asset="BTCUSDT", exchange="binance", market_type=MarketType.SPOT, window=altered_window)


def test_order_block_definition_depth_and_backtest() -> None:
    series = order_block_candles()
    config = OrderBlockConfig(displacement_atr=1.0, target_rr=1.0, max_holding_bars=10)
    zones = detect_order_blocks(series, config)
    assert zones
    bullish = next(zone for zone in zones if zone.side == "bullish")
    assert bullish.price_at_depth(0.0) == bullish.lower
    assert bullish.price_at_depth(1.0) == bullish.upper
    assert bullish.price_at_depth(0.5) == pytest.approx((bullish.lower + bullish.upper) / 2)
    trades = backtest_order_blocks(series, [bullish], config, entry_depth=0.5)
    assert len(trades) <= 1


def test_null_model_and_dependence_preserving_bootstrap_are_deterministic() -> None:
    series = order_block_candles()
    config = OrderBlockConfig(displacement_atr=1.0, target_rr=1.0, max_holding_bars=10)
    zones = detect_order_blocks(series, config)
    request = NullModelRequest(model="random_depth", simulations=100, seed=7)
    first = run_order_block_null_model(series, zones, config, request)
    second = run_order_block_null_model(series, zones, config, request)
    assert first == second
    trades = [
        ResearchTrade(setup_id=str(i), entry_timestamp=1_700_000_000 + i * 60, exit_timestamp=1_700_000_060 + i * 60, side="long", entry_price=100, exit_price=101 if i % 3 else 99, stop_price=99, target_price=102, r_multiple=1 if i % 3 else -1, pnl=10 if i % 3 else -10, day_key=f"2023-11-{14 + i // 4:02d}")
        for i in range(20)
    ]
    day = bootstrap_confidence_interval(trades, method="day", simulations=200, seed=9)
    block = bootstrap_confidence_interval(trades, method="block", simulations=200, seed=9)
    assert day.lower is not None and day.upper is not None
    assert block.lower is not None and block.upper is not None


def test_assets_api_has_initial_universe() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/api/interval/assets")
    assert response.status_code == 200
    symbols = {item["symbol"] for item in response.json()}
    assert {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"}.issubset(symbols)


def test_order_block_validation_selects_on_validation_only() -> None:
    from app.interval.order_blocks import chronological_order_block_validation
    series = order_block_candles() * 4
    # Rebuild timestamps so the repeated deterministic pattern stays chronological.
    rebuilt = [candle.model_copy(update={"timestamp": 1_700_200_000 + index * 60, "availability_timestamp": 1_700_200_000 + (index + 1) * 60}) for index, candle in enumerate(series)]
    config = OrderBlockConfig(displacement_atr=1.0, target_rr=1.0, max_holding_bars=10)
    result = chronological_order_block_validation(rebuilt, config)
    assert result["selection_partition"] == "validation"
    assert result["selected_entry_depth"] in config.entry_depths
    assert len(result["parameter_results"]) == len(config.entry_depths)


def test_order_block_api_uses_chronological_partitions() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    series = order_block_candles() * 4
    rebuilt = [candle.model_copy(update={"timestamp": 1_700_300_000 + index * 60, "availability_timestamp": 1_700_300_000 + (index + 1) * 60}) for index, candle in enumerate(series)]
    response = client.post("/api/interval/order-blocks/research", json={
        "asset": "BTCUSDT",
        "market_type": "spot",
        "candles": [candle.model_dump(mode="json") for candle in rebuilt],
        "config": {
            "definition": "displacement",
            "lookback_structure": 20,
            "displacement_atr": 1.0,
            "imbalance_fraction": 0.1,
            "zone_mode": "full",
            "entry_depths": [1.0, 0.75, 0.5, 0.25, 0.0],
            "stop_buffer_atr": 0.2,
            "target_rr": 1.0,
            "confirmation": "touch",
            "max_holding_bars": 10
        },
        "entry_depth": 0.5,
        "null_models": [{"model": "random_depth", "simulations": 100, "seed": 3}],
        "bootstrap_simulations": 100,
        "random_seed": 3
    })
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["chronological_validation"]["selection_partition"] == "validation"
    assert payload["result_label"] == "EXPERIMENTAL — NOT A VALIDATED EDGE"
