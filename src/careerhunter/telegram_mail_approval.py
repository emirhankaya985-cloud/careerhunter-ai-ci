"""One-click Telegram approval for owner-reviewed HR email drafts."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, insert, select, update
from starlette.concurrency import run_in_threadpool

from .gmail_send import ApprovedMail, GmailSendError, send_approved_once

router = APIRouter()
_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
_CHAT_RE = re.compile(r"^-?[0-9]{4,20}$")
_REQUEST_RE = re.compile(r"^[A-Za-z0-9_]{20,32}$")
_SOURCES = frozenset({"ashby", "lever", "greenhouse"})
_BASE_URL = "https://careerhunter-private-dashboard.onrender.com"
_metadata = MetaData()
approval_requests = Table(
    "careerhunter_telegram_mail_approvals", _metadata,
    Column("request_id", String(32), primary_key=True),
    Column("created_at", String(40), nullable=False),
    Column("expires_at", String(40), nullable=False),
    Column("status", String(24), nullable=False),
    Column("payload", Text, nullable=False),
    Column("recipient_hash", String(64), nullable=False),
)


def _webhook_secret() -> str | None:
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    return secret if _SECRET_RE.fullmatch(secret) else None


def _writer_url() -> str:
    url = (os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "").strip()
           or os.getenv("DATABASE_URL", "").strip())
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("private_approval_store_unavailable")
    return url


def queue_owner_approval(*, contact, job, subject: str, body: str) -> bool:
    """Persist an exact draft; a secret-bearing GitHub worker delivers it."""
    if not _webhook_secret() and os.getenv("GITHUB_ACTIONS") != "true":
        return False
    if len(body) > 2300 or not subject.strip():
        return False
    request_id = secrets.token_urlsafe(18).replace("-", "_")
    payload = {
        "person_id": contact.person_id, "source": job.source, "job_id": job.job_id,
        "subject": subject, "body": body,
        "recipient_name": contact.name,
        "recipient_address": contact.email_public,
        "contact_evidence_url": str(contact.primary_source_url),
        "company": job.company, "job_title": job.title, "job_url": str(job.job_url),
    }
    now = datetime.now(timezone.utc)
    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as connection:
            _metadata.create_all(connection, tables=[approval_requests])
            connection.execute(insert(approval_requests).values(
                request_id=request_id, created_at=now.isoformat(),
                expires_at=(now + timedelta(hours=24)).isoformat(), status="queued",
                payload=json.dumps(payload, ensure_ascii=False),
                recipient_hash=hashlib.sha256(contact.email_public.casefold().encode()).hexdigest(),
            ))
    finally:
        engine.dispose()

    # True means durably queued. The Actions worker handles external delivery.
    return True


def _require_mail_worker(request: Request) -> None:
    from .scheduled_scan import TELEGRAM_MAIL_WORKFLOW, _require_github_oidc
    _require_github_oidc(
        request, workflow=TELEGRAM_MAIL_WORKFLOW,
        events=frozenset({"schedule", "workflow_dispatch", "push"}),
    )


@router.get("/internal/telegram/mail-approval/config")
def telegram_mail_worker_config(request: Request) -> dict[str, str]:
    """Expose only the webhook secret to the exact Actions workflow that needs it."""
    _require_mail_worker(request)
    secret = _webhook_secret()
    if not secret:
        raise HTTPException(503, "Telegram webhook secret is not configured")
    return {"url": _BASE_URL + "/internal/telegram/mail-approval", "secret": secret}


@router.post("/internal/telegram/mail-approval/claim")
async def claim_telegram_mail(request: Request) -> JSONResponse:
    """Atomically reserve the oldest queued draft for private Telegram delivery."""
    _require_mail_worker(request)
    try:
        data = await request.json()
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid JSON") from None
    chat_id = str(data.get("chat_id", "")) if isinstance(data, dict) else ""
    if not _CHAT_RE.fullmatch(chat_id):
        raise HTTPException(422, "Invalid private chat identity")
    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                select(approval_requests).where(
                    approval_requests.c.status == "queued",
                    approval_requests.c.expires_at >= datetime.now(timezone.utc).isoformat(),
                ).order_by(approval_requests.c.created_at).limit(1).with_for_update(skip_locked=True)
            ).mappings().first()
            if row is None:
                return JSONResponse({"status": "empty"})
            payload = json.loads(row["payload"])
            payload["owner_chat_id"] = chat_id
            changed = connection.execute(update(approval_requests).where(
                approval_requests.c.request_id == row["request_id"],
                approval_requests.c.status == "queued",
            ).values(status="delivering", payload=json.dumps(payload, ensure_ascii=False))).rowcount
            if changed != 1:
                return JSONResponse({"status": "empty"})
            return JSONResponse({
                "status": "claimed", "request_id": row["request_id"],
                "expires_at": row["expires_at"], "draft": payload,
            })
    finally:
        engine.dispose()


@router.post("/internal/telegram/mail-approval/delivery")
async def finish_telegram_mail_delivery(request: Request) -> JSONResponse:
    """Record a positive Telegram receipt without reopening a claimed request."""
    _require_mail_worker(request)
    try:
        data = await request.json()
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid JSON") from None
    if not isinstance(data, dict):
        raise HTTPException(422, "Invalid delivery receipt")
    request_id = str(data.get("request_id", ""))
    outcome = str(data.get("outcome", ""))
    message_id = data.get("message_id")
    if (not _REQUEST_RE.fullmatch(request_id)
            or outcome not in {"delivered", "failed", "unknown"}
            or (outcome == "delivered" and (type(message_id) is not int or message_id <= 0))):
        raise HTTPException(422, "Invalid delivery receipt")
    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as connection:
            row = connection.execute(select(approval_requests).where(
                approval_requests.c.request_id == request_id,
                approval_requests.c.status == "delivering",
            )).mappings().first()
            if row is None:
                return JSONResponse({"status": "already_final"})
            payload = json.loads(row["payload"])
            if outcome == "delivered":
                payload["telegram_message_id"] = message_id
                status = "pending"
            else:
                status = "notification_failed" if outcome == "failed" else "delivery_unknown"
            connection.execute(update(approval_requests).where(
                approval_requests.c.request_id == request_id,
                approval_requests.c.status == "delivering",
            ).values(status=status, payload=json.dumps(payload, ensure_ascii=False)))
            return JSONResponse({"status": status})
    finally:
        engine.dispose()


def _load_and_claim(request_id: str, chat_id: str, message_id: int) -> dict | None:
    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as connection:
            row = connection.execute(select(approval_requests).where(
                approval_requests.c.request_id == request_id
            )).mappings().first()
            if (row is None or row["status"] not in {"pending", "delivering"}
                    or row["expires_at"] < datetime.now(timezone.utc).isoformat()):
                return None
            payload = json.loads(row["payload"])
            if (str(payload.get("owner_chat_id", "")) != chat_id
                    or (payload.get("telegram_message_id") is not None
                        and payload.get("telegram_message_id") != message_id)):
                return None
            changed = connection.execute(update(approval_requests).where(
                approval_requests.c.request_id == request_id,
                approval_requests.c.status.in_(("pending", "delivering")),
            ).values(status="processing")).rowcount
            if changed != 1:
                return None
            return {**payload, "recipient_hash": row["recipient_hash"]}
    finally:
        engine.dispose()


def _set_status(request_id: str, status: str) -> None:
    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as connection:
            connection.execute(update(approval_requests).where(
                approval_requests.c.request_id == request_id,
                approval_requests.c.status == "processing",
            ).values(status=status))
    finally:
        engine.dispose()


def _dispatch(request_id: str, chat_id: str, message_id: int) -> str:
    pending = _load_and_claim(request_id, chat_id, message_id)
    if pending is None:
        return "expired_or_already_used"
    try:
        if os.getenv("CAREERHUNTER_GMAIL_SEND_ENABLED") != "true":
            raise GmailSendError("gmail_send_disabled")
        writer = os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "").strip()
        from .database import DatabaseRepository
        from .github_operations import production_database_url
        repo = DatabaseRepository(production_database_url())
        job = repo.get_job(pending["source"], pending["job_id"])
        contact = next((c for c in repo.list_contacts(limit=5000)
                        if c.person_id == pending["person_id"]), None)
        from .gmail_outbound_api import _email_job_fit, _is_ik_contact
        if (pending["source"] not in _SOURCES or not _email_job_fit(job) or contact is None
                or contact.status != "approved_by_user" or contact.do_not_contact
                or contact.company.strip().casefold() != job.company.strip().casefold()
                or contact.research_confidence != "high" or not contact.email_public
                or not contact.primary_source_url
                or urlsplit(str(contact.primary_source_url)).scheme != "https"
                or hashlib.sha256(contact.email_public.casefold().encode()).hexdigest()
                != pending["recipient_hash"] or not _is_ik_contact(contact)):
            raise GmailSendError("approval_target_changed")
        mail = ApprovedMail(
            recipient=contact.email_public, subject=pending["subject"], body=pending["body"],
            contact_evidence_url=str(contact.primary_source_url),
            approval_id=hashlib.sha256(("\0".join((
                pending["source"], pending["job_id"], pending["person_id"],
            ))).encode()).hexdigest()[:40],
            approved_by_owner=True,
            reply_to=os.getenv("CAREERHUNTER_APPLICATION_REPLY_TO", "").strip() or None,
        )
        send_approved_once(mail, database_url=writer)
        _set_status(request_id, "sent")
        return "sent"
    except GmailSendError as exc:
        _set_status(request_id, "failed")
        return "unknown" if str(exc) not in {
            "gmail_send_disabled", "gmail_send_oauth_missing", "daily_limit_reached",
            "duplicate_or_previous_attempt", "approval_target_changed",
        } else "blocked"
    except Exception:
        _set_status(request_id, "failed")
        return "unknown"


def _answer_callback(callback_id: str, message: str, *, alert: bool = False) -> JSONResponse:
    # Telegram supports one Bot API method as the response to a webhook update.
    # This clears the button spinner without giving Render the bot token.
    return JSONResponse({"method": "answerCallbackQuery", "callback_query_id": callback_id,
                         "text": message[:180], "show_alert": alert})


def _cancel_request(request_id: str, chat_id: str, message_id: int) -> bool:
    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as connection:
            row = connection.execute(select(approval_requests).where(
                approval_requests.c.request_id == request_id,
                approval_requests.c.status.in_(("pending", "delivering")),
            )).mappings().first()
            if row is None:
                return False
            payload = json.loads(row["payload"])
            if (str(payload.get("owner_chat_id", "")) != chat_id
                    or (payload.get("telegram_message_id") is not None
                        and payload.get("telegram_message_id") != message_id)):
                return False
            return connection.execute(update(approval_requests).where(
                approval_requests.c.request_id == request_id,
                approval_requests.c.status.in_(("pending", "delivering")),
            ).values(status="cancelled")).rowcount == 1
    finally:
        engine.dispose()


@router.post("/internal/telegram/mail-approval")
async def telegram_mail_approval(request: Request) -> JSONResponse:
    secret = _webhook_secret()
    if not secret:
        raise HTTPException(503, "Telegram approval is not configured")
    supplied = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not hmac.compare_digest(supplied, secret):
        raise HTTPException(403, "Invalid Telegram webhook secret")
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > 12000:
            raise HTTPException(413, "Telegram update too large")
    try:
        update_data = json.loads(raw)
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid Telegram update") from None
    callback = update_data.get("callback_query") if isinstance(update_data, dict) else None
    if not isinstance(callback, dict):
        return JSONResponse({"ok": True})
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    sender = callback.get("from") or {}
    callback_id = str(callback.get("id", ""))
    message_id = message.get("message_id")
    chat_id = str(chat.get("id", ""))
    if (chat.get("type") != "private" or not _CHAT_RE.fullmatch(chat_id)
            or str(sender.get("id")) != chat_id or type(message_id) is not int
            or message_id <= 0):
        return _answer_callback(callback_id, "Bu düğme yalnızca sahibine açıktır.", alert=True)
    callback_data = str(callback.get("data", ""))
    if callback_data.startswith("chcancel:"):
        request_id = callback_data.removeprefix("chcancel:")
        if not _REQUEST_RE.fullmatch(request_id):
            return _answer_callback(callback_id, "İstek geçersiz veya süresi dolmuş.", alert=True)
        cancelled = await run_in_threadpool(_cancel_request, request_id, chat_id, message_id)
        return _answer_callback(callback_id, "E-posta isteği iptal edildi." if cancelled
                                else "İstek kullanılmış, süresi dolmuş veya geçersiz.",
                                alert=not cancelled)
    if not callback_data.startswith("chmail:"):
        return _answer_callback(callback_id, "Bilinmeyen işlem.", alert=True)
    request_id = callback_data.removeprefix("chmail:")
    if not _REQUEST_RE.fullmatch(request_id):
        return _answer_callback(callback_id, "Onay geçersiz veya süresi dolmuş.", alert=True)
    status = await run_in_threadpool(_dispatch, request_id, chat_id, message_id)
    text = {
        "sent": "✅ E-posta Gmail tarafından gönderildi.",
        "blocked": "⛔ E-posta gönderilmedi: onay, ilan veya Gmail koşulları uygun değil.",
        "unknown": "⚠️ Gönderim sonucu doğrulanamadı. Tekrar basma; Gmail ve kayıt defterini kontrol et.",
        "expired_or_already_used": "ℹ️ Bu e-posta süresi dolduğu veya daha önce kullanıldığı için gönderilmedi.",
    }[status]
    return _answer_callback(callback_id, text, alert=status != "sent")
