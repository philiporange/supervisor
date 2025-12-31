"""
Supervisor FastAPI application.

Provides REST API for managing services and cron jobs, viewing logs and metrics,
triggering auto-fixes, and managing Caddy configuration. Cron jobs are triggered
via a /api/cron/tick endpoint called by system cron every minute.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .caddy import generate_caddyfile, get_caddy_config, reload_caddy
from .config import config
from .cron import cron_manager
from .fixer import auto_fixer
from .robot_integration import run_robot_onboard, run_security_scan, stream_robot_chat, resolve_project_path
from .jobs import JobStatus, job_manager
from .models import CronExecution, CronJob, FixAttempt, LogEntry, Metric, Service, initialize_db
from .monitor import resource_monitor
from .process import process_manager

# Configure logging with rotation
log_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Rotating file handler (auto-compaction)
file_handler = RotatingFileHandler(
    config.supervisor_log,
    maxBytes=config.log_max_bytes,
    backupCount=config.log_backup_count,
)
file_handler.setFormatter(log_formatter)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler],
)
logger = logging.getLogger(__name__)

# Initialize database
initialize_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup
    logger.info("Starting supervisor...")

    # Wire up log callback to auto-fixer
    def log_callback(service_name: str, level: str, message: str):
        # Save to database
        service = Service.get_or_none(Service.name == service_name)
        if service:
            LogEntry.create(service=service, level=level, message=message[:2000])
        # Notify auto-fixer
        auto_fixer.on_log(service_name, level, message)

    process_manager.set_log_callback(log_callback)

    # Wire up cron fix callback
    cron_manager.set_fix_callback(auto_fixer.fix_cron_job)

    # Start enabled services
    for service in Service.select().where(Service.enabled == True):
        if not process_manager.is_running(service.name):
            logger.info(f"Starting service: {service.name}")
            process_manager.start(service)

    # Update next run times for all cron jobs
    for cron_job in CronJob.select().where(CronJob.enabled == True):
        cron_manager.update_next_run(cron_job)

    # Start background tasks
    await resource_monitor.start()
    await auto_fixer.start()

    # Start crash monitor
    crash_monitor_task = asyncio.create_task(crash_monitor_loop())

    yield

    # Shutdown
    logger.info("Shutting down supervisor...")
    crash_monitor_task.cancel()
    await resource_monitor.stop()
    await auto_fixer.stop()
    process_manager.shutdown_all()


async def crash_monitor_loop():
    """Background task to check for crashed processes."""
    while True:
        try:
            await process_manager.check_and_restart_crashed()
        except Exception as e:
            logger.error(f"Error in crash monitor: {e}")
        await asyncio.sleep(10)


app = FastAPI(
    title="Supervisor",
    description="Service manager for Python/FastAPI projects",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates and static files
templates_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"

if templates_dir.exists():
    templates = Jinja2Templates(directory=str(templates_dir))
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# Pydantic models for API
class ServiceCreate(BaseModel):
    name: str = Field(..., description="Unique service identifier")
    command: str = Field(..., description="Command to run the service")
    working_dir: Optional[str] = Field(None, description="Working directory")
    port: Optional[int] = Field(None, description="Port the service listens on")
    enabled: bool = Field(True, description="Whether to auto-start")
    expose_caddy: bool = Field(False, description="Expose via Caddy reverse proxy")
    caddy_subdomain: Optional[str] = Field(None, description="Subdomain for Caddy routing (e.g., 'myapp' -> myapp.domain.com)")
    caddy_path: Optional[str] = Field(None, description="URL path for Caddy routing (legacy)")
    watch_dirs: Optional[list[str]] = Field(None, description="Directories to track disk usage")


class ServiceUpdate(BaseModel):
    command: Optional[str] = None
    working_dir: Optional[str] = None
    port: Optional[int] = None
    enabled: Optional[bool] = None
    expose_caddy: Optional[bool] = None
    caddy_subdomain: Optional[str] = None
    caddy_path: Optional[str] = None
    watch_dirs: Optional[list[str]] = None


class ServiceResponse(BaseModel):
    id: int
    name: str
    command: str
    working_dir: Optional[str]
    port: Optional[int]
    enabled: bool
    expose_caddy: bool
    caddy_subdomain: Optional[str]
    caddy_path: Optional[str]
    watch_dirs: list[str] = []
    created_at: str
    updated_at: str
    running: bool = False
    pid: Optional[int] = None


# Cron job models
class CronJobCreate(BaseModel):
    name: str = Field(..., description="Unique cron job identifier")
    command: str = Field(..., description="Command to run")
    schedule: str = Field(..., description="Cron expression (e.g., '*/15 * * * *')")
    working_dir: Optional[str] = Field(None, description="Working directory")
    enabled: bool = Field(True, description="Whether the job is active")
    timeout: int = Field(300, description="Execution timeout in seconds")
    watch_dirs: Optional[list[str]] = Field(None, description="Directories to track disk usage")
    env_vars: Optional[dict[str, str]] = Field(None, description="Environment variables")
    env_file: Optional[str] = Field(None, description="Path to .env file to load")


class CronJobUpdate(BaseModel):
    command: Optional[str] = None
    schedule: Optional[str] = None
    working_dir: Optional[str] = None
    enabled: Optional[bool] = None
    timeout: Optional[int] = None
    watch_dirs: Optional[list[str]] = None
    env_vars: Optional[dict[str, str]] = None
    env_file: Optional[str] = None


class CronJobResponse(BaseModel):
    id: int
    name: str
    command: str
    schedule: str
    working_dir: Optional[str]
    enabled: bool
    timeout: int
    watch_dirs: list[str] = []
    env_vars: dict[str, str] = {}
    env_file: Optional[str] = None
    last_run: Optional[str]
    next_run: Optional[str]
    created_at: str
    updated_at: str
    running: bool = False
    schedule_description: str = ""


# Dashboard
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the dashboard."""
    if not templates_dir.exists():
        return HTMLResponse("<h1>Supervisor</h1><p>Dashboard templates not installed.</p>")

    services = []
    for service in Service.select():
        running = process_manager.is_running(service.name)
        # Get metrics for all services (includes disk usage even when stopped)
        metrics = resource_monitor.get_current_metrics(service.name)
        services.append(
            {
                "service": service,
                "running": running,
                "pid": process_manager.get_pid(service.name),
                "metrics": metrics,
            }
        )

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "services": services,
            "config": config,
        },
    )


