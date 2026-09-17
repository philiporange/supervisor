"""
Tiered error detection for service and cron output.

Log lines pass through a sluice of increasingly expensive gates. The cheap
gates run on every line; the expensive ones run rarely and only on what the
cheap gates let through.

1. Channel: a line written to stderr is a candidate. A stdout line is only a
   candidate if it matches a strong pattern, since many tools write ordinary
   logs to stderr and errors rarely go to stdout unflagged.
2. Regex: strong patterns (tracebacks, exception names, CRITICAL/FATAL,
   crashes) mark a line as a genuine error signal. Weak patterns (the words
   error, exception, failed) keep the line as context. Ignore patterns drop
   access-log lines and "0 errors" style output before either check.
3. Jev (TypeSafe System One): when a window holds strong hits and the
   per-service interval has elapsed, the recent candidate lines are sent as
   one typed-classification request. Jev returns the kind of failure with a
   probability per option, plus whether the service's own code could fix it.
   No text is generated, so the call costs a fraction of a cent.
4. LLM: the decision to hand the incident to a coding agent is made by the
   caller (fixer.py) from the Jev verdict, its own cooldowns and caps.

This module owns tiers 1 to 3: line classification, the per-service window,
and the Jev client. It keeps no reference to processes or fixing.
"""

import logging
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from .config import config

logger = logging.getLogger(__name__)

# Lines matching these are dropped before any other check.
IGNORE_PATTERNS = [
    # HTTP access log lines: '"GET /path HTTP/1.1" 500'
    r'"(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) [^"]*"\s+\d{3}\b',
    r"(?i)\b(?:0|no|zero) errors?\b",
    r"(?i)['\"]?errors?['\"]?\s*[:=]\s*0\b",
    r"(?i)\berror[_ ]?(?:rate|count|handler|page|log|_message)\b",
    r"(?i)\bon_error\b|\berror_callback\b",
]

# A single line matching one of these is a real error signal.
STRONG_PATTERNS = [
    r"Traceback \(most recent call last\)",
    r"^\s*(?:[\w.]+\.)?[A-Z]\w*(?:Error|Exception|Interrupt)\b\s*(?::|$)",
    r"Exception in thread",
    r"Unhandled (?:exception|error|promise rejection)",
    r"\b(?:CRITICAL|FATAL)\b",
    r"(?i)\bsegmentation fault\b|\bcore dumped\b|^\s*panic:",
    r"(?i)\bout of memory\b|\bOOM\b",
    r"(?i)disk I/O error|no space left on device",
    # Logger-level ERROR records, e.g. "2026-01-01 ERROR name message" or "ERROR:    ..."
    r"^(?:\[?[\d:.,T -]{8,}\]?\s*)?(?:\[\s*)?ERROR\b",
]

# These keep a line as context but do not on their own trigger anything.
WEAK_PATTERNS = [
    r"(?i)\berror\b",
    r"(?i)\bexception\b",
    r"(?i)\bfailed\b|\bfailure\b",
    r"(?i)\btimed? ?out\b",
    r"(?i)\brefused\b",
]

WARNING_PATTERNS = [r"(?i)\bwarn(?:ing)?\b"]

_IGNORE = [re.compile(p) for p in IGNORE_PATTERNS]
_STRONG = [re.compile(p) for p in STRONG_PATTERNS]
_WEAK = [re.compile(p) for p in WEAK_PATTERNS]
_WARNING = [re.compile(p) for p in WARNING_PATTERNS]

STDERR = "stderr"
STDOUT = "stdout"


def classify_line(stream: str, message: str) -> str | None:
    """Return "strong", "weak", or None for a single output line.

    Tier 1 (channel) and tier 2 (regex) together. A stdout line must match a
    strong pattern to count at all; a stderr line counts as weak if it
    matches any weak pattern.
    """
    if any(p.search(message) for p in _IGNORE):
        return None
    if any(p.search(message) for p in _STRONG):
        return "strong"
    if stream == STDERR and any(p.search(message) for p in _WEAK):
        return "weak"
    return None


def detect_level(stream: str, message: str) -> str:
    """Map a line to the log level stored in the database: info, warning, or error."""
    signal = classify_line(stream, message)
    if signal == "strong":
        return "error"
    if signal == "weak":
        return "error" if any(p.search(message) for p in _WEAK[:2]) else "warning"
    if any(p.search(message) for p in _WARNING):
        return "warning"
    return "info"


@dataclass
class Window:
    """Recent candidate lines for one service, with tier 3 bookkeeping."""

    lines: deque = field(default_factory=lambda: deque(maxlen=config.sluice_window_lines))
    strong_since_review: int = 0
    last_review: datetime | None = None
    reviewing: bool = False

    def add(self, stream: str, message: str, signal: str):
        self.lines.append((datetime.now(), stream, message))
        if signal == "strong":
            self.strong_since_review += 1

    def due_for_review(self, now: datetime | None = None) -> bool:
        """True when strong hits have arrived and the review interval has elapsed."""
        if self.reviewing or self.strong_since_review == 0:
            return False
        now = now or datetime.now()
        if self.last_review and now - self.last_review < timedelta(minutes=config.jev_interval_minutes):
            return False
        return True

    def take_sample(self) -> str:
        """Render the window as text for review and reset the strong counter."""
        self.strong_since_review = 0
        self.last_review = datetime.now()
        return render_lines(self.lines)

    def clear(self):
        self.lines.clear()
        self.strong_since_review = 0


