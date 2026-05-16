# Supervisor Usage Guide

A unified service manager for Python/FastAPI projects with process supervision, cron job scheduling, resource monitoring, auto-fix capabilities, and Caddy reverse proxy integration.

## Quick Start

```bash
# Install supervisor
pip install -e /path/to/supervisor

# Run supervisor
supervisor

# Dashboard available at http://localhost:9900
```

Register your first service:

```bash
curl -X POST http://localhost:9900/api/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "myapp",
    "command": "python /path/to/app.py",
    "port": 8000,
    "enabled": true
  }'
```

## Installation

### Basic Installation

```bash
cd /path/to/supervisor
pip install -e .
```

Or install dependencies only:

```bash
pip install -r requirements.txt
```

### Install as System Service

To run supervisor at boot using systemd:

```bash
sudo cp supervisor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable supervisor
sudo systemctl start supervisor
```

Check status:

```bash
sudo systemctl status supervisor
```

### Enable Cron Job Scheduling

For scheduled jobs to work, add this to your crontab (triggers once per minute):

```bash
(crontab -l 2>/dev/null; echo "* * * * * curl -s -X POST http://localhost:9900/api/cron/tick > /dev/null") | crontab -
```

Verify it's installed:

```bash
crontab -l
```

## Basic Usage

### Running Supervisor

```bash
# Direct command
supervisor

# Via Python module
python -m supervisor

# With custom port
SUPERVISOR_PORT=9999 supervisor
```

The web dashboard is available at `http://localhost:9900` (default port).

### Web Dashboard

Open `http://localhost:9900` in your browser to:
- View all services and their status
- Start/stop/restart services
- View logs and resource metrics
- Trigger auto-fixes
- Run security scans
- Manage cron jobs
- Chat with AI assistant
- Onboard new projects

### Managing Services via CLI

**List all services:**

```bash
curl http://localhost:9900/api/services
```

**Get service status:**

```bash
curl http://localhost:9900/api/services/myapp
```

**Start a service:**

```bash
curl -X POST http://localhost:9900/api/services/myapp/start
```

**Stop a service:**

```bash
curl -X POST http://localhost:9900/api/services/myapp/stop
```

**Restart a service:**

```bash
curl -X POST http://localhost:9900/api/services/myapp/restart
```

**Delete a service:**

```bash
curl -X DELETE http://localhost:9900/api/services/myapp
```

## Service Management

### Registering a Service

**Minimal example:**

```bash
curl -X POST http://localhost:9900/api/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "api",
    "command": "python /home/user/myapp/run.py",
    "port": 8001,
    "enabled": true
  }'
```

**Full example with all options:**

```bash
curl -X POST http://localhost:9900/api/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "frontend",
    "command": "npm start",
    "working_dir": "/home/user/frontend",
    "port": 3000,
    "enabled": true,
    "expose_caddy": true,
    "caddy_subdomain": "app",
    "watch_dirs": ["/home/user/frontend", "/home/user/data"]
  }'
```

**Service configuration fields:**

- `name` (required): Unique identifier for the service
- `command` (required): Shell command to run the service
- `working_dir` (optional): Working directory (auto-detected if not provided)
- `port` (optional): Port number for health checks and Caddy routing
- `enabled` (optional, default: true): Auto-start on supervisor boot
- `expose_caddy` (optional, default: false): Expose via Caddy reverse proxy
- `caddy_subdomain` (optional): Subdomain for Caddy (e.g., "myapp" → myapp.domain.com)
- `caddy_path` (optional): Legacy path-based routing (deprecated)
- `watch_dirs` (optional): Directories to track for disk usage (defaults to working_dir)

### Updating a Service

```bash
curl -X PUT http://localhost:9900/api/services/myapp \
  -H "Content-Type: application/json" \
  -d '{
    "port": 8080,
    "enabled": false,
    "expose_caddy": true,
    "caddy_subdomain": "newname"
  }'
```

Only include fields you want to update.

### Viewing Logs

**Get recent logs:**

```bash
curl "http://localhost:9900/api/services/myapp/logs?limit=100"
```

**Filter by level:**

```bash
curl "http://localhost:9900/api/services/myapp/logs?level=error&limit=50"
```

**Pagination:**

```bash
curl "http://localhost:9900/api/services/myapp/logs?limit=20&offset=40"
```

**Example response:**

```json
[
  {
    "id": 123,
    "service_id": 1,
    "level": "info",
    "message": "Server started on port 8000",
    "timestamp": "2026-05-16T10:30:00"
  },
  {
    "id": 124,
    "level": "error",
    "message": "Database connection failed",
    "timestamp": "2026-05-16T10:31:15"
  }
]
```

