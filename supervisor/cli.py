"""
CLI client for the supervisor service.

Provides subcommands to manage services and cron jobs on a running supervisor
server. Communicates with the server's HTTP API using httpx. When invoked with
no arguments (or the 'serve' subcommand), starts the server directly.
"""

import argparse
import json
import os
import sys

import httpx

BASE_URL = os.environ.get("SUPERVISOR_URL", "http://localhost:9900")
TIMEOUT = 30.0


def client():
    """Create an httpx client pointed at the supervisor server."""
    return httpx.Client(base_url=BASE_URL, timeout=TIMEOUT)


def api_request(method, path, **kwargs):
    """Make an API request and handle common errors."""
    try:
        with client() as c:
            resp = getattr(c, method)(path, **kwargs)
    except httpx.ConnectError:
        print("Error: supervisor server is not running", file=sys.stderr)
        sys.exit(1)
    except httpx.TimeoutException:
        print("Error: request timed out", file=sys.stderr)
        sys.exit(1)

    if resp.status_code == 404:
        detail = resp.json().get("detail", "not found")
        print(f"Error: {detail}", file=sys.stderr)
        sys.exit(1)
    elif resp.status_code == 409:
        detail = resp.json().get("detail", "conflict")
        print(f"Error: {detail}", file=sys.stderr)
        sys.exit(1)
    elif resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        print(f"Error ({resp.status_code}): {detail}", file=sys.stderr)
        sys.exit(1)

    return resp.json()


# -- Formatting helpers --

