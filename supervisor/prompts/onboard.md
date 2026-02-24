# Project Onboarding Prompt

You are onboarding a project to the Supervisor service manager. Your task is to analyze the project and register it as a running service.

## Project Information
- Project path: {project_path}
- Project name: {project_name}
{requested_port}

## Currently Registered Services
{existing_services}

## Your Tasks

1. **Analyze the project** to determine:
   - The main entry point (look for run.py, main.py, app.py, server.py, or similar)
   - The command needed to run it
   - The port it runs on
   - Check pyproject.toml for `[project.scripts]` entry points
   - Check for run scripts, Makefiles, docker-compose, or README instructions

2. **Choose a port.** {port_instruction}

3. **Register with Supervisor** by making an API call:
   ```bash
   curl -X POST http://localhost:9900/api/services \
     -H "Content-Type: application/json" \
     -d '{{
       "name": "{project_name}",
       "command": "<command>",
       "working_dir": "{project_path}",
       "port": <port>,
       "enabled": true,
       "watch_dirs": ["{project_path}"]
     }}'
   ```

4. **Verify the service started** by checking:
   ```bash
   curl -s http://localhost:9900/api/services/{project_name}
   ```
   If `"running": false`, check the logs:
   ```bash
   curl -s http://localhost:9900/api/services/{project_name}/logs?limit=20
   ```
   Diagnose the failure, fix the command, update the service, and retry.

## Command Execution Constraints

Commands are executed directly via `subprocess.Popen` without a shell. This means:

- **No inline environment variables**: `MY_VAR=value command` will NOT work. The `MY_VAR=value` part is treated as the executable name, causing the command to fail.
- **No shell operators**: Pipes (`|`), redirects (`>`), chaining (`&&`), and subshells do not work.
- **Exception**: Commands starting with `cd ` are run through a shell.

To set ports or other configuration, pass them as explicit command-line arguments rather than environment variables.

## Command Guidelines

- For **FastAPI/uvicorn** projects, always use:
  `python -m uvicorn <package>.server:app --host 0.0.0.0 --port <port>`
  Even if the project has an entry point script (in pyproject.toml or run.py) that internally calls uvicorn, use the uvicorn command directly so the port can be set explicitly via `--port`. Check server.py (or the main module) for the correct `app` object path.

- For **Flask** projects:
  `python -m flask run --host 0.0.0.0 --port <port>`

- For projects with a **run.py** that takes port arguments:
  `python {project_path}/run.py --port <port>`

- For **docker-compose** projects:
  `docker-compose up`

- Always set `working_dir` to the project path
- Include the project directory in `watch_dirs`

## Data Directory

If the project uses sqlite or persistent data, the convention is `~/.{{project_name}}/` for databases, logs, and cache. If the project already follows this pattern, no changes are needed.

## Output

After registering and verifying, provide a brief summary:
- The command being used
- The port assigned
- Whether the service started successfully
- Any issues encountered
