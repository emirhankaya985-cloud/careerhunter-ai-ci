from __future__ import annotations

import os
import re
import json
import time
import hashlib

import httpx

from ..models import RunStats


TOPIC_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def configured_topic() -> str | None:
    topic = os.getenv("NTFY_TOPIC", "").strip()
    if not topic:
        return None
    if not TOPIC_PATTERN.fullmatch(topic):
        raise ValueError("NTFY_TOPIC must contain 8-128 safe characters")
    return topic


def _safe_text(value: str, limit: int = 300) -> str:
    """Remove values that could disclose secrets in push notifications."""
    value = re.sub(r"(?i)(?:postgres(?:ql)?|https?)://[^\s]+", "[redacted-url]", value)
    value = re.sub(r"(?i)(token|secret|password|api[_-]?key)\s*[=:]\s*[^\s]+", r"\1=[redacted]", value)
    return value[:limit]


def publish(message: str, *, title: str, priority: int = 3,
            sequence_id: str | None = None) -> bool:
    """Publish an aggregate-only notification; return False when not configured."""
    topic = configured_topic()
    acceptance_file = os.getenv("NTFY_ACCEPTANCE_FILE", "").strip()
    if not topic:
        if acceptance_file:
            _write_acceptance(acceptance_file, {"configured": False, "accepted": False, "reason": "NTFY_TOPIC not configured"})
        return False
    payload = {"topic": topic, "title": title, "message": _safe_text(message, limit=1200),
               "priority": priority, "tags": ["briefcase"]}
    for attempt in range(3):
        try:
            headers = {"X-Sequence-ID": sequence_id} if sequence_id else None
            response = httpx.post("https://ntfy.sh/", json=payload,
                                  headers=headers, timeout=15)
            response.raise_for_status()
            if acceptance_file:
                _write_acceptance(acceptance_file, {"configured": True, "accepted": True, "http_status": response.status_code})
            return True
        except httpx.HTTPError as exc:
            if attempt == 2 and acceptance_file:
                _write_acceptance(acceptance_file, {"configured": True, "accepted": False, "error": type(exc).__name__})
            if attempt < 2:
                time.sleep(2**attempt)
    return False


def _write_acceptance(path: str, payload: dict) -> None:
    """Write transport acceptance only; never implies phone delivery/read status."""
    try:
        target = os.path.abspath(path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except OSError:
        # Notification evidence must never break the career data pipeline.
        pass


def publish_run(stats: RunStats) -> bool:
    # ntfy replaces a message carrying the same sequence ID, so retries of this
    # exact run do not create duplicate notifications on subscribed clients.
    run_key = f"{stats.slot}:{stats.started_at.isoformat()}"
    sequence_id = hashlib.sha256(run_key.encode("utf-8")).hexdigest()
    if stats.status == "success":
        partial = bool(stats.error)
        message = (
            f"Slot: {stats.slot}\n"
            f"İşlenen ilan: {stats.jobs_processed}\n"
            f"Yeni ilan: {stats.jobs_new}\n"
            f"Kapanan ilan: {stats.jobs_closed}\n"
            f"LLM çağrısı: {stats.llm_calls}"
        )
        if partial:
            message += "\nKaynak durumu: kısmi tarama\n" + _safe_text(stats.error or "")
        return publish(
            message,
            title=("CareerHunter tarama kısmi" if partial
                   else "CareerHunter günlük tarama tamamlandı"),
            priority=4 if partial else 3,
            sequence_id=sequence_id,
        )
    error = _safe_text(stats.error or "Bilinmeyen hata")
    return publish(
        f"Slot: {stats.slot}\nHata: {error}",
        title="CareerHunter çalışması başarısız",
        priority=4,
        sequence_id=sequence_id,
    )
