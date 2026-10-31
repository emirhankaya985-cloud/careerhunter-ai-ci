"""Private read-only snapshot reconciliation before Neon cutover.

The endpoint NEVER modifies either database or exposes a database credential,
record, contact, private email, or per-row fingerprint.  A green comparison
does not freeze future writers: re-check immediately before the cutover.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from .database import metadata
from .pg_transfer import _check_urls, _fingerprint, _source_counts, _start_snapshot
from .scheduled_scan import REPO, _require_github_oidc

logger = logging.getLogger(__name__)
router = APIRouter()
WORKFLOW = REPO + "/.github/workflows/neon-reconcile.yml@refs/heads/main"


def _connections() -> tuple[str, str]:
    # Do not use the *selected* database here: a previous operator may
    # already have switched the app to Neon. Explicitly read the retained
    # ORIGINAL Render DSN and compare it to the current Neon destination.
    source = os.environ.get("DASHBOARD_DATABASE_URL", "").strip()
    target = os.environ.get("CAREERHUNTER_NEON_DATABASE_URL", "").strip()
    try:
        parsed = make_url(target)
        if not (
            parsed.get_backend_name() == "postgresql"
            and (parsed.host or "").lower().endswith(".neon.tech")
            and parsed.database == "careerhunter_live"
            and bool(parsed.username)
        ):
            raise ValueError("Invalid dedicated Neon target")
        original = make_url(source)
        if (original.get_backend_name() != "postgresql"
                or original.database != "careerhunter_ai_db"
                or not original.host
                or original.host.lower().endswith(".neon.tech")):
            raise ValueError("Original Render source identity cannot be proven")
        source, target = _check_urls(source, target, False)
    except (ArgumentError, ValueError, TypeError):
        raise RuntimeError("Reconciliation cannot access a verified Neon target") from None
    if not source.startswith("postgresql+psycopg://"):
        raise RuntimeError("Source must be hosted PostgreSQL")
    return source, target


def _compare(source_url: str, target_url: str) -> dict:
    options = {"connect_args": {"options": "-c default_transaction_read_only=on"}}
    source = create_engine(source_url, pool_pre_ping=True, **options)
    target = create_engine(target_url, pool_pre_ping=True, **options)
    try:
        with source.connect() as left, target.connect() as right:
            _start_snapshot(left)
            _start_snapshot(right)
            source_counts = _source_counts(left)
            target_counts = _source_counts(right)
            exact = source_counts == target_counts
            if exact:
                for table in metadata.sorted_tables:
                    # Canonical SHA-256 over every complete row in every table;
                    # no row content or hash escapes the process.
                    if _fingerprint(left, table) != _fingerprint(right, table):
                        exact = False
                        break
            return {
                "status": "match" if exact else "mismatch",
                "source_counts": source_counts,
                "target_counts": target_counts,
                "all_row_hashes_equal": exact,
                "production_cutover_performed": False,
            }
    finally:
        source.dispose()
        target.dispose()


@router.get("/internal/neon-cutover/preflight")
def neon_preflight(request: Request) -> dict:
    _require_github_oidc(
        request, workflow=WORKFLOW,
        events=frozenset({"push", "workflow_dispatch"}),
    )
    stage = "validate"
    try:
        source, target = _connections()
        stage = "read_only_compare"
        return _compare(source, target)
    except Exception as exc:
        # Fixed diagnostic codes only; SQL driver exceptions may contain
        # connection details and must never be included in application logs.
        safe_reasons = {
            "Reconciliation cannot access a verified Neon target": "target_validation",
            "Source must be hosted PostgreSQL": "source_validation",
        }
        reason = safe_reasons.get(str(exc), "unclassified") if stage == "validate" else "comparison"
        logger.warning("Neon reconciliation blocked at %s (%s, %s)",
                       stage, reason, type(exc).__name__)
        raise HTTPException(503, "Neon reconciliation is unavailable") from None


@router.get("/internal/neon-cutover/state")
def neon_effective_state(request: Request) -> dict:
    """Only sanitized effective database identity, never host or credentials."""
    _require_github_oidc(
        request, workflow=WORKFLOW,
        events=frozenset({"push", "workflow_dispatch"}),
    )
    from .private_site import _settings
    try:
        effective = make_url(_settings()[2])
        chosen = os.getenv("CAREERHUNTER_DB_TARGET", "render").strip().lower()
        return {
            "selected_target": chosen if chosen in {"render", "neon"} else "invalid",
            "effective_backend": ("neon" if (effective.host or "").lower().endswith(".neon.tech")
                                  else "non_neon"),
            "effective_database": (
                effective.database if effective.database in {"careerhunter", "careerhunter_live",
                                                              "careerhunter_ai_db"} else "other"),
            "does_not_write": True,
        }
    except Exception as exc:
        logger.warning("Safe database state probe failed (%s)", type(exc).__name__)
        raise HTTPException(503, "Database identity unavailable") from None
