# Supervisor

A unified service manager for Python/FastAPI projects with process supervision, cron job scheduling, resource monitoring, auto-fix capabilities, and Caddy integration.

## Installation

```bash
# Install dependencies
cd /home/sam/Code/supervisor
pip install -r requirements.txt

# Install systemd service
sudo cp supervisor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable supervisor
sudo systemctl start supervisor

# Enable cron job scheduling (triggers once per minute)
(crontab -l 2>/dev/null; echo "* * * * * curl -s -X POST http://localhost:9900/api/cron/tick > /dev/null") | crontab -
```

## Usage

Dashboard available at http://localhost:9900

### Register a service

```bash
curl -X POST http://localhost:9900/api/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "myapp",
    "command": "python /path/to/run.py",
    "port": 8000,
    "enabled": true
  }'
```

### Onboard a project with AI

Use the Chat tab in the dashboard or API:

```bash
# Onboard by project name (assumes ~/Code/<name>)
curl -X POST http://localhost:9900/api/onboard \
  -H "Content-Type: application/json" \
  -d '{"project": "myproject", "model": "opus"}'

# Or by full path
curl -X POST http://localhost:9900/api/onboard \
  -H "Content-Type: application/json" \
  -d '{"project": "/path/to/project", "model": "opus"}'
```

The AI will analyze the project, determine how to run it, and register it with supervisor.
Projects use `~/.{project_name}/` as the default data directory for databases, logs, and cache.

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/services | List all services |
| POST | /api/services | Register new service |
| GET | /api/services/{name} | Get service details |
| DELETE | /api/services/{name} | Remove service |
| POST | /api/services/{name}/start | Start service |
| POST | /api/services/{name}/stop | Stop service |
| POST | /api/services/{name}/restart | Restart service |
| GET | /api/services/{name}/logs | Get service logs |
| GET | /api/services/{name}/metrics | Get resource history |
| POST | /api/services/{name}/fix | Trigger auto-fix (background job) |
| GET | /api/services/{name}/fixes | Get fix attempt history |
| POST | /api/fixes/{id}/restore | Restore code from backup |
| GET | /api/status | Overview of all services |
| GET | /api/cron | List all cron jobs |
| POST | /api/cron | Register new cron job |
| GET | /api/cron/{name} | Get cron job details |
| PUT | /api/cron/{name} | Update cron job |
| DELETE | /api/cron/{name} | Remove cron job |
| POST | /api/cron/{name}/run | Trigger cron job immediately |
| POST | /api/cron/{name}/stop | Stop running cron job |
| GET | /api/cron/{name}/executions | Get execution history |
| POST | /api/cron/tick | Trigger scheduled jobs (called by system cron) |
| GET | /api/cron/status | Cron jobs overview |
| GET | /api/cron/validate | Validate cron schedule expression |
| GET | /api/jobs | List background jobs |
| GET | /api/jobs/{id} | Get job status/result |
| GET | /api/supervisor/logs | Get supervisor logs |
| POST | /api/caddy/reload | Reload Caddy config |
| POST | /api/onboard | Onboard project with AI |
| GET | /api/onboard/preview | Preview onboard without running |
| POST | /api/chat | Stream chat with AI (SSE) |

### Service Registration Options

```json
{
  "name": "myapp",
  "command": "python /path/to/run.py",
  "working_dir": "/path/to",
  "port": 8000,
  "enabled": true,
  "expose_caddy": true,
  "caddy_subdomain": "myapp",
  "watch_dirs": ["/path/to/project", "/path/to/data"]
}
```

- `name` - Unique identifier
- `command` - Command to run
- `working_dir` - Working directory (optional, auto-detected)
- `port` - Port for health checks and Caddy
- `enabled` - Auto-start on supervisor boot
- `expose_caddy` - Add to Caddy reverse proxy
- `caddy_subdomain` - Subdomain for Caddy routing (e.g., "myapp" -> myapp.domain.com)
- `caddy_path` - Legacy path-based routing (deprecated in favor of subdomain)
- `watch_dirs` - Directories to track for disk usage (defaults to working_dir)

