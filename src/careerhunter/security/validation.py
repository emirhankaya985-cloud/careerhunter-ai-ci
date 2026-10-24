from __future__ import annotations

import re
from urllib.parse import urlparse


ALLOWED_HOSTS = {
    "boards-api.greenhouse.io",
    "api.lever.co",
    "api.ashbyhq.com",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "job-boards.greenhouse.io",
    "boards.greenhouse.io",
}
SLUG = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$")


def validate_slug(value: str) -> str:
    if not SLUG.fullmatch(value):
        raise ValueError(f"Invalid board slug: {value!r}")
    return value


def validate_public_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("Untrusted ATS URL")
    return value


def untrusted_content(text: str) -> str:
    """Delimit web text so downstream prompts treat it only as data."""
    return f"<UNTRUSTED_WEB_DATA>\n{text[:20000]}\n</UNTRUSTED_WEB_DATA>"