### Resource Monitoring

**Get current metrics:**

```bash
curl http://localhost:9900/api/services/myapp/metrics/current
```

**Example response:**

```json
{
  "cpu_percent": 15.2,
  "memory_mb": 245.8,
  "disk_mb": 1024.5,
  "uptime_seconds": 3600
}
```

**Get historical metrics:**

```bash
# Last 24 hours (default)
curl http://localhost:9900/api/services/myapp/metrics

# Last 7 days
curl "http://localhost:9900/api/services/myapp/metrics?hours=168"
```

**Example response:**

```json
[
  {
    "id": 1,
    "service_id": 1,
    "cpu_percent": 12.5,
    "memory_mb": 230.0,
    "disk_mb": 1020.0,
    "timestamp": "2026-05-16T10:00:00"
  },
  {
    "id": 2,
    "service_id": 1,
    "cpu_percent": 15.2,
    "memory_mb": 245.8,
    "disk_mb": 1024.5,
    "timestamp": "2026-05-16T10:05:00"
  }
]
```

**System overview:**

```bash
curl http://localhost:9900/api/status
```

**Example response:**

```json
{
  "services": [
    {
      "name": "api",
      "enabled": true,
      "running": true,
      "pid": 12345,
      "port": 8000,
      "metrics": {
        "cpu_percent": 15.2,
        "memory_mb": 245.8,
        "disk_mb": 1024.5,
        "uptime_seconds": 3600
      }
    },
    {
      "name": "worker",
      "enabled": true,
      "running": false,
      "pid": null,
      "port": null,
      "metrics": null
    }
  ],
  "total": 2,
  "running": 1,
  "enabled": 2,
  "service_host": "10.0.0.10"
}
```

## Cron Job Management

### Registering a Cron Job

**Basic example (runs daily at 2 AM):**

```bash
curl -X POST http://localhost:9900/api/cron \
  -H "Content-Type: application/json" \
  -d '{
    "name": "backup",
    "command": "python /home/user/scripts/backup.py",
    "schedule": "0 2 * * *",
    "enabled": true
  }'
```

**Full example with environment variables:**

```bash
curl -X POST http://localhost:9900/api/cron \
  -H "Content-Type: application/json" \
  -d '{
    "name": "data-sync",
    "command": "python sync.py",
    "schedule": "*/15 * * * *",
    "working_dir": "/home/user/project",
    "enabled": true,
    "timeout": 600,
    "env_file": ".env",
    "env_vars": {
      "API_KEY": "secret123",
      "DEBUG": "true"
    },
    "watch_dirs": ["/home/user/project", "/data"]
  }'
```

**Cron job configuration fields:**

- `name` (required): Unique identifier
- `command` (required): Shell command to execute
- `schedule` (required): Cron expression (e.g., `*/15 * * * *` for every 15 minutes)
- `working_dir` (optional): Working directory for the command
- `enabled` (optional, default: true): Whether the job is active
- `timeout` (optional, default: 300): Maximum execution time in seconds
- `env_file` (optional): Path to .env file (relative paths resolved from working_dir)
- `env_vars` (optional): Dictionary of environment variables (overrides env_file)
- `watch_dirs` (optional): Directories to track for disk usage

### Cron Schedule Examples

```bash
# Every minute
"* * * * *"

# Every 5 minutes
"*/5 * * * *"

# Every hour at minute 30
"30 * * * *"

# Daily at 2:00 AM
"0 2 * * *"

# Every Monday at 9:00 AM
"0 9 * * 1"

# First day of every month at midnight
"0 0 1 * *"

# Every weekday at 6:00 PM
"0 18 * * 1-5"
```

### Managing Cron Jobs

**List all cron jobs:**

```bash
curl http://localhost:9900/api/cron
```

**Get cron job status:**

```bash
curl http://localhost:9900/api/cron/backup
```

**Update a cron job:**

```bash
curl -X PUT http://localhost:9900/api/cron/backup \
  -H "Content-Type: application/json" \
  -d '{
    "schedule": "0 3 * * *",
    "timeout": 900
  }'
```

**Run a job manually:**

```bash
curl -X POST http://localhost:9900/api/cron/backup/run
```

**Stop a running job:**

```bash
curl -X POST http://localhost:9900/api/cron/backup/stop
```

**Delete a cron job:**

```bash
curl -X DELETE http://localhost:9900/api/cron/backup
```

