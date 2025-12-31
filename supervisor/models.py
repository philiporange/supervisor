"""
Database models for supervisor.

Uses Peewee ORM with SQLite. Stores service definitions, log entries,
resource metrics, auto-fix attempt history, and cron job schedules with execution history.
"""

import os
from datetime import datetime

from peewee import (
    AutoField,
    BooleanField,
    CharField,
    DatabaseProxy,
    DateTimeField,
    FloatField,
    ForeignKeyField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

from .config import config

database = DatabaseProxy()


def initialize_db():
    """Initialize database connection and create tables."""
    os.makedirs(os.path.dirname(config.db_path), exist_ok=True)
    db = SqliteDatabase(
        str(config.db_path),
        pragmas={
            "journal_mode": "wal",
            "cache_size": -64 * 1000,
            "foreign_keys": 1,
            "busy_timeout": 5000,
        },
    )
    database.initialize(db)
    database.create_tables([Service, LogEntry, Metric, FixAttempt, CronJob, CronExecution], safe=True)


class BaseModel(Model):
    """Base model with common configuration."""

    class Meta:
        database = database


class Service(BaseModel):
    """A managed service definition."""

    id = AutoField()
    name = CharField(unique=True, index=True)
    command = TextField()
    working_dir = CharField(null=True)
    port = IntegerField(null=True)
    enabled = BooleanField(default=True)
    expose_caddy = BooleanField(default=False)
    caddy_subdomain = CharField(null=True)  # Subdomain for Caddy routing (e.g., "myapp" -> myapp.domain.com)
    caddy_path = CharField(null=True)  # Legacy path-based routing
    watch_dirs = TextField(null=True)  # JSON list of directories to track disk usage
    created_at = DateTimeField(default=datetime.now)
    updated_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "services"

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now()
        return super().save(*args, **kwargs)

    def get_watch_dirs(self) -> list[str]:
        """Get list of directories to watch for disk usage."""
        if not self.watch_dirs:
            # Default to working_dir if set
            return [self.working_dir] if self.working_dir else []
        import json
        try:
            return json.loads(self.watch_dirs)
        except (json.JSONDecodeError, TypeError):
            return []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "command": self.command,
            "working_dir": self.working_dir,
            "port": self.port,
            "enabled": self.enabled,
            "expose_caddy": self.expose_caddy,
            "caddy_subdomain": self.caddy_subdomain,
            "caddy_path": self.caddy_path,
            "watch_dirs": self.get_watch_dirs(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class LogEntry(BaseModel):
    """A log entry from a service's stdout/stderr."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="logs", on_delete="CASCADE")
    level = CharField(default="info")  # info, warning, error
    message = TextField()
    timestamp = DateTimeField(default=datetime.now, index=True)

    class Meta:
        table_name = "log_entries"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "service_id": self.service_id,
            "level": self.level,
            "message": self.message,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class Metric(BaseModel):
    """Resource usage snapshot for a service."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="metrics", on_delete="CASCADE")
    cpu_percent = FloatField()
    memory_mb = FloatField()
    disk_mb = FloatField(null=True)  # Total size of watched directories
    timestamp = DateTimeField(default=datetime.now, index=True)

    class Meta:
        table_name = "metrics"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "service_id": self.service_id,
            "cpu_percent": self.cpu_percent,
            "memory_mb": self.memory_mb,
            "disk_mb": self.disk_mb,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class FixAttempt(BaseModel):
    """Record of a Robot auto-fix attempt."""

    id = AutoField()
    service = ForeignKeyField(Service, backref="fix_attempts", on_delete="CASCADE")
    error_summary = TextField()
    robot_response = TextField(null=True)
    success = BooleanField(default=False)
    files_modified = TextField(null=True)  # JSON list
    backup_path = CharField(null=True)  # Path to backup directory
    restored = BooleanField(default=False)  # Whether backup was restored
    timestamp = DateTimeField(default=datetime.now, index=True)

    class Meta:
        table_name = "fix_attempts"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "service_id": self.service_id,
            "error_summary": self.error_summary,
            "robot_response": self.robot_response,
            "success": self.success,
            "files_modified": self.files_modified,
            "backup_path": self.backup_path,
            "restored": self.restored,
            "can_restore": bool(self.backup_path and not self.restored),
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class CronJob(BaseModel):
    """A scheduled cron job definition."""

    id = AutoField()
    name = CharField(unique=True, index=True)
    command = TextField()
    schedule = CharField()  # Cron expression (e.g., "*/15 * * * *")
    working_dir = CharField(null=True)
    enabled = BooleanField(default=True)
    timeout = IntegerField(default=300)  # Execution timeout in seconds
    watch_dirs = TextField(null=True)  # JSON list of directories to track disk usage
    env_vars = TextField(null=True)  # JSON dict of environment variables
    env_file = CharField(null=True)  # Path to .env file to load
    last_run = DateTimeField(null=True)
    next_run = DateTimeField(null=True)
    created_at = DateTimeField(default=datetime.now)
    updated_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "cron_jobs"

    def save(self, *args, **kwargs):
        self.updated_at = datetime.now()
        return super().save(*args, **kwargs)

    def get_watch_dirs(self) -> list[str]:
        """Get list of directories to watch for disk usage."""
        if not self.watch_dirs:
            return [self.working_dir] if self.working_dir else []
        import json
        try:
            return json.loads(self.watch_dirs)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_env_vars(self) -> dict[str, str]:
        """Get environment variables as a dict."""
        if not self.env_vars:
            return {}
        import json
        try:
            return json.loads(self.env_vars)
        except (json.JSONDecodeError, TypeError):
            return {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "command": self.command,
            "schedule": self.schedule,
            "working_dir": self.working_dir,
            "enabled": self.enabled,
            "timeout": self.timeout,
            "watch_dirs": self.get_watch_dirs(),
            "env_vars": self.get_env_vars(),
            "env_file": self.env_file,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CronExecution(BaseModel):
    """Record of a cron job execution."""

    id = AutoField()
    cron_job = ForeignKeyField(CronJob, backref="executions", on_delete="CASCADE")
    started_at = DateTimeField(default=datetime.now, index=True)
    finished_at = DateTimeField(null=True)
    exit_code = IntegerField(null=True)
    stdout = TextField(null=True)
    stderr = TextField(null=True)
    success = BooleanField(default=False)
    duration_seconds = FloatField(null=True)
    cpu_percent = FloatField(null=True)  # Peak CPU usage
    memory_mb = FloatField(null=True)  # Peak memory usage
    fix_attempted = BooleanField(default=False)
    fix_success = BooleanField(null=True)

    class Meta:
        table_name = "cron_executions"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cron_job_id": self.cron_job_id,
            "cron_job_name": self.cron_job.name if self.cron_job else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "cpu_percent": self.cpu_percent,
            "memory_mb": self.memory_mb,
            "fix_attempted": self.fix_attempted,
            "fix_success": self.fix_success,
        }