def print_table(rows, headers):
    """Print aligned columns from a list of row dicts."""
    if not rows:
        print("(none)")
        return

    # Extract values in header order
    table = []
    for row in rows:
        table.append([str(row.get(h, "")) for h in headers])

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in table:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(val))

    # Print header
    header_line = "  ".join(h.upper().ljust(widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("  ".join("-" * w for w in widths))

    # Print rows
    for row in table:
        print("  ".join(val.ljust(widths[i]) for i, val in enumerate(row)))


def format_bytes(n):
    """Format bytes as human-readable string."""
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


# -- Service commands --

def cmd_status(args):
    """Show overview of all services with resource usage."""
    data = api_request("get", "/api/status")
    rows = []
    for s in data["services"]:
        m = s.get("metrics") or {}
        rows.append({
            "name": s["name"],
            "state": "running" if s["running"] else ("stopped" if s["enabled"] else "disabled"),
            "port": str(s["port"] or "-"),
            "pid": str(s["pid"] or "-"),
            "cpu": f"{m['cpu_percent']:.0f}%" if m.get("cpu_percent") is not None else "-",
            "mem": format_bytes(m.get("memory_rss")),
        })
    print_table(rows, ["name", "state", "port", "pid", "cpu", "mem"])
    print(f"\n{data['running']}/{data['total']} running, {data['enabled']} enabled")


def cmd_ls(args):
    """List all registered services."""
    services = api_request("get", "/api/services")
    rows = []
    for s in services:
        rows.append({
            "name": s["name"],
            "state": "running" if s["running"] else ("stopped" if s["enabled"] else "disabled"),
            "port": str(s.get("port") or "-"),
            "command": s["command"],
        })
    print_table(rows, ["name", "state", "port", "command"])


def cmd_start(args):
    """Start a service."""
    data = api_request("post", f"/api/services/{args.name}/start")
    if data.get("status") == "already_running":
        print(f"{args.name}: already running")
    else:
        print(f"{args.name}: started (pid {data.get('pid', '?')})")


def cmd_stop(args):
    """Stop a service."""
    data = api_request("post", f"/api/services/{args.name}/stop")
    if data.get("status") == "not_running":
        print(f"{args.name}: not running")
    else:
        print(f"{args.name}: stopped")


def cmd_restart(args):
    """Restart a service."""
    data = api_request("post", f"/api/services/{args.name}/restart")
    print(f"{args.name}: restarted (pid {data.get('pid', '?')})")


def cmd_logs(args):
    """Show recent logs for a service."""
    params = {"limit": args.limit}
    if args.level:
        params["level"] = args.level
    logs = api_request("get", f"/api/services/{args.name}/logs", params=params)
    for entry in reversed(logs):
        ts = entry.get("timestamp", "")[:19]
        level = entry.get("level", "").upper()
        msg = entry.get("message", "")
        print(f"{ts}  {level:7s}  {msg}")
    if not logs:
        print("(no logs)")


def cmd_add(args):
    """Register a new service."""
    payload = {
        "name": args.name,
        "command": args.run_command,
    }
    if args.dir:
        payload["working_dir"] = args.dir
    if args.port is not None:
        payload["port"] = args.port
    if args.caddy_subdomain:
        payload["expose_caddy"] = True
        payload["caddy_subdomain"] = args.caddy_subdomain
    if args.disabled:
        payload["enabled"] = False

    data = api_request("post", "/api/services", json=payload)
    state = "running" if data.get("running") else "registered"
    print(f"{data['name']}: {state}")


def cmd_rm(args):
    """Remove a service."""
    data = api_request("delete", f"/api/services/{args.name}")
    print(f"{data['name']}: removed")


# -- Cron commands --

def cmd_cron_ls(args):
    """List all cron jobs."""
    jobs = api_request("get", "/api/cron")
    rows = []
    for j in jobs:
        rows.append({
            "name": j["name"],
            "state": "running" if j.get("running") else ("enabled" if j["enabled"] else "disabled"),
            "schedule": j["schedule"],
            "description": j.get("schedule_description", ""),
        })
    print_table(rows, ["name", "state", "schedule", "description"])


def cmd_cron_status(args):
    """Show cron job overview with execution stats."""
    data = api_request("get", "/api/cron/status")
    rows = []
    for j in data["jobs"]:
        last = j.get("last_run")
        if last:
            last = last[:19]
        nxt = j.get("next_run")
        if nxt:
            nxt = nxt[:19]
        rows.append({
            "name": j["name"],
            "state": "running" if j["running"] else ("enabled" if j["enabled"] else "disabled"),
            "schedule": j["schedule"],
            "last_run": last or "-",
            "next_run": nxt or "-",
            "24h": str(j.get("executions_24h", 0)),
            "fail": str(j.get("failures_24h", 0)),
        })
    print_table(rows, ["name", "state", "schedule", "last_run", "next_run", "24h", "fail"])
    print(f"\n{data['running']}/{data['total']} running, {data['enabled']} enabled")


def cmd_cron_run(args):
    """Manually trigger a cron job."""
    data = api_request("post", f"/api/cron/{args.name}/run")
    if data.get("status") == "already_running":
        print(f"{args.name}: already running")
    else:
        print(f"{args.name}: started (execution {data.get('execution_id', '?')})")


def cmd_cron_stop(args):
    """Stop a running cron job."""
    data = api_request("post", f"/api/cron/{args.name}/stop")
    if data.get("status") == "not_running":
        print(f"{args.name}: not running")
    else:
        print(f"{args.name}: stopped")


def cmd_cron_logs(args):
    """Show execution history for a cron job."""
    params = {"limit": args.limit}
    executions = api_request("get", f"/api/cron/{args.name}/executions", params=params)
    for ex in executions:
        started = ex.get("started_at", "")[:19]
        duration = ex.get("duration")
        dur_str = f"{duration:.1f}s" if duration is not None else "-"
        success = "ok" if ex.get("success") else "FAIL"
        output = (ex.get("output") or "")[:120]
        print(f"{started}  {dur_str:>7s}  {success:4s}  {output}")
    if not executions:
        print("(no executions)")


def cmd_cron_add(args):
    """Register a new cron job."""
    payload = {
        "name": args.name,
        "command": args.run_command,
        "schedule": args.schedule,
    }
    if args.dir:
        payload["working_dir"] = args.dir
    if args.timeout is not None:
        payload["timeout"] = args.timeout
    if args.env_file:
        payload["env_file"] = args.env_file
    if args.disabled:
        payload["enabled"] = False

    data = api_request("post", "/api/cron", json=payload)
    print(f"{data['name']}: added ({data.get('schedule_description', data['schedule'])})")


def cmd_cron_rm(args):
    """Remove a cron job."""
    data = api_request("delete", f"/api/cron/{args.name}")
    print(f"{data['name']}: removed")


# -- Other commands --

def cmd_onboard(args):
    """Onboard a project via AI analysis."""
    payload = {
        "project": args.project,
    }
    if args.model:
        payload["model"] = args.model
    if args.port is not None:
        payload["port"] = args.port

    data = api_request("post", "/api/onboard", json=payload)
    print(f"Onboarding {args.project} (job {data['job_id']})")
    print(f"Track progress: curl {BASE_URL}/api/jobs/{data['job_id']}")


def cmd_projects(args):
    """List available projects."""
    data = api_request("get", "/api/projects")
    for p in data.get("projects", []):
        print(p["name"])


def cmd_install_skill(args):
    """Copy SKILL.md to Claude's skills directory."""
    from pathlib import Path
    import shutil

    src = Path(__file__).parent.parent / "SKILL.md"
    dest_dir = Path.home() / ".claude" / "skills" / "supervisor"
    dest = dest_dir / "SKILL.md"

    if not src.exists():
        print("Error: SKILL.md not found in project root", file=sys.stderr)
        sys.exit(1)

    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"Installed {dest}")


def cmd_serve(args):
    """Start the supervisor server."""
    import uvicorn
    from .config import config
    uvicorn.run(
        "supervisor.main:app",
        host=config.host,
        port=config.port,
        reload=False,
    )


# -- Parser --

def build_parser():
    """Build the argparse parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="supervisor",
        description="Manage services and cron jobs on a supervisor instance",
    )
    sub = parser.add_subparsers(dest="command")

    # serve
    sub.add_parser("serve", help="Start the supervisor server")

    # status
    sub.add_parser("status", help="Overview of all services with resource usage")

    # ls
    sub.add_parser("ls", help="List registered services")

    # start
    p = sub.add_parser("start", help="Start a service")
    p.add_argument("name", help="Service name")

    # stop
    p = sub.add_parser("stop", help="Stop a service")
    p.add_argument("name", help="Service name")

    # restart
    p = sub.add_parser("restart", help="Restart a service")
    p.add_argument("name", help="Service name")

    # logs
    p = sub.add_parser("logs", help="Show service logs")
    p.add_argument("name", help="Service name")
    p.add_argument("--level", choices=["info", "warning", "error"], help="Filter by level")
    p.add_argument("--limit", type=int, default=50, help="Number of entries (default: 50)")

    # add
    p = sub.add_parser("add", help="Register a new service")
    p.add_argument("name", help="Service name")
    p.add_argument("run_command", metavar="command", help="Command to run")
    p.add_argument("--dir", help="Working directory")
    p.add_argument("--port", type=int, help="Port the service listens on")
    p.add_argument("--caddy-subdomain", help="Expose via Caddy with this subdomain")
    p.add_argument("--disabled", action="store_true", help="Register without starting")

    # rm
    p = sub.add_parser("rm", help="Remove a service")
    p.add_argument("name", help="Service name")

    # cron
    cron_parser = sub.add_parser("cron", help="Cron job management")
    cron_sub = cron_parser.add_subparsers(dest="cron_command")

    # cron ls
    cron_sub.add_parser("ls", help="List cron jobs")

    # cron status
    cron_sub.add_parser("status", help="Cron job overview with stats")

    # cron run
    p = cron_sub.add_parser("run", help="Manually trigger a cron job")
    p.add_argument("name", help="Cron job name")

    # cron stop
    p = cron_sub.add_parser("stop", help="Stop a running cron job")
    p.add_argument("name", help="Cron job name")

    # cron logs
    p = cron_sub.add_parser("logs", help="Show cron job execution history")
    p.add_argument("name", help="Cron job name")
    p.add_argument("--limit", type=int, default=20, help="Number of entries (default: 20)")

    # cron add
    p = cron_sub.add_parser("add", help="Register a new cron job")
    p.add_argument("name", help="Cron job name")
    p.add_argument("run_command", metavar="command", help="Command to run")
    p.add_argument("schedule", help="Cron expression (e.g. '*/15 * * * *')")
    p.add_argument("--dir", help="Working directory")
    p.add_argument("--timeout", type=int, help="Execution timeout in seconds")
    p.add_argument("--env-file", help="Path to .env file")
    p.add_argument("--disabled", action="store_true", help="Add without enabling")

    # cron rm
    p = cron_sub.add_parser("rm", help="Remove a cron job")
    p.add_argument("name", help="Cron job name")

    # onboard
    p = sub.add_parser("onboard", help="Onboard a project via AI")
    p.add_argument("project", help="Project name or path")
    p.add_argument("--model", default="opus", help="AI model (default: opus)")
    p.add_argument("--port", type=int, help="Requested port number")

    # projects
    sub.add_parser("projects", help="List ~/Code/ projects")

    # install-skill
    sub.add_parser("install-skill", help="Install Claude skill to ~/.claude/skills/")

    return parser


def main():
    """Entry point for the supervisor CLI."""
    parser = build_parser()
    args = parser.parse_args()

    # No subcommand -> start server
    if args.command is None:
        cmd_serve(args)
        return

    dispatch = {
        "serve": cmd_serve,
        "status": cmd_status,
        "ls": cmd_ls,
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "logs": cmd_logs,
        "add": cmd_add,
        "rm": cmd_rm,
        "onboard": cmd_onboard,
        "projects": cmd_projects,
        "install-skill": cmd_install_skill,
    }

    if args.command == "cron":
        cron_dispatch = {
            "ls": cmd_cron_ls,
            "status": cmd_cron_status,
            "run": cmd_cron_run,
            "stop": cmd_cron_stop,
            "logs": cmd_cron_logs,
            "add": cmd_cron_add,
            "rm": cmd_cron_rm,
        }
        if not args.cron_command:
            # Default to cron ls
            cmd_cron_ls(args)
        else:
            cron_dispatch[args.cron_command](args)
    else:
        dispatch[args.command](args)