# Service CRUD
@app.post("/api/services", response_model=ServiceResponse)
async def create_service(data: ServiceCreate):
    """Register a new service."""
    if Service.get_or_none(Service.name == data.name):
        raise HTTPException(status_code=409, detail=f"Service '{data.name}' already exists")

    import json
    watch_dirs_json = json.dumps(data.watch_dirs) if data.watch_dirs else None

    service = Service.create(
        name=data.name,
        command=data.command,
        working_dir=data.working_dir,
        port=data.port,
        enabled=data.enabled,
        expose_caddy=data.expose_caddy,
        caddy_subdomain=data.caddy_subdomain,
        caddy_path=data.caddy_path,
        watch_dirs=watch_dirs_json,
    )

    # Start if enabled
    if service.enabled:
        process_manager.start(service)

    return _service_response(service)


@app.get("/api/services")
async def list_services():
    """List all registered services."""
    services = []
    for service in Service.select():
        services.append(_service_response(service))
    return services


@app.get("/api/services/{name}", response_model=ServiceResponse)
async def get_service(name: str):
    """Get a specific service."""
    service = Service.get_or_none(Service.name == name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")
    return _service_response(service)


@app.put("/api/services/{name}", response_model=ServiceResponse)
async def update_service(name: str, data: ServiceUpdate):
    """Update a service configuration."""
    service = Service.get_or_none(Service.name == name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")

    if data.command is not None:
        service.command = data.command
    if data.working_dir is not None:
        service.working_dir = data.working_dir
    if data.port is not None:
        service.port = data.port
    if data.enabled is not None:
        service.enabled = data.enabled
    if data.expose_caddy is not None:
        service.expose_caddy = data.expose_caddy
    if data.caddy_subdomain is not None:
        service.caddy_subdomain = data.caddy_subdomain
    if data.caddy_path is not None:
        service.caddy_path = data.caddy_path
    if data.watch_dirs is not None:
        import json
        service.watch_dirs = json.dumps(data.watch_dirs)

    service.save()
    return _service_response(service)


@app.delete("/api/services/{name}")
async def delete_service(name: str):
    """Unregister a service (stops it first)."""
    service = Service.get_or_none(Service.name == name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")

    # Stop if running
    if process_manager.is_running(name):
        process_manager.stop(name)

    service.delete_instance()
    return {"status": "deleted", "name": name}


# Service control
@app.post("/api/services/{name}/start")
async def start_service(name: str):
    """Start a service."""
    service = Service.get_or_none(Service.name == name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")

    if process_manager.is_running(name):
        return {"status": "already_running", "name": name}

    success = process_manager.start(service)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to start service")

    return {"status": "started", "name": name, "pid": process_manager.get_pid(name)}


@app.post("/api/services/{name}/stop")
async def stop_service(name: str):
    """Stop a service."""
    service = Service.get_or_none(Service.name == name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")

    if not process_manager.is_running(name):
        return {"status": "not_running", "name": name}

    success = process_manager.stop(name)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to stop service")

    return {"status": "stopped", "name": name}


@app.post("/api/services/{name}/restart")
async def restart_service(name: str):
    """Restart a service."""
    service = Service.get_or_none(Service.name == name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")

    success = process_manager.restart(service)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to restart service")

    return {"status": "restarted", "name": name, "pid": process_manager.get_pid(name)}


# Logs
@app.get("/api/services/{name}/logs")
async def get_service_logs(
    name: str,
    level: Optional[str] = Query(None, description="Filter by level: info, warning, error"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Get recent logs for a service."""
    service = Service.get_or_none(Service.name == name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")

    query = LogEntry.select().where(LogEntry.service == service)
    if level:
        query = query.where(LogEntry.level == level)

    logs = query.order_by(LogEntry.timestamp.desc()).offset(offset).limit(limit)
    return [log.to_dict() for log in logs]


# Metrics
@app.get("/api/services/{name}/metrics")
async def get_service_metrics(
    name: str,
    hours: int = Query(24, ge=1, le=168),
):
    """Get resource metrics history for a service."""
    service = Service.get_or_none(Service.name == name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")

    since = datetime.now() - timedelta(hours=hours)
    metrics = (
        Metric.select()
        .where(Metric.service == service, Metric.timestamp >= since)
        .order_by(Metric.timestamp.asc())
    )
    return [m.to_dict() for m in metrics]


@app.get("/api/services/{name}/metrics/current")
async def get_service_current_metrics(name: str):
    """Get current resource usage for a service."""
    service = Service.get_or_none(Service.name == name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")

    metrics = resource_monitor.get_current_metrics(name)
    if not metrics:
        raise HTTPException(status_code=404, detail="Service not running")
    return metrics


# Status overview
@app.get("/api/status")
async def get_status():
    """Get overview of all services."""
    services = []
    for service in Service.select():
        running = process_manager.is_running(service.name)
        metrics = resource_monitor.get_current_metrics(service.name) if running else None
        services.append(
            {
                "name": service.name,
                "enabled": service.enabled,
                "running": running,
                "pid": process_manager.get_pid(service.name),
                "port": service.port,
                "metrics": metrics,
            }
        )
    return {
        "services": services,
        "total": len(services),
        "running": sum(1 for s in services if s["running"]),
        "enabled": sum(1 for s in services if s["enabled"]),
        "service_host": config.get_service_host(),
    }


# Auto-fix
@app.post("/api/services/{name}/fix")
async def trigger_fix(name: str, error_description: Optional[str] = None):
    """Manually trigger an auto-fix attempt. Runs in background, returns job ID."""
    service = Service.get_or_none(Service.name == name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")

    # Run fix in background
    job = await job_manager.run_async_in_background(
        f"fix:{service.name}",
        auto_fixer.manual_fix,
        service,
        error_description,
    )

    return {"job_id": job.id, "status": "started", "service": service.name}


@app.get("/api/services/{name}/fixes")
async def get_fix_history(name: str, limit: int = Query(20, ge=1, le=100)):
    """Get fix attempt history for a service."""
    service = Service.get_or_none(Service.name == name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")

    fixes = (
        FixAttempt.select()
        .where(FixAttempt.service == service)
        .order_by(FixAttempt.timestamp.desc())
        .limit(limit)
    )
    return [f.to_dict() for f in fixes]


@app.post("/api/fixes/{fix_id}/restore")
async def restore_fix_backup(fix_id: int):
    """Restore code from a fix attempt's backup."""
    from .fixer import restore_backup

    fix = FixAttempt.get_or_none(FixAttempt.id == fix_id)
    if not fix:
        raise HTTPException(status_code=404, detail=f"Fix attempt {fix_id} not found")

    if not fix.backup_path:
        raise HTTPException(status_code=400, detail="No backup available for this fix")

    if fix.restored:
        raise HTTPException(status_code=400, detail="Backup already restored")

    # Get working directory
    service = fix.service
    working_dir = service.working_dir
    if not working_dir:
        import shlex
        parts = shlex.split(service.command)
        for part in parts:
            if part.endswith(".py") and "/" in part:
                working_dir = str(Path(part).parent)
                break

    if not working_dir:
        raise HTTPException(status_code=400, detail="Cannot determine working directory")

    # Restore backup
    success = restore_backup(fix.backup_path, working_dir)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to restore backup")

    # Mark as restored
    fix.restored = True
    fix.save()

    # Restart service
    process_manager.restart(service)

    return {
        "status": "restored",
        "fix_id": fix_id,
        "backup_path": fix.backup_path,
        "service": service.name,
    }


# Caddy
@app.get("/api/caddy/config")
async def get_caddy_generated_config():
    """Get the generated Caddy configuration."""
    return {
        "caddyfile": generate_caddyfile(),
        "services": [
            {"name": s.name, "port": s.port, "path": s.caddy_path}
            for s in Service.select().where(Service.expose_caddy == True)
        ],
    }


@app.get("/api/caddy/current")
async def get_caddy_current_config():
    """Get the current running Caddy configuration."""
    conf = await get_caddy_config()
    if conf is None:
        raise HTTPException(status_code=503, detail="Could not connect to Caddy")
    return conf


@app.post("/api/caddy/reload")
async def reload_caddy_config():
    """Regenerate and reload Caddy configuration."""
    success, message = await reload_caddy()
    if not success:
        raise HTTPException(status_code=500, detail=message)
    return {"status": "reloaded", "message": message}


# Jobs
@app.get("/api/jobs")
async def list_jobs(status: Optional[str] = None):
    """List all background jobs."""
    filter_status = None
    if status:
        try:
            filter_status = JobStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    jobs = job_manager.list_jobs(filter_status)
    return [j.to_dict() for j in jobs]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Get a specific job by ID."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job.to_dict()


# Supervisor logs
@app.get("/api/supervisor/logs")
async def get_supervisor_logs(lines: int = Query(100, ge=1, le=1000)):
    """Get recent supervisor log entries."""
    try:
        with open(config.supervisor_log, "r") as f:
            all_lines = f.readlines()
            return {"lines": all_lines[-lines:], "total": len(all_lines)}
    except FileNotFoundError:
        return {"lines": [], "total": 0}


# Helper functions
def _service_response(service: Service) -> dict:
    """Convert service to response dict with runtime info."""
    data = service.to_dict()
    data["running"] = process_manager.is_running(service.name)
    data["pid"] = process_manager.get_pid(service.name)
    return data


# Robot AI Integration
class OnboardRequest(BaseModel):
    project: str = Field(..., description="Project name (in ~/Code/) or full path")
    model: str = Field("opus", description="AI model to use")


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message")
    project: Optional[str] = Field(None, description="Optional project context")
    model: str = Field("opus", description="AI model to use")
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity")


@app.post("/api/onboard")
async def onboard_project(data: OnboardRequest):
    """
    Onboard a project to supervisor using AI.

    The AI will analyze the project, determine how to run it,
    and register it with supervisor.
    """
    # Run onboard in background
    job = await job_manager.run_async_in_background(
        f"onboard:{data.project}",
        run_robot_onboard,
        data.project,
        data.model,
    )

    return {"job_id": job.id, "status": "started", "project": data.project}


@app.get("/api/onboard/preview")
async def preview_onboard(project: str):
    """Preview what will be onboarded without running AI."""
    try:
        project_path, project_name = resolve_project_path(project)
        return {
            "project_name": project_name,
            "project_path": project_path,
            "data_dir": f"~/.{project_name}/",
            "exists": True,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/projects")
async def list_projects():
    """List available projects in ~/Code/."""
    code_dir = Path.home() / "Code"
    if not code_dir.exists():
        return {"projects": []}

    projects = []
    for item in sorted(code_dir.iterdir()):
        if item.is_dir() and not item.name.startswith("."):
            projects.append({
                "name": item.name,
                "path": str(item),
            })
    return {"projects": projects}


@app.post("/api/chat")
async def chat_with_robot(data: ChatRequest):
    """
    Stream chat with AI assistant.

    Returns Server-Sent Events (SSE) stream.
    """
    import json

    async def event_stream():
        async for event in stream_robot_chat(
            message=data.message,
            project=data.project,
            model=data.model,
            session_id=data.session_id,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class SecurityScanRequest(BaseModel):
    """Request to run a security scan."""
    service_name: str = Field(..., description="Name of the service to scan")
    model: str = Field(default="sonnet", description="AI model to use")


@app.post("/api/services/{name}/security-scan")
async def run_service_security_scan(name: str, model: str = "sonnet"):
    """
    Run a security scan against a Caddy-exposed service.

    Returns a job ID that can be polled for results.
    """
    service = Service.get_or_none(Service.name == name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")

    if not service.expose_caddy or not service.caddy_subdomain:
        raise HTTPException(
            status_code=400,
            detail=f"Service '{name}' is not exposed via Caddy subdomain"
        )

    # Build the service URL
    service_url = f"https://{service.caddy_subdomain}.{config.caddy_base_domain}:{config.caddy_port}"

    # Run scan in background
    job = await job_manager.run_async_in_background(
        f"security-scan:{name}",
        run_security_scan,
        service.name,
        service_url,
        service.port or 443,
        model,
    )

    return {
        "job_id": job.id,
        "status": "started",
        "service": name,
        "url": service_url,
    }


@app.get("/api/services/{name}/security-scan/latest")
async def get_latest_security_scan(name: str):
    """
    Get the latest security scan result for a service.

    Returns the most recent scan job result if available.
    """
    service = Service.get_or_none(Service.name == name)
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")

    # Find the most recent security scan job for this service
    job_key = f"security-scan:{name}"
    job = job_manager.get_job(job_key)

    if not job:
        return {"has_scan": False, "message": "No security scan has been run for this service"}

    return {
        "has_scan": True,
        "job_id": job.id,
        "status": job.status.value,
        "result": job.result if job.status == JobStatus.COMPLETED else None,
        "error": job.error if job.status == JobStatus.FAILED else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


# Cron Jobs
@app.post("/api/cron", response_model=CronJobResponse)
async def create_cron_job(data: CronJobCreate):
    """Register a new cron job."""
    if CronJob.get_or_none(CronJob.name == data.name):
        raise HTTPException(status_code=409, detail=f"Cron job '{data.name}' already exists")

    # Validate schedule
    valid, error = cron_manager.validate_schedule(data.schedule)
    if not valid:
        raise HTTPException(status_code=400, detail=f"Invalid cron schedule: {error}")

    import json
    watch_dirs_json = json.dumps(data.watch_dirs) if data.watch_dirs else None
    env_vars_json = json.dumps(data.env_vars) if data.env_vars else None

    cron_job = CronJob.create(
        name=data.name,
        command=data.command,
        schedule=data.schedule,
        working_dir=data.working_dir,
        enabled=data.enabled,
        timeout=data.timeout,
        watch_dirs=watch_dirs_json,
        env_vars=env_vars_json,
        env_file=data.env_file,
    )

    # Calculate next run time
    cron_manager.update_next_run(cron_job)

    return _cron_job_response(cron_job)


@app.get("/api/cron")
async def list_cron_jobs():
    """List all registered cron jobs."""
    jobs = []
    for job in CronJob.select():
        jobs.append(_cron_job_response(job))
    return jobs


@app.post("/api/cron/tick")
async def cron_tick():
    """
    Called every minute by system cron to trigger due jobs.

    Add to crontab: * * * * * curl -s -X POST http://localhost:9900/api/cron/tick
    """
    execution_ids = await cron_manager.tick()
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "jobs_started": len(execution_ids),
        "execution_ids": execution_ids,
    }


@app.get("/api/cron/status")
async def get_cron_status():
    """Get overview of all cron jobs and their status."""
    jobs = []
    for job in CronJob.select():
        # Get last execution
        last_exec = (
            CronExecution.select()
            .where(CronExecution.cron_job == job)
            .order_by(CronExecution.started_at.desc())
            .first()
        )

        # Count recent executions
        recent_count = (
            CronExecution.select()
            .where(
                CronExecution.cron_job == job,
                CronExecution.started_at >= datetime.now() - timedelta(hours=24),
            )
            .count()
        )

        # Count failures
        recent_failures = (
            CronExecution.select()
            .where(
                CronExecution.cron_job == job,
                CronExecution.started_at >= datetime.now() - timedelta(hours=24),
                CronExecution.success == False,
            )
            .count()
        )

        jobs.append({
            "name": job.name,
            "enabled": job.enabled,
            "schedule": job.schedule,
            "schedule_description": cron_manager.get_schedule_description(job.schedule),
            "running": cron_manager.is_running(job.id),
            "last_run": job.last_run.isoformat() if job.last_run else None,
            "next_run": job.next_run.isoformat() if job.next_run else None,
            "last_success": last_exec.success if last_exec else None,
            "executions_24h": recent_count,
            "failures_24h": recent_failures,
        })

    return {
        "jobs": jobs,
        "total": len(jobs),
        "enabled": sum(1 for j in jobs if j["enabled"]),
        "running": sum(1 for j in jobs if j["running"]),
    }


@app.get("/api/cron/validate")
async def validate_cron_schedule(schedule: str):
    """Validate a cron schedule expression."""
    valid, message = cron_manager.validate_schedule(schedule)
    description = cron_manager.get_schedule_description(schedule) if valid else None
    next_runs = []

    if valid:
        from croniter import croniter
        cron = croniter(schedule, datetime.now())
        for _ in range(5):
            next_runs.append(cron.get_next(datetime).isoformat())

    return {
        "valid": valid,
        "message": message,
        "description": description,
        "next_runs": next_runs,
    }


@app.get("/api/cron/{name}", response_model=CronJobResponse)
async def get_cron_job(name: str):
    """Get a specific cron job."""
    job = CronJob.get_or_none(CronJob.name == name)
    if not job:
        raise HTTPException(status_code=404, detail=f"Cron job '{name}' not found")
    return _cron_job_response(job)


@app.put("/api/cron/{name}", response_model=CronJobResponse)
async def update_cron_job(name: str, data: CronJobUpdate):
    """Update a cron job configuration."""
    job = CronJob.get_or_none(CronJob.name == name)
    if not job:
        raise HTTPException(status_code=404, detail=f"Cron job '{name}' not found")

    if data.schedule is not None:
        valid, error = cron_manager.validate_schedule(data.schedule)
        if not valid:
            raise HTTPException(status_code=400, detail=f"Invalid cron schedule: {error}")
        job.schedule = data.schedule

    if data.command is not None:
        job.command = data.command
    if data.working_dir is not None:
        job.working_dir = data.working_dir
    if data.enabled is not None:
        job.enabled = data.enabled
    if data.timeout is not None:
        job.timeout = data.timeout
    if data.watch_dirs is not None:
        import json
        job.watch_dirs = json.dumps(data.watch_dirs)
    if data.env_vars is not None:
        import json
        job.env_vars = json.dumps(data.env_vars) if data.env_vars else None
    if data.env_file is not None:
        job.env_file = data.env_file if data.env_file else None

    job.save()
    cron_manager.update_next_run(job)
    return _cron_job_response(job)


@app.delete("/api/cron/{name}")
async def delete_cron_job(name: str):
    """Delete a cron job."""
    job = CronJob.get_or_none(CronJob.name == name)
    if not job:
        raise HTTPException(status_code=404, detail=f"Cron job '{name}' not found")

    job.delete_instance(recursive=True)
    return {"status": "deleted", "name": name}


@app.post("/api/cron/{name}/run")
async def run_cron_job_now(name: str):
    """Manually trigger a cron job to run immediately."""
    job = CronJob.get_or_none(CronJob.name == name)
    if not job:
        raise HTTPException(status_code=404, detail=f"Cron job '{name}' not found")

    if cron_manager.is_running(job.id):
        return {"status": "already_running", "name": name}

    execution_id = await cron_manager.run_now(job)
    if not execution_id:
        raise HTTPException(status_code=500, detail="Failed to start cron job")

    return {"status": "started", "name": name, "execution_id": execution_id}


@app.post("/api/cron/{name}/stop")
async def stop_cron_job(name: str):
    """Stop a running cron job."""
    job = CronJob.get_or_none(CronJob.name == name)
    if not job:
        raise HTTPException(status_code=404, detail=f"Cron job '{name}' not found")

    if not cron_manager.is_running(job.id):
        return {"status": "not_running", "name": name}

    success = cron_manager.kill_job(job.id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to stop cron job")

    return {"status": "stopped", "name": name}


@app.get("/api/cron/{name}/executions")
async def get_cron_executions(
    name: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Get execution history for a cron job."""
    job = CronJob.get_or_none(CronJob.name == name)
    if not job:
        raise HTTPException(status_code=404, detail=f"Cron job '{name}' not found")

    executions = (
        CronExecution.select()
        .where(CronExecution.cron_job == job)
        .order_by(CronExecution.started_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [e.to_dict() for e in executions]


@app.get("/api/cron/{name}/executions/{execution_id}")
async def get_cron_execution(name: str, execution_id: int):
    """Get a specific execution record."""
    job = CronJob.get_or_none(CronJob.name == name)
    if not job:
        raise HTTPException(status_code=404, detail=f"Cron job '{name}' not found")

    execution = CronExecution.get_or_none(
        CronExecution.id == execution_id, CronExecution.cron_job == job
    )
    if not execution:
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

    return execution.to_dict()


def _cron_job_response(job: CronJob) -> dict:
    """Convert cron job to response dict with runtime info."""
    data = job.to_dict()
    data["running"] = cron_manager.is_running(job.id)
    data["schedule_description"] = cron_manager.get_schedule_description(job.schedule)
    return data
