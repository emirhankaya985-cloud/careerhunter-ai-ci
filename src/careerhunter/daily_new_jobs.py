"""Daily Telegram recap of ALL new job discoveries, independent of fit score."""
from __future__ import annotations

import html
import os
import sys

from .render_scan_client import call
from .telegram_github import configured, send

DASHBOARD = "https://careerhunter-private-dashboard.onrender.com/?view=jobs&sort=fit"


def escape(value: object, limit: int = 90) -> str:
    return html.escape(" ".join(str(value or "").split())[:limit], quote=True)


def compose(data: dict) -> tuple[str, list[dict]] | None:
    if data.get("status") != "ready":
        raise RuntimeError("Daily report not ready")
    total = int(data.get("jobs_new", 0))
    items = data.get("items", [])[:5]
    if not total and not items:
        return None
    strong = int(data.get("strong_count", 0))
    threshold = int(data.get("threshold", 75))
    listed = int(data.get("listed_count", len(items)))
    lines = [
        "📬 <b>CareerHunter AI | Yeni İş İlanları</b>", "",
        f"🆕 Yeni bulunan ilan: <b>{total}</b>",
        f"⭐ Güçlü eşleşme: <b>{strong}</b> (en az {threshold}/100)",
        "",
    ]
    buttons = []
    for index, job in enumerate(items, 1):
        score = int(job["score"])
        restricted = job.get("eligibility") == "ineligible" or job.get("level") == "senior"
        fit = "⛔ Uygun değil" if restricted else (
            "⭐ Güçlü eşleşme" if score >= threshold else "ℹ️ Düşük/orta eşleşme")
        eligibility = "⛔ Türkiye'den çalışma uygun değil" if (
            job.get("eligibility") == "ineligible") else (
            "✅ Türkiye uygunluğu doğrulanmış" if job.get("eligibility") == "eligible"
            else "🌍 Türkiye uygunluğu teyit edilmeli")
        lines.extend([
            f"<b>{index}. {escape(job['title'])}</b>",
            f"🏢 {escape(job['company'], 70)} · 📍 {escape(job['location'], 70)}",
            f"🎯 {score}/100 · {fit}", eligibility, "",
        ])
        link = str(job["url"])
        if not link.startswith("https://"):
            raise ValueError("Job URL must be https")
        buttons.append({"text": f"🔗 {index}. ilana git", "url": link})
    if listed > len(items):
        lines.append(f"➕ {listed - len(items)} yeni ilan daha var.")
    if total and not items:
        lines.append("İlan ayrıntıları için kariyer panelini kontrol et.")
    buttons.append({"text": "📊 Tüm ilanları gör", "url": DASHBOARD})
    lines.append("<i>Puanı düşük ilanlar da bilgilendirme amaçlı gösterilir.</i>")
    return "\n".join(lines), buttons


def main() -> int:
    if not configured():
        print("FAIL: Telegram secrets missing or malformed")
        return 1
    result = compose(call("/internal/telegram/digest"))
    if result is None:
        print("PASS: no new jobs to report")
        return 0
    if send(*result):
        print("PASS: Telegram accepted daily new-jobs report")
        return 0
    print("FAIL: Telegram rejected new-jobs report")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, TypeError, KeyError):
        print("FAIL: cannot prepare new-jobs report")
        sys.exit(1)
