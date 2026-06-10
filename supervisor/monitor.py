"""
Resource monitoring for supervised services and cron jobs.

Collects CPU, memory, and disk usage in a background thread on a configurable
interval and caches results in memory. API endpoints read from the cache
instead of computing metrics live, keeping request handlers non-blocking.
psutil.Process handles are kept between collection intervals so cpu_percent()
measures usage since the previous interval (a fresh handle always reports 0.0).
Handles cleanup of old log entries, metrics, and cron execution records.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from .config import config
from .models import CronExecution, LogEntry, Metric, Service, database
from .process import process_manager

logger = logging.getLogger(__name__)


def get_directory_size(path: str) -> float:
    """Get total size of a directory in MB."""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total += os.path.getsize(filepath)
                except (OSError, FileNotFoundError):
                    pass
    except (OSError, PermissionError):
        pass
    return total / 1024 / 1024  # Convert to MB


class ResourceMonitor:
    """Monitors resource usage of supervised services.

    Collects metrics in a background thread and caches them in memory.
    The cache is read by API endpoints for instant responses.
    """

    def __init__(self):
        self._running = False
        self._task = None
        self._cache: dict[str, dict] = {}
        # pid -> psutil.Process, reused across intervals so cpu_percent()
        # has a previous sample to diff against
        self._proc_handles: dict[int, psutil.Process] = {}

    def _get_proc_handle(self, pid: int) -> psutil.Process:
        """Get a cached psutil.Process for a pid, creating it if needed."""
        proc = self._proc_handles.get(pid)
        if proc is None or proc.pid != pid:
            proc = psutil.Process(pid)
            proc.cpu_percent(interval=None)  # Prime the CPU sample
            self._proc_handles[pid] = proc
        return proc

    async def start(self):
        """Start the monitoring loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Resource monitor started")

    async def stop(self):
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Resource monitor stopped")

    async def _monitor_loop(self):
        """Main monitoring loop. Runs collection in a thread to avoid blocking."""
        while self._running:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._collect_metrics_sync)
                await self._cleanup_old_data()
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")

            await asyncio.sleep(config.monitor_interval)

    def _collect_metrics_sync(self):
        """Collect metrics for all running services (runs in thread pool)."""
        live_pids = set()

        for service in Service.select():
            try:
                pid = process_manager.get_pid(service.name)
                if not pid:
                    # Not running: drop stale cache so APIs don't report old numbers
                    self._cache.pop(service.name, None)
                    continue

                cpu_percent = 0.0
                memory_mb = 0.0
                child_count = 0

                try:
                    proc = self._get_proc_handle(pid)
                    live_pids.add(pid)
                    cpu_percent = proc.cpu_percent(interval=None)
                    memory_mb = proc.memory_info().rss / 1024 / 1024

                    # Also collect child processes
                    try:
                        for child in proc.children(recursive=True):
                            try:
                                child_proc = self._get_proc_handle(child.pid)
                                live_pids.add(child.pid)
                                cpu_percent += child_proc.cpu_percent(interval=None)
                                memory_mb += child_proc.memory_info().rss / 1024 / 1024
                                child_count += 1
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                except psutil.NoSuchProcess:
                    logger.warning(f"Process for {service.name} no longer exists")
                except psutil.AccessDenied:
                    logger.warning(f"Access denied for {service.name}")

                # Collect disk usage for watched directories
                disk_mb = 0.0
                watch_dirs = service.get_watch_dirs()
                for dir_path in watch_dirs:
                    if dir_path and os.path.isdir(dir_path):
                        disk_mb += get_directory_size(dir_path)

                Metric.create(
                    service=service,
                    cpu_percent=cpu_percent,
                    memory_mb=memory_mb,
                    disk_mb=disk_mb if disk_mb > 0 else None,
                )

                # Update in-memory cache
                info = process_manager.get_info(service.name)
                self._cache[service.name] = {
                    "pid": pid,
                    "cpu_percent": round(cpu_percent, 1),
                    "memory_mb": round(memory_mb, 1),
                    "disk_mb": round(disk_mb, 1),
                    "child_processes": child_count,
                    "uptime_seconds": (datetime.now() - info.started_at).total_seconds() if info else 0,
                    "restart_count": info.restart_count if info else 0,
                    "watch_dirs": watch_dirs,
                }

                logger.debug(
                    f"Metrics for {service.name}: CPU={cpu_percent:.1f}%, "
                    f"MEM={memory_mb:.1f}MB, DISK={disk_mb:.1f}MB"
                )

            except Exception as e:
                logger.error(f"Error collecting metrics for {service.name}: {e}")

        # Drop handles for processes that are gone
        for pid in list(self._proc_handles):
            if pid not in live_pids:
                del self._proc_handles[pid]

    async def _cleanup_old_data(self):
        """Remove old log entries, metrics, and cron executions."""
        try:
            cutoff = datetime.now() - timedelta(days=config.log_retention_days)

            # Clean old log entries
            deleted_logs = LogEntry.delete().where(LogEntry.timestamp < cutoff).execute()
            if deleted_logs:
                logger.debug(f"Cleaned up {deleted_logs} old log entries")

            # Clean old metrics
            deleted_metrics = Metric.delete().where(Metric.timestamp < cutoff).execute()
            if deleted_metrics:
                logger.debug(f"Cleaned up {deleted_metrics} old metrics")

            # Clean old cron executions
            deleted_cron = CronExecution.delete().where(CronExecution.started_at < cutoff).execute()
            if deleted_cron:
                logger.debug(f"Cleaned up {deleted_cron} old cron executions")

        except Exception as e:
            logger.error(f"Error cleaning up old data: {e}")

    def get_cached_metrics(self, service_name: str) -> dict | None:
        """Get cached metrics for a service. Instant, non-blocking."""
        return self._cache.get(service_name)

    def get_current_metrics(self, service_name: str) -> dict | None:
        """Get current resource usage for a service.

        Returns cached metrics enriched with live uptime, or minimal live data
        if the cache is empty (first interval hasn't run yet). Returns None if
        the service is not running.
        """
        pid = process_manager.get_pid(service_name)
        if not pid:
            return None

        cached = self._cache.get(service_name)
        if cached:
            # Refresh uptime from live process info
            info = process_manager.get_info(service_name)
            if info:
                cached["uptime_seconds"] = (datetime.now() - info.started_at).total_seconds()
                cached["restart_count"] = info.restart_count
            return cached

        # Fallback: return minimal info without expensive computation
        info = process_manager.get_info(service_name)
        return {
            "pid": pid,
            "cpu_percent": 0.0,
            "memory_mb": 0.0,
            "disk_mb": 0.0,
            "child_processes": 0,
            "uptime_seconds": (datetime.now() - info.started_at).total_seconds() if info else 0,
            "restart_count": info.restart_count if info else 0,
        }


# Global monitor instance
resource_monitor = ResourceMonitor()
