"""
Coding-agent runner for the final tier of the error sluice.

Runs `muse exec` headlessly in a service's working directory with the fix
prompt from prompts/fix.md. The agent is asked to end with a VERDICT line
(fixed, not_a_code_bug, unable) which is parsed from its output. Files it
changed are found by diffing `git status --porcelain` before and after the
run, so the result is trustworthy even when the agent's own report is not.
Everything here is blocking and meant to be called via asyncio.to_thread.
"""

import logging
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import config

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "fix.md"
VERDICT_RE = re.compile(r"VERDICT:\s*(fixed|not_a_code_bug|unable)\b", re.IGNORECASE)


@dataclass
class FixResult:
    """Outcome of one agent run."""

    verdict: str  # fixed, not_a_code_bug, unable, error
    output: str
    files_modified: list[str] = field(default_factory=list)
    duration: float = 0.0
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.verdict == "fixed" and bool(self.files_modified)


def build_prompt(name: str, command: str, working_dir: str, sample: str,
                 kind: str, kind_probability: float, fixable: float) -> str:
    template = PROMPT_PATH.read_text()
    return template.format(
        name=name,
        command=command,
        working_dir=working_dir,
        sample=sample,
        kind=kind,
        kind_probability=kind_probability,
        fixable=fixable,
    )


def git_status(working_dir: str) -> set[str] | None:
    """Return the set of dirty paths, or None when the directory is not a git repo."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return {line[3:] for line in out.stdout.splitlines() if line.strip()}


def parse_verdict(output: str) -> str:
    matches = VERDICT_RE.findall(output)
    return matches[-1].lower() if matches else "unable"


def run_fix(working_dir: str, prompt: str, timeout: int | None = None) -> FixResult:
    """Run the coding agent once in working_dir and return what it did."""
    timeout = timeout or config.autofix_timeout
    before = git_status(working_dir)
    start = time.time()

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(prompt)
        prompt_file = f.name

    cmd = [
        "muse", "exec",
        "--model", config.fix_model,
        "--reasoning-effort", config.fix_reasoning_effort,
        "--workspace", working_dir,
        "--disable-approval",
        "--user-input-auto-resolve",
        "--no-session-log",
        "--max-model-steps", str(config.fix_max_steps),
        "--prompt-file", prompt_file,
    ]
    logger.info(f"Running fix agent in {working_dir}: model={config.fix_model}")
    try:
        proc = subprocess.run(
            cmd,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return FixResult(
            verdict="error",
            output="",
            duration=time.time() - start,
            error=f"agent timed out after {timeout}s",
        )
    except FileNotFoundError as e:
        return FixResult(verdict="error", output="", duration=time.time() - start, error=str(e))
    finally:
        Path(prompt_file).unlink(missing_ok=True)

    output = proc.stdout
    duration = time.time() - start
    after = git_status(working_dir)
    if before is not None and after is not None:
        files_modified = sorted(after - before)
    else:
        files_modified = []

    if proc.returncode != 0:
        return FixResult(
            verdict="error",
            output=output,
            files_modified=files_modified,
            duration=duration,
            error=(proc.stderr or f"exit code {proc.returncode}")[-2000:],
        )

    verdict = parse_verdict(output)
    if verdict == "fixed" and not files_modified and before is not None:
        verdict = "unable"
    return FixResult(verdict=verdict, output=output, files_modified=files_modified, duration=duration)