### Validating Cron Schedules

```bash
curl "http://localhost:9900/api/cron/validate?schedule=*/15%20*%20*%20*%20*"
```

**Example response:**

```json
{
  "valid": true,
  "message": "Valid schedule",
  "description": "Every 15 minutes",
  "next_runs": [
    "2026-05-16T10:45:00",
    "2026-05-16T11:00:00",
    "2026-05-16T11:15:00",
    "2026-05-16T11:30:00",
    "2026-05-16T11:45:00"
  ]
}
```

### Viewing Execution History

**Get recent executions:**

```bash
curl http://localhost:9900/api/cron/backup/executions
```

**Example response:**

```json
[
  {
    "id": 1,
    "cron_job_id": 1,
    "started_at": "2026-05-16T02:00:00",
    "completed_at": "2026-05-16T02:05:30",
    "success": true,
    "exit_code": 0,
    "stdout": "Backup completed successfully",
    "stderr": "",
    "cpu_percent": 25.5,
    "memory_mb": 150.0,
    "disk_mb": 5000.0
  }
]
```

**Get specific execution:**

```bash
curl http://localhost:9900/api/cron/backup/executions/1
```

**Get overview of all cron jobs:**

```bash
curl http://localhost:9900/api/cron/status
```

**Example response:**

```json
{
  "jobs": [
    {
      "name": "backup",
      "enabled": true,
      "schedule": "0 2 * * *",
      "schedule_description": "Daily at 2:00",
      "running": false,
      "last_run": "2026-05-16T02:00:00",
      "next_run": "2026-05-17T02:00:00",
      "last_success": true,
      "executions_24h": 1,
      "failures_24h": 0
    }
  ],
  "total": 1,
  "enabled": 1,
  "running": 0
}
```

## Auto-Fix Feature

Supervisor can automatically detect and fix errors in your services using the Robot AI agent.

### Triggering Auto-Fix Manually

```bash
curl -X POST http://localhost:9900/api/services/myapp/fix
```

**With error description:**

```bash
curl -X POST "http://localhost:9900/api/services/myapp/fix?error_description=Database%20connection%20timeout"
```

**Example response:**

```json
{
  "job_id": "fix:myapp",
  "status": "started",
  "service": "myapp"
}
```

### Checking Fix Status

Auto-fix runs as a background job. Poll the job endpoint:

```bash
curl http://localhost:9900/api/jobs/fix:myapp
```

**Example response:**

```json
{
  "id": "fix:myapp",
  "status": "completed",
  "started_at": "2026-05-16T10:30:00",
  "completed_at": "2026-05-16T10:32:15",
  "result": {
    "success": true,
    "message": "Fixed database connection timeout by updating connection pool settings"
  },
  "error": null
}
```

### Viewing Fix History

```bash
curl http://localhost:9900/api/services/myapp/fixes
```

**Example response:**

```json
[
  {
    "id": 1,
    "service_id": 1,
    "timestamp": "2026-05-16T10:30:00",
    "error_log": "Database connection timeout after 30s",
    "robot_output": "Updated connection pool max_connections from 10 to 50",
    "backup_path": "~/.supervisor/backups/myapp/20260516_103000",
    "success": true,
    "restored": false
  }
]
```

### Restoring from Backup

If an auto-fix breaks your code, restore from backup:

```bash
curl -X POST http://localhost:9900/api/fixes/1/restore
```

**Example response:**

```json
{
  "status": "restored",
  "fix_id": 1,
  "backup_path": "~/.supervisor/backups/myapp/20260516_103000",
  "service": "myapp"
}
```

The service will be automatically restarted after restore.

## AI Onboarding

Use AI to automatically analyze and register projects.

### Onboard a Project

**By project name (assumes ~/Code/<name>):**

```bash
curl -X POST http://localhost:9900/api/onboard \
  -H "Content-Type: application/json" \
  -d '{
    "project": "myproject",
    "model": "opus"
  }'
```

**By full path:**

```bash
curl -X POST http://localhost:9900/api/onboard \
  -H "Content-Type: application/json" \
  -d '{
    "project": "/home/user/projects/myapp",
    "model": "sonnet"
  }'
```

**With specific port:**

```bash
curl -X POST http://localhost:9900/api/onboard \
  -H "Content-Type: application/json" \
  -d '{
    "project": "myproject",
    "model": "opus",
    "port": 8010
  }'
```

**Example response:**

```json
{
  "job_id": "onboard:myproject",
  "status": "started",
  "project": "myproject"
}
```

