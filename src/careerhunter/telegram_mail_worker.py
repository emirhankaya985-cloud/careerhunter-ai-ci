"""Deliver queued HR email approvals using GitHub-only Telegram credentials."""
from __future__ import annotations

import html
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .render_scan_client import BASE, token as oidc_token, wait_ready

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


def _render(path: str, *, method: str = "GET", data: dict | None = None) -> dict:
    if not path.startswith("/"):
        raise WorkerError("Invalid protected endpoint")
    return _json_request(BASE + path, method=method, data=data, bearer=oidc_token())


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


def _configure_webhook(token: str, *, url: str, secret: str) -> None:
    if not url.startswith("https://") or len(secret) < 32:
        raise WorkerError("Webhook configuration is invalid")
    info = _telegram(token, "getWebhookInfo", {})
    current = str((info.get("result") or {}).get("url") or "")
    if current and current != url:
        raise WorkerError("Another Telegram webhook owns this bot; left unchanged")
    _telegram(token, "setWebhook", {
        "url": url,
        "secret_token": secret,
        "allowed_updates": ["callback_query"],
        "drop_pending_updates": False,
    })


def run() -> int:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not _TOKEN.fullmatch(bot_token) or not _CHAT.fullmatch(chat_id):
        raise WorkerError("Telegram bot or private chat secret is invalid")

    wait_ready()
    # The exact OIDC-bound workflow receives the webhook secret, never the bot token.
    config = _render("/internal/telegram/mail-approval/config")
    webhook_url = str(config.get("url") or "")
    webhook_secret = str(config.get("secret") or "")
    _configure_webhook(bot_token, url=webhook_url, secret=webhook_secret)

    for _ in range(_MAX_DRAFTS):
        claim = _render(
            "/internal/telegram/mail-approval/claim",
            method="POST", data={"chat_id": chat_id},
        )
        if claim.get("status") == "empty":
            break
        if claim.get("status") != "claimed":
            raise WorkerError("Approval queue returned an unexpected state")
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
            _render("/internal/telegram/mail-approval/delivery", method="POST", data={
                "request_id": request_id, "outcome": outcome,
            })
            raise
        message_id = (response.get("result") or {}).get("message_id")
        if type(message_id) is not int or message_id <= 0:
            _render("/internal/telegram/mail-approval/delivery", method="POST", data={
                "request_id": request_id, "outcome": "unknown",
            })
            raise WorkerError("Telegram message receipt was not confirmed")
        _render("/internal/telegram/mail-approval/delivery", method="POST", data={
            "request_id": request_id, "outcome": "delivered", "message_id": message_id,
        })
        print("Telegram approval draft delivered; message body and recipient are omitted.")
    return 0


def main() -> int:
    try:
        return run()
    except WorkerError as exc:
        print("Telegram mail approval worker blocked:", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
