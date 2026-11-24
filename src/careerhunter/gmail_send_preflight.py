"""OIDC-protected, non-sending Gmail capability check for Render secrets."""
from __future__ import annotations

import os

import httpx
from sqlalchemy import create_engine, select, text
from fastapi import APIRouter, Request

router = APIRouter()
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def _check_send_scope() -> bool:
    """Refresh an access token and inspect scopes without sending or logging it."""
    from .gmail_send import _credentials, TOKEN_URL

    client_id, client_secret, refresh_token = _credentials()
    if not all((client_id, client_secret, refresh_token)):
        return False
    try:
        response = httpx.post(
            TOKEN_URL,
            data={"client_id": client_id, "client_secret": client_secret,
                  "refresh_token": refresh_token, "grant_type": "refresh_token"},
            timeout=15,
            follow_redirects=False,
            trust_env=False,
        )
        if response.status_code != 200:
            return False
        body = response.json()
        token = body.get("access_token")
        scope = body.get("scope", "")
        # Never return or log the access token. It exists only for this check.
        return (isinstance(token, str) and 5 <= len(token) <= 8192
                and isinstance(scope, str) and SEND_SCOPE in scope.split())
    except (httpx.HTTPError, ValueError, TypeError, OSError):
        return False


def _writer_identity() -> dict[str, object]:
    """Check the secret writer target without returning its host or credentials."""
    from .telegram_mail_approval import _writer_url

    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as connection:
            row = connection.execute(text(
                "SELECT current_database() AS database_name, current_user AS role_name, "
                "to_regclass('public.careerhunter_telegram_mail_approvals') IS NOT NULL "
                "AS approval_table_exists"
            )).mappings().one()
            database_name = str(row["database_name"])
            role_name = str(row["role_name"])
            return {
                "writer_reachable": True,
                "writer_database_matches": database_name == "careerhunter_live",
                "writer_database": database_name,
                "writer_role": role_name,
                "approval_table_exists": bool(row["approval_table_exists"]),
            }
    except Exception:
        return {
            "writer_reachable": False,
            "writer_database_matches": False,
            "writer_database": None,
            "writer_role": None,
            "approval_table_exists": False,
        }
    finally:
        engine.dispose()


def build_preflight() -> dict[str, object]:
    """Inspect GitHub Actions credentials and records without sending email."""
    from .database import contacts
    from .github_operations import production_database_url
    from .models import Contact

    contact_store_ready = False
    approved_count = 0
    application_count = 0
    try:
        engine = create_engine(production_database_url(), pool_pre_ping=True,
                               pool_size=1, max_overflow=0)
        try:
            with engine.connect() as connection:
                rows = connection.execute(select(contacts.c.payload).limit(5000)).scalars().all()
            records = [Contact.model_validate_json(row) for row in rows]
            approved_count = sum(
                c.status == "approved_by_user" and c.research_confidence == "high"
                and bool(c.email_public) and bool(c.primary_source_url) and not c.do_not_contact
                for c in records
            )
            application_count = sum(
                c.category == "job_application_email" and c.research_confidence == "high"
                and bool(c.email_public) and bool(c.primary_source_url)
                and not c.do_not_contact and c.status not in {"not_interested", "closed"}
                for c in records
            )
            contact_store_ready = True
        finally:
            engine.dispose()
    except Exception:
        # Never expose driver errors or connection strings in workflow logs.
        pass

    send_enabled = os.getenv("CAREERHUNTER_GMAIL_SEND_ENABLED") == "true"
    writer_present = bool((os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "")
                           or os.getenv("DATABASE_URL", "")).strip())
    writer_identity = _writer_identity()
    scope_verified = _check_send_scope()
    template_approved = os.getenv("CAREERHUNTER_GMAIL_AUTO_TEMPLATE_APPROVED") == "v1"
    automatic_enabled = (
        os.getenv("CAREERHUNTER_GMAIL_AUTO_OUTREACH_ENABLED") == "true"
        and template_approved
    )
    ready = (send_enabled and writer_present and writer_identity["writer_database_matches"]
             and writer_identity["writer_reachable"] and scope_verified and contact_store_ready
             and (approved_count > 0 or application_count > 0))
    return {
        "status": "ready" if ready else "blocked",
        "send_enabled": send_enabled,
        "send_oauth_scope_verified": scope_verified,
        "receipt_writer_present": writer_present,
        **writer_identity,
        "contact_store_ready": contact_store_ready,
        "approved_contact_count": approved_count,
        "application_contact_count": application_count,
        "automatic_dispatch_enabled": automatic_enabled,
        "automatic_template_approved": template_approved,
        "messages_sent": 0,
    }


@router.get("/internal/gmail/send-preflight")
def send_preflight(request: Request) -> dict[str, object]:
    """Report deployment readiness; this endpoint never sends mail."""
    from .scheduled_scan import _require_github_oidc, MAIL_SEND_PREFLIGHT_WORKFLOW
    _require_github_oidc(request, workflow=MAIL_SEND_PREFLIGHT_WORKFLOW,
                          events=frozenset({"workflow_dispatch", "schedule", "push"}))
    return build_preflight()

