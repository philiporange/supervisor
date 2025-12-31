"""
Cron job scheduler and executor for supervisor.

Manages scheduled tasks that run periodically based on cron expressions.
Each minute, the tick() method is called (triggered by system cron) to
check which jobs should run and execute them with resource monitoring.
Failed jobs can trigger Robot auto-fix attempts.
"""

import asyncio
import logging
import os
import shlex
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import psutil
from croniter import croniter

from .config import config
from .models import CronExecution, CronJob

logger = logging.getLogger(__name__)


class CronManager:
    """Manages scheduled cron job execution."""

    def __init__(self):
        self._running_jobs: dict[int, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._on_fix_needed: callable = None

    def set_fix_callback(self, callback: callable):
        """Set callback for triggering auto-fix: callback(cron_job, execution)."""
        self._on_fix_needed = callback

    def _load_env_file(self, path: Path) -> dict[str, str]:
        """Load environment variables from a .env file."""
        env = {}
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith("#"):
                        continue
                    # Handle export prefix
                    if line.startswith("export "):
                        line = line[7:]
                    # Parse KEY=VALUE
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        # Remove quotes if present
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        env[key] = value
        except Exception as e:
            logger.error(f"Error loading env file {path}: {e}")
        return env

    def get_next_run(self, schedule: str, base_time: datetime = None) -> datetime:
        """Calculate the next run time for a cron schedule."""
        if base_time is None:
            base_time = datetime.now()
        try:
            cron = croniter(schedule, base_time)
            return cron.get_next(datetime)
        except (KeyError, ValueError) as e:
            logger.error(f"Invalid cron schedule '{schedule}': {e}")
            return None

    def should_run_now(self, job: CronJob) -> bool:
        """Check if a job should run at the current minute."""
        now = datetime.now().replace(second=0, microsecond=0)
        try:
            cron = croniter(job.schedule, now - timedelta(minutes=1))
            next_run = cron.get_next(datetime)
            return next_run == now
        except (KeyError, ValueError) as e:
            logger.error(f"Invalid cron schedule for {job.name}: {e}")
            return False

    def update_next_run(self, job: CronJob):
        """Update the next_run field for a job."""
        next_run = self.get_next_run(job.schedule)
        if next_run:
            job.next_run = next_run
            job.save()

    async def tick(self) -> list[int]:
        """
        Called every minute to check and execute due jobs.

        Returns list of execution IDs that were started.
        """
        execution_ids = []
        jobs = CronJob.select().where(CronJob.enabled == True)

        for job in jobs:
            if self.should_run_now(job):
                logger.info(f"Cron job {job.name} is due, executing")
                execution_id = await self.execute(job)
                if execution_id:
                    execution_ids.append(execution_id)

        return execution_ids

    async def execute(self, job: CronJob) -> int | None:
        """
        Execute a cron job and record the result.

        Returns the execution ID or None if failed to start.
        """
        # Check if already running
        with self._lock:
            if job.id in self._running_jobs:
                logger.warning(f"Cron job {job.name} is already running, skipping")
                return None

        # Create execution record
        execution = CronExecution.create(
            cron_job=job,
            started_at=datetime.now(),
        )

        try:
            # Parse command
            working_dir = job.working_dir
            if job.command.startswith("cd "):
                shell = True
                cmd = job.command
            else:
                shell = False
                cmd = shlex.split(job.command)

            # Build environment
            env = os.environ.copy()

            # Load .env file if specified
            if job.env_file:
                env_file_path = Path(job.env_file)
                if not env_file_path.is_absolute() and working_dir:
                    env_file_path = Path(working_dir) / env_file_path
                if env_file_path.exists():
                    env.update(self._load_env_file(env_file_path))
                else:
                    logger.warning(f"Env file not found for {job.name}: {env_file_path}")

            # Add job-specific env vars (overrides env file)
            env.update(job.get_env_vars())

            # Start process
            process = subprocess.Popen(
                cmd,
                shell=shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=working_dir,
                env=env,
                start_new_session=True,
            )

            with self._lock:
                self._running_jobs[job.id] = process

            # Update job timestamps
            job.last_run = datetime.now()
            self.update_next_run(job)

            # Monitor and wait for completion
            stdout, stderr, metrics = await self._monitor_process(
                process, job.timeout, job.name
            )

            # Calculate duration
            finished_at = datetime.now()
            duration = (finished_at - execution.started_at).total_seconds()

            # Update execution record
            execution.finished_at = finished_at
            execution.exit_code = process.returncode
            execution.stdout = stdout
            execution.stderr = stderr
            execution.success = process.returncode == 0
            execution.duration_seconds = duration
            execution.cpu_percent = metrics.get("cpu_percent")
            execution.memory_mb = metrics.get("memory_mb")
            execution.save()

            # Log result
            if execution.success:
                logger.info(
                    f"Cron job {job.name} completed successfully in {duration:.1f}s"
                )
            else:
                logger.warning(
                    f"Cron job {job.name} failed with exit code {process.returncode}"
                )
                # Trigger auto-fix if callback is set
                if self._on_fix_needed and config.autofix_enabled:
                    await self._on_fix_needed(job, execution)

            return execution.id

        except subprocess.TimeoutExpired:
            logger.error(f"Cron job {job.name} timed out after {job.timeout}s")
            execution.finished_at = datetime.now()
            execution.exit_code = -1
            execution.stderr = f"Timeout after {job.timeout} seconds"
            execution.success = False
            execution.duration_seconds = job.timeout
            execution.save()
            return execution.id

        except Exception as e:
            logger.error(f"Error executing cron job {job.name}: {e}")
            execution.finished_at = datetime.now()
            execution.exit_code = -1
            execution.stderr = str(e)
            execution.success = False
            execution.save()
            return execution.id

        finally:
            with self._lock:
                self._running_jobs.pop(job.id, None)

    async def _monitor_process(
        self, process: subprocess.Popen, timeout: int, job_name: str
    ) -> tuple[str, str, dict]:
        """
        Monitor a process and capture output with resource metrics.

        Returns (stdout, stderr, metrics_dict).
        """
        metrics = {"cpu_percent": 0.0, "memory_mb": 0.0}

        try:
            proc = psutil.Process(process.pid)
        except psutil.NoSuchProcess:
            proc = None

        # Use asyncio to wait for process with timeout
        loop = asyncio.get_event_loop()

        async def read_output():
            return await loop.run_in_executor(
                None, lambda: process.communicate(timeout=timeout)
            )

        # Sample metrics periodically while waiting
        output_task = asyncio.create_task(read_output())

        while not output_task.done():
            if proc:
                try:
                    cpu = proc.cpu_percent(interval=0)
                    mem = proc.memory_info().rss / 1024 / 1024

                    # Include children
                    try:
                        for child in proc.children(recursive=True):
                            cpu += child.cpu_percent(interval=0)
                            mem += child.memory_info().rss / 1024 / 1024
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                    metrics["cpu_percent"] = max(metrics["cpu_percent"], cpu)
                    metrics["memory_mb"] = max(metrics["memory_mb"], mem)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            await asyncio.sleep(0.5)

        stdout_bytes, stderr_bytes = await output_task
        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        return stdout, stderr, metrics

    def is_running(self, job_id: int) -> bool:
        """Check if a job is currently running."""
        with self._lock:
            return job_id in self._running_jobs

    def get_running_jobs(self) -> list[int]:
        """Get list of currently running job IDs."""
        with self._lock:
            return list(self._running_jobs.keys())

    async def run_now(self, job: CronJob) -> int | None:
        """Manually trigger a job to run immediately."""
        logger.info(f"Manually triggering cron job {job.name}")
        return await self.execute(job)

    def kill_job(self, job_id: int) -> bool:
        """Kill a running job."""
        with self._lock:
            process = self._running_jobs.get(job_id)

        if not process:
            return False

        try:
            os.killpg(os.getpgid(process.pid), 9)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def validate_schedule(self, schedule: str) -> tuple[bool, str]:
        """Validate a cron schedule expression."""
        try:
            croniter(schedule)
            return True, "Valid schedule"
        except (KeyError, ValueError) as e:
            return False, str(e)

    def get_schedule_description(self, schedule: str) -> str:
        """Get a human-readable description of when a job will run."""
        try:
            now = datetime.now()
            cron = croniter(schedule, now)

            # Get next few run times
            runs = []
            for _ in range(3):
                runs.append(cron.get_next(datetime))

            parts = schedule.split()
            if len(parts) != 5:
                return f"Next: {runs[0].strftime('%Y-%m-%d %H:%M')}"

            # Simple descriptions for common patterns
            minute, hour, dom, month, dow = parts

            if schedule == "* * * * *":
                return "Every minute"
            elif minute.startswith("*/"):
                interval = minute[2:]
                return f"Every {interval} minutes"
            elif minute != "*" and hour == "*":
                return f"Every hour at minute {minute}"
            elif minute != "*" and hour != "*" and dom == "*" and dow == "*":
                return f"Daily at {hour}:{minute.zfill(2)}"
            else:
                return f"Next: {runs[0].strftime('%Y-%m-%d %H:%M')}"

        except Exception:
            return "Invalid schedule"


# Global cron manager instance
cron_manager = CronManager()
