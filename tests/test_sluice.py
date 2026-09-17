"""Tests for the error sluice's channel, regex, window, and Jev request tiers."""

from datetime import datetime, timedelta

from supervisor import sluice
from supervisor.config import config


def test_stdout_needs_strong_pattern():
    assert sluice.classify_line("stdout", "error: something") is None
    assert sluice.classify_line("stdout", "Traceback (most recent call last):") == "strong"


def test_stderr_weak_and_strong():
    assert sluice.classify_line("stderr", "request failed, retrying") == "weak"
    assert sluice.classify_line("stderr", "AttributeError: module 'x' has no attribute 'y'") == "strong"
    assert sluice.classify_line("stderr", "sqlite3.OperationalError: disk I/O error") == "strong"
    assert sluice.classify_line("stderr", "2026-09-13 04:51:08 ERROR   bell.scheduler failed") == "strong"


def test_ignore_patterns_drop_noise():
    assert sluice.classify_line("stderr", 'INFO: 1.2.3.4:0 - "POST /v1/chat HTTP/1.1" 500 Internal Server Error') is None
    assert sluice.classify_line("stderr", "Scan complete: {'skipped': 5, 'errors': 0}") is None
    assert sluice.classify_line("stderr", "hello world") is None


def test_detect_level():
    assert sluice.detect_level("stderr", "INFO: started") == "info"
    assert sluice.detect_level("stderr", "WARNING: slow query") == "warning"
    assert sluice.detect_level("stderr", "Traceback (most recent call last):") == "error"
    assert sluice.detect_level("stdout", "connection refused") == "info"


def test_window_review_gating(monkeypatch):
    monkeypatch.setattr(config, "jev_interval_minutes", 30)
    w = sluice.Window()
    assert not w.due_for_review()
    w.add("stderr", "failed", "weak")
    assert not w.due_for_review()
    w.add("stderr", "ValueError: bad", "strong")
    assert w.due_for_review()
    sample = w.take_sample()
    assert "[E] ValueError: bad" in sample
    assert not w.due_for_review()
    w.add("stderr", "ValueError: bad", "strong")
    assert not w.due_for_review(datetime.now())
    assert w.due_for_review(datetime.now() + timedelta(minutes=31))


def test_jev_request_and_verdict(monkeypatch):
    monkeypatch.setattr(config, "jev_threshold", 0.7)
    monkeypatch.setattr(config, "jev_fixable_threshold", 0.6)
    req = sluice.build_jev_request("svc", "python app.py", "[E] KeyError: 'x'")
    assert set(req["questions"]) == {"kind", "fixable", "persistent"}
    assert set(req["questions"]["kind"]["criteria"]) == set(sluice.JEV_KINDS)

    body = {
        "model": "jev-1",
        "answers": {
            "kind": {"choice": "code_bug", "probabilities": {"code_bug": 0.6, "dependency": 0.2, "noise": 0.2}},
            "fixable": {"noul": 0.9},
            "persistent": {"noul": 0.5},
        },
        "usage": {"input_tokens": 100},
    }
    verdict = sluice.parse_jev_response(body)
    assert verdict.should_escalate()
    body["answers"]["kind"] = {"choice": "external", "probabilities": {"external": 0.8, "code_bug": 0.2}}
    assert not sluice.parse_jev_response(body).should_escalate()
