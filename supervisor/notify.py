"""
Telegram notifications for the error sluice.

Sends one message per notable incident through the Telegram Bot API with
httpx. Messages use Telegram's HTML parse mode, so every piece of service
output is escaped and long samples and diagnoses are trimmed to stay under
the 4096-character message limit. Sending is best-effort: a missing token or
chat id disables notifications, and a delivery failure is logged and
swallowed so the sluice never stalls on it.
"""

import html
import logging

import httpx

from .config import config

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096
SAMPLE_CHARS = 1200


def enabled() -> bool:
    return bool(config.telegram_token and config.telegram_chat_id)


def _tail(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    text = text[-limit:]
    return "..." + text[text.find("\n") + 1 :] if "\n" in text else "..." + text


def format_incident(name: str, verdict, sample: str, strong_hits: int = 0,
                    diagnosis: str | None = None, fix: str | None = None) -> str:
    """Render an incident as Telegram HTML, trimmed to the message limit."""
    if verdict:
        head = (
            f"<b>{html.escape(name)}</b>: {html.escape(verdict.kind)} "
            f"(p={verdict.kind_probability:.2f}, fixable={verdict.fixable:.2f}, "
            f"persistent={verdict.persistent:.2f})"
        )
    else:
        head = f"<b>{html.escape(name)}</b>: {strong_hits} error lines, classifier unavailable"
    parts = [head, f"<pre>{html.escape(_tail(sample, SAMPLE_CHARS))}</pre>"]
    budget = TELEGRAM_LIMIT - sum(len(p) for p in parts) - 100
    if fix:
        parts.append(f"<b>Fix</b>: {html.escape(_tail(fix, min(budget, 800)))}")
        budget -= len(parts[-1])
    if diagnosis and budget > 200:
        parts.append(f"<b>Diagnosis</b>\n{html.escape(_tail(diagnosis, budget))}")
    return "\n".join(parts)


async def send(text: str) -> bool:
    """Deliver one message. Returns False when disabled or on any failure."""
    if not enabled():
        return False
    url = f"https://api.telegram.org/bot{config.telegram_token}/sendMessage"
    payload = {
        "chat_id": config.telegram_chat_id,
        "text": text[:TELEGRAM_LIMIT],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
    except Exception as e:
        logger.error(f"Telegram notification failed: {e}")
        return False
    return True
