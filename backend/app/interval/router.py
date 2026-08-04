from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.research.types import Candle, MarketType

from .bootstrap import bootstrap_confidence_interval
from .contracts import PolymarketPublicAdapter, compare_contracts
from .null_models import run_order_block_null_model
from .order_blocks import chronological_order_block_validation
from .presets import PRESETS, backtest_preset, current_preset_rows
from .service import IntervalService
from .storage import IntervalStorage
from .types import Horizon, NullModelRequest, OrderBlockConfig, SUPPORTED_ASSETS

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("RESEARCH_DATA_DIR", BACKEND_ROOT / "data"))
DATABASE_PATH = DATA_ROOT / "research_lab.sqlite3"
MIGRATION_PATH = BACKEND_ROOT / "migrations" / "002_crypto_interval_analyzer.sql"

storage = IntervalStorage(DATABASE_PATH, MIGRATION_PATH)
service = IntervalService(storage)
contract_adapter = PolymarketPublicAdapter()
router = APIRouter(tags=["crypto-interval-analyzer"])


class OrderBlockResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str = "BTCUSDT"
    market_type: MarketType = MarketType.SPOT
    candles: list[Candle] | None = None
    fetch_limit: int = Field(default=1000, ge=100, le=1000)
    config: OrderBlockConfig = Field(default_factory=OrderBlockConfig)
    entry_depth: float = Field(default=0.5, ge=0, le=1)
    null_models: list[NullModelRequest] = Field(default_factory=lambda: [
        NullModelRequest(model="random_timing", simulations=1000, seed=42),
        NullModelRequest(model="random_depth", simulations=1000, seed=43),
    ])
    bootstrap_simulations: int = Field(default=1000, ge=100, le=100_000)
    random_seed: int = 42


@router.get("/interval", include_in_schema=False)
def interval_page() -> FileResponse:
    path = REPOSITORY_ROOT / "interval.html"
    if not path.exists():
        raise HTTPException(404, "Crypto Interval Analyzer frontend is not installed")
    return FileResponse(path)


@router.get("/api/interval/assets")
def assets() -> list[dict[str, Any]]:
    return service.assets()


@router.get("/api/interval/live")
def live_interval(
    asset: str = Query(default="BTCUSDT"),
    market_type: MarketType = Query(default=MarketType.SPOT),
    horizon: Horizon = Query(default=Horizon.FIFTEEN_MINUTES),
    persist: bool = Query(default=True),
) -> dict[str, Any]:
    try:
        return service.live(asset, market_type, horizon, persist=persist).model_dump(mode="json")
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/api/interval/chart")
def chart(
    asset: str = Query(default="BTCUSDT"),
    market_type: MarketType = Query(default=MarketType.SPOT),
    limit: int = Query(default=500, ge=50, le=1000),
) -> dict[str, Any]:
    try:
        return service.chart(asset, market_type, limit)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/api/interval/contracts/current")
def current_contracts(
    asset: str = Query(default="BTCUSDT"),
    market_type: MarketType = Query(default=MarketType.SPOT),
    horizon: Horizon = Query(default=Horizon.FIFTEEN_MINUTES),
    manual_up: float | None = Query(default=None, gt=0, lt=1),
    manual_down: float | None = Query(default=None, gt=0, lt=1),
) -> dict[str, Any]:
    try:
        analysis = service.live(asset, market_type, horizon, persist=False)
        quote = contract_adapter.current_quote(
            asset=asset,
            horizon=horizon,
            start_timestamp=analysis.interval_start_timestamp,
            expiry_timestamp=analysis.expiry_timestamp,
        )
        return compare_contracts(analysis, quote, manual_up=manual_up, manual_down=manual_down)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/api/interval/presets")
