"""Owner-authorized, OIDC-signed, read-only Gmail acceptance (no mail data)."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from .scheduled_scan import REPO, _require_github_oidc

logger = logging.getLogger(__name__)
router = APIRouter()
WORKFLOW = REPO + "/.github/workflows/gmail-acceptance.yml@refs/heads/main"


@router.get("/internal/gmail/acceptance")
def gmail_acceptance(request: Request) -> dict:
    _require_github_oidc(
        request, workflow=WORKFLOW,
        events=frozenset({"push", "workflow_dispatch"}),
    )
    from .gmail_reader import configured, read_readonly
    if os.getenv("CAREERHUNTER_GMAIL_READONLY_ENABLED") != "true":
        return {"status": "disabled", "read_only": True}
    if not configured():
        return {"status": "missing_render_oauth", "read_only": True}
    try:
        summary = read_readonly(max_results=3)
        return {
            "status": "ready",
            "scanned": int(summary.scanned),
            "review_required": int(summary.review_required),
            "read_only": True,
            "messages_sent": 0,
            "messages_modified": 0,
        }
    except Exception as exc:
        # Never include OAuth, email subjects/bodies or Gmail API error text.
        logger.warning("Gmail acceptance unavailable (%s)", type(exc).__name__)
        return {"status": "read_failed", "read_only": True}
