"""Verify dashboard status includes the settings needed for service menu actions.

Replace service queries and process lookups with in-memory fixtures to check the
HTTP response without starting processes or modifying the service database.
"""

import httpx
import pytest

from supervisor import main
from supervisor.models import Service


@pytest.mark.asyncio
async def test_status_includes_service_exposure(monkeypatch):
    services = [
        Service(name="public", command="example", port=8123,
                expose_caddy=True, caddy_subdomain="public"),
        Service(name="private", command="example", expose_caddy=False),
    ]
    monkeypatch.setattr(Service, "select", lambda: services)
    monkeypatch.setattr(main.process_manager, "is_running", lambda name: False)
    monkeypatch.setattr(main.process_manager, "get_pid", lambda name: None)
    monkeypatch.setattr(main.config, "get_service_host", lambda: "localhost")
    monkeypatch.setattr(main, "_last_incidents", lambda hours: {})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        response = await client.get("/api/status")

    assert response.status_code == 200
    public, private = response.json()["services"]
    assert public["expose_caddy"] is True
    assert public["caddy_subdomain"] == "public"
    assert private["expose_caddy"] is False
    assert private["caddy_subdomain"] is None
    assert public["last_incident"] is None
