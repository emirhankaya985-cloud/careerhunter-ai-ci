"""Opt-in, privacy-preserving Gmail review summary to private Telegram.

Only aggregate counts leave the Render service; no Gmail credentials, sender
addresses, subjects, body text, message IDs or CRM mutation are transferred.
"""
from __future__ import annotations

import os
import sys

from .github_operations import production_database_url
from .gmail_reader import configured as gmail_configured, read_readonly
from .telegram_github import configured, send


def prepare(data: dict) -> str:
    if data.get("status") != "ready":
        raise RuntimeError("Gmail read-only monitor is not active")
    scanned = int(data.get("scanned", -1))
    review_required = int(data.get("review_required", -1))
    categories = data.get("categories")
    if (scanned < 0 or review_required < 0 or review_required > scanned
            or not isinstance(categories, dict)):
        raise ValueError("Gmail summary counts invalid")
    names = {"application": "Başvuru alındı olasılığı",
             "followup": "Takip / başvuru güncellemesi olasılığı",
             "interview": "Mülakat olasılığı", "assessment": "Teknik test olasılığı",
             "rejection": "Ret olasılığı", "needs_review": "Diğer / belirsiz"}
    result = [
        "📨 <b>CareerHunter AI | Gmail başvuru incelemesi</b>",
        f"📬 Son 24 saatte incelenen ileti: <b>{scanned}</b>",
    ]
    for code, label in names.items():
        try:
            count = int(categories.get(code, 0))
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid Gmail category count") from exc
        if count < 0 or count > scanned:
            raise ValueError("Invalid Gmail category count")
        if count:
            result.append(f"• {label}: <b>{count}</b>")
    result.append(
        "🔒 <i>Bu sayılar insan incelemesi gerektiren işaretlerdir; "
        "mesaj okunmadı olarak bırakılır, yanıt gönderilmez.</i>"
    )
    return "\n".join(result)


def main() -> int:
    if os.getenv("GITHUB_RUN_ATTEMPT", "1") != "1":
        print("SKIP: Gmail monitor retry suppressed")
        return 0
    if not configured():
        print("FAIL: private Telegram destination is not ready")
        return 1
    if os.getenv("CAREERHUNTER_GMAIL_READONLY_ENABLED") != "true":
        print("SKIP: Gmail review is not opted in; mailbox was not read")
        return 0
    if not gmail_configured():
        print("FAIL: Gmail read-only OAuth secrets are missing")
        return 1
    ledger_url = (production_database_url()
                  if os.getenv("CAREERHUNTER_GMAIL_LEDGER_ENABLED") == "true" else None)
    data = read_readonly(max_results=20, ledger_url=ledger_url).as_dict()
    if data.get("status") != "ready":
        print("FAIL: Gmail readonly monitor not configured or not opted in")
        return 1
    message = prepare(data)
    if not send(message):
        print("FAIL: Telegram did not acknowledge Gmail summary")
        return 1
    print("PASS: Telegram accepted aggregate Gmail review summary")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, TypeError, KeyError, OSError):
        print("FAIL: Gmail review summary unavailable; no sensitive fields logged")
        sys.exit(1)
