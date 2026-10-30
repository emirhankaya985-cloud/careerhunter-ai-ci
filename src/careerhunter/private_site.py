"""Private, read-only CareerHunter site. Never publishes exports or writes CRM data.

Start: uvicorn careerhunter.private_site:app --host 127.0.0.1 --port 8765
Deployment needs DASHBOARD_DATABASE_URL (prefer a SELECT-only PostgreSQL user),
DASHBOARD_PASSWORD and DASHBOARD_SESSION_SECRET. No default credentials exist.
"""
from __future__ import annotations

import hmac
import html
import hashlib
import logging
import os
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import Integer, cast, create_engine, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.url import make_url
from sqlalchemy.engine import Engine

from .database import DatabaseRepository, contacts, jobs, runs
from .models import Job
from .private_site_view import render_dashboard, render_login
from .scheduled_scan import router as scan_router
from .application_actions import router as application_router

logger = logging.getLogger(__name__)
SESSION_AGE = 12 * 60 * 60
MAX_LOGIN_ATTEMPTS = 10
LOGIN_WINDOW = 15 * 60
failed_logins: dict[str, list[float]] = {}


def _settings() -> tuple[str, str, str, bool]:
    password = os.environ.get("DASHBOARD_PASSWORD", "")
    secret = os.environ.get("DASHBOARD_SESSION_SECRET", "")
    database = os.environ.get("DASHBOARD_DATABASE_URL", "")
    secure = os.environ.get("DASHBOARD_SECURE_COOKIE", "true").lower() != "false"
    if len(password) < 16 or len(secret) < 32 or len(database) < 8:
        raise RuntimeError("DASHBOARD_PASSWORD (16+), DASHBOARD_SESSION_SECRET (32+) "
                           "and DASHBOARD_DATABASE_URL are required")
    if os.environ.get("RENDER") and not secure:
        raise RuntimeError("Secure cookies cannot be disabled in Render")
    if database.startswith("sqlite:///"):
        if os.environ.get("DASHBOARD_ALLOW_SQLITE_TEST") != "true":
            raise RuntimeError("SQLite requires explicit test-only opt-in")
        return password, secret, database, secure
    # SQLAlchemy's default PostgreSQL driver is psycopg2, not installed here.
    # Force the installed psycopg3 driver on both hosted URL variants.
    if database.startswith("postgres://"):
        database = "postgresql+psycopg://" + database[len("postgres://"):]
    elif database.startswith("postgresql://"):
        database = "postgresql+psycopg://" + database[len("postgresql://"):]
    if not database.startswith("postgresql+psycopg://"):
        raise RuntimeError("Dashboard must use a PostgreSQL read-only connection")
    url = make_url(database)
    if not url.host or not url.database or not url.username:
        raise RuntimeError("Dashboard PostgreSQL URL is missing connection fields")
    return password, secret, database, secure


def _cookie_name(secure: bool) -> str:
    return "__Host-careerhunter" if secure else "careerhunter_local"


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_settings()[1], salt="careerhunter-private-owner-session-v1")


def _credential_fingerprint(password: str, secret: str) -> str:
    """Invalidate old sessions when the site password is rotated."""
    return hmac.new(secret.encode(), password.encode(), hashlib.sha256).hexdigest()


def _authenticated(request: Request) -> bool:
    cookie = request.cookies.get(_cookie_name(_settings()[3]))
    if not cookie:
        return False
    try:
        value = _signer().loads(cookie, max_age=SESSION_AGE)
        if not isinstance(value, dict) or value.get("scope") != "owner":
            return False
        password, secret, _, _ = _settings()
        return hmac.compare_digest(
            str(value.get("credential_version", "")),
            _credential_fingerprint(password, secret),
        )
    except BadSignature:
        return False


def _bootstrap_fresh_schema_if_requested(database_url: str) -> None:
    """Explicit one-time setup for an entirely empty Render PostgreSQL database.

    Never migrate or write to an existing database. Disable the flag after setup.
    The normal dashboard engine remains read-only.
    """
    if os.environ.get("DASHBOARD_BOOTSTRAP_SCHEMA") != "true":
        return
    if not database_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Schema bootstrap requires PostgreSQL")
    from sqlalchemy import inspect, insert
    from .database import metadata, schema_versions, SCHEMA_VERSION
    from .models import utc_now

    bootstrap_engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with bootstrap_engine.begin() as connection:
            if inspect(connection).get_table_names():
                logger.info("Schema bootstrap skipped: database is not empty")
                return
            metadata.create_all(connection)
            connection.execute(insert(schema_versions).values(
                version=SCHEMA_VERSION, applied_at=utc_now().isoformat()
            ))
            logger.info("Fresh CareerHunter PostgreSQL schema initialized")
    finally:
        bootstrap_engine.dispose()


