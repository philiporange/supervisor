"""Tests for toggling a service's auto-start flag over the API."""

import httpx
import pytest
from peewee import SqliteDatabase

from supervisor import main, models


@pytest.fixture
def db():
    test_db = SqliteDatabase(":memory:")
    models.database.initialize(test_db)
    test_db.create_tables([models.Service])
    yield test_db
    test_db.close()


@pytest.mark.asyncio
async def test_disable_and_enable(db, monkeypatch):
    models.Service.create(name="svc", command="python app.py")
    monkeypatch.setattr(main.process_manager, "is_running", lambda name: True)
    monkeypatch.setattr(main.process_manager, "get_pid", lambda name: 42)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        r = await client.post("/api/services/svc/disable")
        assert r.status_code == 200 and r.json()["enabled"] is False and r.json()["running"] is True
        assert models.Service.get(models.Service.name == "svc").enabled is False
        r = await client.post("/api/services/svc/enable")
        assert r.json()["enabled"] is True
        assert (await client.post("/api/services/nope/disable")).status_code == 404
