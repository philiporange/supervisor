"""
Robot AI integration for project onboarding, security scanning, and chat.

This module resolves project paths, builds task-specific prompts, and runs the
`robot` CLI in both one-shot and streamed modes. Onboarding is handled through a
dedicated agent prompt so chat messages like "onboard ~/Code/foo" can trigger
the full registration workflow while exposing granular status updates from the
agent as it analyzes and configures the project.
"""

import asyncio
import json
import logging
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
CODE_DIR = Path.home() / "Code"


def get_existing_services_context() -> str:
    """Build a summary of currently registered services and their ports."""
    from .models import Service

    services = Service.select()
    if not services:
        return "No services are currently registered."

    lines = []
    for s in services:
        status = "enabled" if s.enabled else "disabled"
        port_str = str(s.port) if s.port else "no port"
        lines.append(f"- {s.name}: port {port_str} ({status})")

    used_ports = sorted(s.port for s in services if s.port)
    lines.append(f"\nPorts already in use: {', '.join(str(p) for p in used_ports)}")

    return "\n".join(lines)


def get_onboard_prompt(project_path: str, project_name: str, port: int = None) -> str:
    """Load and format the onboard prompt template with live service context."""
    template_path = PROMPTS_DIR / "onboard.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Onboard prompt template not found: {template_path}")

    if port:
        requested_port = f"- Requested port: {port}"
        port_instruction = f"Use port {port} as requested by the user."
    else:
        requested_port = ""
        port_instruction = (
            "Pick a port that does not conflict with existing services (listed above). "
            "If the project has a default port that is already taken, pick the next available port."
        )

    template = template_path.read_text()
    return template.format(
        project_path=project_path,
        project_name=project_name,
        existing_services=get_existing_services_context(),
        requested_port=requested_port,
        port_instruction=port_instruction,
    )


def resolve_project_path(project: str) -> tuple[str, str]:
    """
    Resolve a project name or path to full path and name.

    Args:
        project: Either a project name (in ~/Code/) or a full path

    Returns:
        Tuple of (full_path, project_name)
    """
    # If it's just a name, assume ~/Code/<name>
    if "/" not in project and not project.startswith("~"):
        project_path = (CODE_DIR / project).resolve()
        project_name = project
    else:
        project_path = Path(project).expanduser().resolve()
        project_name = project_path.name

    if not project_path.exists():
        raise FileNotFoundError(f"Project not found: {project_path}")

    return str(project_path), project_name


def parse_onboard_request(message: str) -> tuple[Optional[str], Optional[int]]:
    """
    Parse a chat message that requests project onboarding.

    Supported forms include:
    - `onboard myproject`
    - `onboard ~/Code/myproject`
    - `onboard ~/Code/myproject --port 8010`
    - `onboard myproject port 8010`
    """
    try:
        tokens = shlex.split(message)
    except ValueError:
        return None, None

    if not tokens:
        return None, None

    command = tokens[0].lower().rstrip(":")
    if command not in {"onboard", "/onboard"}:
        return None, None

    project = None
    port = None
    i = 1
    while i < len(tokens):
        token = tokens[i]
        lowered = token.lower()
        if lowered in {"--port", "-p", "port"} and i + 1 < len(tokens):
            try:
                port = int(tokens[i + 1])
            except ValueError:
                return None, None
            i += 2
            continue

        if project is None:
            project = token
        i += 1

    return project, port


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from robot CLI output."""
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


def _classify_robot_output(line: str) -> dict:
    """Classify a single robot output line into a frontend-friendly event."""
    cleaned = _strip_ansi(line).strip()
    if not cleaned:
        return {"type": "status", "content": ""}

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    if cleaned.startswith(("→", "·", "▶", "✓")):
        return {"type": "status", "content": cleaned}
    if cleaned.startswith(("Usage:", "Try 'robot", "Error:")):
        return {"type": "error", "content": cleaned}
    return {"type": "text", "content": cleaned}


async def _stream_robot_command(
    cmd: list[str],
    timeout: int,
    on_event: Optional[Callable[[dict], None]] = None,
) -> tuple[int, str]:
    """Run a robot command, streaming parsed events while capturing a transcript."""
    logger.info("Starting robot command: %s", " ".join(cmd[:6]))
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    transcript_lines: list[str] = []
    buffer = ""

    async def emit_line(raw_line: str):
        event = _classify_robot_output(raw_line)
        if event["content"]:
            transcript_lines.append(event["content"])
        if on_event and event["content"]:
            on_event(event)

    try:
        while True:
            chunk = await asyncio.wait_for(process.stdout.read(1024), timeout=timeout)
            if not chunk:
                break

            buffer += chunk.decode("utf-8", errors="replace").replace("\r", "\n")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                await emit_line(line)

        if buffer.strip():
            await emit_line(buffer)

        returncode = await asyncio.wait_for(process.wait(), timeout=timeout)
        return returncode, "\n".join(transcript_lines).strip()
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)


async def run_robot_onboard(
    project: str,
    model: str = "opus",
    port: int = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Run robot to onboard a project to supervisor.

    Args:
        project: Project name or path
        model: Model to use (default: opus)
        port: Optional requested port number

    Returns:
        Dict with success status and output
    """
    if not shutil.which("robot"):
        raise RuntimeError(
            "robot CLI not found in PATH. Install it with: pip install robot-cli"
        )

    project_path, project_name = resolve_project_path(project)
    prompt = get_onboard_prompt(project_path, project_name, port)

    logger.info(f"Onboarding project: {project_name} from {project_path}")

    if progress_callback:
        progress_callback(f"Preparing onboarding for {project_name}")

    def handle_event(event: dict):
        content = event.get("content", "").strip()
        if not content:
            return
        if progress_callback and event.get("type") == "status":
            progress_callback(content)

    returncode, output = await _stream_robot_command(
        [
            "robot",
            "run",
            "-m", model,
            "-d", project_path,
            "-t", "600",
            "-s",
            prompt,
        ],
        timeout=660,
        on_event=handle_event,
    )

    if returncode != 0:
        raise RuntimeError(output or "Onboard process failed")

    return {
        "success": True,
        "project_name": project_name,
        "project_path": project_path,
        "output": output,
    }


