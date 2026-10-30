"""Security and data-integrity regressions for the owner-only website."""
import pytest
from fastapi.testclient import TestClient

from careerhunter.database import SQLiteRepository
from careerhunter.models import Contact, Job
from careerhunter.private_site import app, _get_engine, failed_logins, _settings
from careerhunter.private_site_view import safe_external_href, render_dashboard
from pydantic import HttpUrl
from types import SimpleNamespace


@pytest.fixture
def private_client(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'private.db'}"
    repo = SQLiteRepository(tmp_path / "private.db")
    jobs = [Job(
        job_id=str(i), source="greenhouse", company="Example",
        title=f"Python Engineer {i}", location="United States",
        description="A remote Python engineering role.",
        job_url=f"https://jobs.example.test/{i}",
        source_url="https://jobs.example.test",
    ) for i in range(48)]
    repo.upsert_jobs(jobs)
    repo.upsert_contact(Contact(
        person_id="1", name="Test <script>alert(1)</script>", company="Example",
        role="Engineer", category="company_page",
        message_variant_a="Hello <img src=x onerror=alert(1)>",
        primary_source_url="https://example.test/team"
    ))
    monkeypatch.setenv("DASHBOARD_PASSWORD", "local-testing-secret-password-123")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "very-long-session-secret-for-tests-123456")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", url)
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("DASHBOARD_SECURE_COOKIE", "true")
    _get_engine.cache_clear()
    failed_logins.clear()
    try:
        with TestClient(app, base_url="https://testserver") as client:
            yield client, repo
    finally:
        _get_engine.cache_clear()
        repo.engine.dispose()


def test_all_private_data_requires_login(private_client):
    client, _ = private_client
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/login"
    assert client.get("/?view=jobs", follow_redirects=False).status_code == 303
    assert client.get("/?view=people", follow_redirects=False).status_code == 303
    assert "Test" not in client.get("/login").text
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/robots.txt").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_owner_login_browse_and_logout(private_client):
    client, repo = private_client
    wrong = client.post("/login", data={"password": "bad"}, follow_redirects=False)
    assert wrong.status_code == 401
    login = client.post("/login", data={"password": "local-testing-secret-password-123"},
                        follow_redirects=False)
    assert login.status_code == 303
    cookie = login.headers["set-cookie"]
    assert "__Host-careerhunter=" in cookie and "httponly" in cookie.lower()
    assert "secure" in cookie.lower() and "samesite=strict" in cookie.lower()

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "48" in dashboard.text
    assert "Kariyer kontrol merkezi" in dashboard.text
    assert dashboard.headers["cache-control"] == "no-store, private"
    assert dashboard.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in dashboard.headers["content-security-policy"]

    people = client.get("/?view=people")
    assert people.status_code == 200
    assert "Test &lt;script&gt;" in people.text
    assert "Hello &lt;img" in people.text
    assert '<script>alert(1)</script>' not in people.text
    assert "Hazır mesajı görüntüle" in people.text
    assert "Gönder" not in people.text

    jobs = client.get("/?view=jobs")
    assert jobs.status_code == 200
    assert jobs.text.count("İlana git ↗") == 40
    assert "Sonraki" in jobs.text
    page2 = client.get("/?view=jobs&page=2")
    assert page2.text.count("İlana git ↗") == 8
    assert client.get("/?view=jobs&q=nonexistent").text.count("İlana git ↗") == 0

    # Navigation does not write new records or drafts to the database.
    assert repo.aggregate_job_counts(__import__("careerhunter.models", fromlist=["utc_now"]).utc_now())[
        "total"
    ] == 48
    client.post("/logout", follow_redirects=False)
    assert client.get("/", follow_redirects=False).status_code == 303


def test_login_rate_limit(private_client):
    client, _ = private_client
    for _ in range(10):
        assert client.post("/login", data={"password": "wrong"}).status_code == 401
    assert client.post("/login", data={"password": "wrong"}).status_code == 429


