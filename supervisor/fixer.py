"""
Auto-fix orchestration: the final two tiers of the error sluice.

Log lines arrive via on_log after the process manager has captured them.
Tiers 1 and 2 (channel and regex, in sluice.py) decide per line whether it
enters a per-service window. Once a minute the loop checks each window: if
it holds strong hits and the Jev interval has elapsed, the window is sent to
Jev (tier 3) for a typed verdict on what kind of failure it shows. Only a
verdict of a repo-fixable code or dependency fault, outside the per-service
cooldown and under the daily cap, reaches tier 4: a coding agent run in the
service's working directory. Tier 4 is off unless AUTOFIX_ENABLED is set;
the dashboard's manual Trigger Fix still works. Every Jev review is recorded
as an Incident so decisions can be audited; every agent run is a FixAttempt
listing the files it changed. Nothing is copied aside first: the host keeps
its own daily copies of every project.

Fix runs happen in background tasks, one service at a time, so a slow agent
never blocks reviews of other services. Cooldowns are derived from stored
FixAttempt timestamps and survive supervisor restarts. Failed cron jobs go
through the same tiers using the execution's captured output.
"""

import asyncio
import json
import logging
import shlex
from datetime import datetime, timedelta
from pathlib import Path

from .config import config
from .fix_agent import build_prompt, run_fix
from .models import CronExecution, CronJob, FixAttempt, Incident, LogEntry, Service
from .process import process_manager
from .sluice import (
    STDERR,
    STDOUT,
    JevVerdict,
    Window,
    classify_line,
    jev_review,
    lines_from_text,
    render_lines,
)

logger = logging.getLogger(__name__)


def working_dir_for(command: str, working_dir: str | None) -> str | None:
    """Use the configured working directory, else the directory of a .py path in the command."""
    if working_dir:
        return working_dir
    for part in shlex.split(command):
        if part.endswith(".py") and "/" in part:
            return str(Path(part).parent)
    return None


