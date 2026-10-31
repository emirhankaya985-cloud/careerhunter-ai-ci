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
TELEGRAM_REPORT_WORKFLOW = REPO + "/.github/workflows/telegram-report.yml@refs/heads/main"
FOLLOWUP_WORKFLOW = REPO + "/.github/workflows/followup-reminder.yml@refs/heads/main"
MAIL_REVIEW_WORKFLOW = REPO + "/.github/workflows/gmail-review.yml@refs/heads/main"
JWK_URL = ISSUER + "/.well-known/jwks"
_jwks = PyJWKClient(JWK_URL, cache_jwk_set=True, lifespan=3600, timeout=10)
_lock = threading.Lock()
_state: dict[str, object] = {"status": "idle"}

router = APIRouter()


def _require_github_oidc(request: Request, *, workflow: str = WORKFLOW,
                         events: frozenset[str] | None = None) -> None:
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
    valid_events = events if events is not None else {"schedule", "workflow_dispatch", "push"}
    if claims.get("event_name") not in valid_events:
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
            "mode": "jobs",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        threading.Thread(target=_collect, name="careerhunter-collector", daemon=True).start()
        return dict(_state)


@router.get("/internal/scan/receipt")
def scan_receipt(request: Request) -> dict[str, object]:
    """Read-only durable proof after a web process restart erases _state.

    This never accepts arbitrary SQL or an external database URL. A success
    receipt must be from a NEW completed jobs run, not the previous day's.
    """
    _require_github_oidc(request)
    from datetime import timedelta
    from sqlalchemy import create_engine, select
    from .database import runs
    from .private_site import _settings

    raw = request.query_params.get("since", "")
    try:
        since = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if since.tzinfo is None:
            raise ValueError("timestamp must have timezone")
        since = since.astimezone(timezone.utc)
        age = datetime.now(timezone.utc) - since
        if age < timedelta(seconds=-90) or age > timedelta(hours=3):
            raise ValueError("timestamp outside scan acceptance window")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid scan timestamp") from None

    url = _settings()[2]
    readonly = ({"connect_args": {"options": "-c default_transaction_read_only=on"}}
                if url.startswith("postgresql+psycopg://") else {})
    engine = create_engine(url, pool_pre_ping=True, **readonly)
    try:
        with engine.connect() as connection:
            record = connection.execute(
                select(runs.c.id, runs.c.started_at, runs.c.status,
                       runs.c.jobs_processed, runs.c.jobs_new)
                .where(runs.c.slot == "jobs", runs.c.started_at >= since.isoformat())
                .order_by(runs.c.id.desc()).limit(1)
            ).mappings().first()
    except Exception as exc:
        logger.warning("Durable scan receipt read failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Scan receipt unavailable") from None
    finally:
        engine.dispose()
    if record is None:
        return {"status": "absent"}
    return {
        "status": str(record["status"]),
        "run_id": int(record["id"]),
        "jobs_processed": int(record["jobs_processed"] or 0),
        "jobs_new": int(record["jobs_new"] or 0),
        "durable_receipt": True,
    }


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
        state = dict(_state)
    # A free-tier rolling deploy can reset this process-local status to idle
    # after the collector committed a successful PostgreSQL run. Recover only
    # a run begun AFTER this authenticated caller's specific scan request;
    # never infer success from a previous day's completed scan.
    since = request.query_params.get("since", "")
    if state.get("status") != "idle" or not since:
        return state
    try:
        origin = datetime.fromisoformat(since)
        if (origin.tzinfo is None or
                not 0 <= (datetime.now(timezone.utc) - origin).total_seconds() <= 35 * 60):
            raise ValueError("Invalid scan start time")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid scan start time") from None
    from sqlalchemy import select
    from .database import runs as runs_table
    from .private_site import _get_engine
    with _get_engine().connect() as connection:
        latest = connection.execute(
            select(runs_table.c.status, runs_table.c.jobs_processed,
                   runs_table.c.jobs_new, runs_table.c.started_at,
                   runs_table.c.finished_at)
            .where(runs_table.c.slot == "jobs")
            .where(runs_table.c.started_at >= since)
            .order_by(runs_table.c.id.desc()).limit(1)
        ).mappings().first()
    if latest:
        return {
            "status": latest["status"],
            "jobs_processed": int(latest["jobs_processed"] or 0),
            "jobs_new": int(latest["jobs_new"] or 0),
            "started_at": latest["started_at"],
            "finished_at": latest["finished_at"],
            "durable_recovery": True,
        }
    return state


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


