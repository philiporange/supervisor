---
name: supervisor
description: Register the current project as a service on the local Supervisor instance (localhost:9900). Analyzes the project to determine the run command and port, checks for conflicts, registers via the API, and verifies startup.
allowed-tools: Bash, Read, Glob, Grep, WebFetch
argument-hint: "[port]"
---

# Supervisor — Manage Services and Cron Jobs

Control services and cron jobs on the local Supervisor instance via the `supervisor` CLI. The server runs at `http://localhost:9900` and is assumed to be already running.

If an argument is provided and it looks like a port number, treat the invocation as a request to register the current project as a service on that port. If no argument is provided, show the current status.

## CLI Reference

### Service overview

```bash
supervisor status          # table: name, state, port, pid, cpu, mem
supervisor ls              # table: name, state, port, command
```

### Service control

```bash
supervisor start <name>
supervisor stop <name>
supervisor restart <name>
supervisor logs <name> [--level info|warning|error] [--limit N]
```

### Register / remove services

```bash
supervisor add <name> "<command>" [--dir /path] [--port N] [--caddy-subdomain sub] [--disabled]
supervisor rm <name>
```

### Cron jobs

```bash
supervisor cron ls
supervisor cron status     # includes 24h execution/failure counts
supervisor cron run <name>
supervisor cron stop <name>
supervisor cron logs <name> [--limit N]
supervisor cron add <name> "<command>" "<schedule>" [--dir /path] [--timeout N] [--env-file /path] [--disabled]
supervisor cron rm <name>
```

### Other

```bash
supervisor onboard <project> [--model opus] [--port N]
supervisor projects        # list ~/Code/ directories
```

## Registering the Current Project

When asked to register a project (or invoked with a port argument):

### 1. Analyze the project

Examine the current working directory:

- **Entry point**: Look for `run.py`, `main.py`, `app.py`, `server.py`, or `pyproject.toml` `[project.scripts]`
- **Framework**: Check imports for FastAPI/uvicorn, Flask, Django
- **Port**: Look for port configuration in the code (argparse, uvicorn config, etc.)

### 2. Check existing services and pick a port

```bash
supervisor status
```

If a port was provided as an argument, use that. Otherwise, choose an unused port starting from 8001 upward.

### 3. Check for duplicate registration

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:9900/api/services/<project_name>
```

If `200`, the project is already registered — tell the user and stop. Only proceed if `404`.

### 4. Determine the run command

- **FastAPI/uvicorn**: `python -m uvicorn <package>.<module>:app --host 0.0.0.0 --port <port>`
- **Flask**: `python -m flask run --host 0.0.0.0 --port <port>`
- **Django**: `python manage.py runserver 0.0.0.0:<port>`
- **docker-compose**: `docker-compose up`
- **Node.js**: `node <entry>` or `npm start`

Commands run via `subprocess.Popen` **without a shell** — no inline env vars, pipes, redirects, or chaining. Wrap in `bash -c "..."` if shell features are needed.

### 5. Register

```bash
supervisor add <project_name> "<command>" --dir "<project_path>" --port <port>
```

### 6. Verify startup

Wait 3 seconds, then:

```bash
supervisor status
```

If not running, check logs:

```bash
supervisor logs <project_name> --limit 20
```

Common fixes: wrong module path, missing dependencies, wrong port argument. If fixable, update via the API and restart:

```bash
curl -X PUT http://localhost:9900/api/services/<name> -H "Content-Type: application/json" -d '{"command": "<fixed>"}'
supervisor restart <name>
```

### 7. Report

State the service name, command, port, whether it started, and link to `http://localhost:9900`.
