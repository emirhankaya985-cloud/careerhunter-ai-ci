"""Send CareerHunter Telegram notifications using only GitHub Actions secrets.

Render provides a short public-job digest through GitHub's signed OIDC identity.
No bot token, user chat ID or PostgreSQL credentials are passed to Render.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .render_scan_client import call

_TOKEN = re.compile(r"^[0-9]{6,15}:[A-Za-z0-9_-]{25,}$")
_CHAT = re.compile(r"^-?[0-9]{4,20}$")
_DASHBOARD = "https://careerhunter-private-dashboard.onrender.com/?view=jobs&sort=fit"


def configured() -> bool:
    return bool(_TOKEN.fullmatch(os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
                and _CHAT.fullmatch(os.getenv("TELEGRAM_CHAT_ID", "").strip()))


def send(text: str, buttons: list[dict] | None = None) -> bool:
    """Return True only after Telegram acknowledges a positive message_id."""
    if not configured():
        return False
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()
    payload: dict = {
        "chat_id": chat_id,
        "text": text[:4000],
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "protect_content": True,
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": [[button] for button in buttons]}
    req = Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "CareerHunter-Notify/1.0"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=22) as response:
            if response.status != 200:
                print("Telegram rejected request (non-200 HTTP)")
                return False
            reply = json.load(response)
        receipt = (reply.get("result") or {}).get("message_id")
        return reply.get("ok") is True and isinstance(receipt, int) and receipt > 0
    except HTTPError as exc:
        # Never print the exception, URL, response JSON, chat ID or token.
        # Telegram error descriptions can contain arbitrary data, so permit
        # only a narrow, known diagnostic label.
        try:
            detail = json.loads(exc.read(2048)).get("description", "").casefold()
        except (ValueError, TypeError, AttributeError):
            detail = ""
        reason = ("chat_not_found" if "chat not found" in detail else
                  "bot_not_started_or_blocked" if "bot was blocked" in detail or
                  "bot can\u2019t initiate" in detail or "bot can't initiate" in detail else
                  "invalid_chat_id" if "chat_id" in detail else
                  "telegram_format_error" if "parse entities" in detail else
                  "unknown")
        print(f"Telegram HTTP {exc.code}; safe_failure_reason={reason}")
        return False
    except (URLError, TimeoutError, ValueError, KeyError, TypeError, OSError):
        print("Telegram transport failed; sensitive details not printed")
        return False




def diagnose_connection() -> bool:
    """Test the actual token's bot identity and exact chat access, without leaks.

    Return diagnostic booleans and public bot username only. Never output chat ID,
    token, Telegram response bodies or private sender information.
    """
    if not configured():
        print("DIAG: token_or_chat_secret_invalid")
        return False
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat = os.environ["TELEGRAM_CHAT_ID"].strip()

    def bot_api(method: str, body: dict | None = None) -> tuple[int, dict]:
        req = Request(
            "https://api.telegram.org/bot" + token + "/" + method,
            method="POST",
            data=json.dumps(body or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=16) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            # Error payloads may be sensitive. Do not print them.
            return exc.code, {}
        except (URLError, TimeoutError, OSError, ValueError):
            return 0, {}

    code, who = bot_api("getMe")
    if code != 200 or who.get("ok") is not True:
        print("DIAG: token_getMe_failed HTTP", code)
        return False
    public_username = str((who.get("result") or {}).get("username") or "")
    safe_username = re.sub(r"[^A-Za-z0-9_]", "", public_username)[:64]
    print("DIAG: authenticated_bot_username=@" + safe_username)

    chat_code, chat_data = bot_api("getChat", {"chat_id": chat})
    print("DIAG: configured_chat_getChat_http=" + str(chat_code))
    if chat_code == 200 and chat_data.get("ok") is True:
        print("DIAG: bot_can_access_configured_chat=true")
        return True

    updates_code, updates_data = bot_api("getUpdates", {"limit": 100, "timeout": 0,
                                                       "allowed_updates": ["message"]})
    print("DIAG: bot_getUpdates_http=" + str(updates_code))
    if updates_code == 200 and updates_data.get("ok") is True:
        recent = [
            event.get("message", {})
            for event in updates_data.get("result", [])
            if isinstance(event, dict)
        ]
        started_chats = {
            str(message.get("chat", {}).get("id"))
            for message in recent
            if isinstance(message, dict) and
               str(message.get("text", "")).startswith("/start") and
               isinstance(message.get("chat"), dict) and
               message.get("chat", {}).get("type") == "private"
        }
        print("DIAG: private_start_message_seen=" +
              ("true" if bool(started_chats) else "false"))
        print("DIAG: configured_chat_matches_private_start=" +
              ("true" if chat in started_chats else "false"))
    return False

def html_safe(value: object, maxlen: int = 90) -> str:
    return html.escape(" ".join(str(value or "").split())[:maxlen], quote=True)


def digest_message(data: dict) -> tuple[str, list[dict]] | None:
    if data.get("status") != "ready":
        raise RuntimeError("Production digest did not return a successful scan")
    if not data.get("items"):
        return None
    items = data["items"][:3]
    count = int(data.get("strong_count", 0))
    threshold = int(data.get("threshold", 75))
    lines = [
        "🎯 <b>CareerHunter AI | Günlük İş Fırsatları</b>", "",
        f"🆕 Yeni ilan: <b>{int(data.get('jobs_new', 0))}</b>",
        f"⭐ Güçlü eşleşme: <b>{count}</b> (≥{threshold}/100)", "",
    ]
    buttons = []
    for index, item in enumerate(items, 1):
        score = int(item["score"])
        method = "NVIDIA AI" if item.get("method") == "llm" else "Kişisel puan"
        eligibility = ("✅ Türkiye'den uygunluk kanıtı" if
                       item.get("eligibility") == "eligible" else
                       "🌍 Türkiye'den çalışma: teyit gerekli")
        lines += [
            f"<b>{index}. {html_safe(item['title'])}</b>",
            f"🏢 {html_safe(item['company'])} · 📍 {html_safe(item['location'])}",
            f"🎯 {score}/100 · {method}", eligibility, "",
        ]
        link = str(item["url"])
        if not link.startswith("https://"):
            raise ValueError("Job link is not an HTTPS URL")
        buttons.append({"text": f"🔗 {index}. ilana git", "url": link})
    buttons.append({"text": "📊 Şifreli kariyer paneli", "url": _DASHBOARD})
    if count > len(items):
        lines.append(f"➕ {count-len(items)} uygun ilan daha panelde.")
    lines.append("<i>Çalışma izni, vize ve sponsorluk koşullarını doğrula.</i>")
    return "\n".join(lines), buttons


def main() -> int:
    args = set(sys.argv[1:])
    if not configured():
        print("NOT_CONFIGURED: GitHub Secrets TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing or invalid")
        return 1 if ("--test" in args or "--failure" in args) else 0
    if "--diagnose" in args:
        return 0 if diagnose_connection() else 1
    if "--test" in args:
        accepted = send(
            "✅ <b>CareerHunter AI bağlandı!</b>\n"
            "🎯 Kişisel kariyer fırsatların artık bu sohbete iletilebilir.\n"
            "🔒 Bot tokenı yalnızca GitHub Secrets içinde saklanır.",
            [{"text": "🎯 Kariyer paneli", "url": _DASHBOARD}],
        )
        print("PASS: Telegram accepted test message" if accepted else
              "FAIL: Telegram refused test message")
        return 0 if accepted else 1
    if "--failure" in args:
        result = send(
            "⚠️ <b>CareerHunter AI: Tarama başarısız</b>\n"
            "GitHub Actions ve Render kayıtlarını kontrol et.",
            [{"text": "🛠️ GitHub Actions", "url":
              "https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions"}],
        )
        return 0 if result else 1
    if "--digest" not in args:
        raise ValueError("Expected --test, --digest or --failure")
    # No recurring job is re-notified if GitHub is manually re-running the workflow.
    if os.getenv("GITHUB_RUN_ATTEMPT", "1") != "1":
        print("SKIP: repeat workflow attempt; no duplicate Telegram digest")
        return 0
    payload = call("/internal/telegram/digest")
    message = digest_message(payload)
    if message is None:
        print("PASS: no new strong matches; no Telegram message needed")
        return 0
    success = send(*message)
    print("PASS: Telegram accepted new-job digest" if success else
          "FAIL: Telegram digest rejected")
    return 0 if success else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        # Only predictable, authored errors are printed; do not print token URLs.
        print(f"FAIL: {type(exc).__name__}: {str(exc)[:150]}", file=sys.stderr)
        sys.exit(1)
