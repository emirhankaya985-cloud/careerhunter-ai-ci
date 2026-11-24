"""Deliver queued HR email approvals using GitHub-only Telegram credentials."""
from __future__ import annotations

import html
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .github_operations import production_database_url
from .telegram_mail_approval import (
    _BASE_URL, _REQUEST_RE, _cancel_request, _dispatch, _metadata, _writer_url,
    approval_requests,
)
from sqlalchemy import create_engine, select, update

_TOKEN = re.compile(r"^[0-9]{6,15}:[A-Za-z0-9_-]{25,}$")
_CHAT = re.compile(r"^[1-9][0-9]{4,20}$")
_MAX_DRAFTS = 10


class WorkerError(RuntimeError):
    pass


def _json_request(url: str, *, method: str = "GET", data: dict | None = None,
                  bearer: str | None = None, timeout: int = 30) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "CareerHunter-Telegram-Mail/1.0"}
    body = None
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise WorkerError(f"Protected endpoint returned HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise WorkerError("Protected endpoint or Telegram transport failed") from None
    if not isinstance(result, dict):
        raise WorkerError("Unexpected endpoint response")
    return result


def _telegram(token: str, method: str, data: dict) -> dict:
    result = _json_request(
        "https://api.telegram.org/bot" + token + "/" + method,
        method="POST", data=data, timeout=25,
    )
    if result.get("ok") is not True:
        raise WorkerError("Telegram rejected the approval notification")
    return result


def _escape(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _format_message(request_id: str, draft: dict) -> dict:
    body = draft.get("body")
    subject = draft.get("subject")
    if (not isinstance(body, str) or len(body) > 2300
            or not isinstance(subject, str) or not subject.strip()):
        raise WorkerError("Draft content is invalid")
    evidence = str(draft.get("contact_evidence_url") or "")
    if not evidence.startswith("https://"):
        raise WorkerError("Contact evidence is not HTTPS")
    message = (
        "✉️ <b>CareerHunter | E-posta onayı</b>\n\n"
        f"<b>Alıcı:</b> {_escape(draft.get('recipient_name'))} "
        f"&lt;{_escape(draft.get('recipient_address'))}&gt;\n"
        f"<b>Şirket:</b> {_escape(draft.get('company'))}\n"
        f"<b>İlan:</b> <a href=\"{_escape(draft.get('job_url'))}\">"
        f"{_escape(draft.get('job_title'))}</a>\n"
        f"<b>Konu:</b> {_escape(subject)}\n\n"
        f"<b>Gönderilecek e-posta:</b>\n<pre>{_escape(body)}</pre>\n"
        "Göndermek için düğmeye bas. Bu onay 24 saat geçerlidir."
    )
    return {
        "text": message,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "protect_content": True,
        "reply_markup": {"inline_keyboard": [
            [{"text": "🔎 Kaynak kanıtı", "url": evidence}],
            [
                {"text": "✅ Bu e-postayı gönder", "callback_data": "chmail:" + request_id},
                {"text": "İptal", "callback_data": "chcancel:" + request_id},
            ],
        ]},
    }


def _prepare_polling(token: str) -> None:
    """Remove only the legacy CareerHunter webhook, then poll callbacks in Actions."""
    info = _telegram(token, "getWebhookInfo", {})
    current = str((info.get("result") or {}).get("url") or "")
    legacy_url = _BASE_URL + "/internal/telegram/mail-approval"
    if current == legacy_url:
        _telegram(token, "deleteWebhook", {"drop_pending_updates": False})
    elif current:
        raise WorkerError("Another Telegram webhook owns this bot; left unchanged")


def _configure_webhook(token: str, *, url: str, secret: str) -> None:
    """Compatibility guard for callers validating the old Render webhook path."""
    if url != _BASE_URL + "/internal/telegram/mail-approval" or len(secret) < 32:
        raise WorkerError("Webhook configuration is invalid")
    _prepare_polling(token)


def _claim_queued(chat_id: str) -> dict | None:
    from datetime import datetime, timezone
    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as connection:
            _metadata.create_all(connection, tables=[approval_requests])
            row = connection.execute(select(approval_requests).where(
                approval_requests.c.status == "queued",
                approval_requests.c.expires_at >= datetime.now(timezone.utc).isoformat(),
            ).order_by(approval_requests.c.created_at).limit(1)
                .with_for_update(skip_locked=True)).mappings().first()
            if row is None:
                return None
            payload = json.loads(row["payload"])
            payload["owner_chat_id"] = chat_id
            changed = connection.execute(update(approval_requests).where(
                approval_requests.c.request_id == row["request_id"],
                approval_requests.c.status == "queued",
            ).values(status="delivering", payload=json.dumps(payload, ensure_ascii=False))).rowcount
            if changed != 1:
                return None
            return {"request_id": row["request_id"], "draft": payload}
    finally:
        engine.dispose()


def _finish_delivery(request_id: str, outcome: str, message_id: int | None = None) -> None:
    from datetime import datetime, timezone
    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as connection:
            row = connection.execute(select(approval_requests).where(
                approval_requests.c.request_id == request_id,
                approval_requests.c.status == "delivering",
            )).mappings().first()
            if row is None:
                return
            payload = json.loads(row["payload"])
            if outcome == "delivered" and type(message_id) is int and message_id > 0:
                payload["telegram_message_id"] = message_id
                status = "pending"
            elif outcome == "failed":
                status = "notification_failed"
            else:
                status = "delivery_unknown"
            connection.execute(update(approval_requests).where(
                approval_requests.c.request_id == request_id,
                approval_requests.c.status == "delivering",
            ).values(status=status, payload=json.dumps(payload, ensure_ascii=False),
                     created_at=row["created_at"]))
    finally:
        engine.dispose()


def _answer_callback(token: str, callback_id: str, text: str, *, alert: bool = False) -> None:
    if not callback_id:
        return
    _telegram(token, "answerCallbackQuery", {
        "callback_query_id": callback_id, "text": text[:180], "show_alert": alert,
    })


def _process_callback(token: str, callback: dict, authorized_chat: str) -> None:
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    sender = callback.get("from") or {}
    callback_id = str(callback.get("id") or "")
    chat_id = str(chat.get("id") or "")
    message_id = message.get("message_id")
    if (chat.get("type") != "private" or chat_id != authorized_chat
            or str(sender.get("id")) != authorized_chat
            or type(message_id) is not int or message_id <= 0):
        _answer_callback(token, callback_id, "Bu düğme yalnızca hesap sahibine açıktır.", alert=True)
        return
    value = str(callback.get("data") or "")
    if value.startswith("chcancel:"):
        request_id = value.removeprefix("chcancel:")
        valid = bool(_REQUEST_RE.fullmatch(request_id)) and _cancel_request(
            request_id, chat_id, message_id)
        _answer_callback(token, callback_id,
                         "E-posta isteği iptal edildi." if valid else
                         "İstek kullanılmış, süresi dolmuş veya geçersiz.", alert=not valid)
        return
    if not value.startswith("chmail:"):
        _answer_callback(token, callback_id, "Bilinmeyen işlem.", alert=True)
        return
    request_id = value.removeprefix("chmail:")
    if not _REQUEST_RE.fullmatch(request_id):
        _answer_callback(token, callback_id, "Onay geçersiz veya süresi dolmuş.", alert=True)
        return
    status = _dispatch(request_id, chat_id, message_id)
    texts = {
        "sent": "✅ E-posta Gmail tarafından gönderildi.",
        "blocked": "⛔ E-posta gönderilmedi: onay veya güvenlik koşulu uygun değil.",
        "unknown": "⚠️ Sonuç doğrulanamadı. Tekrar basma; Gmail ve kayıtları kontrol et.",
        "expired_or_already_used": "ℹ️ Bu istek süresi dolduğu veya kullanıldığı için gönderilmedi.",
    }
    _answer_callback(token, callback_id, texts[status], alert=status != "sent")


def run() -> int:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not _TOKEN.fullmatch(bot_token) or not _CHAT.fullmatch(chat_id):
        raise WorkerError("Telegram bot or private chat secret is invalid")

    production_database_url()
    _prepare_polling(bot_token)

    for _ in range(_MAX_DRAFTS):
        claim = _claim_queued(chat_id)
        if claim is None:
            break
        request_id = str(claim.get("request_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_]{20,32}", request_id):
            raise WorkerError("Approval request identity is invalid")
        draft = claim.get("draft")
        if not isinstance(draft, dict):
            raise WorkerError("Approval draft is missing")

        message = _format_message(request_id, draft)
        message.update({"chat_id": chat_id})
        try:
            response = _telegram(bot_token, "sendMessage", message)
        except WorkerError as exc:
            # An uncertain transport outcome is deliberately never retried. A human
            # can inspect the bot and the durable request before requeueing it.
            outcome = "unknown" if "transport" in str(exc) else "failed"
            _finish_delivery(request_id, outcome)
            raise
        message_id = (response.get("result") or {}).get("message_id")
        if type(message_id) is not int or message_id <= 0:
            _finish_delivery(request_id, "unknown")
            raise WorkerError("Telegram message receipt was not confirmed")
        _finish_delivery(request_id, "delivered", message_id)
        print("Telegram approval draft delivered; message body and recipient are omitted.")
    updates = _telegram(bot_token, "getUpdates", {
        "limit": 100, "timeout": 0, "allowed_updates": ["callback_query"],
    })
    entries = updates.get("result", [])
    if not isinstance(entries, list):
        raise WorkerError("Telegram callback response is invalid")
    consumed = []
    for entry in entries[:20]:
        if not isinstance(entry, dict) or type(entry.get("update_id")) is not int:
            continue
        callback = entry.get("callback_query")
        if isinstance(callback, dict):
            try:
                _process_callback(bot_token, callback, chat_id)
            except Exception:
                # Consume an uncertain click after attempting its one-shot DB claim;
                # never re-send an email because a runner was retried.
                print("Telegram approval callback result unavailable; no retry will be attempted.")
        consumed.append(entry["update_id"])
    if consumed:
        _telegram(bot_token, "getUpdates", {
            "offset": max(consumed) + 1, "limit": 1, "timeout": 0,
            "allowed_updates": ["callback_query"],
        })
        print("Telegram approval callbacks processed by GitHub Actions.")
    return 0


def main() -> int:
    try:
        return run()
    except WorkerError as exc:
        print("Telegram mail approval worker blocked:", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
