"""
Background job tracking for supervisor.

Runs blocking operations (like auto-fix) in background threads with
status tracking so the API remains responsive.
"""

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    """A background job."""

    id: str
    name: str
    status: JobStatus = JobStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "duration_seconds": (
                (self.completed_at or datetime.now()) - self.started_at
            ).total_seconds()
            if self.started_at
            else None,
        }


class JobManager:
    """Manages background jobs."""

    def __init__(self, max_completed: int = 100):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_completed = max_completed

    def create_job(self, name: str) -> Job:
        """Create a new job."""
        job_id = str(uuid.uuid4())[:8]
        job = Job(id=job_id, name=name)

        with self._lock:
            self._jobs[job_id] = job
            self._cleanup_old_jobs()

        logger.info(f"Created job {job_id}: {name}")
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, status: Optional[JobStatus] = None) -> list[Job]:
        """List all jobs, optionally filtered by status."""
        with self._lock:
            jobs = list(self._jobs.values())

        if status:
            jobs = [j for j in jobs if j.status == status]

        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def run_in_background(
        self, name: str, func: Callable, *args, **kwargs
    ) -> Job:
        """Run a function in a background thread with job tracking."""
        job = self.create_job(name)

        def wrapper():
            try:
                job.status = JobStatus.RUNNING
                job.started_at = datetime.now()
                logger.info(f"Job {job.id} started: {name}")

                result = func(*args, **kwargs)

                job.result = result
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now()
                logger.info(f"Job {job.id} completed: {name}")

            except Exception as e:
                job.error = str(e)
                job.status = JobStatus.FAILED
                job.completed_at = datetime.now()
                logger.error(f"Job {job.id} failed: {name} - {e}")

        thread = threading.Thread(target=wrapper, daemon=True)
        thread.start()

        return job

    async def run_async_in_background(
        self, name: str, coro_func: Callable, *args, **kwargs
    ) -> Job:
        """Run an async function in background with job tracking."""
        job = self.create_job(name)

        async def wrapper():
            try:
                job.status = JobStatus.RUNNING
                job.started_at = datetime.now()
                logger.info(f"Job {job.id} started: {name}")

                result = await coro_func(*args, **kwargs)

                job.result = result
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now()
                logger.info(f"Job {job.id} completed: {name}")

            except Exception as e:
                job.error = str(e)
                job.status = JobStatus.FAILED
                job.completed_at = datetime.now()
                logger.error(f"Job {job.id} failed: {name} - {e}")

        asyncio.create_task(wrapper())
        return job

    def update_progress(self, job_id: str, progress: str):
        """Update job progress message."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.progress = progress

    def _cleanup_old_jobs(self):
        """Remove old completed/failed jobs to prevent memory growth."""
        completed = [
            j
            for j in self._jobs.values()
            if j.status in (JobStatus.COMPLETED, JobStatus.FAILED)
        ]

        if len(completed) > self._max_completed:
            # Sort by completion time, remove oldest
            completed.sort(key=lambda j: j.completed_at or datetime.min)
            for job in completed[: len(completed) - self._max_completed]:
                del self._jobs[job.id]


# Global job manager instance
job_manager = JobManager()
