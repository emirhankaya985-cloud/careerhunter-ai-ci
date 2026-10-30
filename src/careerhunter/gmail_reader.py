"""Bounded Gmail API readonly scanner; never sends, updates, or logs mail."""
from __future__ import annotations

import base64
import binascii
import os
import re
from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass

import httpx

from .inbox_review import InboxSignal, MAX_EMAIL_BYTES, classify_eml

TOKEN_URL = "https://oauth2.googleapis.com/token"
MAIL_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
_ID = re.compile(r"^[A-Za-z0-9_-]{5,80}$")


@dataclass(frozen=True)
class InboxSummary:
    scanned: int
    categories: dict[str, int]
    review_required: int

    def as_dict(self) -> dict[str, object]:
        return {"status": "ready", "scanned": self.scanned,
                "categories": self.categories, "review_required": self.review_required,
                "automatic_replies_sent": 0, "crm_statuses_changed": 0}


def configured() -> bool:
    return all(os.getenv(key, "").strip() for key in (
        "GMAIL_READONLY_CLIENT_ID", "GMAIL_READONLY_CLIENT_SECRET",
        "GMAIL_READONLY_REFRESH_TOKEN"
    ))


def summarize(signals: list[InboxSignal]) -> InboxSummary:
    counts = Counter(signal.proposed_category for signal in signals)
    return InboxSummary(
        scanned=len(signals), categories=dict(sorted(counts.items())),
        review_required=sum(signal.needs_review for signal in signals),
    )


def read_readonly(*, max_results: int = 20, client: httpx.Client | None = None) -> InboxSummary:
    """Fetch recent owner inbox entries using fixed queries and no write scopes."""
    if not configured():
        raise RuntimeError("Gmail readonly OAuth connection not configured")
    if not 1 <= max_results <= 30:
        raise ValueError("Gmail mail batch must be limited to 1..30")
    context = nullcontext(client) if client else httpx.Client(
        timeout=15, follow_redirects=False, trust_env=False)
    try:
        with context as http:
            response = http.post(TOKEN_URL, data={
                "client_id": os.environ["GMAIL_READONLY_CLIENT_ID"],
                "client_secret": os.environ["GMAIL_READONLY_CLIENT_SECRET"],
                "refresh_token": os.environ["GMAIL_READONLY_REFRESH_TOKEN"],
                "grant_type": "refresh_token",
            })
            response.raise_for_status()
            token = str(response.json().get("access_token") or "")
            if not token or len(token) > 8192:
                raise RuntimeError("Gmail token exchange returned no access token")
            headers = {"Authorization": "Bearer " + token}
            search = http.get(MAIL_URL, headers=headers,
                              params={"q": "newer_than:1d -category:promotions",
                                      "labelIds": "INBOX", "maxResults": max_results})
            search.raise_for_status()
            candidates = search.json().get("messages", [])
            if not isinstance(candidates, list) or len(candidates) > max_results:
                raise RuntimeError("Gmail message list is invalid")
            signals: list[InboxSignal] = []
            seen = set()
            for record in candidates:
                if not isinstance(record, dict) or not _ID.fullmatch(str(record.get("id", ""))):
                    raise RuntimeError("Gmail message identifier is invalid")
                raw_message = http.get(MAIL_URL + "/" + record["id"],
                                       headers=headers, params={"format": "raw"})
                raw_message.raise_for_status()
                encoded = raw_message.json().get("raw", "")
                if not isinstance(encoded, str) or len(encoded) > 1_400_000:
                    raise RuntimeError("Gmail raw message exceeds safe size")
                padding = "=" * (-len(encoded) % 4)
                payload = base64.urlsafe_b64decode(encoded + padding)
                if len(payload) > MAX_EMAIL_BYTES:
                    raise RuntimeError("Gmail message exceeds safe size")
                signal = classify_eml(payload)
                if signal.id_hash not in seen:
                    seen.add(signal.id_hash)
                    signals.append(signal)
            return summarize(signals)
    except (httpx.HTTPError, ValueError, TypeError, KeyError, UnicodeError, binascii.Error):
        # Never print API exceptions, tokens, senders or raw message bodies.
        raise RuntimeError("Gmail readonly fetch failed") from None
