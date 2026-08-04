from __future__ import annotations

import importlib
import os

from fastapi.testclient import TestClient


def test_api_empty_state_and_strategy_registry(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(tmp_path))
    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)
    assert client.get("/health").status_code == 200
    strategies = client.get("/api/research/strategies")
    assert strategies.status_code == 200
    assert len(strategies.json()) == 5
    overview = client.get("/api/research/overview").json()
    assert overview["completed_experiments"] == 0
    assert client.get("/api/research/funnel").status_code == 200


def test_api_import_and_background_experiment(tmp_path, monkeypatch, deterministic_dataset) -> None:
    import time

    monkeypatch.setenv("RESEARCH_DATA_DIR", str(tmp_path))
    import app.main as main
    importlib.reload(main)
    client = TestClient(main.app)
    imported = client.post("/api/research/datasets", json=deterministic_dataset.model_dump(mode="json"))
    assert imported.status_code == 201, imported.text
    dataset = imported.json()
    candles = deterministic_dataset.candles
    payload = {
        "strategy_id": "simple_momentum",
        "strategy_version": "1.0.0",
        "dataset_id": dataset["dataset_id"],
        "asset": "BTCUSDT",
        "exchange": "binance",
        "market_type": "spot",
        "source_timeframe_minutes": 15,
        "prediction_horizon_minutes": 15,
        "start_timestamp": candles[0].timestamp,
        "end_timestamp": candles[-1].timestamp + 900,
        "parameters": {"lookback": 4, "minimum_return": 0.00001, "ema_period": 5, "atr_period": 5, "stop_atr": 1, "target_rr": 1, "max_holding_bars": 1},
        "parameter_sets": [
            {"lookback": 4, "minimum_return": 0.00001, "ema_period": 5, "atr_period": 5, "stop_atr": 1, "target_rr": 1, "max_holding_bars": 1},
            {"lookback": 6, "minimum_return": 0.00002, "ema_period": 5, "atr_period": 5, "stop_atr": 1, "target_rr": 1.5, "max_holding_bars": 1},
        ],
        "search_method": "manual",
        "walk_forward": {"mode": "rolling", "train_days": 2, "validation_days": 1, "test_days": 1, "step_days": 1, "embargo_minutes": 15},
        "cost_model": {"preset": "realistic", "maker_fee_bps": 1, "taker_fee_bps": 1, "spread_bps": 1, "slippage_bps": 1, "latency_ms": 10, "partial_fill_probability": 0, "funding_bps_per_8h": 0, "entry_order_type": "market", "exit_order_type": "market"},
        "validation_policy": {"name": "test", "minimum_trades": 1, "minimum_profit_factor": 0, "minimum_positive_fold_ratio": 0, "maximum_drawdown_fraction": 1, "maximum_cost_to_gross_profit": 10, "maximum_sharpe_degradation": 10, "maximum_bootstrap_loss_probability": 1},
        "initial_capital": 100000,
        "maximum_leverage": 1,
        "position_sizing": "fixed_fractional_risk",
        "risk_fraction": 0.005,
        "random_seed": 42,
        "code_commit_hash": "test",
        "feature_version": "research-v1",
        "dataset_version": "1",
    }
    response = client.post("/api/research/experiments", json=payload)
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    experiment_id = response.json()["experiment"]["experiment_id"]
    for _ in range(100):
        job = client.get(f"/api/research/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.02)
    assert job["status"] == "completed", job
    detail = client.get(f"/api/research/experiments/{experiment_id}")
    assert detail.status_code == 200
    assert detail.json()["folds"]
    assert detail.json()["baselines"]
