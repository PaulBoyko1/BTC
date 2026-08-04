from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Callable

from .engine import ExperimentCancelled, ExperimentEngine
from .storage import ResearchStorage
from .types import DatasetImport, ExperimentCreate, ExperimentStatus


class ResearchJobManager:
    """Bounded in-process worker pool with persistent job state.

    The interface is deliberately queue-agnostic so production deployments can
    replace this implementation with Celery, RQ or Dramatiq without changing
    experiment APIs or storage semantics.
    """

    def __init__(self, storage: ResearchStorage, engine: ExperimentEngine, max_workers: int = 2) -> None:
        self.storage = storage
        self.engine = engine
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="research-lab")
        self.futures: dict[str, Future[None]] = {}
        self.lock = Lock()

    def submit(self, experiment_id: str, config: ExperimentCreate, dataset: DatasetImport) -> str:
        job = self.storage.create_job(experiment_id)
        future = self.executor.submit(self._run, job.id, experiment_id, config, dataset)
        with self.lock:
            self.futures[job.id] = future
        return job.id

    def cancel(self, job_id: str) -> None:
        self.storage.request_cancellation(job_id)
        with self.lock:
            future = self.futures.get(job_id)
        if future and future.cancel():
            self.storage.update_job(job_id, "cancelled", 1.0, "Cancelled before execution")

    def _run(self, job_id: str, experiment_id: str, config: ExperimentCreate, dataset: DatasetImport) -> None:
        self.storage.mark_running(experiment_id)
        self.storage.update_job(job_id, "running", 0.01, "Validating experiment")

        def progress(value: float, message: str) -> None:
            self.storage.update_job(job_id, "running", min(0.99, max(0.0, value)), message)

        def cancelled() -> bool:
            return self.storage.cancellation_requested(job_id)

        try:
            result = self.engine.run(config, dataset, progress=progress, cancelled=cancelled)
            if cancelled():
                raise ExperimentCancelled("Cancellation requested")
            self.storage.save_results(experiment_id, result)
            self.storage.update_job(job_id, "completed", 1.0, "Experiment completed")
        except ExperimentCancelled as exc:
            self.storage.mark_failed(experiment_id, ExperimentStatus.CANCELLED, str(exc))
            self.storage.update_job(job_id, "cancelled", 1.0, str(exc))
        except ValueError as exc:
            message = str(exc)
            status = (
                ExperimentStatus.FAILED_DATA_INTEGRITY
                if message.startswith("FAILED — DATA INTEGRITY")
                else ExperimentStatus.FAILED
            )
            self.storage.mark_failed(experiment_id, status, message)
            self.storage.update_job(job_id, "failed", 1.0, message, error=message)
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            message = f"Worker failure: {type(exc).__name__}: {exc}"
            self.storage.mark_failed(experiment_id, ExperimentStatus.FAILED, message)
            self.storage.update_job(job_id, "failed", 1.0, message, error=message)
