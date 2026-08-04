from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .research.engine import ExperimentEngine
from .research.jobs import ResearchJobManager
from .research.registry import build_default_registry
from .research.storage import ResearchStorage
from .research.types import DatasetImport, ExperimentCreate

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("RESEARCH_DATA_DIR", BACKEND_ROOT / "data"))
DATABASE_PATH = DATA_ROOT / "research_lab.sqlite3"
MIGRATION_PATH = BACKEND_ROOT / "migrations" / "001_research_lab.sql"

registry = build_default_registry()
storage = ResearchStorage(DATABASE_PATH, MIGRATION_PATH)
storage.sync_strategies(registry.definitions())
engine = ExperimentEngine(registry)
jobs = ResearchJobManager(storage, engine, max_workers=int(os.environ.get("RESEARCH_WORKERS", "2")))

app = FastAPI(
    title="Crypto Pulse Strategy Research and Validation Lab",
    version="1.0.0",
    description="Chronological, cost-aware, out-of-sample cryptocurrency strategy research.",
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "component": "strategy-research-validation-lab",
        "database": str(DATABASE_PATH),
        "completed_experiments": storage.overview()["completed_experiments"],
    }


@app.get("/research", include_in_schema=False)
def research_page() -> FileResponse:
    path = REPOSITORY_ROOT / "research.html"
    if not path.exists():
        raise HTTPException(404, "Research dashboard is not installed")
    return FileResponse(path)


@app.get("/api/research/strategies")
def list_strategies() -> list[dict[str, Any]]:
    return [definition.model_dump(mode="json") for definition in registry.definitions()]


@app.get("/api/research/datasets")
def list_datasets() -> list[dict[str, Any]]:
    return storage.list_datasets()


@app.post("/api/research/datasets", status_code=201)
def import_dataset(dataset: DatasetImport) -> dict[str, Any]:
    return storage.create_dataset(dataset)


@app.get("/api/research/overview")
def overview() -> dict[str, Any]:
    return storage.overview()


@app.get("/api/research/funnel")
def validation_funnel() -> list[dict[str, Any]]:
    return storage.validation_funnel()


@app.get("/api/research/experiments")
def list_experiments(limit: int = Query(default=100, ge=1, le=1000)) -> list[dict[str, Any]]:
    return storage.list_experiments(limit)


