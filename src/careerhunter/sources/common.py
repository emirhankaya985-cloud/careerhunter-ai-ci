from __future__ import annotations

import html
import re
from datetime import datetime, timezone


TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")


def clean_html(value: str | None) -> str:
    return SPACE.sub(" ", html.unescape(TAG.sub(" ", value or ""))).strip()


def parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def infer_remote(location: str, text: str = "") -> str:
    combined = f"{location} {text}".lower()
    if "hybrid" in combined:
        return "hybrid"
    if re.search(r"\b(remote|work from home|distributed)\b", combined):
        return "remote"
    return "unknown"

