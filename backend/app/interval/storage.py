from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.research.types import MarketType

from .model import Calibration
from .types import Horizon, IntervalAnalysis, IntervalWindow, PredictionOutcome


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IntervalStorage:
    def __init__(self, database_path: Path, migration_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.migration_path = migration_path
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def migrate(self) -> None:
        sql = self.migration_path.read_text(encoding="utf-8")
        with self.connect() as connection:
            connection.executescript(sql)

    def get_or_create_reference(
        self,
        *,
        asset: str,
        exchange: str,
        market_type: MarketType,
        window: IntervalWindow,
    ) -> str:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT reference_id, reference_price FROM interval_references
                   WHERE asset=? AND exchange_name=? AND market_type=? AND horizon=?
                     AND interval_start_timestamp=?""",
                (asset, exchange, market_type.value, window.horizon.value, window.start_timestamp),
            ).fetchone()
            if row:
                if abs(float(row["reference_price"]) - window.reference_price) > max(1e-8, window.reference_price * 1e-10):
                    raise ValueError("immutable interval reference already exists with a different price")
                return str(row["reference_id"])
            reference_id = str(uuid4())
            connection.execute(
                """INSERT INTO interval_references(
                    reference_id, asset, exchange_name, market_type, horizon,
                    interval_start_timestamp, expiry_timestamp, reference_price,
                    reference_source, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    reference_id, asset, exchange, market_type.value, window.horizon.value,
                    window.start_timestamp, window.expiry_timestamp, window.reference_price,
                    window.reference_source, _now_iso(),
                ),
            )
            return reference_id

    def insert_prediction(self, reference_id: str, analysis: IntervalAnalysis) -> None:
        payload = analysis.model_dump(mode="json")
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT analysis_json FROM expiry_predictions WHERE prediction_id=?",
                (analysis.prediction_id,),
            ).fetchone()
            if existing:
                if json.loads(existing["analysis_json"]) != payload:
                    raise ValueError("historical prediction is immutable")
                return
            connection.execute(
                """INSERT INTO expiry_predictions(
                    prediction_id, reference_id, asset, exchange_name, market_type, horizon,
                    generated_timestamp, interval_start_timestamp, expiry_timestamp,
                    reference_price, current_price, probability_state, up_probability,
                    down_probability, raw_direction_score, expected_close,
                    expected_signed_return, expected_absolute_return, expected_low,
                    expected_high, reversion_score, continuation_score,
                    uncertainty_score, status, current_regime, data_quality_score,
                    model_version, feature_version, calibrated_model_id, analysis_json,
                    feature_snapshot_json, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    analysis.prediction_id, reference_id, analysis.asset, analysis.exchange,
                    analysis.market_type.value, analysis.horizon.value,
                    analysis.generated_timestamp, analysis.interval_start_timestamp,
                    analysis.expiry_timestamp, analysis.reference_price, analysis.current_price,
                    analysis.probability_state.value, analysis.up_probability,
                    analysis.down_probability, analysis.raw_direction_score,
                    analysis.expected_close, analysis.expected_signed_return,
                    analysis.expected_absolute_return, analysis.expected_low,
                    analysis.expected_high, analysis.reversion_score,
                    analysis.continuation_score, analysis.uncertainty_score,
                    analysis.status.value, analysis.current_regime,
                    analysis.data_status.score, analysis.model_version,
                    analysis.feature_version, analysis.calibrated_model_id,
                    json.dumps(payload, separators=(",", ":"), sort_keys=True),
                    json.dumps(analysis.feature_snapshot, separators=(",", ":"), sort_keys=True),
                    _now_iso(),
                ),
            )

    def insert_outcome(self, outcome: PredictionOutcome) -> None:
        payload = outcome.model_dump(mode="json")
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT outcome_json FROM prediction_outcomes WHERE prediction_id=?",
                (outcome.prediction_id,),
            ).fetchone()
            if existing:
                if json.loads(existing["outcome_json"]) != payload:
                    raise ValueError("prediction outcome is immutable")
                return
            connection.execute(
                """INSERT INTO prediction_outcomes(
                    prediction_id, resolved_timestamp, expiry_price,
                    finished_above_reference, signed_return, correct,
                    outcome_json, created_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    outcome.prediction_id, outcome.resolved_timestamp,
                    outcome.expiry_price, int(outcome.finished_above_reference),
                    outcome.signed_return,
                    None if outcome.correct is None else int(outcome.correct),
                    json.dumps(payload, separators=(",", ":"), sort_keys=True),
                    _now_iso(),
                ),
            )

    def list_predictions(
        self,
        *,
        asset: str | None = None,
        horizon: Horizon | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if asset:
            clauses.append("asset=?")
            values.append(asset)
        if horizon:
            clauses.append("horizon=?")
            values.append(horizon.value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT analysis_json FROM expiry_predictions{where} ORDER BY generated_timestamp DESC LIMIT ?",
                values,
            ).fetchall()
        return [json.loads(row["analysis_json"]) for row in rows]

    def unresolved_predictions(self, now_timestamp: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT p.* FROM expiry_predictions p
                   LEFT JOIN prediction_outcomes o ON o.prediction_id=p.prediction_id
                   WHERE o.prediction_id IS NULL AND p.expiry_timestamp<=?
                   ORDER BY p.expiry_timestamp""",
                (now_timestamp,),
            ).fetchall()
        return [dict(row) for row in rows]

    def active_calibration(
        self, asset: str, market_type: MarketType, horizon: Horizon
    ) -> Calibration | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT * FROM interval_calibration_models
                   WHERE asset=? AND market_type=? AND horizon=? AND active=1
                   ORDER BY validation_end_timestamp DESC LIMIT 1""",
                (asset, market_type.value, horizon.value),
            ).fetchone()
        if not row:
            return None
        return Calibration(
            model_id=str(row["model_id"]),
            sample_count=int(row["sample_count"]),
            intercept=float(row["intercept"]),
            coefficient=float(row["coefficient"]),
            brier_skill=float(row["brier_skill"]),
            validation_end_timestamp=int(row["validation_end_timestamp"]),
        )

    def data_quality_event(
        self, *, asset: str, exchange: str, market_type: MarketType, timestamp: int,
        status: str, score: float, details: dict[str, Any]
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO interval_data_quality_events(
                    event_id, asset, exchange_name, market_type, timestamp,
                    status, score, details_json, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()), asset, exchange, market_type.value, timestamp,
                    status, score, json.dumps(details, separators=(",", ":"), sort_keys=True), _now_iso(),
                ),
            )

    def store_order_block_experiment(
        self, *, experiment_id: str, asset: str, market_type: MarketType,
        definition: str, configuration: dict[str, Any], zones: list[dict[str, Any]],
        trades: list[dict[str, Any]], metrics: dict[str, Any], dataset_hash: str,
        random_seed: int, dataset_id: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO order_block_experiments(
                    order_block_experiment_id, dataset_id, asset, market_type,
                    definition, configuration_json, zones_json, trades_json,
                    metrics_json, dataset_hash, random_seed, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    experiment_id, dataset_id, asset, market_type.value, definition,
                    json.dumps(configuration, separators=(",", ":"), sort_keys=True),
                    json.dumps(zones, separators=(",", ":"), sort_keys=True),
                    json.dumps(trades, separators=(",", ":"), sort_keys=True),
                    json.dumps(metrics, separators=(",", ":"), sort_keys=True),
                    dataset_hash, random_seed, _now_iso(),
                ),
            )

    def store_null_result(
        self, *, result_id: str, experiment_id: str, model_name: str,
        seed: int, simulations: int, result: dict[str, Any],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO interval_null_model_results(
                    null_result_id, order_block_experiment_id, model_name, seed,
                    simulations, result_json, created_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (result_id, experiment_id, model_name, seed, simulations,
                 json.dumps(result, separators=(",", ":"), sort_keys=True), _now_iso()),
            )

    def store_bootstrap(
        self, *, run_id: str, source_type: str, source_id: str, method: str,
        seed: int, simulations: int, statistic: str, result: dict[str, Any],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO interval_bootstrap_runs(
                    bootstrap_run_id, source_type, source_id, method, seed,
                    simulations, statistic, result_json, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (run_id, source_type, source_id, method, seed, simulations, statistic,
                 json.dumps(result, separators=(",", ":"), sort_keys=True), _now_iso()),
            )

    def order_block_experiment(self, experiment_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM order_block_experiments WHERE order_block_experiment_id=?",
                (experiment_id,),
            ).fetchone()
            if not row:
                raise KeyError(experiment_id)
            nulls = connection.execute(
                "SELECT result_json FROM interval_null_model_results WHERE order_block_experiment_id=?",
                (experiment_id,),
            ).fetchall()
        result = dict(row)
        for key in ("configuration_json", "zones_json", "trades_json", "metrics_json"):
            result[key.removesuffix("_json")] = json.loads(result.pop(key))
        result["null_models"] = [json.loads(item["result_json"]) for item in nulls]
        return result

    def list_outcomes(self, *, asset: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        clauses = []
        values: list[Any] = []
        if asset:
            clauses.append("p.asset=?")
            values.append(asset)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""SELECT o.outcome_json FROM prediction_outcomes o
                        JOIN expiry_predictions p ON p.prediction_id=o.prediction_id
                        {where} ORDER BY o.resolved_timestamp DESC LIMIT ?""",
                values,
            ).fetchall()
        return [json.loads(row["outcome_json"]) for row in rows]