### Preview Onboarding

Check what will be onboarded without running AI:

```bash
curl "http://localhost:9900/api/onboard/preview?project=myproject"
```

**Example response:**

```json
{
  "project_name": "myproject",
  "project_path": "/home/user/Code/myproject",
  "data_dir": "~/.myproject/",
  "exists": true
}
```

### List Available Projects

```bash
curl http://localhost:9900/api/projects
```

**Example response:**

```json
{
  "projects": [
    {"name": "api", "path": "/home/user/Code/api"},
    {"name": "frontend", "path": "/home/user/Code/frontend"},
    {"name": "worker", "path": "/home/user/Code/worker"}
  ]
}
```

## AI Chat Assistant

Interactive chat with AI for project help and debugging.

### Chat Endpoint

```bash
curl -X POST http://localhost:9900/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "How do I add a new endpoint to my API?",
    "project": "myapi",
    "model": "sonnet"
  }'
```

The response is a Server-Sent Events (SSE) stream. Each event is JSON:

```
data: {"type": "text", "content": "To add a new endpoint..."}

data: {"type": "status", "content": "Analyzing code..."}

data: {"type": "code", "language": "python", "content": "def new_endpoint():..."}
```

**Chat with session continuity:**

```bash
curl -X POST http://localhost:9900/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Thanks! Now how do I add authentication?",
    "project": "myapi",
    "model": "sonnet",
    "session_id": "abc123"
  }'
```

## Security Scanning

Run AI-powered security scans on Caddy-exposed services.

### Run Security Scan

```bash
curl -X POST "http://localhost:9900/api/services/myapp/security-scan?model=sonnet"
```

**Example response:**

```json
{
  "job_id": "security-scan:myapp",
  "status": "started",
  "service": "myapp",
  "url": "https://myapp.ph1l.uk:60443"
}
```

### Get Latest Scan Results

```bash
curl http://localhost:9900/api/services/myapp/security-scan/latest
```

**Example response:**

```json
{
  "has_scan": true,
  "job_id": "security-scan:myapp",
  "status": "completed",
  "result": {
    "vulnerabilities": [],
    "recommendations": [
      "Add rate limiting to API endpoints",
      "Implement CSRF protection"
    ],
    "risk_level": "low"
  },
  "started_at": "2026-05-16T10:00:00",
  "completed_at": "2026-05-16T10:05:00"
}
```

## Caddy Integration

Supervisor can generate and manage Caddy reverse proxy configuration.

### Get Generated Config

```bash
curl http://localhost:9900/api/caddy/config
```

**Example response:**

```json
{
  "caddyfile": "myapp.ph1l.uk:60443 {\n  reverse_proxy localhost:8000\n}\n",
  "services": [
    {"name": "myapp", "port": 8000, "path": null}
  ]
}
```

### Get Current Running Config

```bash
curl http://localhost:9900/api/caddy/current
```

### Reload Caddy

Regenerate configuration and reload Caddy:

```bash
curl -X POST http://localhost:9900/api/caddy/reload
```

**Example response:**

```json
{
  "status": "reloaded",
  "message": "Configuration written and Caddy reloaded"
}
```

## Background Jobs

Long-running operations (auto-fix, onboarding, security scans) run as background jobs.

### List All Jobs

```bash
curl http://localhost:9900/api/jobs
```

**Filter by status:**

```bash
curl "http://localhost:9900/api/jobs?status=running"
```

Valid statuses: `pending`, `running`, `completed`, `failed`

### Get Job Details

```bash
curl http://localhost:9900/api/jobs/fix:myapp
```

**Example response:**

```json
{
  "id": "fix:myapp",
  "status": "running",
  "started_at": "2026-05-16T10:30:00",
  "completed_at": null,
  "result": null,
  "error": null,
  "progress": "Analyzing error logs..."
}
```

## Configuration