@app.post("/api/research/experiments", status_code=202)
def create_experiment(config: ExperimentCreate) -> dict[str, Any]:
    try:
        dataset_row = storage.get_dataset(config.dataset_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    mismatches: list[str] = []
    for key, requested, actual in (
        ("asset", config.asset, dataset_row["asset"]),
        ("exchange", config.exchange, dataset_row["exchange_name"]),
        ("market_type", config.market_type, dataset_row["market_type"]),
        ("source_timeframe_minutes", config.source_timeframe_minutes, dataset_row["source_timeframe_minutes"]),
    ):
        if str(requested) != str(actual):
            mismatches.append(f"{key}: requested {requested}, dataset has {actual}")
    if config.start_timestamp < dataset_row["start_timestamp"] or config.end_timestamp > dataset_row["end_timestamp"] + config.source_timeframe_minutes * 60:
        mismatches.append("requested date range is outside the dataset")
    if mismatches:
        raise HTTPException(422, "; ".join(mismatches))
    try:
        registry.validate_compatibility(
            config.strategy_id,
            config.strategy_version,
            config.asset,
            config.market_type,
            config.source_timeframe_minutes,
            config.prediction_horizon_minutes,
        )
        registry.get(config.strategy_id, config.strategy_version).validate_parameters(config.parameters)
        for parameters in config.parameter_sets:
            registry.get(config.strategy_id, config.strategy_version).validate_parameters(parameters)
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc

    experiment = storage.create_experiment(config)
    candles = storage.load_candles(config.dataset_id)
    dataset = DatasetImport(
        name=dataset_row["name"],
        asset=dataset_row["asset"],
        exchange=dataset_row["exchange_name"],
        market_type=dataset_row["market_type"],
        source_timeframe_minutes=dataset_row["source_timeframe_minutes"],
        candles=candles,
        feature_version=dataset_row["feature_version"],
        adapter_version=dataset_row["adapter_version"],
    )
    job_id = jobs.submit(experiment["experiment_id"], config, dataset)
    return {"experiment": experiment, "job_id": job_id}


@app.get("/api/research/experiments/{experiment_id}")
def get_experiment(experiment_id: str) -> dict[str, Any]:
    try:
        return storage.get_experiment(experiment_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/research/experiments/{experiment_id}/rerun", status_code=202)
def rerun_experiment(experiment_id: str) -> dict[str, Any]:
    try:
        original = storage.get_experiment(experiment_id)
        config = ExperimentCreate.model_validate(original["configuration"])
        dataset_row = storage.get_dataset(config.dataset_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    rerun = storage.create_experiment(config, parent_experiment_id=experiment_id)
    dataset = DatasetImport(
        name=dataset_row["name"],
        asset=dataset_row["asset"],
        exchange=dataset_row["exchange_name"],
        market_type=dataset_row["market_type"],
        source_timeframe_minutes=dataset_row["source_timeframe_minutes"],
        candles=storage.load_candles(config.dataset_id),
        feature_version=dataset_row["feature_version"],
        adapter_version=dataset_row["adapter_version"],
    )
    job_id = jobs.submit(rerun["experiment_id"], config, dataset)
    return {"experiment": rerun, "job_id": job_id, "compares_to": experiment_id}


@app.get("/api/research/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    try:
        return storage.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/research/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: str) -> dict[str, str]:
    try:
        storage.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    jobs.cancel(job_id)
    return {"status": "cancellation_requested"}


@app.get("/api/research/experiments/{experiment_id}/export/config.json")
def export_config(experiment_id: str) -> JSONResponse:
    try:
        experiment = storage.get_experiment(experiment_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return JSONResponse(
        content={
            "experiment_id": experiment_id,
            "configuration": experiment["configuration"],
            "configuration_hash": experiment["configuration_hash"],
            "environment": experiment["environment"],
        },
        headers={"Content-Disposition": f'attachment; filename="{experiment_id}-config.json"'},
    )


@app.get("/api/research/experiments/{experiment_id}/export/metrics.json")
def export_metrics(experiment_id: str) -> JSONResponse:
    try:
        experiment = storage.get_experiment(experiment_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return JSONResponse(
        content={
            "experiment_id": experiment_id,
            "status": experiment["status"],
            "strategy_status": experiment["strategy_status"],
            "metrics": experiment["metrics"],
            "baselines": experiment["baselines"],
            "bootstrap": experiment["bootstrap"],
            "multiple_testing": experiment["multiple_testing"],
        },
        headers={"Content-Disposition": f'attachment; filename="{experiment_id}-metrics.json"'},
    )


@app.get("/api/research/experiments/{experiment_id}/export/trades.csv")
def export_trades(experiment_id: str) -> StreamingResponse:
    try:
        storage.get_experiment(experiment_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    with storage.connect() as connection:
        rows = connection.execute(
            "SELECT trade_json FROM trades WHERE experiment_id=? ORDER BY entry_timestamp",
            (experiment_id,),
        ).fetchall()
    buffer = io.StringIO()
    writer: csv.DictWriter[str] | None = None
    for row in rows:
        import json

        trade = json.loads(row["trade_json"])
        trade.pop("feature_snapshot", None)
        if writer is None:
            writer = csv.DictWriter(buffer, fieldnames=list(trade))
            writer.writeheader()
        writer.writerow(trade)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{experiment_id}-trades.csv"'},
    )


# Serve the existing static analyzer and the Research Lab assets after API routes.
if REPOSITORY_ROOT.exists():
    app.mount("/", StaticFiles(directory=REPOSITORY_ROOT, html=True), name="static")