def get_security_scan_prompt(service_name: str, service_url: str, port: int) -> str:
    """Load and format the security scan prompt template."""
    template_path = PROMPTS_DIR / "security_scan.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Security scan prompt template not found: {template_path}")

    template = template_path.read_text()
    return template.format(
        service_name=service_name,
        service_url=service_url,
        port=port,
    )


async def run_security_scan(
    service_name: str,
    service_url: str,
    port: int,
    model: str = "sonnet",
) -> dict:
    """
    Run a security scan against a web service.

    Args:
        service_name: Name of the service being scanned
        service_url: Full URL to scan (e.g., https://myapp.ph1l.uk:60443)
        port: Service port
        model: Model to use (default: sonnet for speed)

    Returns:
        Dict with scan results in RAG format
    """
    prompt = get_security_scan_prompt(service_name, service_url, port)

    logger.info(f"Running security scan: {service_name} at {service_url}")

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "robot",
                "run",
                "-m", model,
                "-t", "300",  # 5 minute timeout
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=360,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "service_name": service_name,
                "url": service_url,
                "error": result.stderr or "Security scan failed",
            }

        # Parse JSON from output - robot may include other text
        output = result.stdout.strip()

        # Try to extract JSON from the output
        json_start = output.find("{")
        json_end = output.rfind("}") + 1

        if json_start != -1 and json_end > json_start:
            json_str = output[json_start:json_end]
            try:
                scan_results = json.loads(json_str)
                scan_results["success"] = True
                return scan_results
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse scan results JSON: {e}")
                return {
                    "success": False,
                    "service_name": service_name,
                    "url": service_url,
                    "error": f"Failed to parse scan results: {e}",
                    "raw_output": output,
                }
        else:
            return {
                "success": False,
                "service_name": service_name,
                "url": service_url,
                "error": "No JSON found in scan output",
                "raw_output": output,
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "service_name": service_name,
            "url": service_url,
            "error": "Security scan timed out after 5 minutes",
        }
    except Exception as e:
        logger.error(f"Error running security scan: {e}")
        return {
            "success": False,
            "service_name": service_name,
            "url": service_url,
            "error": str(e),
        }


