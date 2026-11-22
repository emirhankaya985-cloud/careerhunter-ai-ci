"""Owner-only encrypted storage for the candidate's language-specific CV PDFs.

The vault never places plaintext CV bytes in database rows, logs, HTML or
workflow artifacts. Production requires a separate PostgreSQL writer and an
AES-256 key stored only in Render's private environment.
"""
from __future__ import annotations

import base64
import hashlib
import html
import hmac
import os
from datetime import datetime, timezone

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import Column, LargeBinary, MetaData, String, Table, create_engine, inspect, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine.url import make_url

router = APIRouter()
metadata = MetaData()
vault = Table(
    "careerhunter_cv_vault", metadata,
    Column("language", String(2), primary_key=True),
    Column("nonce", LargeBinary(12), nullable=False),
    Column("ciphertext", LargeBinary, nullable=False),
    Column("integrity_mac", String(64), nullable=False),
    Column("size_bytes", String(20), nullable=False),
    Column("updated_at", String(40), nullable=False),
)
LANGUAGES = frozenset({"tr", "en"})
MAX_CV_BYTES = 10 * 1024 * 1024
PREFLIGHT_WORKFLOW = (
    "emirhankaya985-cloud/careerhunter-ai-ci/"
    ".github/workflows/cv-vault-preflight.yml@refs/heads/main"
)


def _owner(request: Request) -> str:
    from .application_actions import _cookie_binding, _require_owner
    _require_owner(request)
    return _cookie_binding(request)


def _signer() -> URLSafeTimedSerializer:
    from .private_site import _settings
    return URLSafeTimedSerializer(_settings()[1], salt="careerhunter-cv-vault-csrf-v1")


def _key() -> bytes:
    value = os.getenv("CAREERHUNTER_CV_VAULT_KEY", "").strip()
    try:
        key = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError):
        key = b""
    if len(key) != 32:
        raise HTTPException(503, "CV vault encryption key is not configured")
    return key


def _engine():
    from .application_actions import _writer_url
    url = _writer_url()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    parsed = make_url(url)
    backend = parsed.get_backend_name()
    if backend == "postgresql":
        if not parsed.host or not parsed.username or not parsed.database:
            raise HTTPException(503, "CV vault database writer is invalid")
    elif backend != "sqlite":
        raise HTTPException(503, "CV vault requires PostgreSQL")
    engine = create_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        metadata.create_all(engine, tables=[vault])
    except Exception:
        engine.dispose()
        raise HTTPException(503, "CV vault storage is unavailable") from None
    return engine


@router.get("/internal/cv-vault/preflight")
def cv_vault_preflight(request: Request) -> dict[str, object]:
    """Verify the production writer target without owner login or secret output."""
    from .scheduled_scan import _require_github_oidc

    _require_github_oidc(
        request, workflow=PREFLIGHT_WORKFLOW,
        events=frozenset({"workflow_dispatch", "push"}),
    )
    from .application_actions import _writer_url

    writer_matches = False
    writer_database = "other"
    vault_table_exists = False
    writer_reachable = False
    encryption_key_configured = False
    try:
        _key()
        encryption_key_configured = True
    except HTTPException:
        pass
    try:
        url = _writer_url()
        parsed = make_url(url)
        writer_matches = (
            parsed.get_backend_name() == "postgresql"
            and parsed.database == "careerhunter_live"
            and bool(parsed.host and parsed.host.lower().endswith(".neon.tech"))
        )
        if parsed.database in {"careerhunter_live", "careerhunter_ai_db"}:
            writer_database = parsed.database
        if writer_matches:
            engine = create_engine(
                url, pool_pre_ping=True, pool_size=1, max_overflow=0,
                connect_args={"connect_timeout": 5},
            )
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                    writer_reachable = True
                    vault_table_exists = inspect(connection).has_table(vault.name)
            finally:
                engine.dispose()
    except Exception:
        # Deliberately return only fixed readiness fields, never driver errors.
        pass
    ready = (writer_matches and writer_reachable and vault_table_exists
             and encryption_key_configured)
    return {
        "status": "ready" if ready else "blocked",
        "writer_database": writer_database,
        "writer_matches_selected_neon": writer_matches,
        "writer_reachable": writer_reachable,
        "vault_table_exists": vault_table_exists,
        "encryption_key_configured": encryption_key_configured,
        "cv_upload_performed": False,
    }


