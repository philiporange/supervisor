"""
Coding-agent runners for the last two tiers of the error sluice.

Both run `muse exec` headlessly in a service's working directory. The
diagnosis run (prompts/diagnose.md) launches the agent with filesystem writes
and shell execution disabled and returns its written report; the fix run
(prompts/fix.md) lets the agent edit the repo and asks it to end with a
VERDICT line (fixed, not_a_code_bug, unable) which is parsed from its output.
Files changed are found by diffing `git status --porcelain` before and after
either run, so a fix result is trustworthy even when the agent's own report
is not, and a diagnosis that somehow wrote files is flagged. Everything here
is blocking and meant to be called via asyncio.to_thread.
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
DIAGNOSE_PROMPT_PATH = Path(__file__).parent / "prompts" / "diagnose.md"
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


@dataclass
class DiagnosisResult:
    """Outcome of one read-only diagnosis run."""

    report: str
    duration: float = 0.0
    error: str | None = None
    files_modified: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.error is None and bool(self.report.strip())


def build_prompt(name: str, command: str, working_dir: str, sample: str,
                 kind: str, kind_probability: float, fixable: float,
                 template_path: Path = PROMPT_PATH) -> str:
    template = template_path.read_text()
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


def _run_muse(working_dir: str, prompt: str, model: str, reasoning_effort: str,
              max_steps: int, timeout: int, extra_args: list[str]):
    """Run one headless muse session. Returns (stdout, stderr, returncode, error, duration, files_modified)."""
    before = git_status(working_dir)
    start = time.time()

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(prompt)
        prompt_file = f.name

    cmd = [
        "muse", "exec",
        "--model", model,
        "--reasoning-effort", reasoning_effort,
        "--workspace", working_dir,
        "--disable-approval",
        "--user-input-auto-resolve",
        "--no-session-log",
        "--max-model-steps", str(max_steps),
        "--prompt-file", prompt_file,
        *extra_args,
    ]
    logger.info(f"Running agent in {working_dir}: model={model} flags={extra_args}")
    try:
        proc = subprocess.run(cmd, cwd=working_dir, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", "", None, f"agent timed out after {timeout}s", time.time() - start, []
    except FileNotFoundError as e:
        return "", "", None, str(e), time.time() - start, []
    finally:
        Path(prompt_file).unlink(missing_ok=True)

    duration = time.time() - start
    after = git_status(working_dir)
    files_modified = sorted(after - before) if before is not None and after is not None else []
    error = None
    if proc.returncode != 0:
        error = (proc.stderr or f"exit code {proc.returncode}")[-2000:]
    return proc.stdout, proc.stderr, proc.returncode, error, duration, files_modified


def run_diagnosis(working_dir: str, prompt: str, timeout: int | None = None) -> DiagnosisResult:
    """Run the agent read-only and return its diagnosis report."""
    output, _, _, error, duration, files_modified = _run_muse(
        working_dir, prompt,
        model=config.diagnose_model,
        reasoning_effort=config.diagnose_reasoning_effort,
        max_steps=config.diagnose_max_steps,
        timeout=timeout or config.diagnose_timeout,
        extra_args=["--disable-write", "--disable-shell"],
    )
    if files_modified:
        logger.warning(f"Diagnosis run modified files in {working_dir}: {files_modified}")
    return DiagnosisResult(report=output.strip(), duration=duration, error=error,
                           files_modified=files_modified)


def run_fix(working_dir: str, prompt: str, timeout: int | None = None) -> FixResult:
    """Run the coding agent once in working_dir and return what it did."""
    output, _, _, error, duration, files_modified = _run_muse(
        working_dir, prompt,
        model=config.fix_model,
        reasoning_effort=config.fix_reasoning_effort,
        max_steps=config.fix_max_steps,
        timeout=timeout or config.autofix_timeout,
        extra_args=[],
    )
    if error:
        return FixResult(verdict="error", output=output, files_modified=files_modified,
                         duration=duration, error=error)

    verdict = parse_verdict(output)
    if verdict == "fixed" and not files_modified and git_status(working_dir) is not None:
        verdict = "unable"
    return FixResult(verdict=verdict, output=output, files_modified=files_modified, duration=duration)