### Register a cron job

```bash
curl -X POST http://localhost:9900/api/cron \
  -H "Content-Type: application/json" \
  -d '{
    "name": "backup",
    "command": "python /path/to/backup.py",
    "schedule": "0 2 * * *",
    "working_dir": "/path/to/project",
    "enabled": true
  }'
```

### Cron Job Registration Options

```json
{
  "name": "backup",
  "command": "python /path/to/backup.py",
  "schedule": "0 2 * * *",
  "working_dir": "/path/to/project",
  "enabled": true,
  "timeout": 300,
  "env_file": "/path/to/.env",
  "env_vars": {"API_KEY": "secret", "DEBUG": "true"}
}
```

- `name` - Unique identifier
- `command` - Command to run
- `schedule` - Cron expression (e.g., `*/15 * * * *` for every 15 minutes)
- `working_dir` - Working directory for the command
- `enabled` - Whether the job is active
- `timeout` - Maximum execution time in seconds (default: 300)
- `env_file` - Path to a .env file to load (relative paths resolved from working_dir)
- `env_vars` - Dictionary of environment variables (overrides env_file values)

Cron jobs capture stdout/stderr, track CPU/memory usage during execution, and can trigger auto-fix on failures if a working directory is set.

## Features

- **Process Management** - Start/stop/restart with graceful shutdown
- **Crash Recovery** - Auto-restarts crashed services with backoff
- **Cron Scheduling** - Run scripts on cron schedules with execution history and resource tracking
- **Log Capture** - Stores stdout/stderr in SQLite and log files
- **Resource Monitoring** - Tracks CPU/memory/disk usage per service and cron job
- **Auto-Fix** - Uses Robot to detect and fix errors in services and cron jobs (with backup/restore)
- **AI Onboarding** - Analyze projects and register them automatically using Robot AI
- **AI Chat** - Interactive chat assistant for project help and debugging
- **Background Jobs** - Long operations run async with job tracking
- **Caddy Integration** - Generates subdomain-based reverse proxy config
- **Web Dashboard** - View and control services and cron jobs from browser with live updates

## Configuration

Environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| SUPERVISOR_HOST | 0.0.0.0 | Host to bind API server |
| SUPERVISOR_PORT | 9900 | API port |
| SERVICE_HOST | (auto-detect) | Host for service links (auto-detects machine IP) |
| CADDY_ADMIN_URL | http://localhost:2019 | Caddy admin API |
| CADDY_DOMAIN | h.ph1l.uk:60443 | Domain for Caddy config |
| CADDY_BASE_DOMAIN | ph1l.uk | Base domain for subdomain routing |
| CADDY_PORT | 60443 | Port for Caddy routing |
| CADDY_SUPERVISOR_FILE | /etc/caddy/supervisor.conf | Path to supervisor Caddy config |
| MONITOR_INTERVAL | 60 | Metrics collection interval (seconds) |
| LOG_MAX_BYTES | 10485760 | Max log file size (10MB) |
| LOG_BACKUP_COUNT | 5 | Number of rotated log files to keep |
| LOG_RETENTION_DAYS | 7 | Days to keep logs in database |
| AUTOFIX_ENABLED | true | Enable Robot auto-fix |
| AUTOFIX_TIMEOUT | 300 | Auto-fix timeout (seconds) |
| MAX_RESTART_ATTEMPTS | 3 | Max restarts before giving up |
| RESTART_DELAY | 5 | Delay before restarting crashed services (seconds) |

## Data

All data stored in `~/.supervisor/`:
- `supervisor.db` - SQLite database
- `supervisor.log` - Supervisor logs (with rotation, max 10MB x 5 files)
- `logs/{service}/` - Per-service log files
- `backups/{service}/` - Code backups before auto-fix (keeps last 10)

## License

CC0
