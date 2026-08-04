from __future__ import annotations

import hashlib
import json
import os
import platform
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .data import dataset_hash, validate_dataset
from .types import (
    DatasetImport,
    ExperimentCreate,
    ExperimentStatus,
    JobView,
    StrategyStatus,
    new_id,
    utc_now_iso,
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class ResearchStorage:
    def __init__(self, database_path: str | Path, migration_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.migration_path = Path(migration_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        sql = self.migration_path.read_text(encoding="utf-8")
        with self.connect() as connection:
            connection.executescript(sql)

    def sync_strategies(self, definitions: list[Any]) -> None:
        now = utc_now_iso()
        with self.connect() as connection:
            for definition in definitions:
                payload = definition.model_dump(mode="json")
                connection.execute(
                    """
                    INSERT INTO strategies(strategy_id, family, name, description, enabled, created_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(strategy_id) DO UPDATE SET
                      family=excluded.family, name=excluded.name,
                      description=excluded.description, enabled=excluded.enabled
                    """,
                    (
                        definition.strategy_id,
                        definition.family,
                        definition.name,
                        definition.description,
                        int(definition.enabled),
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO strategy_versions(
                      strategy_id, version, definition_json, definition_hash, status, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(strategy_id, version) DO UPDATE SET
                      definition_json=excluded.definition_json,
                      definition_hash=excluded.definition_hash
                    """,
                    (
                        definition.strategy_id,
                        definition.strategy_version,
                        canonical_json(payload),
                        hash_json(payload),
                        StrategyStatus.EXPERIMENTAL,
                        now,
                    ),
                )

    def create_dataset(self, dataset: DatasetImport, required_features: tuple[str, ...] = ()) -> dict[str, Any]:
        integrity = validate_dataset(dataset, required_features)
        digest = dataset_hash(dataset)
        now = utc_now_iso()
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM datasets WHERE dataset_hash = ?", (digest,)
            ).fetchone()
            if existing:
                return self._dataset_row(existing)
            dataset_id = new_id("dataset")
            timestamps = [c.timestamp for c in dataset.candles]
            connection.execute(
                """
                INSERT INTO datasets(
                  dataset_id, name, asset, exchange_name, market_type,
                  source_timeframe_minutes, start_timestamp, end_timestamp,
                  observation_count, dataset_hash, feature_version,
                  adapter_version, integrity_status, integrity_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    dataset.name,
                    dataset.asset,
                    dataset.exchange,
                    dataset.market_type,
                    dataset.source_timeframe_minutes,
                    min(timestamps),
                    max(timestamps),
                    len(timestamps),
                    digest,
                    dataset.feature_version,
                    dataset.adapter_version,
                    "passed" if integrity.passed else "failed",
                    canonical_json(integrity.__dict__),
                    now,
                ),
            )
            connection.executemany(
                "INSERT INTO dataset_candles(dataset_id, timestamp, candle_json) VALUES(?, ?, ?)",
                [
                    (dataset_id, candle.timestamp, canonical_json(candle.model_dump(mode="json")))
                    for candle in dataset.candles
                ],
            )
            if not integrity.passed:
                for reason in integrity.reasons:
                    connection.execute(
                        """
                        INSERT INTO data_quality_events(
                          data_quality_event_id, dataset_id, experiment_id, severity,
                          event_type, reason, details_json, created_at
                        ) VALUES(?, ?, NULL, 'error', 'dataset_integrity', ?, '{}', ?)
                        """,
                        (new_id("dq"), dataset_id, reason, now),
                    )
            row = connection.execute("SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,)).fetchone()
            assert row is not None
            return self._dataset_row(row)

    def list_datasets(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM datasets ORDER BY created_at DESC").fetchall()
        return [self._dataset_row(row) for row in rows]

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown dataset {dataset_id}")
        return self._dataset_row(row)

    def load_candles(self, dataset_id: str) -> list[Any]:
        from .types import Candle

        with self.connect() as connection:
            rows = connection.execute(
                "SELECT candle_json FROM dataset_candles WHERE dataset_id = ? ORDER BY timestamp",
                (dataset_id,),
            ).fetchall()
        return [Candle.model_validate(json.loads(row["candle_json"])) for row in rows]

    def create_experiment(self, config: ExperimentCreate, parent_experiment_id: str | None = None) -> dict[str, Any]:
        experiment_id = new_id("experiment")
        payload = config.model_dump(mode="json")
        now = utc_now_iso()
        environment = {
            "python": sys.version,
            "platform": platform.platform(),
            "implementation": platform.python_implementation(),
        }
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO experiments(
                  experiment_id, parent_experiment_id, strategy_id, strategy_version,
                  dataset_id, asset, exchange_name, market_type,
                  source_timeframe_minutes, prediction_horizon_minutes,
                  start_timestamp, end_timestamp, configuration_json,
                  configuration_hash, status, strategy_status, failure_reason,
                  code_commit_hash, feature_version, dataset_version, random_seed,
                  environment_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    parent_experiment_id,
                    config.strategy_id,
                    config.strategy_version,
                    config.dataset_id,
                    config.asset,
                    config.exchange,
                    config.market_type,
                    config.source_timeframe_minutes,
                    config.prediction_horizon_minutes,
                    config.start_timestamp,
                    config.end_timestamp,
                    canonical_json(payload),
                    hash_json(payload),
                    ExperimentStatus.QUEUED,
                    StrategyStatus.EXPERIMENTAL,
                    config.code_commit_hash,
                    config.feature_version,
                    config.dataset_version,
                    config.random_seed,
                    canonical_json(environment),
                    now,
                ),
            )
            parameter_sets = config.parameter_sets or [config.parameters]
            for index, parameters in enumerate(parameter_sets):
                connection.execute(
                    "INSERT INTO experiment_parameters VALUES(?, ?, ?, 0)",
                    (experiment_id, index, canonical_json(parameters)),
                )
            self._insert_status_change(
                connection,
                experiment_id,
                None,
                StrategyStatus.EXPERIMENTAL,
                "system",
                "Experiment created",
                {"configuration_hash": hash_json(payload)},
                False,
            )
        return self.get_experiment(experiment_id)

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown experiment {experiment_id}")
            metrics = {
                metric["metric_scope"]: json.loads(metric["metrics_json"])
                for metric in connection.execute(
                    "SELECT metric_scope, metrics_json FROM experiment_metrics WHERE experiment_id = ?",
                    (experiment_id,),
                ).fetchall()
            }
            folds = []
            for item in connection.execute(
                "SELECT * FROM walk_forward_folds WHERE experiment_id = ? ORDER BY fold_index",
                (experiment_id,),
            ).fetchall():
                fold = {
                    **dict(item),
                    "selected_parameters": json.loads(item["selected_parameters_json"]),
                    "data_quality": json.loads(item["data_quality_json"]),
                }
                fold_metrics = {
                    metric["partition_name"]: json.loads(metric["metrics_json"])
                    for metric in connection.execute(
                        "SELECT partition_name, metrics_json FROM fold_metrics WHERE experiment_id=? AND fold_index=?",
                        (experiment_id, item["fold_index"]),
                    ).fetchall()
                }
                fold["train_metrics"] = fold_metrics.get("train", {})
                fold["validation_metrics"] = fold_metrics.get("validation", {})
                fold["test_metrics"] = fold_metrics.get("test", {})
                folds.append(fold)
            baselines = {
                item["baseline_id"]: json.loads(item["metrics_json"])
                for item in connection.execute(
                    "SELECT * FROM baseline_results WHERE experiment_id = ?",
                    (experiment_id,),
                ).fetchall()
            }
            ablations = {
                item["ablation_id"]: {
                    "definition": json.loads(item["definition_json"]),
                    "metrics": json.loads(item["metrics_json"]) if item["metrics_json"] else None,
                }
                for item in connection.execute(
                    "SELECT * FROM ablation_results WHERE experiment_id = ?",
                    (experiment_id,),
                ).fetchall()
            }
            bootstrap = [
                {
                    "run_id": item["bootstrap_run_id"],
                    "method": item["method"],
                    "statistics": json.loads(item["statistics_json"]),
                }
                for item in connection.execute(
                    """
                    SELECT br.bootstrap_run_id, br.method, bs.statistics_json
                    FROM bootstrap_runs br JOIN bootstrap_statistics bs USING(bootstrap_run_id)
                    WHERE br.experiment_id = ?
                    """,
                    (experiment_id,),
                ).fetchall()
            ]
            multiple = connection.execute(
                "SELECT results_json FROM multiple_testing_results WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        result = self._experiment_row(row)
        result.update({
            "metrics": metrics,
            "folds": folds,
            "baselines": baselines,
            "ablations": ablations,
            "bootstrap": bootstrap,
            "multiple_testing": json.loads(multiple["results_json"]) if multiple else None,
        })
        return result

    def list_experiments(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM experiments ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._experiment_row(row) for row in rows]

    def mark_running(self, experiment_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE experiments SET status = ?, started_at = ? WHERE experiment_id = ?",
                (ExperimentStatus.RUNNING, utc_now_iso(), experiment_id),
            )

    def mark_failed(self, experiment_id: str, status: ExperimentStatus, reason: str) -> None:
        strategy_status = (
            StrategyStatus.DATA_INTEGRITY_FAILED
            if status == ExperimentStatus.FAILED_DATA_INTEGRITY
            else StrategyStatus.VALIDATION_FAILED
        )
        now = utc_now_iso()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT strategy_status FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            prior = row["strategy_status"] if row else None
            connection.execute(
                """
                UPDATE experiments SET status = ?, strategy_status = ?, failure_reason = ?, completed_at = ?
                WHERE experiment_id = ?
                """,
                (status, strategy_status, reason, now, experiment_id),
            )
            self._insert_status_change(connection, experiment_id, prior, strategy_status, "system", reason, {}, False)

    def save_results(self, experiment_id: str, result: dict[str, Any]) -> None:
        now = utc_now_iso()
        strategy_status = result["strategy_status"]
        with self.connect() as connection:
            prior_row = connection.execute(
                "SELECT strategy_status FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            prior_status = prior_row["strategy_status"] if prior_row else None
            for scope, metrics in result["metrics"].items():
                connection.execute(
                    "INSERT OR REPLACE INTO experiment_metrics VALUES(?, ?, ?)",
                    (experiment_id, scope, canonical_json(metrics)),
                )
            for fold in result["folds"]:
                definition = fold["definition"]
                connection.execute(
                    """
                    INSERT OR REPLACE INTO walk_forward_folds VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        experiment_id,
                        definition["fold_index"],
                        definition["train_start"],
                        definition["train_end"],
                        definition["validation_start"],
                        definition["validation_end"],
                        definition["test_start"],
                        definition["test_end"],
                        canonical_json(fold["selected_parameters"]),
                        definition["purged_observations"],
                        definition["embargoed_observations"],
                        canonical_json(fold.get("data_quality", {})),
                    ),
                )
                for partition in ("train", "validation", "test"):
                    connection.execute(
                        "INSERT OR REPLACE INTO fold_metrics VALUES(?, ?, ?, ?)",
                        (
                            experiment_id,
                            definition["fold_index"],
                            partition,
                            canonical_json(fold[f"{partition}_metrics"]),
                        ),
                    )
                for parameter_result in fold.get("parameter_results", []):
                    connection.execute(
                        "INSERT OR REPLACE INTO parameter_results VALUES(?, ?, ?, ?, ?, ?)",
                        (
                            experiment_id,
                            definition["fold_index"],
                            parameter_result["parameter_set_index"],
                            parameter_result["partition"],
                            canonical_json(parameter_result["parameters"]),
                            canonical_json(parameter_result["metrics"]),
                        ),
                    )
                for partition, trades in fold.get("trades", {}).items():
                    for trade in trades:
                        connection.execute(
                            "INSERT OR REPLACE INTO trades VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                new_id("trade"),
                                experiment_id,
                                definition["fold_index"],
                                partition,
                                trade["signal_timestamp"],
                                trade["entry_timestamp"],
                                trade["exit_timestamp"],
                                trade["side"],
                                trade["net_pnl"],
                                trade["net_return"],
                                canonical_json(trade),
                            ),
                        )
            for baseline_id, metrics in result["baselines"].items():
                connection.execute(
                    "INSERT OR REPLACE INTO baseline_results VALUES(?, ?, ?)",
                    (experiment_id, baseline_id, canonical_json(metrics)),
                )
            for ablation_id, ablation in result.get("ablations", {}).items():
                definition = {
                    "status": ablation.get("status"),
                    "definition": ablation.get("definition"),
                    "reason": ablation.get("reason"),
                }
                metrics_payload = ablation.get("metrics")
                connection.execute(
                    "INSERT OR REPLACE INTO ablation_results VALUES(?, ?, ?, ?)",
                    (
                        experiment_id,
                        ablation_id,
                        canonical_json(definition),
                        canonical_json(metrics_payload) if metrics_payload is not None else "null",
                    ),
                )
            for bootstrap in result["bootstrap"]:
                run_id = new_id("bootstrap")
                connection.execute(
                    "INSERT INTO bootstrap_runs VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        experiment_id,
                        bootstrap["method"],
                        bootstrap["seed"],
                        bootstrap["simulations"],
                        canonical_json(bootstrap.get("configuration", {})),
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO bootstrap_statistics VALUES(?, ?)",
                    (run_id, canonical_json(bootstrap["statistics"])),
                )
            connection.execute(
                "INSERT OR REPLACE INTO multiple_testing_results VALUES(?, ?, ?)",
                (experiment_id, result["multiple_testing"]["total_trials"], canonical_json(result["multiple_testing"])),
            )
            connection.execute(
                """
                INSERT INTO parameter_searches VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("search"),
                    experiment_id,
                    result["parameter_search"]["method"],
                    result["parameter_search"]["total_configurations"],
                    canonical_json(result["parameter_search"]["search_space"]),
                    canonical_json(result["parameter_search"]["result"]),
                ),
            )
            connection.execute(
                """
                UPDATE experiments SET status = ?, strategy_status = ?, failure_reason = NULL, completed_at = ?
                WHERE experiment_id = ?
                """,
                (ExperimentStatus.COMPLETED, strategy_status, now, experiment_id),
            )
            self._insert_status_change(
                connection,
                experiment_id,
                prior_status,
                strategy_status,
                "system",
                result["validation"]["reason"],
                result["validation"],
                False,
            )

    def overview(self) -> dict[str, Any]:
        with self.connect() as connection:
            total_strategies = connection.execute("SELECT COUNT(*) FROM strategies").fetchone()[0]
            total_experiments = connection.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
            active = connection.execute(
                "SELECT COUNT(*) FROM experiments WHERE status IN ('queued', 'running')"
            ).fetchone()[0]
            counts = {
                row["strategy_status"]: row["count"]
                for row in connection.execute(
                    "SELECT strategy_status, COUNT(*) count FROM experiments GROUP BY strategy_status"
                ).fetchall()
            }
            configs = connection.execute("SELECT COUNT(*) FROM experiment_parameters").fetchone()[0]
            completed = connection.execute(
                "SELECT COUNT(*) FROM experiments WHERE status = 'completed'"
            ).fetchone()[0]
        return {
            "total_strategies": total_strategies,
            "total_configurations_tested": configs,
            "total_experiments": total_experiments,
            "active_experiments": active,
            "completed_experiments": completed,
            "strategy_status_counts": counts,
        }

    def validation_funnel(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            completed = connection.execute(
                "SELECT COUNT(*) FROM experiments WHERE status = 'completed'"
            ).fetchone()[0]
            total = connection.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
            integrity = connection.execute(
                "SELECT COUNT(*) FROM experiments WHERE status != 'failed_data_integrity'"
            ).fetchone()[0]
            positive_after_costs = connection.execute(
                """
                SELECT COUNT(DISTINCT experiment_id) FROM experiment_metrics
                WHERE metric_scope='out_of_sample' AND json_extract(metrics_json, '$.expectancy') > 0
                """
            ).fetchone()[0]
            walk_forward = connection.execute(
                """
                SELECT COUNT(DISTINCT experiment_id) FROM experiment_metrics
                WHERE metric_scope='stability' AND json_extract(metrics_json, '$.positive_fold_ratio') >= 0.5
                """
            ).fetchone()[0]
            robustness = connection.execute(
                """
                SELECT COUNT(DISTINCT experiment_id) FROM experiment_metrics
                WHERE metric_scope='robustness' AND json_extract(metrics_json, '$.parameter_stability.classification')='robust_plateau'
                """
            ).fetchone()[0]
        return [
            {"stage": "Configurations created", "count": total},
            {"stage": "Data integrity passed", "count": integrity},
            {"stage": "Completed experiments", "count": completed},
            {"stage": "Positive expectancy after costs", "count": positive_after_costs},
            {"stage": "Walk-forward stability passed", "count": walk_forward},
            {"stage": "Parameter robustness passed", "count": robustness},
            {"stage": "Forward paper trading passed", "count": 0},
        ]

    def create_job(self, experiment_id: str) -> JobView:
        job = JobView(
            id=new_id("job"),
            experiment_id=experiment_id,
            status="queued",
            progress=0.0,
            message="Queued",
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO research_jobs VALUES(?, ?, ?, ?, ?, 0, NULL, ?, ?)",
                (job.id, job.experiment_id, job.status, job.progress, job.message, job.created_at, job.updated_at),
            )
        return job

    def update_job(self, job_id: str, status: str, progress: float, message: str, error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE research_jobs SET status=?, progress=?, message=?, error=?, updated_at=? WHERE job_id=?",
                (status, progress, message, error, utc_now_iso(), job_id),
            )

    def request_cancellation(self, job_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE research_jobs SET cancellation_requested=1, updated_at=? WHERE job_id=?",
                (utc_now_iso(), job_id),
            )

    def cancellation_requested(self, job_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT cancellation_requested FROM research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return bool(row and row[0])

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM research_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown job {job_id}")
        return dict(row)

    def _insert_status_change(
        self,
        connection: sqlite3.Connection,
        experiment_id: str,
        prior_status: str | None,
        new_status: str,
        user_name: str,
        reason: str,
        evidence: dict[str, Any],
        policy_override: bool,
    ) -> None:
        connection.execute(
            "INSERT INTO validation_status_changes VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("status"),
                experiment_id,
                prior_status,
                new_status,
                user_name,
                reason,
                canonical_json(evidence),
                int(policy_override),
                utc_now_iso(),
            ),
        )

    @staticmethod
    def _dataset_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["integrity"] = json.loads(result.pop("integrity_json"))
        return result

    @staticmethod
    def _experiment_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["configuration"] = json.loads(result.pop("configuration_json"))
        result["environment"] = json.loads(result.pop("environment_json"))
        return result
