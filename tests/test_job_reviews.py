"""Owner review decisions are durable, CSRF protected, and separate from sends."""
import pytest
from fastapi.testclient import TestClient

from careerhunter.database import SQLiteRepository
from careerhunter.models import Job
from careerhunter.private_site import app, _get_engine, failed_logins


@pytest.fixture
def owner_client(tmp_path, monkeypatch):
    db_path = tmp_path / "job-review.sqlite"
    repo = SQLiteRepository(db_path)
    repo.upsert_jobs([Job(
        job_id="role-1", source="ashby", company="Example",
        title="Junior Python Developer", job_url="https://example.org/role-1",
        source_url="https://api.ashbyhq.com/posting-api/job-board/example",
    )])
    repo.engine.dispose()
    db_url = "sqlite:///" + str(db_path)
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-owner-passphrase-123456")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "fake-session-secret-123456789012345")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", db_url)
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("CAREERHUNTER_CRM_DATABASE_URL", db_url)
    monkeypatch.setenv("CAREERHUNTER_CRM_SQLITE_TEST", "true")
    monkeypatch.setenv("DASHBOARD_SECURE_COOKIE", "true")
    _get_engine.cache_clear()
    failed_logins.clear()
    try:
        with TestClient(app, base_url="https://testserver") as client:
            yield client, db_path
    finally:
        _get_engine.cache_clear()


def _login_and_csrf(client):
    assert client.post("/login", data={"password": "test-owner-passphrase-123456"}).status_code == 200
    return client.get("/internal/owner/job-review/csrf").json()["csrf_token"]


def _review(client, token, decision, *, origin="https://testserver"):
    return client.post(
        "/internal/owner/job-review",
        json={"source": "ashby", "job_id": "role-1", "decision": decision},
        headers={"Origin": origin, "X-CSRF-Token": token},
    )


def test_job_review_endpoint_requires_owner_and_csrf(owner_client):
    client, _ = owner_client
    assert client.get("/internal/owner/job-review/csrf").status_code == 401
    assert _review(client, "", "saved").status_code == 401
    token = _login_and_csrf(client)
    assert _review(client, "wrong", "saved").status_code == 403
    assert _review(client, token, "saved", origin="https://attacker.example").status_code == 403
    assert _review(client, token, "sent_email").status_code == 422


@pytest.mark.parametrize("decision", ["saved", "approved", "rejected"])
def test_owner_review_persists_and_is_idempotent_without_touching_opportunities(
    owner_client, decision
):
    client, db = owner_client
    token = _login_and_csrf(client)
    response = _review(client, token, decision)
    assert response.status_code == 200
    assert response.json()["decision"] == decision
    assert _review(client, token, decision).status_code == 200
    repo = SQLiteRepository(db)
    assert [item.decision for item in repo.list_job_reviews()] == [decision]
    assert repo.list_opportunities() == []


def test_review_survives_job_rescan_and_dashboard_shows_controls(owner_client):
    client, db = owner_client
    token = _login_and_csrf(client)
    assert _review(client, token, "saved").status_code == 200
    repo = SQLiteRepository(db)
    job = repo.get_job("ashby", "role-1")
    job.title = "Junior Python Developer II"
    repo.upsert_jobs([job])
    repo.engine.dispose()

    page = client.get("/?view=jobs")
    assert page.status_code == 200
    assert "Kaydedildi" in page.text
    assert 'data-decision="saved"' in page.text
    assert 'data-decision="approved"' in page.text
    assert 'data-decision="rejected"' in page.text
    assert "işverene başvuru veya e-posta göndermez" in page.text


def test_job_review_rejects_unknown_listing(owner_client):
    client, _ = owner_client
    token = _login_and_csrf(client)
    response = client.post(
        "/internal/owner/job-review",
        json={"source": "ashby", "job_id": "missing", "decision": "saved"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": token},
    )
    assert response.status_code == 404