Configure supervisor via environment variables or a `.env` file in the current directory.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SUPERVISOR_HOST` | `0.0.0.0` | Host to bind API server |
| `SUPERVISOR_PORT` | `9900` | API port |
| `SERVICE_HOST` | (auto-detect) | Host for service links (auto-detects machine IP) |
| `CADDY_ADMIN_URL` | `http://localhost:2019` | Caddy admin API URL |
| `CADDY_DOMAIN` | `h.ph1l.uk:60443` | Domain for Caddy config |
| `CADDY_BASE_DOMAIN` | `ph1l.uk` | Base domain for subdomain routing |
| `CADDY_PORT` | `60443` | Port for Caddy routing |
| `CADDY_SUPERVISOR_FILE` | `/etc/caddy/supervisor.conf` | Path to supervisor Caddy config |
| `MONITOR_INTERVAL` | `300` | Metrics collection interval (seconds) |
| `LOG_MAX_BYTES` | `10485760` | Max log file size (10MB) |
| `LOG_BACKUP_COUNT` | `5` | Number of rotated log files to keep |
| `LOG_RETENTION_DAYS` | `3` | Days to keep logs in database |
| `AUTOFIX_ENABLED` | `true` | Enable Robot auto-fix |
| `AUTOFIX_TIMEOUT` | `300` | Auto-fix timeout (seconds) |
| `MAX_RESTART_ATTEMPTS` | `3` | Max restarts before giving up |
| `RESTART_DELAY` | `5` | Delay before restarting crashed services (seconds) |

### Example .env File

```bash
# Server
SUPERVISOR_PORT=9999
SUPERVISOR_HOST=127.0.0.1

# Caddy
CADDY_BASE_DOMAIN=example.com
CADDY_PORT=443

# Monitoring
MONITOR_INTERVAL=60
LOG_RETENTION_DAYS=7

# Auto-fix
AUTOFIX_ENABLED=true
AUTOFIX_TIMEOUT=600
```

### Data Storage

All data is stored in `~/.supervisor/`:

```
~/.supervisor/
├── supervisor.db          # SQLite database
├── supervisor.log         # Supervisor logs (rotated)
├── logs/
│   ├── myapp/            # Per-service log files
│   └── worker/
└── backups/
    ├── myapp/            # Code backups before auto-fix
    └── worker/           # (keeps last 10)
```

## Common Patterns

### Pattern 1: Deploy a Flask App

```bash
# Register the service
curl -X POST http://localhost:9900/api/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "flask-api",
    "command": "python app.py",
    "working_dir": "/home/user/flask-app",
    "port": 5000,
    "enabled": true,
    "expose_caddy": true,
    "caddy_subdomain": "api"
  }'

# Check if it's running
curl http://localhost:9900/api/services/flask-api

# View logs
curl "http://localhost:9900/api/services/flask-api/logs?limit=50"

# Monitor resources
curl http://localhost:9900/api/services/flask-api/metrics/current
```

### Pattern 2: Schedule Daily Database Backup

```bash
# Create cron job for daily backup at 2 AM
curl -X POST http://localhost:9900/api/cron \
  -H "Content-Type: application/json" \
  -d '{
    "name": "db-backup",
    "command": "python backup.py",
    "schedule": "0 2 * * *",
    "working_dir": "/home/user/scripts",
    "enabled": true,
    "timeout": 1800,
    "env_file": ".env"
  }'

# Test it manually
curl -X POST http://localhost:9900/api/cron/db-backup/run

# Check execution history
curl http://localhost:9900/api/cron/db-backup/executions
```

### Pattern 3: Multiple Services Behind Caddy

```bash
# Register API service
curl -X POST http://localhost:9900/api/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "api",
    "command": "uvicorn main:app --port 8000",
    "working_dir": "/home/user/api",
    "port": 8000,
    "enabled": true,
    "expose_caddy": true,
    "caddy_subdomain": "api"
  }'

# Register frontend service
curl -X POST http://localhost:9900/api/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "frontend",
    "command": "npm start",
    "working_dir": "/home/user/frontend",
    "port": 3000,
    "enabled": true,
    "expose_caddy": true,
    "caddy_subdomain": "app"
  }'

# Reload Caddy to apply changes
curl -X POST http://localhost:9900/api/caddy/reload

# Now accessible at:
# https://api.ph1l.uk:60443
# https://app.ph1l.uk:60443
```

### Pattern 4: Monitor and Auto-Fix

```bash
# Enable auto-fix in config
export AUTOFIX_ENABLED=true

# Start supervisor
supervisor

# When a service crashes or errors, auto-fix runs automatically
# Check fix history
curl http://localhost:9900/api/services/myapp/fixes

# If fix breaks something, restore from backup
curl -X POST http://localhost:9900/api/fixes/1/restore
```

### Pattern 5: AI-Powered Onboarding

```bash
# List available projects
curl http://localhost:9900/api/projects

# Onboard a project
curl -X POST http://localhost:9900/api/onboard \
  -H "Content-Type: application/json" \
  -d '{
    "project": "myapp",
    "model": "opus"
  }'

# Check onboarding progress
curl http://localhost:9900/api/jobs/onboard:myapp

# Once complete, the service is automatically registered and started
curl http://localhost:9900/api/services/myapp
```

