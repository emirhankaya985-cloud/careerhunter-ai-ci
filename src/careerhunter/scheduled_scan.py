"""GitHub OIDC-authenticated collector trigger for the owner-only Render service.

GitHub owns the schedule, while Render owns the PostgreSQL connection.
No database credentials or production records are exposed to GitHub Actions.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, HTTPException, Request
from jwt import PyJWKClient, PyJWTError

from .database import DatabaseRepository
from .orchestrator import Orchestrator

logger = logging.getLogger(__name__)

ISSUER = "https://token.actions.githubusercontent.com"
AUDIENCE = "careerhunter-ai-render-collector"
REPO = "emirhankaya985-cloud/careerhunter-ai-ci"
REPO_ID = "1431811304"
WORKFLOW = REPO + "/.github/workflows/daily.yml@refs/heads/main"
JWK_URL = ISSUER + "/.well-known/jwks"
_jwks = PyJWKClient(JWK_URL, cache_jwk_set=True, lifespan=3600, timeout=10)
_lock = threading.Lock()
_state: dict[str, object] = {"status": "idle"}

router = APIRouter()


def _require_github_oidc(request: Request) -> None:
    """Verify the signature AND immutable repository/workflow identity."""
    if os.getenv("CAREERHUNTER_OIDC_COLLECTOR") != "true":
        raise HTTPException(status_code=404, detail="Not found")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = auth[7:]
    if not token or len(token) > 12000 or token.count(".") != 2:
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    try:
        key = _jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["iss", "aud", "exp", "iat", "sub"]},
            leeway=30,
        )
    except (PyJWTError, ValueError, TypeError, OSError) as exc:
        logger.info("Rejecting invalid GitHub identity: %s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Invalid identity") from None

    expected = {
        "sub": "repo:" + REPO + ":ref:refs/heads/main",
        "repository": REPO,
        "repository_id": REPO_ID,
        "workflow_ref": WORKFLOW,
        "ref": "refs/heads/main",
    }
    if any(str(claims.get(name)) != value for name, value in expected.items()):
        raise HTTPException(status_code=403, detail="Workflow not authorized")
    if claims.get("event_name") not in {"schedule", "workflow_dispatch", "push"}:
        raise HTTPException(status_code=403, detail="Event not authorized")


def _collect() -> None:
    """Collector is the only route allowed to write; dashboard remains read-only."""
    repo = None
    try:
        # Never accept a DB URL, token, company list, or SQL from HTTP.
        from .private_site import _settings

        database_url = _settings()[2]
        if not database_url.startswith("postgresql+psycopg://"):
            raise RuntimeError("Collector requires hosted PostgreSQL")
        repo = DatabaseRepository(database_url)
        stats, _report = Orchestrator(repo=repo).run("jobs", dry_run=False)
        result = {
            "status": "success" if stats.jobs_processed > 0 else "empty",
            "jobs_processed": stats.jobs_processed,
            "jobs_new": stats.jobs_new,
            "jobs_closed": stats.jobs_closed,
            "sources_partial": bool(stats.error),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        with _lock:
            _state.clear()
            _state.update(result)
    except Exception as exc:
        # Do not expose connection strings or external job descriptions.
        logger.error("Scheduled collection failed: %s", type(exc).__name__)
        with _lock:
            _state.clear()
            _state.update({
                "status": "failed", "error_type": type(exc).__name__,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
    finally:
        if repo is not None:
            repo.engine.dispose()


@router.post("/internal/scan")
def start_scan(request: Request) -> dict[str, object]:
    _require_github_oidc(request)
    with _lock:
        if _state.get("status") == "running":
            return dict(_state)
        _state.clear()
        _state.update({
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        threading.Thread(target=_collect, name="careerhunter-collector", daemon=True).start()
        return dict(_state)


@router.get("/internal/scan/status")
def scan_status(request: Request) -> dict[str, object]:
    _require_github_oidc(request)
    with _lock:
        return dict(_state)
