from __future__ import annotations

import html
import re
from datetime import datetime, timezone


TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")
_DEADLINE_LABEL = re.compile(
    r"\b(?:application deadline|deadline to apply|apply by|applications? close(?:s)?|"
    r"closing date|son başvuru tarihi|son başvuru günü|başvuru için son tarih)"
    r"\s*(?:is|:|-|on)?\s*([^;\n]{1,50})",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_LOCAL_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b")
_MONTH_DATE = re.compile(
    r"\b(?:(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)|"
    r"([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{1,2}),?)\s+(20\d{2})\b",
    re.IGNORECASE,
)
_MONTHS = {
    "january": 1, "jan": 1, "ocak": 1,
    "february": 2, "feb": 2, "şubat": 2, "subat": 2,
    "march": 3, "mar": 3, "mart": 3,
    "april": 4, "apr": 4, "nisan": 4,
    "may": 5, "mayıs": 5, "mayis": 5,
    "june": 6, "jun": 6, "haziran": 6,
    "july": 7, "jul": 7, "temmuz": 7,
    "august": 8, "aug": 8, "ağustos": 8, "agustos": 8,
    "september": 9, "sep": 9, "eylül": 9, "eylul": 9,
    "october": 10, "oct": 10, "ekim": 10,
    "november": 11, "nov": 11, "kasım": 11, "kasim": 11,
    "december": 12, "dec": 12, "aralık": 12, "aralik": 12,
}


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


def parse_application_deadline(text: str) -> datetime | None:
    """Parse only a full date explicitly attached to an application-deadline label."""
    for label in _DEADLINE_LABEL.finditer(text or ""):
        value = re.sub(r"^(?:on|by)\s+", "", label.group(1).strip(), flags=re.IGNORECASE)
        match = _ISO_DATE.search(value)
        if match:
            year, month, day = map(int, match.groups())
        else:
            match = _LOCAL_DATE.search(value)
            if match:
                day, month, year = map(int, match.groups())
                if "/" in match.group(0) and day <= 12 and month <= 12:
                    # Numeric slash dates are ambiguous across locales.
                    continue
            else:
                match = _MONTH_DATE.search(value)
                if not match:
                    continue
                day_first, month_first, month_last, day_last, year_text = match.groups()
                day = int(day_first or day_last)
                month_name = (month_first or month_last).casefold()
                month = _MONTHS.get(month_name)
                year = int(year_text)
                if month is None:
                    continue
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def infer_remote(location: str, text: str = "") -> str:
    combined = f"{location} {text}".lower()
    if "hybrid" in combined:
        return "hybrid"
    if re.search(r"\b(remote|work from home|distributed)\b", combined):
        return "remote"
    return "unknown"