class AutoFixer:
    """Runs the sluice's review and fix tiers over service and cron output."""

    def __init__(self):
        self._running = False
        self._task = None
        self._windows: dict[str, Window] = {}
        self._fix_tasks: set[asyncio.Task] = set()
        self._fix_lock = asyncio.Lock()

    async def start(self):
        if not config.autofix_enabled:
            logger.info("Auto-fix is disabled; output is still classified and windowed")
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._review_loop())
        logger.info("Auto-fixer started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for task in list(self._fix_tasks):
            task.cancel()
        logger.info("Auto-fixer stopped")

    # -- Tiers 1-2: per-line intake --

    def on_log(self, service_name: str, stream: str, level: str, message: str):
        """Feed one captured line through the channel and regex gates."""
        signal = classify_line(stream, message)
        if not signal:
            return
        window = self._windows.get(service_name)
        if window is None:
            window = self._windows[service_name] = Window()
        window.add(stream, message, signal)

    def recent_errors(self, service_name: str) -> str:
        window = self._windows.get(service_name)
        return render_lines(window.lines) if window else ""

    # -- Tier 3: periodic review --

    async def _review_loop(self):
        while self._running:
            try:
                await self._review_windows()
            except Exception as e:
                logger.error(f"Error in fixer review loop: {e}")
            await asyncio.sleep(60)

    async def _review_windows(self):
        now = datetime.now()
        for service_name, window in list(self._windows.items()):
            if not window.due_for_review(now):
                continue
            service = Service.get_or_none(Service.name == service_name)
            if not service or not service.enabled:
                window.clear()
                continue
            strong_hits = window.strong_since_review
            sample = window.take_sample()
            window.reviewing = True
            try:
                await self._review(service, None, sample, strong_hits)
            finally:
                window.reviewing = False

    async def _review(self, service: Service | None, cron_job: CronJob | None,
                      sample: str, strong_hits: int):
        """Send a sample to Jev, record the Incident, and escalate if warranted."""
        name = service.name if service else f"cron:{cron_job.name}"
        command = service.command if service else cron_job.command
        verdict = await jev_review(name, command, sample)

        incident = Incident(
            service=service,
            cron_job=cron_job,
            sample=sample,
            strong_hits=strong_hits,
            decision="jev_unavailable",
        )
        if verdict:
            incident.jev_kind = verdict.kind
            incident.jev_probabilities = json.dumps(verdict.probabilities)
            incident.jev_fixable = verdict.fixable
            incident.jev_persistent = verdict.persistent
            incident.jev_tokens = verdict.input_tokens
            incident.decision = self._decide(name, verdict)
        incident.save()

        if incident.decision != "fix_attempted":
            logger.info(f"Sluice {name}: {incident.decision}"
                        + (f" ({verdict.kind} p={verdict.kind_probability:.2f})" if verdict else ""))
            return

        task = asyncio.create_task(self._run_fix(incident, service, cron_job, sample, verdict))
        self._fix_tasks.add(task)
        task.add_done_callback(self._fix_tasks.discard)

    def _decide(self, name: str, verdict: JevVerdict) -> str:
        if not verdict.should_escalate():
            return "dismissed"
        if not config.autofix_enabled:
            return "disabled"
        if self._in_cooldown(name):
            return "cooldown"
        if self._daily_cap_reached():
            return "daily_cap"
        return "fix_attempted"

    def _in_cooldown(self, name: str) -> bool:
        cutoff = datetime.now() - timedelta(minutes=config.fix_cooldown_minutes)
        query = Incident.select().where(
            Incident.decision == "fix_attempted", Incident.timestamp > cutoff
        )
        if name.startswith("cron:"):
            query = query.join(CronJob).where(CronJob.name == name[5:])
        else:
            query = query.join(Service).where(Service.name == name)
        return query.exists()

    def _daily_cap_reached(self) -> bool:
        cutoff = datetime.now() - timedelta(hours=24)
        count = Incident.select().where(
            Incident.decision == "fix_attempted", Incident.timestamp > cutoff
        ).count()
        return count >= config.fix_daily_cap

    # -- Tier 4: coding agent --

    async def _run_fix(self, incident: Incident, service: Service | None,
                       cron_job: CronJob | None, sample: str, verdict: JevVerdict | None):
        async with self._fix_lock:
            try:
                if service:
                    attempt = await self.attempt_fix(service, sample, verdict)
                    incident.fix_attempt = attempt
                    incident.save()
                    if attempt.success:
                        window = self._windows.get(service.name)
                        if window:
                            window.clear()
                        success, msg = await asyncio.to_thread(process_manager.restart, service)
                        if not success:
                            logger.warning(f"Fix applied but restart failed for {service.name}: {msg}")
                else:
                    await self._fix_cron(cron_job, sample, verdict)
            except Exception as e:
                logger.error(f"Error during fix for {incident.service_id or incident.cron_job_id}: {e}")

    async def attempt_fix(self, service: Service, error_text: str,
                          verdict: JevVerdict | None = None) -> FixAttempt:
        """Run the coding agent for a service and record the attempt."""
        working_dir = working_dir_for(service.command, service.working_dir)
        if not working_dir or not Path(working_dir).is_dir():
            logger.error(f"Cannot determine working directory for {service.name}")
            return FixAttempt.create(
                service=service,
                error_summary=error_text[:500],
                robot_response="Could not determine working directory",
                success=False,
                verdict="error",
                model=config.fix_model,
            )

        prompt = build_prompt(
            name=service.name,
            command=service.command,
            working_dir=working_dir,
            sample=error_text,
            kind=verdict.kind if verdict else "unknown",
            kind_probability=verdict.kind_probability if verdict else 0.0,
            fixable=verdict.fixable if verdict else 0.0,
        )
        logger.info(f"Attempting fix for {service.name}")
        result = await asyncio.to_thread(run_fix, working_dir, prompt)

        attempt = FixAttempt.create(
            service=service,
            error_summary=error_text[:500],
            robot_response=(result.error or result.output)[-5000:] if (result.error or result.output) else None,
            success=result.success,
            files_modified=json.dumps(result.files_modified) if result.files_modified else None,
            model=config.fix_model,
            verdict=result.verdict,
        )
        level = logger.info if result.success else logger.warning
        level(f"Fix for {service.name}: {result.verdict} in {result.duration:.0f}s, "
              f"files={result.files_modified}")
        return attempt

    async def manual_fix(self, service: Service, error_description: str = None) -> dict:
        """Dashboard-triggered fix: skips Jev and cooldowns, uses recent errors if none given."""
        if not error_description:
            error_description = self.recent_errors(service.name)
        if not error_description:
            recent_logs = (
                LogEntry.select()
                .where(LogEntry.service == service, LogEntry.level == "error")
                .order_by(LogEntry.timestamp.desc())
                .limit(30)
            )
            error_description = "\n".join(f"[E] {log.message}" for log in reversed(list(recent_logs)))

        if not error_description:
            fix = FixAttempt.create(
                service=service,
                error_summary="No errors found",
                robot_response="No errors to fix",
                success=False,
                verdict="error",
                model=config.fix_model,
            )
            return fix.to_dict()

        async with self._fix_lock:
            fix = await self.attempt_fix(service, error_description)
            Incident.create(
                service=service, sample=error_description, strong_hits=0,
                decision="fix_attempted", fix_attempt=fix,
            )
            if fix.success:
                window = self._windows.get(service.name)
                if window:
                    window.clear()
                await asyncio.to_thread(process_manager.restart, service)
        return fix.to_dict()

    # -- Cron jobs --

    async def fix_cron_job(self, cron_job: CronJob, execution: CronExecution) -> bool:
        """Route a failed execution's output through the sluice. Returns True if a fix was applied."""
        lines = lines_from_text(execution.stderr or "", STDERR) + lines_from_text(execution.stdout or "", STDOUT)
        strong_hits = sum(1 for line in lines if line[3] == "strong")
        if strong_hits == 0:
            logger.info(f"Cron job {cron_job.name} failed without strong error signals; not reviewing")
            return False
        sample = render_lines([(ts, stream, message) for ts, stream, message, _ in lines])
        await self._review(None, cron_job, sample, strong_hits)
        return False

    async def _fix_cron(self, cron_job: CronJob, sample: str, verdict: JevVerdict | None):
        working_dir = cron_job.working_dir
        if not working_dir or not Path(working_dir).is_dir():
            logger.warning(f"No working directory for cron job {cron_job.name}, cannot fix")
            return

        prompt = build_prompt(
            name=f"cron job {cron_job.name} (schedule {cron_job.schedule})",
            command=cron_job.command,
            working_dir=working_dir,
            sample=sample,
            kind=verdict.kind if verdict else "unknown",
            kind_probability=verdict.kind_probability if verdict else 0.0,
            fixable=verdict.fixable if verdict else 0.0,
        )
        result = await asyncio.to_thread(run_fix, working_dir, prompt)
        latest = (
            CronExecution.select()
            .where(CronExecution.cron_job == cron_job)
            .order_by(CronExecution.started_at.desc())
            .first()
        )
        if latest:
            latest.fix_attempted = True
            latest.fix_success = result.success
            latest.save()
        level = logger.info if result.success else logger.warning
        level(f"Fix for cron job {cron_job.name}: {result.verdict}, files={result.files_modified}")


# Global auto-fixer instance
auto_fixer = AutoFixer()
