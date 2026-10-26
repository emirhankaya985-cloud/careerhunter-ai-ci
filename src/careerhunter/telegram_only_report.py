"""Telegram-first daily career updates. No dashboard login is required by owner.

Bot token and private Chat ID are supplied only by GitHub Actions Secrets.
Only public job metadata is fetched from the OIDC-protected Render service.
"""
from __future__ import annotations

import html
import sys
import time

from .render_scan_client import call
from .telegram_github import configured, send

CHUNK_SIZE = 5


def safe(text: object, limit: int = 85) -> str:
    return html.escape(" ".join(str(text or "").split())[:limit], quote=True)


def make_messages(payload: dict) -> list[tuple[str, list[dict]]]:
    if payload.get("status") != "ready":
        raise RuntimeError("Daily collection has no verified successful snapshot")
    total = max(0, int(payload.get("jobs_new", 0)))
    items = payload.get("items") or []
    strong = max(0, int(payload.get("strong_count", 0)))
    threshold = max(0, int(payload.get("threshold", 75)))
    listed = max(0, int(payload.get("listed_count", len(items))))
    output = []

    if not items:
        lines = [
            "📬 <b>CareerHunter AI | Günlük iş raporu</b>",
            f"🆕 Bugün bulunan yeni ilan: <b>{total}</b>",
            "⭐ Güçlü eşleşme: <b>0</b>",
        ]
        if total:
            lines.append("⚠️ Yeni ilan sayacı var ama ayrıntılar yüklenemedi; bu durum incelenmeli.")
        else:
            lines.append("Bugün yeni ilan yok. Sistem günlük taramasını tamamladı. ✅")
        return [("\n".join(lines), [])]

    count = (len(items) + CHUNK_SIZE - 1) // CHUNK_SIZE
    for part in range(count):
        start = part * CHUNK_SIZE
        batch = items[start:start + CHUNK_SIZE]
        lines = [
            "📬 <b>CareerHunter AI | Günlük yeni ilanlar</b>",
            f"🆕 Yeni ilan: <b>{total}</b> · ⭐ Güçlü: <b>{strong}</b> "
            f"(en az {threshold}/100)",
            f"📦 Bölüm {part + 1}/{count}",
            "",
        ]
        buttons = []
        for offset, job in enumerate(batch, start + 1):
            score = max(0, min(100, int(job.get("score", 0))))
            ineligible = job.get("eligibility") == "ineligible"
            senior = job.get("level") == "senior"
            badge = ("⛔ Uygun görünmüyor" if ineligible or senior else
                     "⭐ Güçlü eşleşme" if score >= threshold else
                     "ℹ️ Düşük/orta uyum")
            eligibility = ("⛔ Türkiye'den uygun değil" if ineligible else
                           "✅ Türkiye uygunluğu doğrulandı" if
                           job.get("eligibility") == "eligible" else
                           "🌍 Türkiye'den çalışma: teyit gerekli")
            url = str(job.get("url", ""))
            if not url.startswith("https://"):
                raise ValueError("Job URL must start with https://")
            lines.extend([
                f"<b>{offset}. {safe(job.get('title'))}</b>",
                f"🏢 {safe(job.get('company'), 60)} · 📍 {safe(job.get('location'), 60)}",
                f"🎯 {score}/100 · {badge}",
                eligibility,
                "",
            ])
            buttons.append({"text": f"🔗 {offset}. İlana git", "url": url})
        if part == count - 1:
            remaining = max(0, listed - len(items))
            if remaining:
                lines.append(f"⚠️ {remaining} ilan günlük Telegram gönderim üst sınırını aştı.")
            lines.append("<i>Başvuru senin onayınla yapılır; çalışma iznini kontrol et.</i>")
        output.append(("\n".join(lines), buttons))
    return output


def main() -> int:
    if not configured():
        print("FAIL: bot secrets are missing; no Telegram message sent")
        return 1
    payload = call("/internal/telegram/digest")
    batches = make_messages(payload)
    for index, (message, buttons) in enumerate(batches):
        if index:
            time.sleep(1.1)  # Conservative per-chat pacing.
        if not send(message, buttons):
            print("FAIL: Telegram delivery declined for batch", index + 1)
            return 1
        print("PASS: Telegram accepted new-jobs batch", index + 1,
              "of", len(batches))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, TypeError, KeyError):
        print("FAIL: daily Telegram report unavailable; no secrets printed")
        sys.exit(1)
