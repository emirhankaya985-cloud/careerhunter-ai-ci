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
from sqlalchemy import Column, MetaData, String, Table, create_engine, func, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import make_url

TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
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
    Column("provider_message_id", String(120)),
    Column("company_key", String(64)),
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
    attachment_pdf: bytes | None = None
    attachment_filename: str | None = None
    company_key: str | None = None

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
        if self.attachment_pdf is not None:
            if (not isinstance(self.attachment_pdf, bytes) or len(self.attachment_pdf) > 10 * 1024 * 1024
                    or not self.attachment_pdf.startswith(b"%PDF-")
                    or b"%%EOF" not in self.attachment_pdf[-2048:]
                    or self.attachment_filename not in {"careerhunter_cv_en.pdf", "careerhunter_cv_tr.pdf"}):
                raise GmailSendError("invalid_cv_attachment")
        elif self.attachment_filename is not None:
            raise GmailSendError("invalid_cv_attachment")
        if self.company_key is not None and not re.fullmatch(r"[a-f0-9]{64}", self.company_key):
            raise GmailSendError("invalid_company_key")
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


def _send(
    mail: ApprovedMail, client: httpx.Client | None = None,
    *, expected_account: str | None = None,
) -> str:
    msg = EmailMessage()
    msg["To"] = mail.recipient
    msg["Subject"] = mail.subject.strip()
    if mail.reply_to:
        msg["Reply-To"] = mail.reply_to
    msg.set_content(mail.body)
    if mail.attachment_pdf is not None:
        msg.add_attachment(mail.attachment_pdf, maintype="application", subtype="pdf",
                           filename=mail.attachment_filename)
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
            headers = {"Authorization": "Bearer " + token}
            if expected_account is not None:
                # The self-test OAuth grant must include `openid email` so the
                # worker can prove the token belongs to the protected owner account.
                identity = http.get(USERINFO_URL, headers=headers)
                identity.raise_for_status()
                identity_body = identity.json()
                actual_email = identity_body.get("email")
                if (identity_body.get("email_verified") is not True
                        or not isinstance(actual_email, str)
                        or actual_email.casefold() != expected_account.casefold()):
                    raise GmailSendError("gmail_sender_account_mismatch")
            result = http.post(
                SEND_URL, headers=headers, json={"raw": encoded},
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
    return _send_durably(
        mail, database_url=database_url, client=client,
        allow_sqlite_tests=allow_sqlite_tests,
        required_gate="CAREERHUNTER_GMAIL_SEND_ENABLED",
        success_status="sent",
    )


def send_owner_self_test_once(
    language: str, attachment_pdf: bytes, *, database_url: str,
    client: httpx.Client | None = None,
    allow_sqlite_tests: bool = False,
) -> str:
    """Send one fixed CV test only to the protected, OAuth-verified owner account.

    This path cannot accept a recipient, subject, or body from workflow input and
    does not consume an application/approval queue row. The stable approval key
    makes repeated or ambiguous attempts fail closed.
    """
    if os.getenv("CAREERHUNTER_GMAIL_SELF_TEST_ENABLED") != "true":
        raise GmailSendError("gmail_self_test_disabled")
    if language not in {"en", "tr"}:
        raise GmailSendError("invalid_self_test_language")
    owner_account = os.getenv("CAREERHUNTER_GMAIL_SELF_TEST_ACCOUNT", "").strip()
    if not EMAIL.fullmatch(owner_account):
        raise GmailSendError("self_test_owner_account_missing")
    filename = f"careerhunter_cv_{language}.pdf"
    mail = ApprovedMail(
        recipient=owner_account,
        subject=f"CareerHunter AI private delivery test ({language.upper()})",
        body="This is a one-time CareerHunter Gmail worker test to your verified owner account.\r\n",
        contact_evidence_url="https://mail.google.com/",
        approval_id=f"careerhunter-self-test-v1-{language}",
        approved_by_owner=True,
        attachment_pdf=attachment_pdf,
        attachment_filename=filename,
    )
    return _send_durably(
        mail, database_url=database_url, client=client,
        allow_sqlite_tests=allow_sqlite_tests,
        required_gate="CAREERHUNTER_GMAIL_SELF_TEST_ENABLED",
        success_status="sent_self_test",
        expected_account=owner_account,
    )


def _send_durably(
    mail: ApprovedMail, *, database_url: str, client: httpx.Client | None,
    allow_sqlite_tests: bool, required_gate: str, success_status: str,
    expected_account: str | None = None,
) -> str:
    mail.validate()
    if os.getenv(required_gate) != "true":
        if required_gate == "CAREERHUNTER_GMAIL_SEND_ENABLED":
            raise GmailSendError("gmail_send_disabled")
        raise GmailSendError("gmail_self_test_disabled")
    if os.getenv("CAREERHUNTER_GMAIL_SEND_ENABLED") != "true":
        if required_gate == "CAREERHUNTER_GMAIL_SEND_ENABLED":
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
            if backend == "postgresql":
                with engine.connect() as conn:
                    if not inspect(conn).has_table(mail_receipts.name, schema="public"):
                        raise GmailSendError("mail_receipt_table_missing")
                    columns = {column["name"] for column in inspect(conn).get_columns(
                        mail_receipts.name, schema="public"
                    )}
                    if not {"provider_message_id", "company_key"}.issubset(columns):
                        raise GmailSendError("mail_receipt_schema_migration_required")
            else:
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
                if mail.company_key:
                    company_count = conn.execute(select(func.count()).select_from(mail_receipts).where(
                        mail_receipts.c.company_key == mail.company_key,
                        mail_receipts.c.claimed_at >= today,
                    )).scalar_one()
                    if company_count >= 1:
                        raise GmailSendError("daily_company_limit_reached")
                values = {"mail_hash": key, "claimed_at": now,
                          "status": "pending_review", "provider_receipt_hash": None,
                          "provider_message_id": None, "company_key": mail.company_key}
                statement = (pg_insert(mail_receipts) if backend == "postgresql"
                             else sqlite_insert(mail_receipts)).values(**values)
                statement = statement.on_conflict_do_nothing(
                    index_elements=[mail_receipts.c.mail_hash]
                )
                if conn.execute(statement).rowcount != 1:
                    raise GmailSendError("duplicate_or_previous_attempt")
            provider_id = _send(mail, client, expected_account=expected_account)
            receipt_hash = hashlib.sha256(provider_id.encode("utf-8")).hexdigest()
            with engine.begin() as conn:
                conn.execute(update(mail_receipts).where(
                    mail_receipts.c.mail_hash == key
                ).values(status=success_status, provider_receipt_hash=receipt_hash,
                         provider_message_id=provider_id))
            return provider_id
        finally:
            engine.dispose()
    except GmailSendError:
        raise
    except Exception:
        # Preserve the pending_review claim if the database or transport failed.
        raise GmailSendError("ledger_unavailable_or_unconfirmed") from None

