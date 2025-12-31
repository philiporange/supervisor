"""
Auto-fix integration using Robot.

Monitors service logs for errors and uses Robot (AI coding agents) to
automatically diagnose and fix issues in the source code. Creates backups
before modifying code so changes can be reverted. Also supports fixing
failed cron jobs.
"""

import asyncio
import json
import logging
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from .config import config
from .models import CronExecution, CronJob, FixAttempt, LogEntry, Service
from .process import process_manager

# Load .env for robot config (ROBOT_CLAUDE_PATH etc)
load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)


def create_backup(working_dir: str, service_name: str) -> str:
    """Create a backup of the working directory before fixing.

    Returns the backup path.
    """
    backup_base = config.data_dir / "backups" / service_name
    backup_base.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_base / timestamp

    # Copy the working directory
    shutil.copytree(
        working_dir,
        backup_path,
        ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".git", "node_modules",
            ".venv", "venv", "*.egg-info", ".mypy_cache"
        ),
    )

    logger.info(f"Created backup at {backup_path}")
    return str(backup_path)


def restore_backup(backup_path: str, working_dir: str) -> bool:
    """Restore a backup to the working directory.

    Returns True if successful.
    """
    try:
        backup = Path(backup_path)
        target = Path(working_dir)

        if not backup.exists():
            logger.error(f"Backup not found: {backup_path}")
            return False

        # Remove current files that exist in backup
        for item in backup.iterdir():
            target_item = target / item.name
            if target_item.exists():
                if target_item.is_dir():
                    shutil.rmtree(target_item)
                else:
                    target_item.unlink()

        # Copy backup files to target
        for item in backup.iterdir():
            target_item = target / item.name
            if item.is_dir():
                shutil.copytree(item, target_item)
            else:
                shutil.copy2(item, target_item)

        logger.info(f"Restored backup from {backup_path} to {working_dir}")
        return True

    except Exception as e:
        logger.error(f"Failed to restore backup: {e}")
        return False


def cleanup_old_backups(service_name: str, keep: int = 10):
    """Remove old backups, keeping only the most recent ones."""
    backup_base = config.data_dir / "backups" / service_name
    if not backup_base.exists():
        return

    backups = sorted(backup_base.iterdir(), key=lambda p: p.name, reverse=True)
    for old_backup in backups[keep:]:
        try:
            shutil.rmtree(old_backup)
            logger.debug(f"Removed old backup: {old_backup}")
        except Exception as e:
            logger.warning(f"Failed to remove old backup {old_backup}: {e}")

# Error patterns to detect
ERROR_PATTERNS = [
    r"Traceback \(most recent call last\)",
    r"Error:|ERROR:",
    r"Exception:|EXCEPTION:",
    r"ModuleNotFoundError:",
    r"ImportError:",
    r"SyntaxError:",
    r"TypeError:",
    r"ValueError:",
    r"AttributeError:",
    r"KeyError:",
    r"IndexError:",
    r"FileNotFoundError:",
    r"ConnectionRefusedError:",
    r"RuntimeError:",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in ERROR_PATTERNS]