## API Reference

### Service Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/services` | List all services |
| `POST` | `/api/services` | Register new service |
| `GET` | `/api/services/{name}` | Get service details |
| `PUT` | `/api/services/{name}` | Update service configuration |
| `DELETE` | `/api/services/{name}` | Remove service |
| `POST` | `/api/services/{name}/start` | Start service |
| `POST` | `/api/services/{name}/stop` | Stop service |
| `POST` | `/api/services/{name}/restart` | Restart service |
| `GET` | `/api/services/{name}/logs` | Get service logs |
| `GET` | `/api/services/{name}/metrics` | Get resource history |
| `GET` | `/api/services/{name}/metrics/current` | Get current resource usage |
| `POST` | `/api/services/{name}/fix` | Trigger auto-fix (background job) |
| `GET` | `/api/services/{name}/fixes` | Get fix attempt history |
| `POST` | `/api/services/{name}/security-scan` | Run security scan (background job) |
| `GET` | `/api/services/{name}/security-scan/latest` | Get latest security scan results |

### Cron Job Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/cron` | List all cron jobs |
| `POST` | `/api/cron` | Register new cron job |
| `GET` | `/api/cron/{name}` | Get cron job details |
| `PUT` | `/api/cron/{name}` | Update cron job |
| `DELETE` | `/api/cron/{name}` | Remove cron job |
| `POST` | `/api/cron/{name}/run` | Trigger cron job immediately |
| `POST` | `/api/cron/{name}/stop` | Stop running cron job |
| `GET` | `/api/cron/{name}/executions` | Get execution history |
| `GET` | `/api/cron/{name}/executions/{id}` | Get specific execution record |
| `POST` | `/api/cron/tick` | Trigger scheduled jobs (called by system cron) |
| `GET` | `/api/cron/status` | Cron jobs overview |
| `GET` | `/api/cron/validate` | Validate cron schedule expression |

### Background Job Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/jobs` | List background jobs |
| `GET` | `/api/jobs/{id}` | Get job status/result |

### Caddy Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/caddy/config` | Get generated Caddy config |
| `GET` | `/api/caddy/current` | Get current running Caddy config |
| `POST` | `/api/caddy/reload` | Reload Caddy config |

### AI & Onboarding Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/projects` | List available projects in ~/Code/ |
| `POST` | `/api/onboard` | Onboard project with AI |
| `GET` | `/api/onboard/preview` | Preview onboard without running |
| `POST` | `/api/chat` | Stream chat with AI (SSE) |

### Fix & Restore Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/fixes/{id}/restore` | Restore code from backup |

### System Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/status` | Overview of all services |
| `GET` | `/api/supervisor/logs` | Get supervisor logs |
| `GET` | `/` | Web dashboard |

## Examples

### Example 1: FastAPI Application

```bash
# Create the service
curl -X POST http://localhost:9900/api/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "fastapi-app",
    "command": "uvicorn main:app --host 0.0.0.0 --port 8001",
    "working_dir": "/home/user/fastapi-app",
    "port": 8001,
    "enabled": true,
    "expose_caddy": true,
    "caddy_subdomain": "fastapi"
  }'

# Response:
{
  "id": 1,
  "name": "fastapi-app",
  "command": "uvicorn main:app --host 0.0.0.0 --port 8001",
  "working_dir": "/home/user/fastapi-app",
  "port": 8001,
  "enabled": true,
  "expose_caddy": true,
  "caddy_subdomain": "fastapi",
  "running": true,
  "pid": 12345,
  "created_at": "2026-05-16T10:00:00",
  "updated_at": "2026-05-16T10:00:00"
}

# Reload Caddy
curl -X POST http://localhost:9900/api/caddy/reload

# App now accessible at https://fastapi.ph1l.uk:60443
```

### Example 2: Data Processing Cron Job

```bash
# Create hourly data processing job
curl -X POST http://localhost:9900/api/cron \
  -H "Content-Type: application/json" \
  -d '{
    "name": "process-data",
    "command": "python process_data.py",
    "schedule": "0 * * * *",
    "working_dir": "/home/user/data-pipeline",
    "enabled": true,
    "timeout": 3600,
    "env_vars": {
      "DATA_SOURCE": "s3://mybucket/data",
      "OUTPUT_DIR": "/data/processed"
    }
  }'

# Response:
{
  "id": 1,
  "name": "process-data",
  "command": "python process_data.py",
  "schedule": "0 * * * *",
  "working_dir": "/home/user/data-pipeline",
  "enabled": true,
  "timeout": 3600,
  "last_run": null,
  "next_run": "2026-05-16T11:00:00",
  "running": false,
  "schedule_description": "Every hour at minute 0",
  "created_at": "2026-05-16T10:30:00",
  "updated_at": "2026-05-16T10:30:00"
}

# Wait for next hour or trigger manually
curl -X POST http://localhost:9900/api/cron/process-data/run

# Check execution
curl http://localhost:9900/api/cron/process-data/executions
```