def test_missing_credentials_fail_closed(monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "very-long-session-secret-for-tests-123456")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", "sqlite:////tmp/nonexistent.db")
    with pytest.raises(RuntimeError, match="DASHBOARD_PASSWORD"):
        with TestClient(app):
            pass


def test_site_never_falls_back_to_job_writer_database(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "local-testing-secret-password-123")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "very-long-session-secret-for-tests-123456")
    monkeypatch.delenv("DASHBOARD_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://writer:secret@db.example.com/prod")
    with pytest.raises(RuntimeError, match="DASHBOARD_DATABASE_URL"):
        _settings()


def test_postgresql_scheme_uses_installed_psycopg3(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "local-testing-secret-password-123")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "very-long-session-secret-for-tests-123456")
    for prefix in ("postgres://", "postgresql://", "postgresql+psycopg://"):
        monkeypatch.setenv("DASHBOARD_DATABASE_URL", prefix + "reader:secret@db.example.com/prod")
        assert _settings()[2].startswith("postgresql+psycopg://")


def test_sqlite_is_never_accidentally_enabled_in_public_server(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "local-testing-secret-password-123")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "very-long-session-secret-for-tests-123456")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", "sqlite:////tmp/unsafe.db")
    monkeypatch.delenv("DASHBOARD_ALLOW_SQLITE_TEST", raising=False)
    with pytest.raises(RuntimeError, match="test-only"):
        _settings()


def test_render_cannot_disable_secure_cookies(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "local-testing-secret-password-123")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "very-long-session-secret-for-tests-123456")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", "postgresql://reader:secret@db.example.com/prod")
    monkeypatch.setenv("DASHBOARD_SECURE_COOKIE", "false")
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(RuntimeError, match="Secure cookies"):
        _settings()


def test_password_rotation_invalidates_previous_session(private_client, monkeypatch):
    client, _ = private_client
    assert client.post("/login", data={"password": "local-testing-secret-password-123"}).status_code == 200
    assert client.get("/").status_code == 200
    monkeypatch.setenv("DASHBOARD_PASSWORD", "a-replacement-strong-password-123")
    assert client.get("/", follow_redirects=False).status_code == 303


def test_bounded_login_payload_without_content_length(private_client):
    client, _ = private_client
    oversized = "password=" + "x" * 2100
    reply = client.post(
        "/login", content=oversized.encode(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert reply.status_code == 413
    invalid_type = client.post("/login", json={"password": "secret"})
    assert invalid_type.status_code == 415


def test_literal_wildcards_not_widened_in_search(private_client):
    client, _ = private_client
    client.post("/login", data={"password": "local-testing-secret-password-123"})
    assert client.get("/?view=jobs&q=%25").text.count("İlana git ↗") == 0
    assert client.get("/?view=jobs&q=_").text.count("İlana git ↗") == 0


def test_db_readiness_detects_missing_tables(private_client):
    client, repo = private_client
    from sqlalchemy import text
    with repo.engine.begin() as connection:
        connection.execute(text("DROP TABLE contacts"))
    response = client.get("/readyz")
    assert response.status_code == 503
    assert "unavailable" in response.text

def test_external_link_filter_accepts_pydantic_http_url():
    """Source URLs are Pydantic HttpUrl, not Python str."""
    valid = HttpUrl("https://example.test/job/1")
    assert safe_external_href(valid) == str(valid)
    assert safe_external_href("http://example.test/profile") == "http://example.test/profile"


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "https://u:p@example.test/secret",
    "//example.test/protocol-relative",
    "https://example.test/hello\\nworld",
    "",
    None,
])
def test_external_link_filter_rejects_unsafe_urls(url):
    assert safe_external_href(url) == "#"


