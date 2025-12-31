"""
Configuration for the supervisor service.

Loads settings from environment variables with sensible defaults.
All persistent data is stored in ~/.supervisor/
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Supervisor configuration."""

    # Paths
    data_dir: Path = Path.home() / ".supervisor"
    db_path: Path = None
    logs_dir: Path = None
    supervisor_log: Path = None

    # Logging
    log_max_bytes: int = int(os.environ.get("LOG_MAX_BYTES", str(10 * 1024 * 1024)))  # 10MB
    log_backup_count: int = int(os.environ.get("LOG_BACKUP_COUNT", "5"))

    # Server
    host: str = os.environ.get("SUPERVISOR_HOST", "0.0.0.0")
    port: int = int(os.environ.get("SUPERVISOR_PORT", "9900"))

    # Service URLs - the host used in links to services (defaults to machine IP)
    service_host: str = os.environ.get("SERVICE_HOST", "")

    def get_service_host(self) -> str:
        """Get the host to use in service URLs."""
        if self.service_host:
            return self.service_host
        # Auto-detect local IP
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "localhost"

    # Caddy
    caddy_admin_url: str = os.environ.get("CADDY_ADMIN_URL", "http://localhost:2019")
    caddy_domain: str = os.environ.get("CADDY_DOMAIN", "h.ph1l.uk:60443")
    caddy_base_domain: str = os.environ.get("CADDY_BASE_DOMAIN", "ph1l.uk")
    caddy_port: str = os.environ.get("CADDY_PORT", "60443")
    caddy_supervisor_file: str = os.environ.get("CADDY_SUPERVISOR_FILE", "/etc/caddy/supervisor.conf")

    # Monitoring
    monitor_interval: int = int(os.environ.get("MONITOR_INTERVAL", "60"))
    log_retention_days: int = int(os.environ.get("LOG_RETENTION_DAYS", "7"))

    # Auto-fix
    autofix_enabled: bool = os.environ.get("AUTOFIX_ENABLED", "true").lower() == "true"
    autofix_timeout: int = int(os.environ.get("AUTOFIX_TIMEOUT", "300"))

    # Process management
    restart_delay: int = int(os.environ.get("RESTART_DELAY", "5"))
    max_restart_attempts: int = int(os.environ.get("MAX_RESTART_ATTEMPTS", "3"))

    def __post_init__(self):
        """Initialize derived paths and create directories."""
        self.db_path = self.data_dir / "supervisor.db"
        self.logs_dir = self.data_dir / "logs"
        self.supervisor_log = self.data_dir / "supervisor.log"

        # Create directories
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


config = Config()
