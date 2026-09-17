"""Tests for Telegram message formatting and the disabled-send path."""

import asyncio

from supervisor import notify
from supervisor.config import config
from supervisor.sluice import JevVerdict


def test_format_incident_escapes_and_trims():
    v = JevVerdict(kind="code_bug", probabilities={"code_bug": 0.9}, fixable=0.8,
                   persistent=0.5, input_tokens=1, model="jev")
    text = notify.format_incident("svc", v, "<tag>\n" + "x" * 5000, diagnosis="<b>root</b>")
    assert text.startswith("<b>svc</b>: code_bug (p=0.90")
    assert "&lt;tag&gt;" not in text  # trimmed away from the tail
    assert "&lt;b&gt;root&lt;/b&gt;" in text
    assert len(text) <= notify.TELEGRAM_LIMIT


def test_format_without_verdict():
    text = notify.format_incident("svc", None, "boom", strong_hits=3)
    assert "3 error lines" in text


def test_send_disabled_without_token(monkeypatch):
    monkeypatch.setattr(config, "telegram_token", "")
    assert not notify.enabled()
    assert asyncio.run(notify.send("hi")) is False
