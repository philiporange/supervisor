"""
Caddy reverse proxy management.

Generates Caddy configuration for supervisor-managed services and writes to
an auxiliary config file that's imported by the main Caddyfile. Uses subdomain
routing by default (e.g., myapp.domain.com -> localhost:port).

The main Caddyfile should include:
    import /etc/caddy/supervisor.conf
"""

import asyncio
import logging
import subprocess
from pathlib import Path

import httpx

from .config import config
from .models import Service

logger = logging.getLogger(__name__)


def generate_supervisor_caddyfile(services: list[Service] = None) -> str:
    """
    Generate Caddyfile content for supervisor-managed services.

    Uses subdomain routing: {subdomain}.{base_domain}:{port}
    Falls back to path-based routing if caddy_subdomain is not set but caddy_path is.
    """
    if services is None:
        services = Service.select().where(Service.expose_caddy == True)

    lines = [
        "# Supervisor-managed services",
        "# Auto-generated - do not edit manually",
        "",
    ]

    subdomain_services = []
    path_services = []

    for service in services:
        if not service.expose_caddy or not service.port:
            continue

        if service.caddy_subdomain:
            subdomain_services.append(service)
        elif service.caddy_path:
            path_services.append(service)

    # Generate subdomain blocks
    for service in subdomain_services:
        subdomain = service.caddy_subdomain
        domain = f"{subdomain}.{config.caddy_base_domain}:{config.caddy_port}"
        lines.extend([
            f"{domain} {{",
            f"\treverse_proxy http://localhost:{service.port}",
            "}",
            "",
        ])

    # Generate path-based routing (legacy support) - grouped under main domain
    if path_services:
        lines.extend([
            f"# Path-based routes on {config.caddy_domain}",
            f"# (Add these to your main domain block manually or via import)",
        ])
        for service in path_services:
            path = service.caddy_path.rstrip("/")
            lines.extend([
                f"# {service.name}: handle {path}/* -> localhost:{service.port}",
            ])

    return "\n".join(lines)


def write_supervisor_config() -> tuple[bool, str]:
    """
    Write the supervisor Caddyfile to the configured path.

    Returns:
        Tuple of (success, message)
    """
    config_path = Path(config.caddy_supervisor_file)

    try:
        content = generate_supervisor_caddyfile()

        # Ensure parent directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write config file
        config_path.write_text(content)
        logger.info(f"Wrote Caddy config to {config_path}")

        return True, f"Config written to {config_path}"

    except PermissionError:
        error = f"Permission denied writing to {config_path}"
        logger.error(error)
        return False, error
    except Exception as e:
        error = f"Error writing Caddy config: {e}"
        logger.error(error)
        return False, error


async def reload_caddy() -> tuple[bool, str]:
    """
    Write supervisor config and reload Caddy.

    Writes to the auxiliary config file and reloads Caddy using systemctl.

    Returns:
        Tuple of (success, message)
    """
    # First write the config file
    success, message = write_supervisor_config()
    if not success:
        return False, message

    # Try to reload Caddy via systemctl
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["sudo", "systemctl", "reload", "caddy"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            logger.info("Caddy reloaded successfully via systemctl")
            return True, "Configuration written and Caddy reloaded"
        else:
            # Try caddy reload command as fallback
            result = await asyncio.to_thread(
                subprocess.run,
                ["caddy", "reload", "--config", "/etc/caddy/Caddyfile"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                logger.info("Caddy reloaded successfully via caddy reload")
                return True, "Configuration written and Caddy reloaded"
            else:
                error = f"Caddy reload failed: {result.stderr}"
                logger.error(error)
                return False, error

    except subprocess.TimeoutExpired:
        error = "Caddy reload timed out"
        logger.error(error)
        return False, error
    except FileNotFoundError:
        # systemctl not available, try admin API
        return await reload_caddy_via_api()
    except Exception as e:
        error = f"Error reloading Caddy: {e}"
        logger.error(error)
        return False, error


async def reload_caddy_via_api() -> tuple[bool, str]:
    """
    Reload Caddy via the admin API.

    Note: This reloads the entire config, so it should only be used
    if the main Caddyfile imports the supervisor config.
    """
    try:
        async with httpx.AsyncClient() as client:
            # Tell Caddy to reload its config file
            response = await client.post(
                f"{config.caddy_admin_url}/load",
                headers={"Content-Type": "text/caddyfile"},
                content=Path("/etc/caddy/Caddyfile").read_text(),
                timeout=30.0,
            )

            if response.status_code == 200:
                logger.info("Caddy reloaded via admin API")
                return True, "Configuration reloaded via API"
            else:
                error = f"Caddy API reload failed: {response.text}"
                logger.error(error)
                return False, error

    except httpx.ConnectError:
        error = f"Could not connect to Caddy admin API at {config.caddy_admin_url}"
        logger.error(error)
        return False, error
    except Exception as e:
        error = f"Error reloading Caddy via API: {e}"
        logger.error(error)
        return False, error


async def get_caddy_config() -> dict | None:
    """Fetch current Caddy configuration from admin API."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{config.caddy_admin_url}/config/",
                timeout=10.0,
            )
            if response.status_code == 200:
                return response.json()
            return None
    except Exception as e:
        logger.error(f"Error fetching Caddy config: {e}")
        return None


def generate_caddyfile(services: list[Service] = None) -> str:
    """
    Generate human-readable Caddyfile format (for display purposes).

    This shows what the supervisor would configure, but the actual
    config is written to the auxiliary file.
    """
    return generate_supervisor_caddyfile(services)


# Legacy function name for compatibility
def generate_caddy_config(services: list[Service] = None) -> dict:
    """
    Generate Caddy JSON config (legacy - prefer generate_supervisor_caddyfile).

    Returns a dict showing the configured services.
    """
    if services is None:
        services = Service.select().where(Service.expose_caddy == True)

    return {
        "supervisor_config_file": config.caddy_supervisor_file,
        "base_domain": config.caddy_base_domain,
        "port": config.caddy_port,
        "services": [
            {
                "name": s.name,
                "subdomain": s.caddy_subdomain,
                "path": s.caddy_path,
                "port": s.port,
                "url": f"https://{s.caddy_subdomain}.{config.caddy_base_domain}:{config.caddy_port}"
                if s.caddy_subdomain else None,
            }
            for s in services
            if s.expose_caddy and s.port
        ],
    }
