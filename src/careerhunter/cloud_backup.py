"""One-time Render -> Neon *backup*, within cloud only.

The Render process already has private DB access. GitHub Actions supplies only
short-lived, signed OIDC identity. The Neon target URL lives in Render secrets.
The original Render database is never written, deleted, or switched here.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.engine import make_url

from .pg_transfer import transfer
from .scheduled_scan import _require_github_oidc, REPO

logger = logging.getLogger(__name__)
router = APIRouter()
WORKFLOW = REPO + "/.github/workflows/neon-cloud-backup.yml@refs/heads/main"
_lock = threading.Lock()
_state: dict[str, object] = {"status": "idle"}


def _require_cloud_identity(request: Request) -> None:
    _require_github_oidc(
        request, workflow=WORKFLOW,
        events=frozenset({"workflow_dispatch", "push"}),
    )


def _urls() -> tuple[str, str]:
    if os.getenv("CAREERHUNTER_NEON_CLOUD_COPY_ENABLED") != "true":
        raise HTTPException(503, "Cloud copy not enabled")
    from .private_site import _settings

    source = _settings()[2]
    target = os.getenv("CAREERHUNTER_NEON_BACKUP_URL", "").strip()
    if not target:
        raise HTTPException(503, "Private Neon backup target not configured")
    parsed = make_url(target)
    if (parsed.get_backend_name() != "postgresql"
            or not (parsed.host or "").lower().endswith(".neon.tech")):
        raise HTTPException(503, "Target must be a dedicated Neon PostgreSQL database")
    if source == target:
        raise HTTPException(503, "Source and target must differ")
    return source, target


@router.get("/internal/cloud-backup/preflight")
def cloud_backup_preflight(request: Request) -> dict:
    _require_cloud_identity(request)
    source, target = _urls()
    try:
        # Read-only on both databases; returns only per-table counts.
        return transfer(source, target, apply=False)
    except Exception as exc:
        logger.warning("Cloud preflight blocked (%s)", type(exc).__name__)
        raise HTTPException(503, "Cloud backup preflight failed") from None


def _create_backup() -> None:
    try:
        source, target = _urls()
        report = transfer(
            source, target, apply=True, create_first_cloud_backup=True,
        )
        if report.get("mode") != "copied-and-verified" or not report.get("cloud_backup_created"):
            raise RuntimeError("Backup transaction did not verify")
        with _lock:
            _state.clear()
            _state.update({
                "status": "success",
                "copied_counts": report["target_counts"],
                "source_counts": report["source_counts"],
                "source_unchanged": True,
                "cutover": False,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as exc:
        # Keep error details away from GitHub and telemetry; a DB driver can
        # include credentials in exception messages.
        logger.error("Cloud backup failed (%s)", type(exc).__name__)
        with _lock:
            _state.clear()
            _state.update({
                "status": "failed",
                "cutover": False,
                "error_type": type(exc).__name__,
            })


@router.post("/internal/cloud-backup/start")
def start_cloud_backup(request: Request) -> dict:
    _require_cloud_identity(request)
    _urls()  # Fail closed before starting a background worker.
    with _lock:
        if _state.get("status") in {"running", "success"}:
            return dict(_state)
        _state.clear()
        _state.update({"status": "running", "cutover": False})
        threading.Thread(
            target=_create_backup, name="careerhunter-neon-cloud-backup",
            daemon=True,
        ).start()
        return dict(_state)


@router.get("/internal/cloud-backup/status")
def cloud_backup_status(request: Request) -> dict:
    _require_cloud_identity(request)
    with _lock:
        return dict(_state)
