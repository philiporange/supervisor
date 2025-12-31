"""
Resource monitoring for supervised services and cron jobs.

Periodically collects CPU, memory, and disk usage statistics for services
and stores them in the database for historical analysis. Also handles cleanup
of old log entries, metrics, and cron execution records.
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
    """Monitors resource usage of supervised services."""

    def __init__(self):
        self._running = False
        self._task = None

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
        """Main monitoring loop."""
        while self._running:
            try:
                await self._collect_metrics()
                await self._cleanup_old_data()
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")

            await asyncio.sleep(config.monitor_interval)

    async def _collect_metrics(self):
        """Collect metrics for all enabled services."""
        # Collect for all enabled services (not just running ones for disk)
        for service in Service.select().where(Service.enabled == True):
            try:
                cpu_percent = 0.0
                memory_mb = 0.0

                # Get process metrics if running
                if process_manager.is_running(service.name):
                    pid = process_manager.get_pid(service.name)
                    if pid:
                        try:
                            proc = psutil.Process(pid)
                            cpu_percent = proc.cpu_percent(interval=0.1)
                            memory_info = proc.memory_info()
                            memory_mb = memory_info.rss / 1024 / 1024

                            # Also collect child processes
                            try:
                                children = proc.children(recursive=True)
                                for child in children:
                                    cpu_percent += child.cpu_percent(interval=0.1)
                                    memory_mb += child.memory_info().rss / 1024 / 1024
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
                logger.debug(
                    f"Metrics for {service.name}: CPU={cpu_percent:.1f}%, "
                    f"MEM={memory_mb:.1f}MB, DISK={disk_mb:.1f}MB"
                )

            except Exception as e:
                logger.error(f"Error collecting metrics for {service.name}: {e}")

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

    def get_current_metrics(self, service_name: str) -> dict | None:
        """Get current resource usage for a service."""
        service = Service.get_or_none(Service.name == service_name)
        if not service:
            return None

        result = {
            "pid": None,
            "cpu_percent": 0.0,
            "memory_mb": 0.0,
            "disk_mb": 0.0,
            "child_processes": 0,
            "uptime_seconds": 0,
            "restart_count": 0,
        }

        # Get process metrics if running
        pid = process_manager.get_pid(service_name)
        if pid:
            try:
                proc = psutil.Process(pid)
                cpu_percent = proc.cpu_percent(interval=0.1)
                memory_info = proc.memory_info()
                memory_mb = memory_info.rss / 1024 / 1024

                # Include children
                child_count = 0
                try:
                    children = proc.children(recursive=True)
                    child_count = len(children)
                    for child in children:
                        cpu_percent += child.cpu_percent(interval=0.1)
                        memory_mb += child.memory_info().rss / 1024 / 1024
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

                info = process_manager.get_info(service_name)

                result.update({
                    "pid": pid,
                    "cpu_percent": round(cpu_percent, 1),
                    "memory_mb": round(memory_mb, 1),
                    "child_processes": child_count,
                    "uptime_seconds": (datetime.now() - info.started_at).total_seconds() if info else 0,
                    "restart_count": info.restart_count if info else 0,
                })

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Get disk usage
        disk_mb = 0.0
        watch_dirs = service.get_watch_dirs()
        for dir_path in watch_dirs:
            if dir_path and os.path.isdir(dir_path):
                disk_mb += get_directory_size(dir_path)
        result["disk_mb"] = round(disk_mb, 1)
        result["watch_dirs"] = watch_dirs

        return result


# Global monitor instance
resource_monitor = ResourceMonitor()
