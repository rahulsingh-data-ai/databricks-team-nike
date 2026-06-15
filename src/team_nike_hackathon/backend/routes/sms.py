"""SMS inbound webhook + simulator.

Anyone with a phone can text "dialysis near Jaipur" to the configured
Twilio number and get a short evidence-attached shortlist back.

Conversation state is kept per phone number via the supervisor's
in-memory session store, so a follow-up ``MORE`` or ``SAVE 1`` is scoped
to that user's last search.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Form
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..agents.sms_formatter import format_sms_reply
from ..agents.supervisor import run_supervisor
from ..db import DatabricksSQLDependency
from ..utils.messaging import send_message

logger = logging.getLogger(__name__)
router = APIRouter(tags=["messaging"])


# ---------------------------------------------------------------------------
# Thread log (in-memory; swap for Lakebase later).
# ---------------------------------------------------------------------------

_threads: dict[str, list[dict]] = {}


def _log(phone: str, direction: str, body: str):
    _threads.setdefault(phone, []).append({
        "direction": direction,
        "body": body,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def _last_result(phone: str) -> dict | None:
    """Find the most recent search result we sent to this phone."""
    for entry in reversed(_threads.get(phone, [])):
        if entry.get("direction") == "system" and "result" in entry:
            return entry["result"]
    return None


def _store_result(phone: str, result: dict):
    _threads.setdefault(phone, []).append({
        "direction": "system",
        "result": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _run_query(body: str, phone: str, db) -> str:
    """Run the supervisor with phone as session_id, then SMS-format."""
    result = await run_supervisor(body, db, session_id=phone)
    facilities = result.get("facilities") or []
    sms_friendly = {
        "query": result.get("parsed_query") or {},
        "facilities": facilities,
        "recommendation_summary": result.get("final_recommendation") or "",
        "result_count": len(facilities),
    }
    _store_result(phone, sms_friendly)
    return format_sms_reply(sms_friendly)


def _handle_more(phone: str) -> str:
    last = _last_result(phone)
    if not last:
        return "Send a query like 'dialysis near Jaipur' to start."
    next_batch = (last.get("facilities") or [])[2:5]
    if not next_batch:
        return "No more results. Send a new query to search again."
    payload = {**last, "facilities": next_batch}
    return format_sms_reply(payload, max_facilities=len(next_batch))


def _handle_save(phone: str, index: int) -> str:
    last = _last_result(phone)
    if not last:
        return "Send a query first, then reply SAVE 1 or SAVE 2."
    facilities = last.get("facilities") or []
    if index < 1 or index > len(facilities):
        return f"Choose a number between 1 and {len(facilities)}."
    f = facilities[index - 1]
    # TODO: persist to Lakebase shortlist once Lakebase is deployed
    return (
        f"Saved {f.get('name', '?')} to your shortlist. "
        f"Open the app for full evidence and to share with colleagues."
    )


def _handle_help() -> str:
    return (
        "Referral Copilot:\n"
        "- Send a query like 'dialysis near Jaipur'\n"
        "- Reply MORE for more results\n"
        "- Reply SAVE 1 to bookmark the top result\n"
        "- Hindi/Tamil/Bengali queries supported"
    )


# ---------------------------------------------------------------------------
# Webhook (Twilio POSTs here)
# ---------------------------------------------------------------------------

@router.post("/sms/inbound")
async def sms_inbound(
    db: DatabricksSQLDependency,
    Body: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
):
    """Twilio inbound SMS webhook.

    Body = user's message, From = their phone. We reply via Twilio's
    REST API and return an empty TwiML acknowledgement.
    """
    phone = (From or "").strip()
    body = (Body or "").strip()
    upper = body.upper()

    _log(phone, "inbound", body)

    try:
        if not body:
            reply = _handle_help()
        elif upper in ("HELP", "?"):
            reply = _handle_help()
        elif upper == "MORE":
            reply = _handle_more(phone)
        elif upper.startswith("SAVE "):
            tail = upper[5:].strip()
            try:
                idx = int(tail)
            except ValueError:
                idx = 0
            reply = _handle_save(phone, idx)
        else:
            reply = await _run_query(body, phone, db)
    except Exception as e:  # noqa: BLE001
        logger.exception("inbound handler failed")
        reply = f"Sorry, something went wrong. Reply HELP for usage. ({str(e)[:80]})"

    _log(phone, "outbound", reply)
    send_message(phone, reply)

    return Response(content="", media_type="text/xml")


# ---------------------------------------------------------------------------
# Simulator (no Twilio required)
# ---------------------------------------------------------------------------

class SimulateRequest(BaseModel):
    phone: str = Field(..., min_length=4)
    body: str = Field(..., min_length=1, max_length=500)


@router.post("/sms/simulate-inbound")
async def sms_simulate(body: SimulateRequest, db: DatabricksSQLDependency):
    """Pretend Twilio sent us a message — for demos and tests.

    Returns ``{ reply, thread }`` instead of TwiML; no Twilio creds required.
    """
    phone = body.phone.strip()
    text = body.body.strip()
    upper = text.upper()

    _log(phone, "inbound", text)

    if not text:
        reply = _handle_help()
    elif upper in ("HELP", "?"):
        reply = _handle_help()
    elif upper == "MORE":
        reply = _handle_more(phone)
    elif upper.startswith("SAVE "):
        tail = upper[5:].strip()
        try:
            idx = int(tail)
        except ValueError:
            idx = 0
        reply = _handle_save(phone, idx)
    else:
        reply = await _run_query(text, phone, db)

    _log(phone, "outbound", reply)
    return {"reply": reply, "thread": _threads.get(phone, [])}


# ---------------------------------------------------------------------------
# Thread inspection endpoints (admin / demo UI)
# ---------------------------------------------------------------------------

@router.get("/sms/threads")
async def list_threads():
    return {"threads": _threads, "count": len(_threads)}


@router.get("/sms/thread/{phone}")
async def get_thread(phone: str):
    return {"phone": phone, "messages": _threads.get(phone, [])}