@lru_cache(maxsize=1)
def _get_engine() -> Engine:
    url = _settings()[2]
    # Intentionally do NOT call DatabaseRepository.__init__/initialize:
    # those methods create tables and write schema migration records.
    connect_args = ({"options": "-c default_transaction_read_only=on"}
                    if url.startswith("postgresql+psycopg://") else {})
    return create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=0,
                         connect_args=connect_args)


def _repo() -> DatabaseRepository:
    # Reuse existing bounded SELECT queries without running schema creation.
    repo = object.__new__(DatabaseRepository)
    repo.engine = _get_engine()
    return repo


def _job_rows(page: int, query: str, limit: int = 40,
              order: str = "fit") -> tuple[list[Job], bool]:
    stmt = select(jobs.c.payload)
    if order == "fit":
        # JSON is stored in TEXT for SQLite/PostgreSQL portability.
        # Extract scores inside SQL: paging must happen after sorting.
        if _get_engine().dialect.name == "postgresql":
            score = cast(func.jsonb_extract_path_text(
                cast(jobs.c.payload, JSONB), "match_score"), Integer)
        else:
            score = cast(func.json_extract(jobs.c.payload, "$.match_score"), Integer)
        stmt = stmt.order_by(score.desc().nullslast(), jobs.c.last_verified_at.desc())
    else:
        stmt = stmt.order_by(jobs.c.last_verified_at.desc())
    if query:
        escaped = (
            query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        stmt = stmt.where(or_(
            func.lower(jobs.c.company).like(pattern, escape="\\"),
            func.lower(jobs.c.title).like(pattern, escape="\\"),
            func.lower(jobs.c.location).like(pattern, escape="\\"),
        ))
    stmt = stmt.limit(limit + 1).offset((page - 1) * limit)
    with _get_engine().connect() as connection:
        values = connection.execute(stmt).scalars().all()
    return [Job.model_validate_json(value) for value in values[:limit]], len(values) > limit


def _panel_data(view: str, query: str, page: int, order: str = "fit") -> dict:
    repo = _repo()
    from datetime import timedelta
    from .models import utc_now

    since = utc_now() - timedelta(hours=24)
    summary = repo.aggregate_job_counts(since)
    groups = repo.aggregate_country_counts(since)
    # For larger installations, contacts can be paginated as well; current
    # project size is small enough to give the owner the full list.
    people = repo.list_contacts(limit=2000)
    countries = [
        {"code": code, "flag": flag, "name": name,
         "total": groups.get(name, {}).get("total", 0),
         "new": groups.get(name, {}).get("new_24h", 0)}
        for code, flag, name in (
            ("US", "🇺🇸", "United States"), ("GB", "🇬🇧", "United Kingdom"),
            ("AU", "🇦🇺", "Australia"), ("TR", "🇹🇷", "Türkiye"),
        )
    ]
    rows, next_page = _job_rows(page if view == "jobs" else 1,
                                query if view == "jobs" else "",
                                limit=40 if view == "jobs" else 8,
                                order=order if view == "jobs" else "recent") if view in {"jobs", "overview"} else ([], False)
    return {
        "view": view,
        "heading": {"overview": "Kariyer kontrol merkezi", "jobs": "İş fırsatları",
                    "people": "Kişiler ve mesaj taslakları",
                    "applications": "Başvurular ve takipler"}[view],
        "subtitle": {"overview": "Tüm ilanları, yeni fırsatları ve kişi kayıtlarını tek yerden izle.",
                     "jobs": "Canlı veritabanından listelenen iş ilanları. Başvuru otomatik yapılmaz.",
                     "people": "Kişileri, kaynaklarını ve gönderilmeyi bekleyen taslaklarını incele.",
                     "applications": "Yalnızca kanıtlı manuel başvurular ve takip kayıtları."}[view],
        "metrics": {"total": summary["total"], "new": summary["new_24h"],
                    "people": len(people),
                    "drafts": sum(bool(p.message_variant_a or p.message_variant_a_tr) for p in people)},
        "countries": countries, "people": people if view == "people" else [],
        "applications": repo.list_opportunities(limit=300) if view == "applications" else [],
        "followups": repo.list_followups(pending_only=True, limit=300)
                     if view == "applications" else [],
        "latest": repo.latest_run() if view == "overview" else None,
        "job_rows": rows, "has_next": next_page, "page": page, "query": query,
        "sort": order,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = _settings()  # Fail closed if secrets are absent.
    _bootstrap_fresh_schema_if_requested(settings[2])
    yield
    if _get_engine.cache_info().currsize:
        _get_engine().dispose()
        _get_engine.cache_clear()


app = FastAPI(title="CareerHunter Private Dashboard", docs_url=None,
              redoc_url=None, openapi_url=None, lifespan=lifespan)


app.include_router(scan_router)
app.include_router(application_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    if _settings()[3]:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/healthz")
def health() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/readyz")
def ready() -> PlainTextResponse:
    """Readiness proves the configured database and minimum schema are readable."""
    try:
        with _get_engine().connect() as connection:
            connection.execute(select(func.count()).select_from(jobs)).scalar_one()
            connection.execute(select(func.count()).select_from(contacts)).scalar_one()
            connection.execute(select(func.count()).select_from(runs)).scalar_one()
    except Exception as exc:
        logger.warning("Dashboard readiness failed (%s)", type(exc).__name__)
        return PlainTextResponse("unavailable", status_code=503)
    return PlainTextResponse("ready")


@app.get("/robots.txt")
def robots() -> PlainTextResponse:
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if _authenticated(request):
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(render_login())


@app.post("/login")
async def login(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    failures = [t for t in failed_logins.get(ip, []) if now - t < LOGIN_WINDOW]
    if len(failures) >= MAX_LOGIN_ATTEMPTS:
        return HTMLResponse(render_login("Çok fazla deneme. Daha sonra tekrar dene."), status_code=429)
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        return PlainTextResponse("Unsupported login form", status_code=415)
    # Chunked requests can omit Content-Length; enforce the limit while reading.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 2048:
            return PlainTextResponse("Request too large", status_code=413)
    password = parse_qs(body.decode("utf-8", errors="replace")).get("password", [""])[0]
    expected, _, _, secure = _settings()
    if not hmac.compare_digest(password.encode(), expected.encode()):
        failures.append(now)
        failed_logins[ip] = failures
        return HTMLResponse(render_login("Şifre hatalı, tekrar dene."), status_code=401)
    failed_logins.pop(ip, None)
    response = RedirectResponse("/", status_code=303)
    value = _signer().dumps({
        "scope": "owner",
        "credential_version": _credential_fingerprint(expected, _settings()[1]),
    })
    response.set_cookie(_cookie_name(secure), value, max_age=SESSION_AGE, path="/",
                        secure=secure, httponly=True, samesite="strict")
    return response


@app.post("/logout")
def logout(request: Request):
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(_cookie_name(_settings()[3]), path="/")
    return response


@app.get("/telegram/setup", response_class=HTMLResponse)
def telegram_setup(request: Request):
    """Owner-only Chat ID setup page; never shows or stores a bot token."""
    if not _authenticated(request):
        return RedirectResponse("/login", status_code=303)
    from .notifications.telegram import recent_private_start_chats

    has_token = bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
    items = recent_private_start_chats() if has_token else []
    if not has_token:
        body = ("<p>1. Render Environment alanına TELEGRAM_BOT_TOKEN ekle.</p>"
                "<p>2. Telegram botuna /start yaz ve bu sayfayı yenile.</p>")
    elif not items:
        body = ("<p>Botuna Telegram uygulamasında /start yaz.</p>"
                "<p>Ardından bu sayfayı yenile. Telegram, bekleyen /start "
                "mesajlarını 24 saat kadar saklar.</p>")
    else:
        rows = "".join(
            "<li><strong>" + html.escape(display) + "</strong>: "
            "<code>" + str(chat_id) + "</code></li>"
            for chat_id, display in items
        )
        body = (
            "<p>Botu başlattığın sohbeti seç. Aşağıdaki ID'yi kopyala ve Render "
            "Environment içinde <code>TELEGRAM_CHAT_ID</code> olarak kaydet:</p>"
            "<ul>" + rows + "</ul>"
        )
    content = (
        "<!doctype html><html lang='tr'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>CareerHunter Telegram kurulumu</title>"
        "<style>body{font:16px system-ui;max-width:620px;margin:50px auto;"
        "padding:0 20px;background:#111827;color:#f9fafb;line-height:1.7}"
        "code{background:#374151;padding:4px 7px;border-radius:6px}"
        "a{color:#93c5fd}</style>"
        "<h1>📲 CareerHunter Telegram bağlantısı</h1>"
        + body + "<p><a href='/'>← Kariyer paneline dön</a></p></html>"
    )
    return HTMLResponse(content)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if not _authenticated(request):
        return RedirectResponse("/login", status_code=303)
    view = request.query_params.get("view", "overview")
    if view not in {"overview", "jobs", "people", "applications"}:
        view = "overview"
    q = request.query_params.get("q", "")[:80].strip()
    try:
        page = min(max(int(request.query_params.get("page", "1")), 1), 1000)
    except ValueError:
        page = 1
    order = request.query_params.get("sort", "fit")
    if order not in {"fit", "recent"}:
        order = "fit"
    try:
        return HTMLResponse(render_dashboard(**_panel_data(view, q, page, order)))
    except Exception as exc:
        # Never disclose DB URLs, SQL or person records to the browser.
        logger.error("Owner dashboard query failed (%s)", type(exc).__name__)
        return HTMLResponse(
            "<h1>Veri kaynağına bağlanılamadı.</h1><p>Biraz sonra tekrar dene.</p>",
            status_code=503,
        )
