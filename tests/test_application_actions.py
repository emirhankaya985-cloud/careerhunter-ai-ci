"""Online CRM records require owner cookie, same origin, signed CSRF and consent."""
import pytest
from fastapi.testclient import TestClient

from careerhunter.database import SQLiteRepository
from careerhunter.models import Job
from careerhunter.private_site import app, _get_engine, failed_logins


@pytest.fixture
def owner_client(tmp_path, monkeypatch):
    db_path = tmp_path / "manual-test.sqlite"
    repo = SQLiteRepository(db_path)
    repo.upsert_jobs([Job(
        job_id="demo42", source="ashby", company="Example",
        title="Junior Python Developer", job_url="https://example.org/demo42",
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


def _auth(client):
    assert client.post("/login", data={"password": "test-owner-passphrase-123456"}).status_code == 200
    response = client.get("/internal/owner/application-csrf")
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _record(client, token, **changes):
    data = {"source": "ashby", "job_id": "demo42", "status": "applied",
            "confirm_manual_event": True}
    data.update(changes)
    return client.post(
        "/internal/owner/application", json=data,
        headers={"Origin": "https://testserver", "X-CSRF-Token": token},
    )


def test_unauthenticated_application_endpoints_do_not_disclose_data(owner_client):
    client, _ = owner_client
    assert client.get("/internal/owner/application-csrf").status_code == 401
    assert _record(client, "not-a-real-token").status_code == 401


def test_no_write_without_valid_csrf_origin_or_explicit_real_confirmation(owner_client):
    client, db = owner_client
    token = _auth(client)
    assert _record(client, "wrong-token").status_code == 403
    assert client.post("/internal/owner/application", json={
        "source": "ashby", "job_id": "demo42", "status": "applied",
        "confirm_manual_event": True
    }, headers={"Origin": "https://evil.example", "X-CSRF-Token": token}).status_code == 403
    assert _record(client, token, confirm_manual_event=False).status_code == 422
    assert SQLiteRepository(db).list_opportunities() == []


def test_owner_records_existing_job_once_with_one_followup(owner_client):
    client, db = owner_client
    token = _auth(client)
    response = _record(client, token)
    assert response.status_code == 200
    assert response.json()["status"] == "recorded"
    assert response.json()["external_application_sent"] is False
    assert _record(client, token).status_code == 200
    repo = SQLiteRepository(db)
    assert len(repo.list_opportunities()) == 1
    assert repo.list_opportunities()[0].status == "applied"
    assert len(repo.list_followups()) == 1


def test_missing_separate_writer_fails_closed(owner_client, monkeypatch):
    client, _ = owner_client
    token = _auth(client)
    monkeypatch.delenv("CAREERHUNTER_CRM_DATABASE_URL", raising=False)
    assert _record(client, token).status_code == 503


def test_session_rotation_invalidates_old_csrf(owner_client, monkeypatch):
    client, _ = owner_client
    old = _auth(client)
    monkeypatch.setenv("DASHBOARD_PASSWORD", "new-test-owner-password-123456")
    assert _record(client, old).status_code == 401
