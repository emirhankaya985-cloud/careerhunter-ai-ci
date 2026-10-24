"""Owner-only Telegram digest for newly discovered, high-fit job opportunities.

No listener/webhook: read-only inline URL buttons, never unsolicited user DMs.
Credentials live exclusively in Render Environment, never in the Git repository.
"""
from __future__ import annotations

import html
import logging
import os
import re
from typing import Iterable

import httpx

from ..models import Job, RunStats

logger = logging.getLogger(__name__)
_TOKEN_RE = re.compile(r"^[0-9]{6,15}:[A-Za-z0-9_-]{25,}$")
_CHAT_RE = re.compile(r"^-?[0-9]{4,20}$")
_DASHBOARD = "https://careerhunter-private-dashboard.onrender.com/?view=jobs&sort=fit"


def is_configured() -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    # Never leak a token in errors, request logs or GitHub Actions outputs.
    if not token and not chat:
        return False
    if not token or not chat:
        return False
    return bool(_TOKEN_RE.fullmatch(token) and _CHAT_RE.fullmatch(chat))


def _send(text: str, buttons: list[dict] | None = None, *, silent: bool = False) -> bool:
    if not is_configured():
        return False
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat = os.environ["TELEGRAM_CHAT_ID"].strip()
    body: dict = {
        "chat_id": chat,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_notification": silent,
        "link_preview_options": {"is_disabled": True},
        "protect_content": True,
    }
    if buttons:
        body["reply_markup"] = {"inline_keyboard": [[button] for button in buttons]}
    try:
        result = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=body,
            timeout=15,
        )
        if result.status_code != 200:
            logger.warning("Telegram notification rejected: HTTP %s", result.status_code)
            return False
        response = result.json()
        # HTTP 200 alone is not sufficient proof the message was accepted.
        message_id = (response.get("result") or {}).get("message_id")
        return response.get("ok") is True and isinstance(message_id, int) and message_id > 0
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        logger.warning("Telegram transport failed; no credentials logged")
        return False


def _safe(value: object, limit: int = 100) -> str:
    cleaned = " ".join(str(value or "").split())[:limit]
    return html.escape(cleaned, quote=True)


def _get_relevant(jobs: Iterable[Job], *, minimum: int) -> list[Job]:
    found: dict[tuple[str, str], Job] = {}
    for job in jobs:
        if (job.status != "new" or job.eligibility_status == "ineligible"
                or job.experience_level == "senior" or (job.match_score or 0) < minimum):
            continue
        found[(job.source, job.job_id)] = job
    return sorted(
        found.values(),
        key=lambda job: (job.match_score or 0, job.match_method == "llm"),
        reverse=True,
    )


def publish_daily_digest(stats: RunStats, jobs: Iterable[Job]) -> bool:
    """Single daily digest, maximum 3 fresh matches, zero if no strong match."""
    if stats.slot != "jobs" or stats.status != "success":
        return False
    if not is_configured():
        return False
    try:
        min_score = max(0, min(100, int(os.getenv("TELEGRAM_MIN_SCORE", "75"))))
    except ValueError:
        min_score = 75
    relevant = _get_relevant(jobs, minimum=min_score)
    if not relevant:
        return False

    top = relevant[:3]
    lines = [
        "🎯 <b>CareerHunter AI | Günlük İş Fırsatları</b>",
        "",
        f"🆕 Yeni ilan: <b>{stats.jobs_new}</b>",
        f"⭐ Güçlü eşleşme: <b>{len(relevant)}</b> (≥{min_score}/100)",
        "",
    ]
    buttons = []
    for index, job in enumerate(top, 1):
        score = int(job.match_score or 0)
        status = ("🌍 Türkiye: teyit gerekli" if job.eligibility_status == "needs_review"
                  else "✅ Türkiye: uygunluk kanıtı var")
        method = "NVIDIA AI" if job.match_method == "llm" else "Profil eşleştirmesi"
        lines.extend([
            f"<b>{index}. {_safe(job.title, 85)}</b>",
            f"🏢 {_safe(job.company, 55)} · 📍 {_safe(job.location, 55)}",
            f"🎯 {score}/100 · {_safe(method, 25)}",
            status, "",
        ])
        buttons.append({"text": f"🔗 {index}. ilana git", "url": str(job.job_url)})
    buttons.append({"text": "📊 Tüm ilanlar (şifreli panel)", "url": _DASHBOARD})
    if len(relevant) > 3:
        lines.append(f"➕ {len(relevant) - 3} güçlü eşleşme daha panelde.")
    if stats.error:
        lines.append("⚠️ Bazı ilan kaynakları bu taramada yanıt vermedi.")
    lines.append("<i>Vize, sponsor ve çalışma iznini ilan üzerinden doğrula.</i>")
    return _send("\n".join(lines), buttons)


def publish_failure(stats: RunStats) -> bool:
    if stats.slot != "jobs" or stats.status != "failed":
        return False
    # Do not include raw exception text; could contain DB URLs or API secrets.
    return _send(
        "⚠️ <b>CareerHunter AI</b>\n"
        "Günlük iş ilanı taramasında hata oluştu.\n"
        "GitHub Actions ve Render kayıtlarını kontrol et.",
        [{"text": "🧰 GitHub Actions", "url":
          "https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions"}],
    )


def publish_connection_test() -> bool:
    """Single owner-requested send; never part of import or health check."""
    return _send(
        "✅ <b>CareerHunter AI bağlandı!</b>\n"
        "🎯 Kişisel iş fırsatların bu sohbete gelecektir.\n"
        "🔔 Yalnızca yeni ve güçlü eşleşmeler bildirilir.",
        [{"text": "🎯 Kariyer panelini aç", "url": _DASHBOARD}],
    )