class AutoFixer:
    """Monitors logs and auto-fixes errors using Robot."""

    def __init__(self):
        self._running = False
        self._task = None
        self._recent_errors: dict[str, list[str]] = {}  # service -> error lines
        self._fix_cooldown: dict[str, datetime] = {}  # service -> last fix time
        self._cooldown_minutes = 10  # Don't fix same service within 10 minutes

    async def start(self):
        """Start the auto-fixer."""
        if not config.autofix_enabled:
            logger.info("Auto-fix is disabled")
            return

        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._fixer_loop())
        logger.info("Auto-fixer started")

    async def stop(self):
        """Stop the auto-fixer."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Auto-fixer stopped")

    def on_log(self, service_name: str, level: str, message: str):
        """Called when a log entry is received. Collects error context."""
        if level != "error":
            return

        # Check if this looks like an error
        is_error = any(p.search(message) for p in COMPILED_PATTERNS)
        if not is_error and level == "error":
            # stderr but not a recognized error pattern - still collect
            is_error = True

        if is_error:
            if service_name not in self._recent_errors:
                self._recent_errors[service_name] = []
            self._recent_errors[service_name].append(message)

            # Keep only last 50 lines of error context
            if len(self._recent_errors[service_name]) > 50:
                self._recent_errors[service_name] = self._recent_errors[service_name][-50:]

    async def _fixer_loop(self):
        """Main fixer loop - checks for accumulated errors and attempts fixes."""
        while self._running:
            try:
                await self._check_and_fix()
            except Exception as e:
                logger.error(f"Error in fixer loop: {e}")

            await asyncio.sleep(60)  # Check every minute

    async def _check_and_fix(self):
        """Check for errors that need fixing."""
        for service_name, errors in list(self._recent_errors.items()):
            if not errors:
                continue

            # Check cooldown
            last_fix = self._fix_cooldown.get(service_name)
            if last_fix and datetime.now() - last_fix < timedelta(minutes=self._cooldown_minutes):
                continue

            # Look for traceback patterns (indicates real error)
            error_text = "\n".join(errors)
            if "Traceback" not in error_text and "Error" not in error_text:
                continue

            # Get service
            service = Service.get_or_none(Service.name == service_name)
            if not service or not service.enabled:
                continue

            logger.info(f"Detected errors in {service_name}, attempting auto-fix")

            # Attempt fix
            try:
                result = await self.attempt_fix(service, error_text)
                if result.success:
                    logger.info(f"Auto-fix succeeded for {service_name}")
                    # Clear errors and restart service
                    self._recent_errors[service_name] = []
                    process_manager.restart(service)
                else:
                    logger.warning(f"Auto-fix failed for {service_name}")
            except Exception as e:
                logger.error(f"Error during auto-fix for {service_name}: {e}")

            # Set cooldown
            self._fix_cooldown[service_name] = datetime.now()

    async def attempt_fix(self, service: Service, error_text: str) -> FixAttempt:
        """Attempt to fix an error using Robot."""
        try:
            from robot import Robot
            from robot.base import AgentConfig

            # Determine working directory
            working_dir = service.working_dir
            if not working_dir:
                # Try to extract from command
                import shlex

                parts = shlex.split(service.command)
                for part in parts:
                    if part.endswith(".py") and "/" in part:
                        working_dir = str(Path(part).parent)
                        break

            if not working_dir:
                logger.error(f"Cannot determine working directory for {service.name}")
                return FixAttempt.create(
                    service=service,
                    error_summary=error_text[:500],
                    robot_response="Could not determine working directory",
                    success=False,
                )

            # Create backup before modifying code
            backup_path = None
            try:
                backup_path = create_backup(working_dir, service.name)
                cleanup_old_backups(service.name)
            except Exception as e:
                logger.warning(f"Failed to create backup for {service.name}: {e}")

            prompt = f"""This service ({service.name}) is encountering the following error:

```
{error_text}
```

Please:
1. Identify the root cause of the error
2. Fix the bug in the code
3. Ensure the fix doesn't break other functionality