def _check_csrf(request: Request, session: str, token: str | None = None) -> None:
    from .application_actions import _check_origin
    _check_origin(request)
    try:
        csrf = token if token is not None else request.headers.get("x-csrf-token", "")
        claims = _signer().loads(csrf, max_age=1200)
    except (BadSignature, ValueError, TypeError):
        raise HTTPException(403, "Invalid CV vault token") from None
    if not isinstance(claims, dict) or claims.get("session") != session:
        raise HTTPException(403, "Invalid CV vault session")


@router.get("/internal/owner/cv/csrf")
def cv_vault_csrf(request: Request) -> dict[str, str]:
    session = _owner(request)
    return {"csrf_token": _signer().dumps({"session": session})}


@router.get("/internal/owner/cv/status")
def cv_vault_status(request: Request) -> dict[str, object]:
    _owner(request)
    _key()
    engine = _engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(select(vault.c.language, vault.c.size_bytes,
                                      vault.c.updated_at).order_by(vault.c.language)).all()
        stored = {row.language: {"uploaded": True, "size_bytes": int(row.size_bytes),
                                 "updated_at": row.updated_at} for row in rows}
        return {"status": "ready", "encrypted_at_rest": True,
                "cvs": {lang: stored.get(lang, {"uploaded": False})
                        for lang in sorted(LANGUAGES)}}
    finally:
        engine.dispose()


@router.get("/internal/owner/cv/manage", response_class=HTMLResponse)
def cv_vault_manage(request: Request) -> Response:
    """Simple owner-only browser form for uploading the final CV PDFs."""
    from .private_site import _authenticated
    if not _authenticated(request):
        return RedirectResponse("/login", status_code=303)
    session = _owner(request)
    token = html.escape(_signer().dumps({"session": session}), quote=True)
    try:
        _key()
        engine = _engine()
        try:
            with engine.connect() as conn:
                rows = conn.execute(select(vault.c.language, vault.c.updated_at)).all()
            stored = {row.language: row.updated_at for row in rows}
            status = ""
        finally:
            engine.dispose()
    except (HTTPException, RuntimeError):
        stored = {}
        status = "CV kasası hazır değil. Render ayarlarını kontrol etmek gerekiyor."
    message = request.query_params.get("status", "")
    if message == "stored":
        language = request.query_params.get("language", "")
        status = f"{html.escape(language.upper())} CV şifreli kasaya yüklendi."
    sections = []
    for language, label in (("en", "İngilizce CV"), ("tr", "Türkçe CV")):
        uploaded = (f"Yüklü • {html.escape(stored[language])}" if language in stored
                    else "Henüz yüklenmedi")
        sections.append(
            f"<section><h2>{label}</h2><p>{uploaded}</p>"
            f"<form method='post' action='/internal/owner/cv/manage/{language}' "
            "enctype='multipart/form-data'>"
            f"<input type='hidden' name='csrf' value='{token}'>"
            "<label>PDF dosyası <input type='file' name='cv' accept='application/pdf' "
            "required></label><button type='submit'>Şifreli kasaya yükle</button></form></section>"
        )
    content = (
        "<!doctype html><html lang='tr'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>CareerHunter CV kasası</title>"
        "<style>body{font:16px system-ui;max-width:680px;margin:40px auto;padding:0 20px;"
        "background:#111827;color:#f9fafb;line-height:1.6}section{border:1px solid #4b5563;"
        "border-radius:12px;padding:16px;margin:16px 0}button{margin:12px 0;padding:10px 14px;"
        "border:0;border-radius:8px;background:#2563eb;color:white}input{display:block;margin-top:8px}"
        "a{color:#93c5fd}</style><h1>CV kasası</h1>"
        "<p>PDF dosyan şifrelenerek saklanır. Bu sayfa tek başına otomatik e-posta gönderimini "
        "açmaz; otomasyon ayrıca bir defalık şablon onayı ve Gmail yetkisi gerektirir.</p>"
        f"<p role='status'>{status}</p>" + "".join(sections)
        + "<p><a href='/'>Kariyer paneline dön</a></p></html>"
    )
    return HTMLResponse(content)


