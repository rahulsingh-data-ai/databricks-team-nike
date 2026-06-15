"""SMS messaging via Twilio.

Env vars expected:
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_SMS_FROM            e.g. +15005550006 or your verified Twilio number

When the env vars aren't set, send_message logs the payload and returns
``{"sent": False, "error": "twilio not configured"}``. This keeps tests
and local development hassle-free.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _twilio_client():
    try:
        from twilio.rest import Client  # type: ignore
    except ImportError:
        logger.warning("twilio package not installed")
        return None

    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        logger.info("Twilio not configured; messages will be logged but not sent")
        return None
    return Client(sid, token)


def send_message(to: str, body: str) -> dict:
    """Send an SMS via Twilio.

    Returns ``{"sent": bool, "message_sid": str | None, "error": str | None}``.
    Never raises — when Twilio isn't configured (or fails), we log and
    return a structured result so callers (and tests) can keep working.
    """
    body = (body or "").strip()
    if not body:
        return {"sent": False, "error": "empty body"}
    if not to:
        return {"sent": False, "error": "missing recipient"}

    # Strip any accidental whatsapp: prefix; we only ship SMS now
    if to.startswith("whatsapp:"):
        to = to.replace("whatsapp:", "", 1)

    from_ = os.getenv("TWILIO_SMS_FROM", "")
    client = _twilio_client()
    if not client or not from_:
        logger.info(f"[messaging] (dry-run) to={to} body={body[:160]!r}")
        return {"sent": False, "error": "twilio not configured"}

    try:
        msg = client.messages.create(body=body[:1600], from_=from_, to=to)
        logger.info(f"[messaging] sent sid={msg.sid} to={to}")
        return {"sent": True, "message_sid": msg.sid, "error": None}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[messaging] send failed: {e}")
        return {"sent": False, "error": str(e)[:300]}