The service command is: {service.command}
"""

            config_obj = AgentConfig(
                model="sonnet",
                timeout=config.autofix_timeout,
                working_dir=Path(working_dir),
            )

            # Run Robot
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: Robot.run(
                    prompt=prompt,
                    agent="claude",
                    config=config_obj,
                ),
            )

            # Record attempt
            files_modified = json.dumps(response.files_modified) if response.files_modified else None

            fix_attempt = FixAttempt.create(
                service=service,
                error_summary=error_text[:500],
                robot_response=response.content[:5000] if response.content else None,
                success=response.success,
                files_modified=files_modified,
                backup_path=backup_path,
            )

            return fix_attempt

        except ImportError:
            logger.error("Robot module not available for auto-fix")
            return FixAttempt.create(
                service=service,
                error_summary=error_text[:500],
                robot_response="Robot module not installed",
                success=False,
            )
        except Exception as e:
            logger.error(f"Error running Robot for {service.name}: {e}")
            return FixAttempt.create(
                service=service,
                error_summary=error_text[:500],
                robot_response=str(e),
                success=False,
            )

    async def manual_fix(self, service: Service, error_description: str = None) -> dict:
        """Manually trigger a fix attempt. Returns dict for job serialization."""
        # Get recent errors if no description provided
        if not error_description:
            errors = self._recent_errors.get(service.name, [])
            if errors:
                error_description = "\n".join(errors[-20:])
            else:
                # Fetch from database
                recent_logs = (
                    LogEntry.select()
                    .where(LogEntry.service == service, LogEntry.level == "error")
                    .order_by(LogEntry.timestamp.desc())
                    .limit(20)
                )
                error_description = "\n".join([log.message for log in recent_logs])

        if not error_description:
            fix = FixAttempt.create(
                service=service,
                error_summary="No errors found",
                robot_response="No errors to fix",
                success=False,
            )
            return fix.to_dict()

        fix = await self.attempt_fix(service, error_description)
        return fix.to_dict()

    async def fix_cron_job(self, cron_job: CronJob, execution: CronExecution) -> bool:
        """
        Attempt to fix a failed cron job using Robot.

        Returns True if fix was successful.
        """
        if not config.autofix_enabled:
            return False

        # Check cooldown (use cron job name as key)
        cooldown_key = f"cron:{cron_job.name}"
        last_fix = self._fix_cooldown.get(cooldown_key)
        if last_fix and datetime.now() - last_fix < timedelta(minutes=self._cooldown_minutes):
            logger.info(f"Cron job {cron_job.name} in fix cooldown, skipping")
            return False

        working_dir = cron_job.working_dir
        if not working_dir:
            logger.warning(f"No working directory for cron job {cron_job.name}, cannot fix")
            return False

        logger.info(f"Attempting auto-fix for cron job {cron_job.name}")

        try:
            from robot import Robot
            from robot.base import AgentConfig

            # Build error context from execution
            error_text = ""
            if execution.stderr:
                error_text = execution.stderr
            elif execution.stdout:
                error_text = execution.stdout

            if not error_text:
                logger.info(f"No error output for cron job {cron_job.name}, skipping fix")
                return False

            # Create backup
            backup_path = None
            try:
                backup_path = create_backup(working_dir, f"cron_{cron_job.name}")
                cleanup_old_backups(f"cron_{cron_job.name}")
            except Exception as e:
                logger.warning(f"Failed to create backup for cron job {cron_job.name}: {e}")

            prompt = f"""This cron job ({cron_job.name}) failed with exit code {execution.exit_code}.

Command: {cron_job.command}
Schedule: {cron_job.schedule}

Error output:
```
{error_text[:3000]}
```

Please:
1. Identify the root cause of the error
2. Fix the bug in the code or script
3. Ensure the fix doesn't break other functionality

Duration: {execution.duration_seconds:.1f}s
"""

            config_obj = AgentConfig(
                model="sonnet",
                timeout=config.autofix_timeout,
                working_dir=Path(working_dir),
            )

            # Run Robot
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: Robot.run(
                    prompt=prompt,
                    agent="claude",
                    config=config_obj,
                ),
            )

            # Update execution record
            execution.fix_attempted = True
            execution.fix_success = response.success
            execution.save()

            # Set cooldown
            self._fix_cooldown[cooldown_key] = datetime.now()

            if response.success:
                logger.info(f"Auto-fix succeeded for cron job {cron_job.name}")
            else:
                logger.warning(f"Auto-fix failed for cron job {cron_job.name}")

            return response.success

        except ImportError:
            logger.error("Robot module not available for cron auto-fix")
            execution.fix_attempted = True
            execution.fix_success = False
            execution.save()
            return False
        except Exception as e:
            logger.error(f"Error running Robot for cron job {cron_job.name}: {e}")
            execution.fix_attempted = True
            execution.fix_success = False
            execution.save()
            return False


# Global auto-fixer instance
auto_fixer = AutoFixer()