@router.get("/internal/telegram/digest")
def telegram_digest(request: Request) -> dict[str, object]:
    """Private owner Telegram daily report, using signed GitHub workflow OIDC.

    Include ALL newly seen jobs, even weak/ineligible matches, with explicit
    suitability labels. Only public job metadata leaves Render. Neither CV
    details nor Bot credentials are transferred.
    """
    _require_github_oidc(
        request, workflow=TELEGRAM_REPORT_WORKFLOW,
        events=frozenset({"workflow_run"}),
    )
    from sqlalchemy import select
    from .database import jobs as jobs_table, runs as runs_table
    from .models import Job
    from .private_site import _get_engine
    from .job_quality import evaluate

    with _get_engine().connect() as connection:
        latest = connection.execute(
            select(runs_table).where(runs_table.c.slot == "jobs")
            .order_by(runs_table.c.id.desc()).limit(1)
        ).mappings().first()
        if not latest or latest["status"] != "success":
            return {"status": "no_successful_scan", "items": []}

        # First observed during the most recent successful scan. A previous
        # status="seen" is not a new discovery even when rescored.
        rows = connection.execute(
            select(jobs_table.c.payload)
            .where(jobs_table.c.first_seen_at >= latest["started_at"])
            .where(jobs_table.c.closed_at.is_(None))
            .order_by(jobs_table.c.first_seen_at.desc())
            .limit(2500)
        ).scalars().all()

    try:
        threshold = max(0, min(100, int(os.getenv("TELEGRAM_MIN_SCORE", "75"))))
    except ValueError:
        threshold = 75
    new_jobs = {}
    for raw in rows:
        job = Job.model_validate_json(raw)
        if job.status == "new":
            new_jobs[(job.source, job.job_id)] = job
    try:
        minimum = max(55, min(85, int(os.getenv("TELEGRAM_ROLE_GATE_MIN_SCORE", "60"))))
    except ValueError:
        minimum = 60
    selected = []
    discarded = {}
    for job in new_jobs.values():
        meta = {
            "title": job.title, "location": job.location,
            "description": job.description[:12000],
            "skills": job.skills_required,
            "score": job.match_score or 0,
            "level": job.experience_level,
            "eligibility": job.eligibility_status,
        }
        permitted, reason = evaluate(meta, minimum=minimum)
        if permitted:
            selected.append(job)
        else:
            discarded[reason] = discarded.get(reason, 0) + 1
    ordered = sorted(
        selected,
        key=lambda j: ((j.match_score or 0), j.match_method == "llm"),
        reverse=True,
    )
    strong = sum(
        1 for j in ordered
        if (j.match_score or 0) >= threshold
        and j.eligibility_status != "ineligible"
        and j.experience_level != "senior"
    )
    items = [{
        "title": job.title[:90],
        "company": job.company[:70],
        "location": job.location[:70],
        "url": str(job.job_url),
        "score": int(job.match_score or 0),
        "method": job.match_method,
        "eligibility": job.eligibility_status,
        "level": job.experience_level,
    } for job in ordered[:200]]
    return {
        "status": "ready",
        "run_id": int(latest["id"]),
        "jobs_new": int(latest["jobs_new"] or 0),
        "strong_count": strong,
        "listed_count": len(ordered),
        "quality_rejected": len(new_jobs) - len(ordered),
        "quality_reasons": discarded,
        "threshold": threshold,
        "items": items,
    }


@router.get("/internal/followups/due")
def due_followups(request: Request) -> dict[str, object]:
    """Bounded, read-only public-job followup summary for one signed GH workflow.

    Never transfer email addresses, people, private notes, resume data or
    database credentials to GitHub Actions.
    """
    _require_github_oidc(
        request, workflow=FOLLOWUP_WORKFLOW,
        events=frozenset({"schedule", "workflow_dispatch"}),
    )
    from datetime import datetime, timezone
    from sqlalchemy import select
    from .database import followups as followups_table, opportunities as opportunities_table
    from .models import FollowUp, Opportunity
    from .private_site import _get_engine

    now = datetime.now(timezone.utc)
    # Bounded read; PostgreSQL connection is in read-only transaction mode.
    stmt = (
        select(followups_table.c.payload, opportunities_table.c.payload)
        .select_from(followups_table.join(
            opportunities_table,
            followups_table.c.opportunity_id == opportunities_table.c.opportunity_id,
        ))
        .where(followups_table.c.status == "pending")
        .order_by(followups_table.c.due_at.asc())
        .limit(500)
    )
    with _get_engine().connect() as connection:
        rows = connection.execute(stmt).all()
    due = []
    for raw_followup, raw_opportunity in rows:
        followup = FollowUp.model_validate_json(raw_followup)
        opportunity = Opportunity.model_validate_json(raw_opportunity)
        if followup.due_at.astimezone(timezone.utc) > now:
            continue
        if opportunity.status in {"closed", "rejected"}:
            continue
        # Only public job information, no original followup note or private person data.
        due.append({
            "title": opportunity.title[:90],
            "company": opportunity.company[:70],
            "job_url": str(opportunity.job_url) if opportunity.job_url else None,
            "due_at": followup.due_at.astimezone(timezone.utc).date().isoformat(),
        })
    return {"status": "ready", "due_count": len(due), "items": due[:10], "bounded": True}


@router.get("/internal/gmail/review-summary")
def gmail_review_summary(request: Request) -> dict[str, object]:
    """Gmail OAuth permission is read-only. Nothing personal leaves Render.

    This endpoint is an optional, *disabled by default* pilot. Only signed
    first-party main-branch scheduled or owner-dispatched workflow can read it.
    """
    _require_github_oidc(
        request, workflow=MAIL_REVIEW_WORKFLOW,
        events=frozenset({"schedule", "workflow_dispatch"}),
    )
    from .gmail_reader import configured, read_readonly

    if os.getenv("CAREERHUNTER_GMAIL_READONLY_ENABLED", "") != "true":
        return {"status": "disabled", "reason": "owner_opt_in_required"}
    if not configured():
        return {"status": "not_configured", "reason": "private_oauth_missing"}
    # No sender details, message bodies, subject lines, Gmail IDs or secret data.
    return read_readonly(max_results=20).as_dict()