@router.post("/internal/owner/cv/manage/{language}")
async def cv_vault_manage_upload(language: str, request: Request) -> RedirectResponse:
    """Owner-authenticated multipart form endpoint, protected by origin and CSRF."""
    session = _owner(request)
    if language not in LANGUAGES:
        raise HTTPException(404, "CV language not supported")
    try:
        form = await request.form(max_files=1, max_fields=2, max_part_size=MAX_CV_BYTES)
    except (ValueError, RuntimeError):
        raise HTTPException(422, "Invalid CV upload form") from None
    _check_csrf(request, session, token=str(form.get("csrf", "")))
    upload = form.get("cv")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(422, "PDF required")
    if getattr(upload, "content_type", "") != "application/pdf":
        raise HTTPException(415, "PDF required")
    plain = await upload.read(MAX_CV_BYTES + 1)
    if len(plain) > MAX_CV_BYTES:
        raise HTTPException(413, "CV exceeds 10 MiB")
    _store_cv(language, plain)
    return RedirectResponse(
        f"/internal/owner/cv/manage?status=stored&language={language}", status_code=303
    )


@router.put("/internal/owner/cv/{language}")
async def upload_cv(language: str, request: Request) -> dict[str, object]:
    session = _owner(request)
    _check_csrf(request, session)
    if language not in LANGUAGES:
        raise HTTPException(404, "CV language not supported")
    if request.headers.get("content-type", "").split(";")[0].lower() != "application/pdf":
        raise HTTPException(415, "PDF required")
    chunks = bytearray()
    async for part in request.stream():
        chunks.extend(part)
        if len(chunks) > MAX_CV_BYTES:
            raise HTTPException(413, "CV exceeds 10 MiB")
    plain = bytes(chunks)
    return _store_cv(language, plain)


def _store_cv(language: str, plain: bytes) -> dict[str, object]:
    """Encrypt and store a validated PDF. Shared by API and owner form."""
    if language not in LANGUAGES:
        raise ValueError("unsupported_cv_language")
    if len(plain) < 8 or len(plain) > MAX_CV_BYTES or not plain.startswith(b"%PDF-") or b"%%EOF" not in plain[-2048:]:
        raise HTTPException(422, "Invalid PDF")
    key = _key()
    nonce = os.urandom(12)
    aad = f"careerhunter-cv-vault:v1:{language}".encode()
    ciphertext = AESGCM(key).encrypt(nonce, plain, aad)
    record = {"language": language, "nonce": nonce, "ciphertext": ciphertext,
              "integrity_mac": hmac.new(key, plain, hashlib.sha256).hexdigest(),
              "size_bytes": str(len(plain)),
              "updated_at": datetime.now(timezone.utc).isoformat()}
    engine = _engine()
    try:
        with engine.begin() as conn:
            statement = (pg_insert(vault) if engine.dialect.name == "postgresql"
                         else sqlite_insert(vault)).values(**record)
            conn.execute(statement.on_conflict_do_update(
                index_elements=[vault.c.language],
                set_={name: getattr(statement.excluded, name) for name in record
                      if name != "language"},
            ))
    finally:
        engine.dispose()
    return {"status": "stored", "language": language,
            "size_bytes": len(plain), "encrypted_at_rest": True}


@router.get("/internal/owner/cv/{language}")
def download_cv(language: str, request: Request) -> Response:
    _owner(request)
    if language not in LANGUAGES:
        raise HTTPException(404, "CV language not supported")
    plain, filename = load_cv_attachment(language)
    return Response(
        plain, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "Cache-Control": "no-store, private", "Pragma": "no-cache"},
    )


def load_cv_attachment(language: str) -> tuple[bytes, str]:
    """Load and integrity-check an encrypted CV for internal send operations."""
    if language not in LANGUAGES:
        raise ValueError("unsupported_cv_language")
    key = _key()
    engine = _engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(select(vault).where(vault.c.language == language)).mappings().first()
    finally:
        engine.dispose()
    if row is None:
        raise LookupError("cv_not_uploaded")
    try:
        plain = AESGCM(key).decrypt(
            row["nonce"], row["ciphertext"],
            f"careerhunter-cv-vault:v1:{language}".encode(),
        )
    except InvalidTag:
        raise RuntimeError("cv_vault_key_mismatch") from None
    if not hmac.compare_digest(
        hmac.new(key, plain, hashlib.sha256).hexdigest(), row["integrity_mac"]
    ):
        raise RuntimeError("cv_vault_integrity_failed")
    return plain, f"careerhunter_cv_{language}.pdf"


@router.delete("/internal/owner/cv/{language}")
def delete_cv(language: str, request: Request) -> dict[str, str]:
    session = _owner(request)
    _check_csrf(request, session)
    if language not in LANGUAGES:
        raise HTTPException(404, "CV language not supported")
    engine = _engine()
    try:
        from sqlalchemy import delete
        with engine.begin() as conn:
            conn.execute(delete(vault).where(vault.c.language == language))
    finally:
        engine.dispose()
    return {"status": "deleted", "language": language}

