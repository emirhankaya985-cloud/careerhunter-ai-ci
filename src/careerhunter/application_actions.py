"""Owner-authenticated, CSRF-protected manual application record API.

Disabled without a separate least-privilege CRM writer DSN. Does not submit
any job application, CV, email, or LinkedIn request. Dashboard SQL stays
read-only; this is an explicitly configured separate write channel.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url

from .database import DatabaseRepository
from .v2_workflow import record_manual_application

router = APIRouter()
_SOURCES = {"ashby", "lever", "greenhouse"}
_STATUSES = {"reviewed", "applied", "interview", "offer", "rejected", "closed"}


class ManualApplication(BaseModel):
    source: str = Field(min_length=1, max_length=20)
    job_id: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=20)
    confirm_manual_event: bool = False
    notes: str = Field(default="", max_length=300)
    proof_url: HttpUrl | None = None


def _require_owner(request: Request) -> None:
    from .private_site import _authenticated
    if not _authenticated(request):
        raise HTTPException(401, "Owner login required")


def _signer() -> URLSafeTimedSerializer:
    from .private_site import _settings
    return URLSafeTimedSerializer(
        _settings()[1], salt="careerhunter-owner-crm-csrf-v1"
    )


def _cookie_binding(request: Request) -> str:
    from .private_site import _cookie_name, _settings
    session = request.cookies.get(_cookie_name(_settings()[3]), "")
    return hashlib.sha256(session.encode("utf-8")).hexdigest()


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    parsed = urlsplit(origin)
    host = request.headers.get("host", "")
    if (parsed.scheme != "https" or parsed.netloc != host
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise HTTPException(403, "Invalid request origin")


def _writer_url() -> str:
    db_url = os.environ.get("CAREERHUNTER_CRM_DATABASE_URL", "").strip()
    if not db_url:
        raise HTTPException(503, "Manual CRM write channel is not configured")
    if db_url.startswith("postgres://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://"):]
    if db_url.startswith("sqlite:///"):
        if os.environ.get("CAREERHUNTER_CRM_SQLITE_TEST") != "true":
            raise HTTPException(503, "SQLite is permitted only in isolated tests")
    elif db_url.startswith("postgresql+psycopg://"):
        parsed = make_url(db_url)
        if not parsed.host or not parsed.username or not parsed.database:
            raise HTTPException(503, "Invalid CRM database configuration")
    else:
        raise HTTPException(503, "Unsupported CRM database configuration")
    return db_url


@router.get("/internal/owner/application-csrf")
def application_csrf(request: Request) -> dict[str, str]:
    _require_owner(request)
    return {"csrf_token": _signer().dumps({"session": _cookie_binding(request)})}


@router.post("/internal/owner/application")
async def application_record(request: Request) -> JSONResponse:
    _require_owner(request)
    _check_origin(request)
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "JSON required")
    token = request.headers.get("x-csrf-token", "")
    try:
        claims = _signer().loads(token, max_age=1200)
    except (BadSignature, ValueError, TypeError):
        raise HTTPException(403, "Invalid CSRF token") from None
    if not isinstance(claims, dict) or not hmac.compare_digest(
        str(claims.get("session", "")), _cookie_binding(request)
    ):
        raise HTTPException(403, "Invalid CSRF session")
    payload = bytearray()
    async for part in request.stream():
        payload.extend(part)
        if len(payload) > 4096:
            raise HTTPException(413, "Request is too large")
    try:
        data = ManualApplication.model_validate(json.loads(payload))
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid manual application record") from None
    if (data.source not in _SOURCES or data.status not in _STATUSES
            or len(data.job_id.split()) != 1):
        raise HTTPException(422, "Invalid job identity or status")
    if data.status != "reviewed" and not data.confirm_manual_event:
        raise HTTPException(422, "Real external event confirmation is required")

    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        # Crucially skip DatabaseRepository.__init__/initialize, which would
        # write schema_version or attempt DDL on a minimally privileged user.
        repo = object.__new__(DatabaseRepository)
        repo.engine = engine
        job = repo.get_job(data.source, data.job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        result = record_manual_application(
            repo, job, data.status, confirmed=data.confirm_manual_event,
            notes=data.notes, proof_url=str(data.proof_url) if data.proof_url else None
        )
        return JSONResponse({"status": "recorded", "opportunity_id": result.opportunity_id,
                             "application_status": result.status,
                             "external_application_sent": False})
    finally:
        engine.dispose()
