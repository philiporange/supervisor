"""Tests for chat-driven onboarding helpers in robot integration."""

import pytest

from supervisor import robot_integration


@pytest.mark.parametrize(
    ("message", "expected_project", "expected_port"),
    [
        ("onboard audiobookbay", "audiobookbay", None),
        ("onboard ~/Code/audiobookbay", "~/Code/audiobookbay", None),
        ("onboard ~/Code/audiobookbay --port 8010", "~/Code/audiobookbay", 8010),
        ("onboard audiobookbay port 8011", "audiobookbay", 8011),
        ("status audiobookbay", None, None),
    ],
)
def test_parse_onboard_request(message, expected_project, expected_port):
    project, port = robot_integration.parse_onboard_request(message)
    assert project == expected_project
    assert port == expected_port


@pytest.mark.asyncio
async def test_stream_robot_chat_routes_onboard_requests(monkeypatch):
    events = [
        {"type": "status", "content": "Preparing onboarding"},
        {"type": "done", "content": ""},
    ]

    async def fake_stream_robot_onboard(project, model="opus", port=None):
        assert project == "~/Code/audiobookbay"
        assert model == "haiku"
        assert port == 8012
        for event in events:
            yield event

    monkeypatch.setattr(robot_integration, "stream_robot_onboard", fake_stream_robot_onboard)

    received = [
        event
        async for event in robot_integration.stream_robot_chat(
            message="onboard ~/Code/audiobookbay --port 8012",
            model="haiku",
        )
    ]

    assert received == events