### Example 3: Monitoring Service Health

```bash
# Get all service statuses
curl http://localhost:9900/api/status

# Response:
{
  "services": [
    {
      "name": "api",
      "enabled": true,
      "running": true,
      "pid": 12345,
      "port": 8000,
      "metrics": {
        "cpu_percent": 25.5,
        "memory_mb": 312.8,
        "disk_mb": 2048.0,
        "uptime_seconds": 7200
      }
    },
    {
      "name": "worker",
      "enabled": true,
      "running": true,
      "pid": 12346,
      "port": null,
      "metrics": {
        "cpu_percent": 45.2,
        "memory_mb": 512.0,
        "disk_mb": 1024.0,
        "uptime_seconds": 3600
      }
    }
  ],
  "total": 2,
  "running": 2,
  "enabled": 2,
  "service_host": "10.0.0.10"
}

# Get detailed metrics for a specific service
curl "http://localhost:9900/api/services/api/metrics?hours=24"

# Check recent logs for errors
curl "http://localhost:9900/api/services/api/logs?level=error&limit=20"
```

### Example 4: Full Workflow with Auto-Fix

```bash
# 1. Register a service
curl -X POST http://localhost:9900/api/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "myapp",
    "command": "python app.py",
    "working_dir": "/home/user/myapp",
    "port": 8080,
    "enabled": true
  }'

# 2. Service crashes with an error
# Auto-fix automatically triggers (if AUTOFIX_ENABLED=true)

# 3. Check fix history
curl http://localhost:9900/api/services/myapp/fixes

# Response:
[
  {
    "id": 1,
    "service_id": 1,
    "timestamp": "2026-05-16T10:30:00",
    "error_log": "ModuleNotFoundError: No module named 'requests'",
    "robot_output": "Added 'requests' to requirements.txt and installed dependencies",
    "backup_path": "~/.supervisor/backups/myapp/20260516_103000",
    "success": true,
    "restored": false
  }
]

# 4. If fix worked, service is running again
curl http://localhost:9900/api/services/myapp

# Response shows running: true, pid: 12350

# 5. If fix broke something, restore backup
curl -X POST http://localhost:9900/api/fixes/1/restore

# Response:
{
  "status": "restored",
  "fix_id": 1,
  "backup_path": "~/.supervisor/backups/myapp/20260516_103000",
  "service": "myapp"
}
```

## Troubleshooting

### Service Won't Start

**Check the logs:**

```bash
curl "http://localhost:9900/api/services/myapp/logs?level=error&limit=10"
```

**Common issues:**

1. **Working directory not set correctly:**
   - Update the working_dir field
   ```bash
   curl -X PUT http://localhost:9900/api/services/myapp \
     -H "Content-Type: application/json" \
     -d '{"working_dir": "/correct/path"}'
   ```

2. **Port already in use:**
   - Check which process is using the port: `lsof -i :8000`
   - Change the port in your service configuration

3. **Missing dependencies:**
   - Trigger auto-fix: `curl -X POST http://localhost:9900/api/services/myapp/fix`
   - Or install manually in the working directory

### Cron Job Not Running

**Check the cron job status:**

```bash
curl http://localhost:9900/api/cron/myjob
```

**Common issues:**

1. **System cron not configured:**
   - Verify crontab entry exists: `crontab -l`
   - Should see: `* * * * * curl -s -X POST http://localhost:9900/api/cron/tick > /dev/null`

2. **Invalid cron schedule:**
   - Validate: `curl "http://localhost:9900/api/cron/validate?schedule=YOUR_SCHEDULE"`

3. **Job disabled:**
   - Enable it:
   ```bash
   curl -X PUT http://localhost:9900/api/cron/myjob \
     -H "Content-Type: application/json" \
     -d '{"enabled": true}'
   ```

4. **Timeout too short:**
   - Increase timeout:
   ```bash
   curl -X PUT http://localhost:9900/api/cron/myjob \
     -H "Content-Type: application/json" \
     -d '{"timeout": 3600}'
   ```

