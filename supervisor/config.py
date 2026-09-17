"""
Configuration for the supervisor service.

Loads settings from environment variables with sensible defaults.
All persistent data is stored in ~/.supervisor/. The error sluice settings
control how output is escalated: regex window size, the Jev classification
interval and thresholds, and the coding-agent cooldown and daily cap.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path.home() / ".env")


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
        """Get the host to use in service URLs (auto-detection is cached)."""
        if self.service_host:
            return self.service_host
        # Auto-detect local IP once; this runs on every status poll otherwise
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            self.service_host = s.getsockname()[0]
            s.close()
        except Exception:
            self.service_host = "localhost"
        return self.service_host

    # Caddy
    caddy_admin_url: str = os.environ.get("CADDY_ADMIN_URL", "http://localhost:2019")
    caddy_domain: str = os.environ.get("CADDY_DOMAIN", "h.ph1l.uk:60443")
    caddy_base_domain: str = os.environ.get("CADDY_BASE_DOMAIN", "ph1l.uk")
    caddy_port: str = os.environ.get("CADDY_PORT", "60443")
    caddy_supervisor_file: str = os.environ.get("CADDY_SUPERVISOR_FILE", "/etc/caddy/supervisor.conf")

    # Monitoring
    monitor_interval: int = int(os.environ.get("MONITOR_INTERVAL", "300"))
    log_retention_days: int = int(os.environ.get("LOG_RETENTION_DAYS", "3"))

    # Error sluice: tiers 1-2 (channel + regex) window
    sluice_window_lines: int = int(os.environ.get("SLUICE_WINDOW_LINES", "80"))
    sluice_sample_chars: int = int(os.environ.get("SLUICE_SAMPLE_CHARS", "6000"))

    # Error sluice: tier 3 (Jev typed classification via TypeSafe)
    typesafe_api_key: str = os.environ.get("TYPESAFE_API_KEY", "")
    typesafe_url: str = os.environ.get("TYPESAFE_URL", "https://api.typesafe.ai/v1/systemone")
    typesafe_model: str = os.environ.get("TYPESAFE_MODEL", "jev-latest")
    jev_interval_minutes: int = int(os.environ.get("JEV_INTERVAL_MINUTES", "30"))
    jev_threshold: float = float(os.environ.get("JEV_THRESHOLD", "0.7"))
    jev_fixable_threshold: float = float(os.environ.get("JEV_FIXABLE_THRESHOLD", "0.6"))

    # Error sluice: tier 4 (coding agent fix, rare last resort)
    autofix_enabled: bool = os.environ.get("AUTOFIX_ENABLED", "false").lower() == "true"
    autofix_timeout: int = int(os.environ.get("AUTOFIX_TIMEOUT", "900"))
    fix_model: str = os.environ.get("FIX_MODEL", "muse-spark-1.3-contributor")
    fix_reasoning_effort: str = os.environ.get("FIX_REASONING_EFFORT", "medium")
    fix_max_steps: int = int(os.environ.get("FIX_MAX_STEPS", "80"))
    fix_cooldown_minutes: int = int(os.environ.get("FIX_COOLDOWN_MINUTES", "360"))
    fix_daily_cap: int = int(os.environ.get("FIX_DAILY_CAP", "6"))

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
