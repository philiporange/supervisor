"""
Process manager for supervised services.

Handles starting, stopping, and restarting processes. Captures stdout/stderr
to log files and monitors for crashes with automatic restart capability.
"""

import asyncio
import logging
import os
import shlex
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import config
from .models import LogEntry, Service

logger = logging.getLogger(__name__)


@dataclass
class ProcessInfo:
    """Information about a running process."""

    service_name: str
    process: subprocess.Popen
    started_at: datetime = field(default_factory=datetime.now)
    restart_count: int = 0
    last_restart: datetime = None


class ProcessManager:
    """Manages supervised service processes."""

    def __init__(self):
        self._processes: dict[str, ProcessInfo] = {}
        self._log_threads: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._on_log: Callable[[str, str, str], None] = None

    def set_log_callback(self, callback: Callable[[str, str, str], None]):
        """Set callback for log entries: callback(service_name, level, message)."""
        self._on_log = callback

    def start(self, service: Service) -> bool:
        """Start a service process. Returns True if started successfully."""
        if self.is_running(service.name):
            logger.info(f"Service {service.name} is already running")
            return True

        try:
            # Create log directory for this service
            log_dir = config.logs_dir / service.name
            log_dir.mkdir(parents=True, exist_ok=True)

            # Determine working directory
            working_dir = service.working_dir
            if not working_dir:
                # Try to extract from command
                parts = shlex.split(service.command)
                for part in parts:
                    if part.endswith(".py") and "/" in part:
                        working_dir = str(Path(part).parent)
                        break

            # Open log files
            stdout_log = open(log_dir / "stdout.log", "a")
            stderr_log = open(log_dir / "stderr.log", "a")

            # Parse command
            if service.command.startswith("cd "):
                # Handle "cd /path && command" pattern
                shell = True
                cmd = service.command
            else:
                shell = False
                cmd = shlex.split(service.command)

            # Start process
            env = os.environ.copy()
            process = subprocess.Popen(
                cmd,
                shell=shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=working_dir,
                env=env,
                start_new_session=True,  # Create new process group
            )

            with self._lock:
                self._processes[service.name] = ProcessInfo(
                    service_name=service.name,
                    process=process,
                )

            # Start log capture threads
            stop_event = threading.Event()
            self._stop_events[service.name] = stop_event

            stdout_thread = threading.Thread(
                target=self._capture_output,
                args=(service.name, process.stdout, "info", stdout_log, stop_event),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=self._capture_output,
                args=(service.name, process.stderr, "error", stderr_log, stop_event),
                daemon=True,
            )

            stdout_thread.start()
            stderr_thread.start()

            logger.info(f"Started service {service.name} with PID {process.pid}")
            return True

        except Exception as e:
            logger.error(f"Failed to start service {service.name}: {e}")
            return False

    def stop(self, service_name: str, timeout: int = 10) -> bool:
        """Stop a service process. Returns True if stopped successfully."""
        with self._lock:
            info = self._processes.get(service_name)

        if not info:
            logger.info(f"Service {service_name} is not running")
            return True

        try:
            # Signal stop to log threads
            if service_name in self._stop_events:
                self._stop_events[service_name].set()

            process = info.process

            # Try graceful shutdown first (SIGTERM)
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass

            # Wait for process to terminate
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Force kill
                logger.warning(f"Service {service_name} did not stop gracefully, forcing kill")
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)

            with self._lock:
                del self._processes[service_name]
                if service_name in self._stop_events:
                    del self._stop_events[service_name]

            logger.info(f"Stopped service {service_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to stop service {service_name}: {e}")
            return False

    def restart(self, service: Service) -> bool:
        """Restart a service. Returns True if restarted successfully."""
        self.stop(service.name)
        time.sleep(config.restart_delay)
        return self.start(service)

    def is_running(self, service_name: str) -> bool:
        """Check if a service is running."""
        with self._lock:
            info = self._processes.get(service_name)

        if not info:
            return False

        # Check if process is still alive
        return info.process.poll() is None

    def get_pid(self, service_name: str) -> int | None:
        """Get the PID of a running service."""
        with self._lock:
            info = self._processes.get(service_name)

        if not info:
            return None

        if info.process.poll() is None:
            return info.process.pid
        return None

    def get_info(self, service_name: str) -> ProcessInfo | None:
        """Get process info for a service."""
        with self._lock:
            return self._processes.get(service_name)

    def get_all_running(self) -> list[str]:
        """Get list of all running service names."""
        with self._lock:
            return [name for name, info in self._processes.items() if info.process.poll() is None]

    def _capture_output(
        self,
        service_name: str,
        stream,
        level: str,
        log_file,
        stop_event: threading.Event,
    ):
        """Capture process output and write to log file and database."""
        try:
            for line in iter(stream.readline, b""):
                if stop_event.is_set():
                    break

                try:
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    if not decoded:
                        continue

                    # Write to log file
                    timestamp = datetime.now().isoformat()
                    log_file.write(f"[{timestamp}] {decoded}\n")
                    log_file.flush()

                    # Detect error level from content
                    detected_level = level
                    lower = decoded.lower()
                    if "error" in lower or "exception" in lower or "traceback" in lower:
                        detected_level = "error"
                    elif "warning" in lower or "warn" in lower:
                        detected_level = "warning"

                    # Call callback if set
                    if self._on_log:
                        self._on_log(service_name, detected_level, decoded)

                except Exception as e:
                    logger.error(f"Error processing log line for {service_name}: {e}")

        except Exception as e:
            logger.error(f"Error in log capture for {service_name}: {e}")
        finally:
            try:
                log_file.close()
            except Exception:
                pass

    async def check_and_restart_crashed(self):
        """Check for crashed processes and restart them."""
        with self._lock:
            crashed = [
                name
                for name, info in self._processes.items()
                if info.process.poll() is not None
            ]

        for service_name in crashed:
            logger.warning(f"Service {service_name} has crashed, attempting restart")

            # Get service from database
            try:
                service = Service.get(Service.name == service_name)
                if not service.enabled:
                    logger.info(f"Service {service_name} is disabled, not restarting")
                    with self._lock:
                        del self._processes[service_name]
                    continue

                # Check restart count
                with self._lock:
                    info = self._processes.get(service_name)
                    if info and info.restart_count >= config.max_restart_attempts:
                        logger.error(
                            f"Service {service_name} exceeded max restart attempts, giving up"
                        )
                        del self._processes[service_name]
                        continue

                # Restart with backoff
                with self._lock:
                    if service_name in self._processes:
                        del self._processes[service_name]

                await asyncio.sleep(config.restart_delay)

                if self.start(service):
                    with self._lock:
                        if service_name in self._processes:
                            self._processes[service_name].restart_count = (
                                info.restart_count + 1 if info else 1
                            )
                            self._processes[service_name].last_restart = datetime.now()

            except Service.DoesNotExist:
                logger.error(f"Service {service_name} not found in database")
                with self._lock:
                    if service_name in self._processes:
                        del self._processes[service_name]

    def shutdown_all(self):
        """Stop all running processes."""
        with self._lock:
            service_names = list(self._processes.keys())

        for name in service_names:
            self.stop(name)


# Global process manager instance
process_manager = ProcessManager()
