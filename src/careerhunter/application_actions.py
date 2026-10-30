"""Owner-authenticated, CSRF-protected manual application record API.

Disabled without a separate least-privilege CRM writer DSN. Does not submit
any job application, CV, email, or LinkedIn request. Dashboard SQL stays
read-only; this is an explicitly configured separate write channel.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
        if (os.environ.get("CAREERHUNTER_CRM_SQLITE_TEST") != "true"
                or os.environ.get("RENDER")):
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



@router.get("/applications/new", response_class=HTMLResponse)
def owner_application_form(request: Request):
    """A no-JS, owner-only form; does not submit an external application."""
    _require_owner(request)
    source = request.query_params.get("source", "")
    job_id = request.query_params.get("job_id", "")
    if (source not in _SOURCES or not 1 <= len(job_id) <= 160
            or len(job_id.split()) != 1):
        raise HTTPException(422, "Invalid job identity")
    from .private_site import _repo
    item = _repo().get_job(source, job_id)
    if item is None:
        raise HTTPException(404, "Job not found")
    csrf = _signer().dumps({"session": _cookie_binding(request)})
    escaped = {name: html.escape(value, quote=True)
               for name, value in {"title": item.title, "company": item.company,
                                   "source": source, "job_id": job_id, "csrf": csrf}.items()}
    document = (
        '<!doctype html><html lang="tr"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Başvuru kaydı · CareerHunter</title>'
        '<style>body{background:#101927;color:#f4f7ff;font:16px system-ui;'
        'max-width:650px;margin:40px auto;padding:20px;line-height:1.6}'
        'input,select,textarea{display:block;margin:8px 0 18px;max-width:100%;'
        'font:inherit;padding:9px}button{padding:12px 18px;font:inherit}'
        'a{color:#9de8cf}label{font-weight:650}</style>'
        '<h1>Manuel başvuru kaydı</h1>'
        '<p>Bu form yalnızca gerçekleşmiş işlemleri kaydeder. İşverene '
        'CV, mesaj veya otomatik başvuru GÖNDERMEZ.</p>'
        '<h2>' + escaped["title"] + ' — ' + escaped["company"] + '</h2>'
        '<form method="post" action="/applications/submit">'
        '<input type="hidden" name="source" value="' + escaped["source"] + '">'
        '<input type="hidden" name="job_id" value="' + escaped["job_id"] + '">'
        '<input type="hidden" name="csrf" value="' + escaped["csrf"] + '">'
        '<label for="status">Durum</label><select id="status" name="status">'
        '<option value="reviewed">Sadece inceledim</option>'
        '<option value="applied">İşverene kendim başvurdum</option>'
        '<option value="interview">Mülakat onayı aldım</option>'
        '<option value="offer">Teklif aldım</option>'
        '<option value="rejected">Ret yanıtı aldım</option>'
        '<option value="closed">Başvuruyu kapattım</option></select>'
        '<label><input type="checkbox" name="confirmed" value="true"> '
        'Seçtiğim gerçek dış olayı ben doğruluyorum</label>'
        '<label for="notes">Özel not (isteğe bağlı)</label>'
        '<textarea id="notes" name="notes" maxlength="300"></textarea>'
        '<button type="submit">Yalnızca kaydet</button></form>'
        '<p><a href="/?view=applications">← Başvuru takiplerine dön</a></p></html>'
    )
    return HTMLResponse(document)


@router.post("/applications/submit")
async def owner_application_submit(request: Request):
    """Browser form with signed session-bound CSRF and explicit human confirmation."""
    _require_owner(request)
    _check_origin(request)
    if request.headers.get("content-type", "").split(";")[0] != (
        "application/x-www-form-urlencoded"
    ):
        raise HTTPException(415, "Form encoding required")
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > 4096:
            raise HTTPException(413, "Form too large")
    values = parse_qs(payload.decode("utf-8", errors="replace"), keep_blank_values=True)
    token = values.get("csrf", [""])[0]
    try:
        signed = _signer().loads(token, max_age=1200)
    except (BadSignature, ValueError, TypeError):
        raise HTTPException(403, "Invalid CSRF token") from None
    if not isinstance(signed, dict) or not hmac.compare_digest(
        str(signed.get("session", "")), _cookie_binding(request)
    ):
        raise HTTPException(403, "Invalid CSRF session")
    data = ManualApplication.model_validate({
        "source": values.get("source", [""])[0],
        "job_id": values.get("job_id", [""])[0],
        "status": values.get("status", [""])[0],
        "confirm_manual_event": values.get("confirmed", [""])[0] == "true",
        "notes": values.get("notes", [""])[0],
    })
    if (data.source not in _SOURCES or data.status not in _STATUSES
            or len(data.job_id.split()) != 1):
        raise HTTPException(422, "Invalid job identity or status")
    if data.status != "reviewed" and not data.confirm_manual_event:
        raise HTTPException(422, "Real external event confirmation is required")
    engine = create_engine(_writer_url(), pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        repo = object.__new__(DatabaseRepository)
        repo.engine = engine
        job = repo.get_job(data.source, data.job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        record_manual_application(
            repo, job, data.status, confirmed=data.confirm_manual_event, notes=data.notes
        )
    finally:
        engine.dispose()
    return RedirectResponse("/?view=applications", status_code=303)