def preset_signals(
    asset: str = Query(default="BTCUSDT"),
    market_type: MarketType = Query(default=MarketType.SPOT),
    horizon: Horizon = Query(default=Horizon.FIFTEEN_MINUTES),
    manual_up: float | None = Query(default=None, gt=0, lt=1),
    manual_down: float | None = Query(default=None, gt=0, lt=1),
) -> dict[str, Any]:
    try:
        analysis = service.live(asset, market_type, horizon, persist=False)
        quote = contract_adapter.current_quote(
            asset=asset,
            horizon=horizon,
            start_timestamp=analysis.interval_start_timestamp,
            expiry_timestamp=analysis.expiry_timestamp,
        )
        comparison = compare_contracts(analysis, quote, manual_up=manual_up, manual_down=manual_down)
        return {
            "asset": asset,
            "market_type": market_type.value,
            "horizon": horizon.value,
            "interval_start_timestamp": analysis.interval_start_timestamp,
            "expiry_timestamp": analysis.expiry_timestamp,
            "elapsed_seconds": max(0, analysis.generated_timestamp - analysis.interval_start_timestamp),
            "contract": comparison,
            "presets": current_preset_rows(analysis, comparison),
        }
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/api/interval/presets/{preset_id}/backtest")
def preset_backtest(
    preset_id: str,
    asset: str = Query(default="BTCUSDT"),
    market_type: MarketType = Query(default=MarketType.SPOT),
    horizon: Horizon = Query(default=Horizon.FIFTEEN_MINUTES),
    elapsed_seconds: int | None = Query(default=None, ge=60, le=3600),
    minimum_score: float | None = Query(default=None, ge=0, le=1),
    limit: int = Query(default=1000, ge=200, le=1000),
) -> dict[str, Any]:
    if preset_id not in {preset.preset_id for preset in PRESETS}:
        raise HTTPException(404, f"unknown preset {preset_id}")
    try:
        analysis = service.live(asset, market_type, horizon, persist=False)
        batch = service.adapter.candles(asset, market_type, limit=limit)
        if not batch.candles:
            raise RuntimeError("market data unavailable: " + "; ".join(batch.data_status.reasons))
        elapsed = elapsed_seconds
        if elapsed is None:
            elapsed = max(60, analysis.generated_timestamp - analysis.interval_start_timestamp)
        return backtest_preset(
            list(batch.candles),
            horizon=horizon,
            preset_id=preset_id,
            elapsed_seconds=elapsed,
            minimum_score=minimum_score,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/api/interval/predictions")
def prediction_history(
    asset: str | None = Query(default=None),
    horizon: Horizon | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return storage.list_predictions(asset=asset, horizon=horizon, limit=limit)


@router.get("/api/interval/outcomes")
def prediction_outcomes(
    asset: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    return storage.list_outcomes(asset=asset, limit=limit)


@router.get("/api/interval/data/status")
def data_status(
    asset: str = Query(default="BTCUSDT"),
    market_type: MarketType = Query(default=MarketType.SPOT),
) -> dict[str, Any]:
    try:
        analysis = service.live(asset, market_type, Horizon.FIFTEEN_MINUTES, persist=False)
        return analysis.data_status.model_dump(mode="json")
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/api/interval/order-blocks/research", status_code=201)
def order_block_research(request: OrderBlockResearchRequest) -> dict[str, Any]:
    if request.asset not in SUPPORTED_ASSETS:
        raise HTTPException(422, f"unsupported asset {request.asset}")
    if request.candles is None:
        batch = service.adapter.candles(request.asset, request.market_type, limit=request.fetch_limit)
        if not batch.candles:
            raise HTTPException(503, "; ".join(batch.data_status.reasons))
        candles = list(batch.candles)
    else:
        candles = list(request.candles)
    if len(candles) < max(100, request.config.lookback_structure + 20):
        raise HTTPException(422, "insufficient completed candles for order-block research")
    try:
        validation = chronological_order_block_validation(candles, request.config)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    zones = list(validation["test_zones"])
    trades = list(validation["test_trades"])
    metrics = dict(validation["test_metrics"])
    selected_depth = float(validation["selected_entry_depth"])
    experiment_id = str(uuid4())
    dataset_hash = hashlib.sha256(
        json.dumps([candle.model_dump(mode="json") for candle in candles], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    storage.store_order_block_experiment(
        experiment_id=experiment_id,
        asset=request.asset,
        market_type=request.market_type,
        definition=request.config.definition.value,
        configuration={
            "config": request.config.model_dump(mode="json"),
            "requested_entry_depth": request.entry_depth,
            "selected_entry_depth": selected_depth,
            "selection_partition": "validation",
            "partition_boundaries": validation["partition_boundaries"],
            "parameter_results": validation["parameter_results"],
            "bootstrap_simulations": request.bootstrap_simulations,
        },
        zones=[zone.model_dump(mode="json") for zone in zones],
        trades=[trade.model_dump(mode="json") for trade in trades],
        metrics=metrics,
        dataset_hash=dataset_hash,
        random_seed=request.random_seed,
    )
    null_results: list[dict[str, Any]] = []
    for null_request in request.null_models:
        result = run_order_block_null_model(
            candles[int(len(candles) * 0.80):], zones, request.config, null_request, observed_depth=selected_depth
        )
        payload = result.model_dump(mode="json")
        storage.store_null_result(
            result_id=str(uuid4()), experiment_id=experiment_id,
            model_name=null_request.model, seed=null_request.seed,
            simulations=null_request.simulations, result=payload,
        )
        null_results.append(payload)
    bootstraps: list[dict[str, Any]] = []
    for method in ("day", "block"):
        result = bootstrap_confidence_interval(
            trades, method=method, statistic="mean_r",
            simulations=request.bootstrap_simulations, seed=request.random_seed,
        )
        payload = result.model_dump(mode="json")
        storage.store_bootstrap(
            run_id=str(uuid4()), source_type="order_block_experiment",
            source_id=experiment_id, method=method, seed=request.random_seed,
            simulations=request.bootstrap_simulations, statistic="mean_r", result=payload,
        )
        bootstraps.append(payload)
    return {
        "experiment_id": experiment_id,
        "status": "completed",
        "result_label": "EXPERIMENTAL — NOT A VALIDATED EDGE",
        "dataset_hash": dataset_hash,
        "zones": len(zones),
        "trades": len(trades),
        "metrics": metrics,
        "chronological_validation": {
            "partition_boundaries": validation["partition_boundaries"],
            "parameter_results": validation["parameter_results"],
            "selected_entry_depth": selected_depth,
            "selection_partition": "validation",
            "test_status": validation["status"],
        },
        "null_models": null_results,
        "bootstrap": bootstraps,
        "configuration": request.model_dump(mode="json", exclude={"candles"}),
    }


@router.get("/api/interval/order-blocks/experiments/{experiment_id}")
def get_order_block_experiment(experiment_id: str) -> dict[str, Any]:
    try:
        return storage.order_block_experiment(experiment_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.websocket("/ws/interval")
async def interval_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        asset = websocket.query_params.get("asset", "BTCUSDT")
        market_type = MarketType(websocket.query_params.get("market_type", "spot"))
        horizon = Horizon(websocket.query_params.get("horizon", "15m"))
        refresh = max(3, min(60, int(websocket.query_params.get("refresh_seconds", "5"))))
        while True:
            try:
                analysis = await asyncio.to_thread(service.live, asset, market_type, horizon)
                await websocket.send_json(analysis.model_dump(mode="json"))
            except Exception as exc:
                await websocket.send_json({"error": str(exc), "status": "Data Stale"})
            await asyncio.sleep(refresh)
    except (WebSocketDisconnect, ValueError):
        return
