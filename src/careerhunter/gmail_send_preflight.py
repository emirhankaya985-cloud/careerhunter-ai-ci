"""OIDC-protected, non-sending Gmail capability check for Render secrets."""
from __future__ import annotations

import os

import httpx
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


@router.get("/internal/gmail/send-preflight")
def send_preflight(request: Request) -> dict[str, object]:
    """Report deployment readiness; this endpoint never sends mail."""
    from .scheduled_scan import _require_github_oidc, MAIL_SEND_PREFLIGHT_WORKFLOW
    _require_github_oidc(request, workflow=MAIL_SEND_PREFLIGHT_WORKFLOW,
                          events=frozenset({"workflow_dispatch", "schedule", "push"}))
    from .private_site import _repo

    try:
        contacts = _repo().list_contacts(limit=5000)
        approved_count = sum(
            c.status == "approved_by_user" and c.research_confidence == "high"
            and bool(c.email_public) and bool(c.primary_source_url) and not c.do_not_contact
            for c in contacts
        )
        contact_store_ready = True
    except Exception:
        approved_count = 0
        contact_store_ready = False

    send_enabled = os.getenv("CAREERHUNTER_GMAIL_SEND_ENABLED") == "true"
    writer_present = bool(os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "").strip())
    scope_verified = _check_send_scope()
    ready = send_enabled and writer_present and scope_verified and contact_store_ready and approved_count > 0
    return {
        "status": "ready" if ready else "blocked",
        "send_enabled": send_enabled,
        "send_oauth_scope_verified": scope_verified,
        "receipt_writer_present": writer_present,
        "contact_store_ready": contact_store_ready,
        "approved_contact_count": approved_count,
        "automatic_dispatch_enabled": False,
        "messages_sent": 0,
    }
