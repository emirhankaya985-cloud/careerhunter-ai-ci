"""One-click Telegram approval for owner-reviewed HR email drafts."""
from __future__ import annotations

import hashlib
import html
import hmac
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, insert, select, update
from starlette.concurrency import run_in_threadpool

from .gmail_send import ApprovedMail, GmailSendError, send_approved_once

router = APIRouter()
logger = logging.getLogger(__name__)
_TOKEN_RE = re.compile(r"^[0-9]{6,15}:[A-Za-z0-9_-]{25,}$")
_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
_CHAT_RE = re.compile(r"^-?[0-9]{4,20}$")
_SOURCES = frozenset({"ashby", "lever", "greenhouse"})
_BASE_URL = "https://careerhunter-private-dashboard.onrender.com"
_WEBHOOK_READY = False
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


def _telegram_config() -> tuple[str, str, str] | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not (_TOKEN_RE.fullmatch(token) and _CHAT_RE.fullmatch(chat)
            and _SECRET_RE.fullmatch(secret)):
        return None
    return token, chat, secret


def _writer_url() -> str:
    url = os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "").strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("private_approval_store_unavailable")
    return url


def _api(token: str, method: str, payload: dict) -> dict | None:
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{token}/{method}", json=payload,
            timeout=15, follow_redirects=False, trust_env=False,
        )
        if response.status_code != 200:
            logger.warning("Telegram mail approval API rejected: %s", method)
            return None
        result = response.json()
        return result if isinstance(result, dict) and result.get("ok") is True else None
    except (httpx.HTTPError, ValueError, TypeError, OSError):
        logger.warning("Telegram mail approval transport failed: %s", method)
        return None


def register_telegram_webhook() -> bool:
    """Register only when no different webhook owns this bot."""
    global _WEBHOOK_READY
    config = _telegram_config()
    if not config:
        return False
    token, _, secret = config
    target = _BASE_URL + "/internal/telegram/mail-approval"
    info = _api(token, "getWebhookInfo", {})
    if info is None:
        return False
    current = str((info.get("result") or {}).get("url") or "")
    if current and current != target:
        logger.warning("Telegram webhook already belongs to another URL; left unchanged")
        return False
    result = _api(token, "setWebhook", {
        "url": target, "secret_token": secret,
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": False,
    })
    if result is None:
        return False
    _WEBHOOK_READY = True
    logger.info("Telegram owner approval webhook is registered")
    return True


def queue_owner_approval(*, contact, job, subject: str, body: str) -> bool:
    """Persist the exact draft before showing it with a one-click approval button."""
    config = _telegram_config()
    if (not config or not _WEBHOOK_READY
            or not _TOKEN_RE.fullmatch(os.getenv("TELEGRAM_BOT_TOKEN", "").strip())):
        return False
    token, chat, _ = config
    if len(body) > 2300 or not subject.strip():
        return False
    request_id = secrets.token_urlsafe(18).replace("-", "_")
    payload = {
        "person_id": contact.person_id, "source": job.source, "job_id": job.job_id,
        "subject": subject, "body": body,
    }
    now = datetime.now(timezone.utc)
    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        _metadata.create_all(engine, tables=[approval_requests])
        with engine.begin() as connection:
            connection.execute(insert(approval_requests).values(
                request_id=request_id, created_at=now.isoformat(),
                expires_at=(now + timedelta(hours=24)).isoformat(), status="pending",
                payload=json.dumps(payload, ensure_ascii=False),
                recipient_hash=hashlib.sha256(contact.email_public.casefold().encode()).hexdigest(),
            ))
    finally:
        engine.dispose()

    def safe(value: object) -> str:
        return html.escape(str(value or ""), quote=True)
    message = (
        "✉️ <b>CareerHunter | E-posta onayı</b>\n\n"
        f"<b>Alıcı:</b> {safe(contact.name)} &lt;{safe(contact.email_public)}&gt;\n"
        f"<b>Şirket:</b> {safe(job.company)}\n"
        f"<b>İlan:</b> <a href=\"{safe(job.job_url)}\">{safe(job.title)}</a>\n"
        f"<b>Konu:</b> {safe(subject)}\n\n"
        f"<b>Gönderilecek e-posta:</b>\n<pre>{safe(body)}</pre>\n"
        "Göndermek için aşağıdaki düğmeye bas. Bu onay 24 saat geçerlidir."
    )
    callback_id = "chmail:" + request_id
    result = _api(token, "sendMessage", {
        "chat_id": chat, "text": message, "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True}, "protect_content": True,
        "reply_markup": {"inline_keyboard": [[
            {"text": "🔎 Kaynak kanıtı", "url": str(contact.primary_source_url)},
        ], [
            {"text": "✅ Bu e-postayı gönder", "callback_data": callback_id},
            {"text": "İptal", "callback_data": "chcancel:" + request_id},
        ]]},
    })
    if result is None:
        with engine.begin() as connection:
            connection.execute(update(approval_requests).where(
                approval_requests.c.request_id == request_id,
                approval_requests.c.status == "pending",
            ).values(status="notification_failed"))
        return False
    return True


