"""Exact GitHub OIDC-only incremental preflight and guarded non-cutover copy."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request

from .neon_incremental import synchronize
from .neon_reconcile import _connections
from .scheduled_scan import REPO, _require_github_oidc

router = APIRouter()
logger = logging.getLogger(__name__)
WORKFLOW = REPO + "/.github/workflows/neon-incremental.yml@refs/heads/main"


@router.get("/internal/neon-incremental/plan")
def incremental_plan(request: Request) -> dict:
    _require_github_oidc(request, workflow=WORKFLOW,
                         events=frozenset({"workflow_dispatch"}))
    try:
        source, target = _connections()
        return synchronize(source, target)
    except Exception as exc:
        logger.warning("Incremental preflight blocked (%s)", type(exc).__name__)
        raise HTTPException(503, "Neon incremental preflight unavailable") from None


@router.post("/internal/neon-incremental/apply")
def incremental_apply(request: Request) -> dict:
    _require_github_oidc(request, workflow=WORKFLOW,
                         events=frozenset({"workflow_dispatch"}))
    if (os.getenv("CAREERHUNTER_NEON_INCREMENTAL_ENABLED") != "true"
            or os.getenv("CAREERHUNTER_NEON_BACKUP_VERIFIED") != "true"):
        raise HTTPException(503, "A proven backup and owner opt-in are required")
    try:
        source, target = _connections()
        # This ONLY adds/updates rows in the dedicated Neon target. It never
        # changes the app's active DB selection or deletes the Render source.
        return synchronize(source, target, apply=True, backup_confirmed=True)
    except Exception as exc:
        logger.warning("Incremental transfer blocked (%s)", type(exc).__name__)
        raise HTTPException(503, "Neon incremental transfer unavailable") from None