def test_person_template_escapes_unsafe_contact_links():
    person = SimpleNamespace(
        name="Untrusted", status="unverified", role="Engineer", company="Acme",
        email_public=None, linkedin_url="javascript:alert(1)",
        primary_source_url="data:text/html,evil",
        message_variant_a="", message_variant_a_tr="",
    )
    html = render_dashboard(
        heading="People", subtitle="Test", view="people", people=[person],
        metrics={}, countries=[], latest=None, job_rows=[], query="", page=1,
        has_next=False,
    )
    assert 'href="javascript:' not in html
    assert 'href="data:' not in html
    assert html.count('href="#"') >= 2



def test_bootstrap_only_runs_with_explicit_flag_and_empty_database(tmp_path, monkeypatch):
    import careerhunter.private_site as site
    from sqlalchemy import create_engine, inspect, text

    db_path = tmp_path / "fresh-schema.db"
    sqlite_url = f"sqlite:///{db_path}"
    # The fake engine confines the test to a local SQLite fixture. Production
    # bootstrap rejects SQLite and only accepts an explicitly configured PG URL.
    monkeypatch.setattr(site, "create_engine", lambda _url, **_kw: create_engine(sqlite_url))
    monkeypatch.delenv("DASHBOARD_BOOTSTRAP_SCHEMA", raising=False)
    site._bootstrap_fresh_schema_if_requested("postgresql+psycopg://test-user@db/test")
    assert not db_path.exists()

    monkeypatch.setenv("DASHBOARD_BOOTSTRAP_SCHEMA", "true")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        site._bootstrap_fresh_schema_if_requested(sqlite_url)

    site._bootstrap_fresh_schema_if_requested("postgresql+psycopg://test-user@db/test")
    engine = create_engine(sqlite_url)
    try:
        with engine.begin() as con:
            tables = set(inspect(con).get_table_names())
            assert {"jobs", "contacts", "runs", "schema_versions"} <= tables
            assert con.execute(text("SELECT version FROM schema_versions")).scalar_one() == 3
            con.execute(text("CREATE TABLE manually_added (id INTEGER)"))
        site._bootstrap_fresh_schema_if_requested("postgresql+psycopg://test-user@db/test")
        with engine.connect() as con:
            assert "manually_added" in inspect(con).get_table_names()
            assert con.execute(text("SELECT COUNT(*) FROM schema_versions")).scalar_one() == 1
    finally:
        engine.dispose()


def test_postgres_dashboard_connections_are_transaction_read_only(monkeypatch):
    import careerhunter.private_site as site

    calls = []
    marker = object()
    monkeypatch.setattr(site, "_settings", lambda: (
        "valid-16-character-password", "long-session-secret-placeholder",
        "postgresql+psycopg://reader:password@host/db", True
    ))
    monkeypatch.setattr(site, "create_engine", lambda url, **kwargs:
                        calls.append((url, kwargs)) or marker)
    site._get_engine.cache_clear()
    try:
        assert site._get_engine() is marker
        assert calls[0][1]["connect_args"]["options"] == "-c default_transaction_read_only=on"
    finally:
        site._get_engine.cache_clear()


def test_owner_only_application_and_evidence_views(private_client):
    from datetime import timedelta
    from careerhunter.models import Opportunity, FollowUp, utc_now
    client, repo = private_client
    repo.upsert_opportunity(Opportunity(
        opportunity_id="greenhouse:0",
        title="Junior Python Developer",
        company="Example",
        status="applied",
        applied_at=utc_now(),
    ))
    repo.upsert_followup(FollowUp(
        followup_id="manual-followup:greenhouse:0",
        opportunity_id="greenhouse:0",
        due_at=utc_now() + timedelta(days=7),
        note="Check reply before reaching out",
    ))
    assert client.get("/?view=applications", follow_redirects=False).status_code == 303
    client.post("/login", data={"password": "local-testing-secret-password-123"})
    response = client.get("/?view=applications")
    assert response.status_code == 200
    assert "Junior Python Developer" in response.text
    assert "Check reply before reaching out" in response.text
    assert "Başvurular ve takipler" in response.text
    assert "salt okunurdur" in response.text
    page = client.get("/?view=jobs")
    assert "Henüz doğrulanmadı" in page.text
    assert "Başvurular ve Takipler" in page.text
