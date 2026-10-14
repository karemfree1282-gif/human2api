"""Scheduled Workflow Manager supporting recurring intervals and cron-style definitions with pause/resume/cancel."""

from __future__ import annotations

import json
import pathlib
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ScheduledJob:
    job_id: str
    workflow_path: str
    workflow_name: str
    interval_seconds: int
    inputs: Dict[str, Any]
    enabled: bool = True
    allow_write: bool = True
    last_run_at: Optional[float] = None
    next_run_at: float = 0.0
    last_status: Optional[str] = None
    run_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WorkflowScheduler:
    """Manages persistent scheduled tasks and dispatches due runs safely."""

    def __init__(
        self,
        schedule_file: pathlib.Path,
        executor: Optional[Callable[[ScheduledJob], str]] = None,
    ) -> None:
        self.schedule_file = pathlib.Path(schedule_file)
        self.executor = executor
        self._lock = threading.RLock()
        self.jobs: Dict[str, ScheduledJob] = {}
        self._load()

    def _load(self) -> None:
        if not self.schedule_file.exists():
            return
        try:
            raw = json.loads(self.schedule_file.read_text(encoding="utf-8"))
            for item in raw:
                job = ScheduledJob(**item)
                self.jobs[job.job_id] = job
        except Exception:
            pass

    def _save(self) -> None:
        self.schedule_file.parent.mkdir(parents=True, exist_ok=True)
        payload = [j.to_dict() for j in self.jobs.values()]
        self.schedule_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def add_job(
        self,
        workflow_path: str,
        workflow_name: str,
        interval_seconds: int,
        inputs: Optional[Dict[str, Any]] = None,
        allow_write: bool = True,
    ) -> ScheduledJob:
        if int(interval_seconds) < 5:
            raise ValueError("Schedule interval_seconds must be at least 5 seconds.")
        with self._lock:
            job_id = f"sched_{uuid.uuid4().hex[:10]}"
            now = time.time()
            job = ScheduledJob(
                job_id=job_id,
                workflow_path=str(workflow_path),
                workflow_name=workflow_name,
                interval_seconds=int(interval_seconds),
                inputs=dict(inputs or {}),
                enabled=True,
                allow_write=allow_write,
                next_run_at=now + int(interval_seconds),
            )
            self.jobs[job_id] = job
            self._save()
            return job

    def set_enabled(self, job_id: str, enabled: bool) -> ScheduledJob:
        with self._lock:
            if job_id not in self.jobs:
                raise KeyError(f"Scheduled job {job_id!r} not found.")
            job = self.jobs[job_id]
            job.enabled = bool(enabled)
            if job.enabled:
                job.next_run_at = time.time() + job.interval_seconds
            self._save()
            return job

    def remove_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self.jobs:
                del self.jobs[job_id]
                self._save()
                return True
            return False

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [j.to_dict() for j in self.jobs.values()]

    def tick(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Execute any due enabled jobs once and update their next_run_at."""
        ts = now if now is not None else time.time()
        executed: List[Dict[str, Any]] = []
        with self._lock:
            due = [j for j in self.jobs.values() if j.enabled and ts >= j.next_run_at]
        for job in due:
            status = "skipped"
            if self.executor is not None:
                try:
                    status = self.executor(job)
                except Exception:
                    status = "failed"
            with self._lock:
                job.last_run_at = ts
                job.last_status = status
                job.run_count += 1
                job.next_run_at = ts + job.interval_seconds
                self._save()
                executed.append(job.to_dict())
        return executed
