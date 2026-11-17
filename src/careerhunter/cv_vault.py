"""Owner-only encrypted storage for the candidate's language-specific CV PDFs.

The vault never places plaintext CV bytes in database rows, logs, HTML or
workflow artifacts. Production requires a separate PostgreSQL writer and an
AES-256 key stored only in Render's private environment.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timezone

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import Column, LargeBinary, MetaData, String, Table, create_engine, select
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


def _check_csrf(request: Request, session: str) -> None:
    from .application_actions import _check_origin
    _check_origin(request)
    try:
        claims = _signer().loads(request.headers.get("x-csrf-token", ""), max_age=1200)
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


@router.put("/internal/owner/cv/{language}")
async def upload_cv(language: str, request: Request) -> dict[str, object]:
    session = _owner(request)
    _check_csrf(request, session)
    if language not in LANGUAGES:
        raise HTTPException(404, "CV language not supported")
    if request.headers.get("content-type", "").split(";")[0].lower() != "application/pdf":
        raise HTTPException(415, "PDF required")
    key = _key()
    chunks = bytearray()
    async for part in request.stream():
        chunks.extend(part)
        if len(chunks) > MAX_CV_BYTES:
            raise HTTPException(413, "CV exceeds 10 MiB")
    plain = bytes(chunks)
    if len(plain) < 8 or not plain.startswith(b"%PDF-") or b"%%EOF" not in plain[-2048:]:
        raise HTTPException(422, "Invalid PDF file")
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
    key = _key()
    engine = _engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(select(vault).where(vault.c.language == language)).mappings().first()
    finally:
        engine.dispose()
    if row is None:
        raise HTTPException(404, "CV is not uploaded")
    try:
        plain = AESGCM(key).decrypt(
            row["nonce"], row["ciphertext"],
            f"careerhunter-cv-vault:v1:{language}".encode(),
        )
    except InvalidTag:
        raise HTTPException(503, "CV vault key does not match stored files") from None
    if not hmac.compare_digest(
        hmac.new(key, plain, hashlib.sha256).hexdigest(), row["integrity_mac"]
    ):
        raise HTTPException(503, "CV vault integrity check failed")
    return Response(
        plain, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="careerhunter_cv_{language}.pdf"',
                 "Cache-Control": "no-store, private", "Pragma": "no-cache"},
    )


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
