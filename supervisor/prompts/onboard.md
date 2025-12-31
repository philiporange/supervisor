# Project Onboarding Prompt

You are onboarding a project to the Supervisor service manager. Your task is to analyze the project and register it with the supervisor API.

## Project Information
- Project path: {project_path}
- Project name: {project_name}

## Your Tasks

1. **Analyze the project** to determine:
   - The main entry point (look for run.py, main.py, app.py, server.py, or similar)
   - The command needed to run it (e.g., `python run.py`, `uvicorn app:app`)
   - The port it runs on (check for uvicorn, FastAPI, Flask config, or command line args)
   - Any dependencies or setup needed

2. **Check for existing configuration**:
   - Look for run scripts, Makefiles, docker-compose, or README instructions
   - Check pyproject.toml, setup.py, or requirements.txt for entry points

3. **Register with Supervisor** by making an API call:
   ```bash
   curl -X POST http://localhost:9900/api/services \
     -H "Content-Type: application/json" \
     -d '{
       "name": "{project_name}",
       "command": "<detected command>",
       "working_dir": "{project_path}",
       "port": <detected port or null>,
       "enabled": true,
       "watch_dirs": ["{project_path}"]
     }'
   ```

4. **Configure data directory** if the project uses sqlite/data:
   - The default data directory should be `~/.{project_name}/`
   - If the project has a config.py or similar, check if it already uses this pattern
   - If not, suggest environment variables or config changes to use `~/.{project_name}/` for:
     - Database files (*.db, *.sqlite)
     - Log files
     - Cache directories
     - Any other persistent data

## Guidelines

- If the project already has a clear run command, use it
- For FastAPI/uvicorn projects, prefer: `uvicorn <module>:app --host 0.0.0.0 --port <port>`
- For Flask projects, prefer: `python -m flask run --host 0.0.0.0 --port <port>`
- Default to port 8000 if not specified, but check if it's already in use
- Always set `working_dir` to the project path
- Include the project directory in `watch_dirs` for disk monitoring

## Output

After analyzing and registering, provide a summary:
- What command will be used
- What port the service will run on
- Any configuration changes suggested
- Confirmation that the service was registered

If there are any issues (missing dependencies, unclear entry point, etc.), explain them and ask for clarification.
