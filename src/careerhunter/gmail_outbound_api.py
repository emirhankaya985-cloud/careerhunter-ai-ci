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
import re
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


class ContactApprovalRequest(BaseModel):
    person_id: str = Field(min_length=1, max_length=160)
    confirm_public_professional_contact: bool = False


class MailDraftRequest(BaseModel):
    source: str
    job_id: str = Field(min_length=1, max_length=160)
    person_id: str = Field(min_length=1, max_length=160)


def _signer() -> URLSafeTimedSerializer:
    from .private_site import _settings
    return URLSafeTimedSerializer(_settings()[1], salt="careerhunter-owner-mail-csrf-v1")


def _owner(request: Request) -> str:
    from .application_actions import _require_owner, _cookie_binding
    _require_owner(request)
    return _cookie_binding(request)


def _csrf_session(request: Request) -> str:
    session = _owner(request)
    from .application_actions import _check_origin
    _check_origin(request)
    try:
        signed = _signer().loads(request.headers.get("x-csrf-token", ""), max_age=1200)
    except (BadSignature, ValueError, TypeError):
        raise HTTPException(403, "Invalid mail approval token") from None
    if not isinstance(signed, dict) or not hmac.compare_digest(
        str(signed.get("session", "")), session
    ):
        raise HTTPException(403, "Invalid owner session")
    return session


def _mail_contact(repo, person_id: str):
    return next((c for c in repo.list_contacts(limit=5000)
                 if c.person_id == person_id), None)


def _is_ik_contact(contact) -> bool:
    role = str(contact.role or "").casefold()
    return (contact.relationship_type in {"recruiter", "hiring_manager"}
            or bool(re.search(r"\b(?:recruiter|recruiting|talent|human resources|\bhr\b|people partner|\bik\b|işe alım|insan kaynakları)\b", role)))


def _email_job_fit(job) -> bool:
    if (job is None or job.status == "closed" or job.remote_type != "remote"
            or job.verification_status not in {"ATS_LISTED", "EMPLOYER_CONFIRMED"}):
        return False
    from .job_quality import classify_profile_fit
    status, _ = classify_profile_fit({
        "title": job.title, "location": job.location, "remote_type": job.remote_type,
        "description": job.description[:12000], "skills": job.skills_required,
        "score": job.match_score or 0, "level": job.experience_level,
    }, strong_minimum=75, review_minimum=60)
    return status in {"strong_match", "review"}


@router.get("/internal/owner/mail/status")
def mail_status(request: Request) -> dict[str, object]:
    _owner(request)
    from .private_site import _repo

    approved_contacts = sum(
        contact.status == "approved_by_user"
        and contact.research_confidence == "high"
        and bool(contact.email_public)
        and bool(contact.primary_source_url)
        and urlsplit(str(contact.primary_source_url)).scheme == "https"
        and _is_ik_contact(contact)
        and not contact.do_not_contact
        for contact in _repo().list_contacts(limit=5000)
    )
    return {
        "status": "ready" if (
            os.getenv("CAREERHUNTER_GMAIL_SEND_ENABLED") == "true"
            and os.getenv("GMAIL_SEND_REFRESH_TOKEN", "").strip()
            and os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "").strip()
            and approved_contacts > 0
        ) else "blocked",
        "read_only_mail_unchanged": True,
        "send_enabled": os.getenv("CAREERHUNTER_GMAIL_SEND_ENABLED") == "true",
        "send_oauth_present": bool(os.getenv("GMAIL_SEND_REFRESH_TOKEN", "").strip()),
        "receipt_writer_present": bool(os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "").strip()),
        "approved_contact_count": approved_contacts,
        "automatic_dispatch_enabled": False,
    }


@router.get("/internal/owner/mail/csrf")
def mail_csrf(request: Request) -> dict[str, str]:
    session = _owner(request)
    return {"csrf_token": _signer().dumps({"session": session})}


@router.post("/internal/owner/mail/contact/approve")
async def approve_public_contact(request: Request) -> JSONResponse:
    _csrf_session(request)
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "JSON required")
    try:
        payload = bytearray()
        async for part in request.stream():
            payload.extend(part)
            if len(payload) > 2048:
                raise HTTPException(413, "Request too large")
        data = ContactApprovalRequest.model_validate(json.loads(payload))
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid contact approval") from None
    if not data.confirm_public_professional_contact:
        raise HTTPException(422, "Explicit public-contact review is required")
    from .private_site import _repo
    contact = _mail_contact(_repo(), data.person_id)
    if (contact is None or contact.do_not_contact or not contact.email_public
            or contact.research_confidence != "high" or not contact.primary_source_url
            or urlsplit(str(contact.primary_source_url)).scheme != "https"
            or not _is_ik_contact(contact)):
        raise HTTPException(422, "Contact must be a publicly sourced, verified HR/recruiting contact")

    from sqlalchemy import create_engine
    from .application_actions import _writer_url
    from .database import DatabaseRepository
    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        writer_repo = object.__new__(DatabaseRepository)
        writer_repo.engine = engine
        writer_repo.update_contact_status(data.person_id, "approved_by_user")
    finally:
        engine.dispose()
    return JSONResponse({"status": "approved", "person_id": data.person_id})