### High CPU/Memory Usage

**Check current metrics:**

```bash
curl http://localhost:9900/api/services/myapp/metrics/current
```

**View historical trends:**

```bash
curl "http://localhost:9900/api/services/myapp/metrics?hours=24"
```

**Solutions:**

1. Restart the service to clear memory leaks:
   ```bash
   curl -X POST http://localhost:9900/api/services/myapp/restart
   ```

2. Check logs for issues:
   ```bash
   curl "http://localhost:9900/api/services/myapp/logs?limit=100"
   ```

3. Trigger auto-fix if there are errors:
   ```bash
   curl -X POST http://localhost:9900/api/services/myapp/fix
   ```

### Caddy Not Proxying Correctly

**Check generated config:**

```bash
curl http://localhost:9900/api/caddy/config
```

**Verify service is exposed:**

```bash
curl http://localhost:9900/api/services/myapp
# Check that expose_caddy: true and caddy_subdomain is set
```

**Update and reload:**

```bash
# Update service
curl -X PUT http://localhost:9900/api/services/myapp \
  -H "Content-Type: application/json" \
  -d '{
    "expose_caddy": true,
    "caddy_subdomain": "myapp"
  }'

# Reload Caddy
curl -X POST http://localhost:9900/api/caddy/reload
```

### Auto-Fix Not Working

**Check if auto-fix is enabled:**

```bash
echo $AUTOFIX_ENABLED
# Should be "true"
```

**Manual trigger:**

```bash
curl -X POST http://localhost:9900/api/services/myapp/fix
```

**Check job status:**

```bash
curl http://localhost:9900/api/jobs/fix:myapp
```

**Common issues:**

1. Robot CLI not installed
2. Service has no working_dir set
3. Timeout too short (increase AUTOFIX_TIMEOUT)

### Dashboard Not Loading

**Check if supervisor is running:**

```bash
curl http://localhost:9900/api/status
```

**Check supervisor logs:**

```bash
curl "http://localhost:9900/api/supervisor/logs?lines=50"
```

Or directly:

```bash
tail -f ~/.supervisor/supervisor.log
```

### Database Locked Errors

Supervisor uses SQLite, which can lock under heavy concurrent access.

**Restart supervisor:**

```bash
sudo systemctl restart supervisor
```

**Check for stuck processes:**

```bash
ps aux | grep supervisor
kill -9 <PID>  # If needed
```

## FAQ

**Q: Can I run supervisor on a different port?**

A: Yes, set `SUPERVISOR_PORT` environment variable:
```bash
SUPERVISOR_PORT=8888 supervisor
```

**Q: How do I back up my supervisor data?**

A: Copy the `~/.supervisor/` directory:
```bash
cp -r ~/.supervisor/ ~/supervisor-backup/
```

**Q: Can I use supervisor with Docker containers?**

A: Yes, register the docker run command as a service:
```bash
curl -X POST http://localhost:9900/api/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "mycontainer",
    "command": "docker run -p 8080:80 myimage",
    "port": 8080,
    "enabled": true
  }'
```

**Q: How do I disable auto-fix for a specific service?**

A: Auto-fix runs globally. To disable, set `AUTOFIX_ENABLED=false` in environment or trigger fixes manually only.

**Q: Can cron jobs send notifications on failure?**

A: Not directly, but you can check execution status via API and integrate with notification services:
```bash
# In your monitoring script
STATUS=$(curl -s http://localhost:9900/api/cron/myjob/executions | jq '.[0].success')
if [ "$STATUS" = "false" ]; then
  # Send notification
fi
```

**Q: How long are logs retained?**

A: Database logs are kept for `LOG_RETENTION_DAYS` (default: 3 days). Log files are rotated at `LOG_MAX_BYTES` (default: 10MB) and kept for `LOG_BACKUP_COUNT` rotations (default: 5).

**Q: Can I run multiple supervisor instances?**

A: Yes, on different ports:
```bash
# Instance 1
SUPERVISOR_PORT=9900 supervisor &

# Instance 2
SUPERVISOR_PORT=9901 supervisor &
```

Each will have separate databases in `~/.supervisor/`.

**Q: How do I migrate services to a new server?**

A: Export service configurations, copy to new server, and re-register:
```bash
# On old server
curl http://localhost:9900/api/services > services.json

# On new server
for service in $(cat services.json | jq -c '.[]'); do
  curl -X POST http://localhost:9900/api/services \
    -H "Content-Type: application/json" \
    -d "$service"
done