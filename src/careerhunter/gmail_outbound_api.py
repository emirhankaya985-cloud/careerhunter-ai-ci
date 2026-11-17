"""Owner-only application email intake. No blind or unattended outreach.

The recipient is looked up from a previously reviewed, high-confidence private
CRM contact; client-provided recipient addresses and evidence URLs are ignored.
Production stays disabled without a separate gmail.send refresh token and
bounded PostgreSQL receipt writer.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .gmail_send import ApprovedMail, GmailSendError, send_approved_once

router = APIRouter()
SOURCES = frozenset({"ashby", "lever", "greenhouse"})


class OwnerMailRequest(BaseModel):
    source: str
    job_id: str = Field(min_length=1, max_length=160)
    person_id: str = Field(min_length=1, max_length=160)
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=12000)
    confirm_send: bool = False


def _signer() -> URLSafeTimedSerializer:
    from .private_site import _settings
    return URLSafeTimedSerializer(_settings()[1], salt="careerhunter-owner-mail-csrf-v1")


def _owner(request: Request) -> str:
    from .application_actions import _require_owner, _cookie_binding
    _require_owner(request)
    return _cookie_binding(request)


@router.get("/internal/owner/mail/status")
def mail_status(request: Request) -> dict[str, object]:
    _owner(request)
    return {
        "status": "ready" if (
            os.getenv("CAREERHUNTER_GMAIL_SEND_ENABLED") == "true"
            and os.getenv("GMAIL_SEND_REFRESH_TOKEN", "").strip()
            and os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "").strip()
        ) else "blocked",
        "read_only_mail_unchanged": True,
        "send_enabled": os.getenv("CAREERHUNTER_GMAIL_SEND_ENABLED") == "true",
        "send_oauth_present": bool(os.getenv("GMAIL_SEND_REFRESH_TOKEN", "").strip()),
        "receipt_writer_present": bool(os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "").strip()),
        "automatic_dispatch_enabled": False,
    }


@router.get("/internal/owner/mail/csrf")
def mail_csrf(request: Request) -> dict[str, str]:
    session = _owner(request)
    return {"csrf_token": _signer().dumps({"session": session})}


@router.post("/internal/owner/mail/send")
async def send_approved_mail(request: Request) -> JSONResponse:
    session = _owner(request)
    from .application_actions import _check_origin
    _check_origin(request)
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "JSON required")
    token = request.headers.get("x-csrf-token", "")
    try:
        signed = _signer().loads(token, max_age=1200)
    except (BadSignature, ValueError, TypeError):
        raise HTTPException(403, "Invalid mail approval token") from None
    if (not isinstance(signed, dict)
            or not hmac.compare_digest(str(signed.get("session", "")), session)):
        raise HTTPException(403, "Invalid owner session")
    payload = bytearray()
    async for part in request.stream():
        payload.extend(part)
        if len(payload) > 15000:
            raise HTTPException(413, "Request too large")
    try:
        data = OwnerMailRequest.model_validate(json.loads(payload))
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid mail request") from None
    if not data.confirm_send:
        raise HTTPException(422, "Explicit message approval is required")
    if (data.source not in SOURCES or len(data.job_id.split()) != 1
            or len(data.person_id.split()) != 1):
        raise HTTPException(422, "Invalid job/contact")
    # Stop before looking up contacts unless a valid send grant and writer are configured.
    if os.getenv("CAREERHUNTER_GMAIL_SEND_ENABLED") != "true":
        raise HTTPException(503, "Outbound Gmail disabled")
    if not os.getenv("GMAIL_SEND_REFRESH_TOKEN", "").strip():
        raise HTTPException(503, "Send-specific Google authorization missing")
    writer = os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "").strip()
    if not writer:
        raise HTTPException(503, "Private outbound receipt writer not configured")

    from .private_site import _repo
    repo = _repo()
    job = repo.get_job(data.source, data.job_id)
    if job is None or job.status == "closed":
        raise HTTPException(404, "Active job not found")
    contact = next((c for c in repo.list_contacts(limit=5000)
                    if c.person_id == data.person_id), None)
    if (contact is None or contact.company.strip().casefold() != job.company.strip().casefold()
            or contact.do_not_contact or contact.status != "approved_by_user"
            or contact.research_confidence != "high" or not contact.email_public
            or not contact.primary_source_url
            or urlsplit(str(contact.primary_source_url)).scheme != "https"):
        raise HTTPException(422, "No verified owner-approved company contact")
    approval_id = hashlib.sha256(
        ("\0".join((data.source, data.job_id, data.person_id))).encode("utf-8")
    ).hexdigest()[:40]
    mail = ApprovedMail(
        recipient=contact.email_public, subject=data.subject, body=data.body,
        contact_evidence_url=str(contact.primary_source_url),
        approval_id=approval_id, approved_by_owner=True,
    )
    try:
        result = await run_in_threadpool(send_approved_once, mail, database_url=writer)
    except GmailSendError as exc:
        reason = str(exc)
        if reason in {"duplicate_or_previous_attempt", "daily_limit_reached"}:
            raise HTTPException(409, "Send blocked: " + reason) from None
        # All unconfirmed results require a manual provider outbox check.
        raise HTTPException(503, "Send not verified; review Gmail and receipt ledger") from None
    return JSONResponse({
        "status": "sent", "gmail_message_id": result,
        "provider_receipt_confirmed": True,
        "recipient_address_disclosed": False, "application_status_changed": False,
    })
