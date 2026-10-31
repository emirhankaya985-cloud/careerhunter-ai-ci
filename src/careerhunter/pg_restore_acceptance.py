"""Signed and isolated recovery test of the live Neon database.

This invokes *real* pg_dump and pg_restore binaries on Render. Never restore
into the live database or touch the retained Render PostgreSQL server.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from .database import metadata
from .pg_transfer import _fingerprint, _source_counts
from .scheduled_scan import REPO, _require_github_oidc

router = APIRouter()
WORKFLOW = REPO + "/.github/workflows/pg-restore-acceptance.yml@refs/heads/main"
SCRATCH = "careerhunter_restore_probe_20261031"
_lock = threading.Lock()
_state: dict[str, object] = {"status": "idle"}
logger = logging.getLogger(__name__)


def _urls() -> tuple[str, str]:
    from .private_site import _settings

    source = _settings()[2]
    parsed = make_url(source)
    if (parsed.get_backend_name() != "postgresql"
            or not (parsed.host or "").lower().endswith(".neon.tech")
            or parsed.database != "careerhunter_live"
            or not parsed.username or not parsed.password):
        raise ValueError("Live Neon database identity invalid")
    destination = parsed.set(database=SCRATCH).render_as_string(hide_password=False)
    return source, destination


def _env(url: str) -> dict[str, str]:
    parsed = make_url(url)
    return {
        **os.environ,
        "PGHOST": str(parsed.host), "PGPORT": str(parsed.port or 5432),
        "PGUSER": str(parsed.username), "PGPASSWORD": str(parsed.password),
        "PGDATABASE": str(parsed.database), "PGSSLMODE": "require",
    }


def _installed() -> bool:
    return bool(shutil.which("pg_dump") and shutil.which("pg_restore"))


def _check() -> None:
    src = dst = None
    try:
        if not _installed():
            raise RuntimeError("postgresql_client_missing")
        source, destination = _urls()
        src = create_engine(source, pool_pre_ping=True,
                            connect_args={"options": "-c default_transaction_read_only=on"})
        dst = create_engine(destination, pool_pre_ping=True)
        # Fail closed if there is a single user table in the scratch database.
        with dst.connect() as connection:
            if inspect(connection).get_table_names(schema="public"):
                raise RuntimeError("scratch_database_not_empty")
        with tempfile.TemporaryDirectory(prefix="careerhunter-restore-") as folder:
            archive = str(Path(folder) / "neon.dump")
            subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-acl",
                            "--no-password", "--file", archive],
                           env=_env(source), check=True, timeout=300,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if Path(archive).stat().st_size < 1024:
                raise RuntimeError("archive_too_small")
            # Populate only a verified empty scratch database; never issue drops.
            subprocess.run(["pg_restore", "--exit-on-error",
                            "--no-owner", "--no-acl", "--no-password",
                            "--dbname", SCRATCH, archive],
                           env=_env(destination), check=True, timeout=300,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with src.connect() as left, dst.connect() as right:
            counts = _source_counts(left)
            if counts != _source_counts(right):
                raise RuntimeError("restored_table_counts_differ")
            for table in metadata.sorted_tables:
                if _fingerprint(left, table) != _fingerprint(right, table):
                    raise RuntimeError("restored_rows_differ")
        with _lock:
            _state.clear()
            _state.update({"status": "success", "pg_dump": True, "pg_restore": True,
                           "tables": len(metadata.sorted_tables),
                           "jobs": counts["jobs"], "runs": counts["runs"],
                           "render_source_untouched": True,
                           "finished_at": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        logger.warning("PG recovery acceptance failed (%s)", type(exc).__name__)
        with _lock:
            _state.clear()
            _state.update({"status": "failed", "error_type": type(exc).__name__})
    finally:
        if src is not None:
            src.dispose()
        if dst is not None:
            dst.dispose()


def _auth(request: Request) -> None:
    _require_github_oidc(request, workflow=WORKFLOW,
                         events=frozenset({"workflow_dispatch"}))


@router.get("/internal/pg-restore/tooling")
def tools_available(request: Request) -> dict:
    _auth(request)
    return {"installed": _installed(),
            "enabled": os.getenv("CAREERHUNTER_PG_RESTORE_ENABLED") == "true"}


@router.post("/internal/pg-restore/start")
def start(request: Request) -> dict:
    _auth(request)
    if os.getenv("CAREERHUNTER_PG_RESTORE_ENABLED") != "true" or not _installed():
        raise HTTPException(503, "Restore test prerequisites absent")
    try:
        _urls()
    except (TypeError, ValueError):
        raise HTTPException(503, "Invalid isolated recovery target") from None
    with _lock:
        if _state.get("status") in {"running", "success"}:
            return dict(_state)
        _state.clear()
        _state.update({"status": "running"})
        threading.Thread(target=_check, name="isolated-pg-restore-test", daemon=True).start()
        return dict(_state)


@router.get("/internal/pg-restore/status")
def status(request: Request) -> dict:
    _auth(request)
    with _lock:
        return dict(_state)