def render_lines(lines, max_chars: int = None) -> str:
    """Render (timestamp, stream, message) tuples oldest first, newest kept on overflow."""
    max_chars = max_chars or config.sluice_sample_chars
    rendered = []
    for ts, stream, message in lines:
        tag = "E" if stream == STDERR else "O"
        rendered.append(f"[{tag}] {message[:500]}")
    text = "\n".join(rendered)
    if len(text) > max_chars:
        text = text[-max_chars:]
        text = text[text.find("\n") + 1 :]
    return text


def lines_from_text(text: str, stream: str):
    """Split captured output into window tuples, keeping only candidate lines."""
    now = datetime.now()
    out = []
    for raw in text.splitlines():
        message = raw.rstrip()
        if not message:
            continue
        signal = classify_line(stream, message)
        if signal:
            out.append((now, stream, message, signal))
    return out


# -- Tier 3: Jev --

JEV_PREAMBLE = (
    "You are triaging the recent output of a long-running service on a developer's home server. "
    "The state lists recent output lines, oldest first; [E] marks stderr and [O] marks stdout. "
    "Judge the most serious failure present. "
)

JEV_KINDS = {
    "code_bug": (
        "A defect in this service's own source code: a traceback whose deepest frame is in the "
        "project's own files, a TypeError, AttributeError, KeyError, NameError or SyntaxError in "
        "project code, a wrong assumption about data shape, or a misconfiguration inside the repo."
    ),
    "dependency": (
        "A library or runtime problem: ImportError or ModuleNotFoundError, a traceback whose deepest "
        "frame is inside site-packages, an attribute missing from an installed package, an API change "
        "in a dependency, or a version mismatch. Fixable by changing pins or the calling code."
    ),
    "external": (
        "A failure of something outside this host: HTTP 4xx or 5xx from another server, connection "
        "refused or timeout to a remote address, DNS, captcha, rate limiting, expired credentials for a "
        "third-party API, an upstream feed missing. Editing this service's code would not resolve it."
    ),
    "environment": (
        "A problem with this host: disk full or disk I/O error, permission denied on a local path, port "
        "already in use, out of memory, a missing system binary or device such as a camera or GPU."
    ),
    "noise": (
        "Not a real failure: access-log lines, handled warnings, the word error appearing in ordinary "
        "output, expected retries that succeeded, informational messages, or lines the service logs on "
        "every request."
    ),
}

JEV_TIE_BREAK = (
    "If a traceback ends inside the project's own files choose code_bug even if a library is involved. "
    "If the only errors are HTTP status codes or connection failures to other hosts choose external. "
    "If lines merely contain the word error but describe normal handled behaviour choose noise."
)


@dataclass
class JevVerdict:
    """Typed answer from Jev for one window of output."""

    kind: str
    probabilities: dict[str, float]
    fixable: float
    persistent: float
    input_tokens: int
    model: str

    @property
    def kind_probability(self) -> float:
        return self.probabilities.get(self.kind, 0.0)

    def should_escalate(self) -> bool:
        """True when Jev thinks this is a code or dependency fault the repo can fix."""
        actionable = self.probabilities.get("code_bug", 0.0) + self.probabilities.get("dependency", 0.0)
        return actionable >= config.jev_threshold and self.fixable >= config.jev_fixable_threshold

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "probabilities": self.probabilities,
            "fixable": self.fixable,
            "persistent": self.persistent,
            "input_tokens": self.input_tokens,
            "model": self.model,
        }


def build_jev_request(name: str, command: str, sample: str) -> dict:
    """Assemble the one-request, three-question Jev payload."""
    state = f"Service: {name}\nCommand: {command}\n\nRecent output:\n{sample}"
    return {
        "state": state,
        "model": config.typesafe_model,
        "questions": {
            "kind": {
                "type": "choice",
                "instructions": JEV_PREAMBLE + "What kind of failure is shown? " + JEV_TIE_BREAK,
                "criteria": JEV_KINDS,
            },
            "fixable": {
                "type": "noul",
                "instructions": JEV_PREAMBLE
                + "A developer could resolve the failure by editing this service's own repository "
                "(its source files, dependency pins, or in-repo configuration) without changing other "
                "machines, other services, or third-party accounts.",
            },
            "persistent": {
                "type": "noul",
                "instructions": JEV_PREAMBLE
                + "The failure is repeating or ongoing rather than a single transient event.",
            },
        },
    }


def parse_jev_response(body: dict) -> JevVerdict:
    answers = body["answers"]
    kind = answers["kind"]
    return JevVerdict(
        kind=kind["choice"],
        probabilities={k: float(v) for k, v in kind.get("probabilities", {}).items()},
        fixable=float(answers["fixable"]["noul"]),
        persistent=float(answers["persistent"]["noul"]),
        input_tokens=int(body.get("usage", {}).get("input_tokens", 0)),
        model=body.get("model", config.typesafe_model),
    )


async def jev_review(name: str, command: str, sample: str) -> JevVerdict | None:
    """Send one window to Jev. Returns None when Jev is unconfigured or unreachable."""
    if not config.typesafe_api_key:
        logger.warning("TYPESAFE_API_KEY not set; Jev tier disabled")
        return None
    payload = build_jev_request(name, command, sample)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                config.typesafe_url,
                headers={"Authorization": f"Bearer {config.typesafe_api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            verdict = parse_jev_response(resp.json())
    except Exception as e:
        logger.error(f"Jev review failed for {name}: {e}")
        return None
    logger.info(
        f"Jev {name}: {verdict.kind} p={verdict.kind_probability:.2f} "
        f"fixable={verdict.fixable:.2f} persistent={verdict.persistent:.2f} "
        f"tokens={verdict.input_tokens}"
    )
    return verdict
