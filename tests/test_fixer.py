"""Tests for the fixer's decision tiers and the agent result parsing."""

import pytest
from peewee import SqliteDatabase

from supervisor import fix_agent, fixer, models
from supervisor.config import config
from supervisor.sluice import JevVerdict


@pytest.fixture
def db():
    test_db = SqliteDatabase(":memory:")
    models.database.initialize(test_db)
    test_db.create_tables([models.Service, models.CronJob, models.FixAttempt, models.Incident])
    yield test_db
    test_db.close()


def verdict(kind="code_bug", p=0.9, fixable=0.9):
    return JevVerdict(kind=kind, probabilities={kind: p}, fixable=fixable, persistent=0.5,
                      input_tokens=10, model="jev")


def test_decide_respects_cooldown_and_cap(db, monkeypatch):
    monkeypatch.setattr(config, "autofix_enabled", True)
    monkeypatch.setattr(config, "fix_daily_cap", 1)
    svc = models.Service.create(name="svc", command="python app.py")
    f = fixer.AutoFixer()
    assert f._decide("svc", verdict("external")) == "dismissed"
    assert f._decide("svc", verdict()) == "fix_attempted"
    models.Incident.create(service=svc, sample="x", decision="fix_attempted")
    assert f._decide("svc", verdict()) == "cooldown"
    assert f._decide("other", verdict()) == "daily_cap"
    monkeypatch.setattr(config, "autofix_enabled", False)
    monkeypatch.setattr(config, "diagnose_enabled", False)
    assert f._decide("other", verdict()) == "disabled"


def test_decide_diagnoses_when_autofix_off(db, monkeypatch):
    monkeypatch.setattr(config, "autofix_enabled", False)
    monkeypatch.setattr(config, "diagnose_enabled", True)
    monkeypatch.setattr(config, "diagnose_daily_cap", 1)
    svc = models.Service.create(name="svc", command="python app.py")
    f = fixer.AutoFixer()
    assert f._decide("svc", verdict()) == "diagnosed"
    models.Incident.create(service=svc, sample="x", decision="diagnosed")
    assert f._decide("svc", verdict()) == "cooldown"
    assert f._decide("other", verdict()) == "daily_cap"


def test_should_notify_skips_noise_and_cooldown(db, monkeypatch):
    monkeypatch.setattr(config, "notify_cooldown_minutes", 60)
    svc = models.Service.create(name="svc", command="python app.py")
    f = fixer.AutoFixer()
    assert f._should_notify("svc", verdict("external"))
    assert not f._should_notify("svc", verdict("noise"))
    assert f._should_notify("svc", None)
    models.Incident.create(service=svc, sample="x", decision="dismissed", notified=True)
    assert not f._should_notify("svc", verdict("external"))
    assert f._should_notify("other", verdict("external"))


def test_on_log_only_windows_candidates():
    f = fixer.AutoFixer()
    f.on_log("svc", "stdout", "info", "all good")
    assert "svc" not in f._windows
    f.on_log("svc", "stderr", "error", "RuntimeError: boom")
    assert f._windows["svc"].strong_since_review == 1


def test_parse_verdict():
    assert fix_agent.parse_verdict("did things\nVERDICT: fixed\n") == "fixed"
    assert fix_agent.parse_verdict("VERDICT: fixed\nlater: VERDICT: not_a_code_bug") == "not_a_code_bug"
    assert fix_agent.parse_verdict("no verdict") == "unable"


def test_working_dir_for():
    assert fixer.working_dir_for("python /a/b/run.py", None) == "/a/b"
    assert fixer.working_dir_for("python run.py", "/x") == "/x"
    assert fixer.working_dir_for("uvicorn app:app", None) is None