@router.post("/internal/owner/mail/draft")
async def prepare_job_email(request: Request) -> JSONResponse:
    _csrf_session(request)
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "JSON required")
    try:
        payload = bytearray()
        async for part in request.stream():
            payload.extend(part)
            if len(payload) > 2048:
                raise HTTPException(413, "Request too large")
        data = MailDraftRequest.model_validate(json.loads(payload))
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid draft request") from None
    if data.source not in SOURCES or len(data.job_id.split()) != 1:
        raise HTTPException(422, "Invalid job identity")
    from .private_site import _repo
    repo = _repo()
    job = repo.get_job(data.source, data.job_id)
    contact = _mail_contact(repo, data.person_id)
    if not _email_job_fit(job):
        raise HTTPException(422, "Job must be active, verified, remote and profile-relevant")
    if (contact is None or contact.company.strip().casefold() != job.company.strip().casefold()
            or contact.status != "approved_by_user" or contact.do_not_contact
            or contact.research_confidence != "high" or not contact.email_public
            or not _is_ik_contact(contact)):
        raise HTTPException(422, "No owner-approved verified company HR contact")

    from .personal_profile import load_match_profile
    profile = load_match_profile()
    declared = [str(s).strip() for s in profile.get("skills", []) if str(s).strip()]
    vacancy = " ".join((job.title, job.description, *job.skills_required)).casefold()
    matched = [s for s in declared if re.search(r"(?<!\w)" + re.escape(s.casefold()) + r"(?!\w)", vacancy)]
    target = str(profile.get("target_roles", [""])[0]).strip() or job.title
    candidate_name = str(profile.get("name", "")).strip()
    skill_line = ("Relevant skills I can bring include " + ", ".join(matched[:5]) + "."
                  if matched else "I would be glad to share how my background aligns with the role.")
    greeting = contact.name.split()[0] if contact.name.strip() else "Hello"
    body = (f"Hi {greeting},\n\n"
            f"I’m reaching out about the {job.title} role at {job.company}. "
            f"I’m exploring opportunities as a {target}. {skill_line}\n\n"
            f"If you’re the right person to contact, would you be open to sharing the next step for this role? "
            f"I’m happy to provide my CV and any further details.\n\nBest regards")
    if candidate_name:
        body += f",\n{candidate_name}"
    from .telegram_mail_approval import queue_owner_approval
    try:
        telegram_notified = await run_in_threadpool(
            queue_owner_approval, contact=contact, job=job, subject=f"Interest in {job.title} at {job.company}", body=body
        )
    except Exception:
        telegram_notified = False
    return JSONResponse({
        "status": "draft_ready", "recipient_name": contact.name,
        "recipient_address": contact.email_public, "contact_evidence_url": str(contact.primary_source_url),
        "job_title": job.title, "company": job.company, "job_url": str(job.job_url),
        "subject": f"Interest in {job.title} at {job.company}", "body": body,
        "matched_profile_skills": matched[:5],
        "telegram_approval_notified": telegram_notified,
    })


@router.post("/internal/owner/mail/send")
async def send_approved_mail(request: Request) -> JSONResponse:
    _csrf_session(request)
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "JSON required")
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
    if not _email_job_fit(job):
        raise HTTPException(422, "Job must be active, verified, remote and profile-relevant")
    contact = next((c for c in repo.list_contacts(limit=5000)
                    if c.person_id == data.person_id), None)
    if (contact is None or contact.company.strip().casefold() != job.company.strip().casefold()
            or contact.do_not_contact or contact.status != "approved_by_user"
            or contact.research_confidence != "high" or not contact.email_public
            or not contact.primary_source_url
            or urlsplit(str(contact.primary_source_url)).scheme != "https"
            or not _is_ik_contact(contact)):
        raise HTTPException(422, "No verified owner-approved company contact")
    approval_id = hashlib.sha256(
        ("\0".join((data.source, data.job_id, data.person_id))).encode("utf-8")
    ).hexdigest()[:40]
    mail = ApprovedMail(
        recipient=contact.email_public, subject=data.subject, body=data.body,
        contact_evidence_url=str(contact.primary_source_url),
        approval_id=approval_id, approved_by_owner=True,
        reply_to=os.getenv("CAREERHUNTER_APPLICATION_REPLY_TO", "").strip() or None,
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