def _load_and_claim(request_id: str) -> dict | None:
    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as connection:
            row = connection.execute(select(approval_requests).where(
                approval_requests.c.request_id == request_id
            )).mappings().first()
            if (row is None or row["status"] != "pending"
                    or row["expires_at"] < datetime.now(timezone.utc).isoformat()):
                return None
            changed = connection.execute(update(approval_requests).where(
                approval_requests.c.request_id == request_id,
                approval_requests.c.status == "pending",
            ).values(status="processing")).rowcount
            if changed != 1:
                return None
            return {**json.loads(row["payload"]), "recipient_hash": row["recipient_hash"]}
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


def _dispatch(request_id: str) -> str:
    pending = _load_and_claim(request_id)
    if pending is None:
        return "expired_or_already_used"
    try:
        if os.getenv("CAREERHUNTER_GMAIL_SEND_ENABLED") != "true":
            raise GmailSendError("gmail_send_disabled")
        writer = os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "").strip()
        from .private_site import _repo
        repo = _repo()
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


def _reply(token: str, callback_id: str, message: str) -> None:
    _api(token, "answerCallbackQuery", {
        "callback_query_id": callback_id, "text": message, "show_alert": False,
    })


def _edit(token: str, chat_id: int, message_id: int, text: str) -> None:
    _api(token, "editMessageText", {
        "chat_id": chat_id, "message_id": message_id,
        "text": text, "reply_markup": {"inline_keyboard": []},
    })


@router.post("/internal/telegram/mail-approval")
async def telegram_mail_approval(request: Request) -> JSONResponse:
    config = _telegram_config()
    if not config:
        raise HTTPException(503, "Telegram approval is not configured")
    token, owner_chat, secret = config
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
    if (chat.get("type") != "private" or str(chat.get("id")) != owner_chat
            or str(sender.get("id")) != owner_chat):
        _reply(token, str(callback.get("id", "")), "Bu düğme yalnızca sahibine açıktır.")
        return JSONResponse({"ok": True})
    callback_data = str(callback.get("data", ""))
    if callback_data.startswith("chcancel:"):
        request_id = callback_data.removeprefix("chcancel:")
        status = "cancelled"
        engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
        try:
            with engine.begin() as connection:
                connection.execute(update(approval_requests).where(
                    approval_requests.c.request_id == request_id,
                    approval_requests.c.status == "pending",
                ).values(status=status))
        finally:
            engine.dispose()
        _reply(token, str(callback.get("id", "")), "E-posta iptal edildi.")
        _edit(token, int(chat["id"]), int(message["message_id"]), "E-posta isteği iptal edildi.")
        return JSONResponse({"ok": True})
    if not callback_data.startswith("chmail:"):
        _reply(token, str(callback.get("id", "")), "Bilinmeyen işlem.")
        return JSONResponse({"ok": True})
    request_id = callback_data.removeprefix("chmail:")
    if not re.fullmatch(r"[A-Za-z0-9_]{20,32}", request_id):
        _reply(token, str(callback.get("id", "")), "Onay geçersiz veya süresi dolmuş.")
        return JSONResponse({"ok": True})
    _reply(token, str(callback.get("id", "")), "Onay alındı, e-posta gönderiliyor…")
    status = await run_in_threadpool(_dispatch, request_id)
    text = {
        "sent": "✅ E-posta Gmail tarafından gönderildi.",
        "blocked": "⛔ E-posta gönderilmedi: onay, ilan veya Gmail koşulları uygun değil.",
        "unknown": "⚠️ Gönderim sonucu doğrulanamadı. Tekrar basma; Gmail ve kayıt defterini kontrol et.",
        "expired_or_already_used": "ℹ️ Bu e-posta süresi dolduğu veya daha önce kullanıldığı için gönderilmedi.",
    }[status]
    _edit(token, int(chat["id"]), int(message["message_id"]), text)
    return JSONResponse({"ok": True, "status": status})