async def stream_robot_chat(
    message: str,
    project: Optional[str] = None,
    model: str = "opus",
    session_id: Optional[str] = None,
) -> AsyncIterator[dict]:
    """
    Stream chat with robot AI agent.

    Args:
        message: User message
        project: Optional project context (name or path)
        model: Model to use
        session_id: Optional session ID to resume conversation

    Yields:
        Dict events with type and content
    """
    project_path = None
    if project:
        try:
            project_path, _ = resolve_project_path(project)
        except FileNotFoundError:
            yield {"type": "error", "content": f"Project not found: {project}"}
            return

    onboard_project, requested_port = parse_onboard_request(message)
    if onboard_project or (message.strip().lower().startswith(("onboard", "/onboard")) and project):
        target_project = onboard_project or project
        async for event in stream_robot_onboard(
            project=target_project,
            model=model,
            port=requested_port,
        ):
            yield event
        return

    # Build command
    cmd = ["robot", "run", "-m", model, "-s"]  # -s for streaming

    if project_path:
        cmd.extend(["-d", project_path])

    cmd.append(message)

    logger.info(f"Starting robot chat: model={model}, project={project}")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Stream stdout
        async def read_stream():
            buffer = ""
            while True:
                chunk = await process.stdout.read(1024)
                if not chunk:
                    break

                text = chunk.decode("utf-8", errors="replace")
                buffer += text

                # Try to parse JSON lines (robot streams JSON events)
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event = json.loads(line)
                        yield event
                    except json.JSONDecodeError:
                        # Plain text output
                        yield {"type": "text", "content": line}

            # Remaining buffer
            if buffer.strip():
                yield {"type": "text", "content": buffer.strip()}

        async for event in read_stream():
            yield event

        # Wait for process to complete
        await process.wait()

        if process.returncode != 0:
            stderr = await process.stderr.read()
            error_msg = stderr.decode("utf-8", errors="replace")
            yield {"type": "error", "content": error_msg}

        yield {"type": "done", "content": ""}

    except Exception as e:
        logger.error(f"Error in robot chat: {e}")
        yield {"type": "error", "content": str(e)}


async def stream_robot_onboard(
    project: str,
    model: str = "opus",
    port: int = None,
) -> AsyncIterator[dict]:
    """Stream onboarding progress and final output for a project."""
    if not shutil.which("robot"):
        yield {
            "type": "error",
            "content": "robot CLI not found in PATH. Install it with: pip install robot-cli",
        }
        return

    try:
        project_path, project_name = resolve_project_path(project)
        prompt = get_onboard_prompt(project_path, project_name, port)
    except FileNotFoundError as exc:
        yield {"type": "error", "content": str(exc)}
        return

    yield {"type": "status", "content": f"Preparing onboarding for {project_name}"}
    yield {"type": "status", "content": f"Resolved project path: {project_path}"}

    events: list[dict] = []

    def capture_event(event: dict):
        if event.get("content"):
            events.append(event)

    try:
        returncode, output = await _stream_robot_command(
            [
                "robot",
                "run",
                "-m", model,
                "-d", project_path,
                "-t", "600",
                "-s",
                prompt,
            ],
            timeout=660,
            on_event=capture_event,
        )
    except subprocess.TimeoutExpired:
        yield {"type": "error", "content": "Onboarding timed out after 10 minutes"}
        yield {"type": "done", "content": ""}
        return
    except Exception as exc:
        logger.error("Error in robot onboarding stream: %s", exc)
        yield {"type": "error", "content": str(exc)}
        yield {"type": "done", "content": ""}
        return

    for event in events:
        yield event

    if returncode != 0:
        yield {"type": "error", "content": output or "Onboard process failed"}
        yield {"type": "done", "content": ""}
        return

    yield {"type": "result", "content": output}
    yield {"type": "done", "content": ""}


def get_system_prompt_for_chat(project_path: Optional[str] = None) -> str:
    """Generate system prompt for chat mode."""
    base_prompt = """You are an AI assistant helping manage services with Supervisor.

You can help with:
- Analyzing and onboarding new projects
- Debugging service issues
- Viewing logs and metrics
- Configuring services
- General coding assistance

The Supervisor API is available at http://localhost:9900 with these endpoints:
- GET /api/services - List all services
- POST /api/services - Register new service
- GET /api/services/{name} - Get service details
- POST /api/services/{name}/start - Start service
- POST /api/services/{name}/stop - Stop service
- POST /api/services/{name}/restart - Restart service
- GET /api/services/{name}/logs - Get service logs
- GET /api/services/{name}/metrics - Get resource history

Default data directory pattern: ~/.{project_name}/ for databases, logs, and cache.
"""

    if project_path:
        base_prompt += f"\n\nCurrent project context: {project_path}"

    return base_prompt
