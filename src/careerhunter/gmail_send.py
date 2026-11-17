"""Owner-approved Gmail application email delivery.

No automatic application is inferred from an ATS listing. This module is
disabled until the owner grants a separate gmail.send OAuth scope and enables
the outbound feature. Every mail requires a vetted destination, explicit
approval and a durable one-shot PostgreSQL claim. No automatic retries.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from urllib.parse import urlsplit

import httpx
from sqlalchemy import Column, MetaData, String, Table, create_engine, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import make_url

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
MAIL_KEY = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
EMAIL = re.compile(r"^[^@\s,<>]+@[^@\s,<>]+\.[^@\s,<>]+$")
GMAIL_MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{5,120}$")
metadata = MetaData()
mail_receipts = Table(
    "careerhunter_approved_mail_receipts", metadata,
    Column("mail_hash", String(64), primary_key=True),
    Column("claimed_at", String(40), nullable=False),
    Column("status", String(24), nullable=False),
    Column("provider_receipt_hash", String(64)),
)


class GmailSendError(RuntimeError):
    """Code-only failure. Never include an email, token, API body or DB URL."""


@dataclass(frozen=True)
class ApprovedMail:
    recipient: str
    subject: str
    body: str
    contact_evidence_url: str
    approval_id: str
    approved_by_owner: bool
    reply_to: str | None = None

    def validate(self) -> None:
        if self.approved_by_owner is not True:
            raise GmailSendError("owner_approval_required")
        if not isinstance(self.recipient, str) or not EMAIL.fullmatch(self.recipient):
            raise GmailSendError("invalid_recipient")
        if self.reply_to is not None and not EMAIL.fullmatch(self.reply_to):
            raise GmailSendError("invalid_reply_to")
        if not isinstance(self.subject, str) or not 1 <= len(self.subject.strip()) <= 160:
            raise GmailSendError("invalid_subject")
        if any(c in self.subject for c in "\r\n"):
            raise GmailSendError("invalid_subject")
        if not isinstance(self.body, str) or not 1 <= len(self.body.strip()) <= 12000:
            raise GmailSendError("invalid_body")
        if not isinstance(self.approval_id, str) or not MAIL_KEY.fullmatch(self.approval_id):
            raise GmailSendError("invalid_approval_id")
        try:
            evidence = urlsplit(self.contact_evidence_url)
            valid = (evidence.scheme == "https" and bool(evidence.hostname)
                     and not evidence.username and not evidence.password
                     and evidence.hostname not in {"localhost", "127.0.0.1"})
        except (TypeError, ValueError, AttributeError):
            valid = False
        if not valid:
            raise GmailSendError("verified_contact_evidence_required")

    def key(self) -> str:
        # Stable approved job/contact identity; changing the text cannot
        # send a second application to the same contact for the same job.
        return hashlib.sha256(self.approval_id.encode("utf-8")).hexdigest()


def _credentials() -> tuple[str, str, str]:
    # Reuse the already-installed OAuth CLIENT credentials, not its readonly
    # refresh token. Google still requires a new gmail.send consent.
    client_id = (os.environ.get("GMAIL_SEND_CLIENT_ID", "").strip()
                 or os.environ.get("GMAIL_READONLY_CLIENT_ID", "").strip())
    client_secret = (os.environ.get("GMAIL_SEND_CLIENT_SECRET", "").strip()
                     or os.environ.get("GMAIL_READONLY_CLIENT_SECRET", "").strip())
    send_refresh = os.environ.get("GMAIL_SEND_REFRESH_TOKEN", "").strip()
    return client_id, client_secret, send_refresh


def _configured() -> bool:
    return all(_credentials())


def _send(mail: ApprovedMail, client: httpx.Client | None = None) -> str:
    msg = EmailMessage()
    msg["To"] = mail.recipient
    msg["Subject"] = mail.subject.strip()
    if mail.reply_to:
        msg["Reply-To"] = mail.reply_to
    msg.set_content(mail.body)
    encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii").rstrip("=")
    ctx = nullcontext(client) if client is not None else httpx.Client(
        timeout=20, follow_redirects=False, trust_env=False,
    )
    try:
        with ctx as http:
            client_id, client_secret, refresh = _credentials()
            response = http.post(TOKEN_URL, data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            })
            response.raise_for_status()
            token = response.json().get("access_token")
            if not isinstance(token, str) or not 5 <= len(token) <= 8192:
                raise GmailSendError("oauth_token_invalid")
            result = http.post(
                SEND_URL, headers={"Authorization": "Bearer " + token},
                json={"raw": encoded},
            )
            result.raise_for_status()
            provider_id = result.json().get("id")
            if not isinstance(provider_id, str) or not GMAIL_MESSAGE_ID.fullmatch(provider_id):
                raise GmailSendError("gmail_receipt_unconfirmed")
            return provider_id
    except GmailSendError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError):
        raise GmailSendError("provider_result_unconfirmed") from None


def send_approved_once(
    mail: ApprovedMail, *, database_url: str, client: httpx.Client | None = None,
    allow_sqlite_tests: bool = False,
) -> str:
    """Send at most once after durable claim; uncertain results require manual review.

    A claim is written BEFORE hitting Gmail. This intentionally prefers missing a
    send over duplicating an application if the provider response is lost.
    """
    mail.validate()
    if os.getenv("CAREERHUNTER_GMAIL_SEND_ENABLED") != "true":
        raise GmailSendError("gmail_send_disabled")
    if not _configured():
        raise GmailSendError("gmail_send_oauth_missing")
    try:
        if database_url.startswith("postgres://"):
            database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
        elif database_url.startswith("postgresql://"):
            database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
        parsed = make_url(database_url)
        backend = parsed.get_backend_name()
        if backend != "postgresql" and not (allow_sqlite_tests and backend == "sqlite"):
            raise GmailSendError("postgresql_ledger_required")
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            metadata.create_all(engine, tables=[mail_receipts])
            key = mail.key()
            now = datetime.now(timezone.utc).isoformat()
            today = datetime.now(timezone.utc).date().isoformat()
            with engine.begin() as conn:
                if backend == "postgresql":
                    # Serialize daily quota checks among concurrent workers.
                    conn.execute(text("SELECT pg_advisory_xact_lock(98520261117)"))
                count = conn.execute(select(func.count()).select_from(mail_receipts).where(
                    mail_receipts.c.claimed_at >= today
                )).scalar_one()
                if count >= 5:
                    raise GmailSendError("daily_limit_reached")
                values = {"mail_hash": key, "claimed_at": now,
                          "status": "pending_review", "provider_receipt_hash": None}
                statement = (pg_insert(mail_receipts) if backend == "postgresql"
                             else sqlite_insert(mail_receipts)).values(**values)
                statement = statement.on_conflict_do_nothing(
                    index_elements=[mail_receipts.c.mail_hash]
                )
                if conn.execute(statement).rowcount != 1:
                    raise GmailSendError("duplicate_or_previous_attempt")
            provider_id = _send(mail, client)
            receipt_hash = hashlib.sha256(provider_id.encode("utf-8")).hexdigest()
            with engine.begin() as conn:
                conn.execute(update(mail_receipts).where(
                    mail_receipts.c.mail_hash == key
                ).values(status="sent", provider_receipt_hash=receipt_hash))
            return provider_id
        finally:
            engine.dispose()
    except GmailSendError:
        raise
    except Exception:
        # Preserve the pending_review claim if the database or transport failed.
        raise GmailSendError("ledger_unavailable_or_unconfirmed") from None
