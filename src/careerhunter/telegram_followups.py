"""Reminder sender for overdue *manual* job applications.

Reads a small OIDC-protected Render summary and sends only to the configured
private owner Telegram chat. Never emails, applies, or updates CRM state.
"""
from __future__ import annotations

import html
import os
import sys

from .render_scan_client import call
from .telegram_github import configured, send


def _clean(value: object, limit: int) -> str:
    return html.escape(" ".join(str(value or "").split())[:limit], quote=True)


def prepare(payload: dict) -> tuple[str, list[dict]] | None:
    if payload.get("status") != "ready":
        raise ValueError("No verified followup snapshot")
    count = int(payload.get("due_count", 0))
    if count < 0:
        raise ValueError("Invalid followup count")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("Invalid followup entries")
    if count == 0:
        return None
    text = [
        "⏰ <b>CareerHunter AI | Başvuru takipleri</b>",
        f"📌 İncelenmesi gereken takip: <b>{count}</b>",
        "<i>Bu sadece hatırlatmadır; mesaj veya başvuru gönderilmedi.</i>",
        "",
    ]
    buttons: list[dict] = []
    for index, item in enumerate(items[:10], 1):
        if not isinstance(item, dict):
            raise ValueError("Invalid reminder item")
        text.append(f"{index}. <b>{_clean(item.get('title'), 85)}</b>")
        text.append(f"🏢 {_clean(item.get('company'), 65)} · 📅 {_clean(item.get('due_at'), 12)}")
        url = str(item.get("job_url") or "")
        if url.startswith("https://") and not any(c.isspace() for c in url):
            buttons.append({"text": f"🔗 {index}. İlana git", "url": url})
    if count > 10:
        text.append(f"➕ {count - 10} ek takip kontrol panelinde.")
    buttons.append({"text": "📋 Takipleri görüntüle", "url":
                    "https://careerhunter-private-dashboard.onrender.com/?view=applications"})
    return "\n".join(text), buttons


def main() -> int:
    if os.getenv("GITHUB_RUN_ATTEMPT", "1") != "1":
        print("SKIP: GitHub retry; reminder already attempted")
        return 0
    if not configured():
        print("FAIL: owner Telegram chat not configured")
        return 1
    payload = call("/internal/followups/due")
    reminder = prepare(payload)
    if reminder is None:
        print("PASS: zero due application followups")
        return 0
    if not send(*reminder):
        print("FAIL: Telegram followup reminder was not accepted")
        return 1
    print("PASS: Telegram accepted overdue followup summary")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, KeyError, TypeError, OSError):
        print("FAIL: followup reminder unavailable; no secrets printed")
        sys.exit(1)
