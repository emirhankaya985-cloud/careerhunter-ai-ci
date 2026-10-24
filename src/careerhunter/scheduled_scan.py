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
RESCORE_WORKFLOW = REPO + "/.github/workflows/personalize.yml@refs/heads/main"
SMOKE_WORKFLOW = REPO + "/.github/workflows/nvidia-smoke.yml@refs/heads/main"
TELEGRAM_SMOKE_WORKFLOW = REPO + "/.github/workflows/telegram-smoke.yml@refs/heads/main"
JWK_URL = ISSUER + "/.well-known/jwks"
_jwks = PyJWKClient(JWK_URL, cache_jwk_set=True, lifespan=3600, timeout=10)
_lock = threading.Lock()
_state: dict[str, object] = {"status": "idle"}

router = APIRouter()


def _require_github_oidc(request: Request, *, workflow: str = WORKFLOW) -> None:
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
        "repository": REPO,
        "repository_id": REPO_ID,
        "workflow_ref": workflow,
        "ref": "refs/heads/main",
    }
    mismatched = [name for name, value in expected.items()
                  if str(claims.get(name)) != value]
    # New GitHub OIDC subject templates can include immutable IDs instead of
    # repo names. Bind access to the verified repository_id, exact workflow and
    # ref claims above; still require a non-empty, signed subject.
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        mismatched.append("sub")
    if mismatched:
        logger.warning("GitHub OIDC claim mismatch fields: %s", ",".join(mismatched))
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
    # Read-only status is permitted for either independently verified workflow.
    # The collect and rescore POST endpoints keep their distinct authorizations.
    try:
        _require_github_oidc(request)
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        _require_github_oidc(request, workflow=RESCORE_WORKFLOW)
    with _lock:
        return dict(_state)


def _rescore() -> None:
    """Backfill score JSON using the Render-private profile and database."""
    try:
        from .private_site import _settings
        from .personal_rescore import rescore_existing

        url = _settings()[2]
        if not url.startswith("postgresql+psycopg://"):
            raise RuntimeError("Production rescore requires PostgreSQL")
        processed = rescore_existing(url)
        with _lock:
            _state.clear()
            _state.update({
                "status": "success" if processed > 0 else "empty",
                "mode": "rescore",
                "jobs_processed": processed,
                "jobs_new": 0,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as exc:
        logger.error("Personal backfill failed: %s", type(exc).__name__)
        with _lock:
            _state.clear()
            _state.update({
                "status": "failed", "mode": "rescore",
                "error_type": type(exc).__name__,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })


@router.post("/internal/rescore")
def start_rescore(request: Request) -> dict[str, object]:
    _require_github_oidc(request, workflow=RESCORE_WORKFLOW)
    with _lock:
        if _state.get("status") == "running":
            return dict(_state)
        _state.clear()
        _state.update({
            "status": "running",
            "mode": "rescore",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        threading.Thread(target=_rescore, name="careerhunter-rescore", daemon=True).start()
        return dict(_state)


def _enrich_historical_with_nvidia() -> None:
    """Bounded semantic enrichment of historic matches, not a full re-scan."""
    try:
        from .private_site import _settings
        from .personal_rescore import enrich_best_existing
        url = _settings()[2]
        if not url.startswith("postgresql+psycopg://"):
            raise RuntimeError("AI enrichment requires hosted PostgreSQL")
        count = enrich_best_existing(url, limit=8)
        with _lock:
            _state.clear()
            _state.update({
                "status": "success", "mode": "ai",
                "jobs_processed": count, "jobs_new": 0,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as exc:
        logger.warning("Historical NVIDIA enrichment failed: %s", type(exc).__name__)
        with _lock:
            _state.clear()
            _state.update({
                "status": "failed", "mode": "ai",
                "error_type": type(exc).__name__,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })


@router.post("/internal/ai-rescore")
def start_ai_rescore(request: Request) -> dict[str, object]:
    _require_github_oidc(request, workflow=RESCORE_WORKFLOW)
    with _lock:
        if _state.get("status") == "running":
            return dict(_state)
        _state.clear()
        _state.update({
            "status": "running",
            "mode": "ai",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        threading.Thread(target=_enrich_historical_with_nvidia,
                         name="careerhunter-nvidia", daemon=True).start()
        return dict(_state)


@router.post("/internal/nvidia-smoke")
def nvidia_smoke(request: Request) -> dict[str, object]:
    """One synthetic free-trial inference, authorized only by signed GitHub OIDC.

    Never return or log a credential or a private real-world candidate profile.
    Keep this probe separate from stored job data or recurring daily scraping.
    """
    _require_github_oidc(request, workflow=SMOKE_WORKFLOW)
    from .llm.provider import create_provider, configured_provider

    provider_mode = configured_provider()
    provider = create_provider()
    if provider_mode != "nvidia" or provider is None:
        return {"status": "missing_key", "model": os.getenv("LLM_MODEL", "")}
    model = getattr(provider, "model", "")
    if model != "nvidia/nemotron-3.5-super-vl-120b-a12b":
        return {"status": "wrong_model", "model": model}
    try:
        result = provider.analyze_job(
            {"skills": ["Python", "FastAPI"],
             "target_roles": ["Junior Python Developer"],
             "experience": ["student", "junior"]},
            "title=Junior Python Developer\\nlocation=Remote from Turkey\\n"
            "description=Python FastAPI internship-friendly role, globally remote."
        )
        return {
            "status": "success",
            "model": model,
            "valid_json": True,
            "score": result.total,
            "note": "synthetic_only",
        }
    except Exception as exc:
        from httpx import HTTPStatusError
        # NVIDIA may return 401 (invalid key), 429 (rate limit), or 422 (params).
        # Surface only the safe status code and Python exception class.
        http_status = exc.response.status_code if isinstance(exc, HTTPStatusError) else None
        logger.warning("NVIDIA smoke failed: %s (HTTP %s)",
                       type(exc).__name__, http_status or "-")
        # Distinguish an invalid credential from a non-entitled model endpoint:
        # only return safe status codes and a model-presence boolean.
        import httpx
        model_list_status = None
        model_list_contains_120b = None
        if getattr(provider, "url", "") == (
            "https://integrate.api.nvidia.com/v1/chat/completions"
        ):
            try:
                catalog = httpx.get(
                    "https://integrate.api.nvidia.com/v1/models",
                    headers={"Authorization": f"Bearer {provider.api_key}"},
                    timeout=12,
                )
                model_list_status = catalog.status_code
                if catalog.status_code == 200:
                    data = catalog.json().get("data", [])
                    model_list_contains_120b = any(
                        item.get("id") == model for item in data
                        if isinstance(item, dict)
                    )
            except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                pass
        return {
            "status": "api_failed",
            "model": model,
            "error_type": type(exc).__name__,
            "http_status": http_status,
            "official_endpoint": getattr(provider, "url", "") ==
                "https://integrate.api.nvidia.com/v1/chat/completions",
            "models_http_status": model_list_status,
            "model_is_listed": model_list_contains_120b,
        }


@router.post("/internal/telegram-smoke")
def telegram_smoke(request: Request) -> dict[str, object]:
    """Send one owner-requested Telegram ping using a protected workflow."""
    _require_github_oidc(request, workflow=TELEGRAM_SMOKE_WORKFLOW)
    from .notifications.telegram import is_configured, publish_connection_test
    if not is_configured():
        return {"status": "not_configured"}
    return {"status": "accepted" if publish_connection_test() else "send_failed"}
