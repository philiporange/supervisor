"""Tests for API model validation (service/cron names used in paths and URLs)."""

import pytest
from pydantic import ValidationError

from supervisor.main import CronJobCreate, ServiceCreate


def test_service_name_accepts_normal_names():
    for name in ("myapp", "my-app", "my_app.v2", "App2"):
        assert ServiceCreate(name=name, command="echo hi").name == name


def test_service_name_rejects_unsafe_names():
    for name in ("../etc", "a/b", "a b", ".hidden", "", "a;rm"):
        with pytest.raises(ValidationError):
            ServiceCreate(name=name, command="echo hi")


def test_cron_name_rejects_unsafe_names():
    with pytest.raises(ValidationError):
        CronJobCreate(name="../escape", command="echo hi", schedule="* * * * *")
