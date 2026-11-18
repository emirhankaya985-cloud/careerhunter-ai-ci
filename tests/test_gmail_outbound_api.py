"""Owner Gmail send API is authenticated, CSRF-bound and contact-restricted."""
import pytest
from fastapi.testclient import TestClient

from careerhunter.database import SQLiteRepository
from careerhunter.models import Contact, Job
from careerhunter.private_site import app, _get_engine, failed_logins
from careerhunter import gmail_outbound_api as outbound


@pytest.fixture
def owner_mail_client(tmp_path, monkeypatch):
    dbfile = tmp_path / "owner.sqlite"
    repo = SQLiteRepository(dbfile)
    repo.upsert_jobs([Job(job_id="demo42", source="ashby", company="Example",
                          title="Junior Python Developer",
                          remote_type="remote", experience_level="junior",
                          match_score=75, verification_status="ATS_LISTED",
                          job_url="https://example.org/demo42",
                          source_url="https://api.ashbyhq.com/posting-api/job-board/example")])
    repo.upsert_contact(Contact(
        person_id="recruiter42", name="Recruitment Team", company="Example",
        role="Recruiter", category="recruitment", email_public="jobs@example.org",
        primary_source_url="https://example.org/careers",
        status="approved_by_user", research_confidence="high",
    ))
    repo.engine.dispose()
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-mail-owner-password-123456")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "test-mail-session-secret-123456789012345")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", "sqlite:///" + str(dbfile))
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("DASHBOARD_SECURE_COOKIE", "true")
    monkeypatch.delenv("CAREERHUNTER_GMAIL_SEND_ENABLED", raising=False)
    monkeypatch.delenv("GMAIL_SEND_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", raising=False)
    _get_engine.cache_clear()
    failed_logins.clear()
    try:
        with TestClient(app, base_url="https://testserver") as client:
            yield client
    finally:
        _get_engine.cache_clear()


def auth(client):
    assert client.post("/login", data={
        "password": "test-mail-owner-password-123456"
    }).status_code == 200
    r = client.get("/internal/owner/mail/csrf")
    assert r.status_code == 200
    return r.json()["csrf_token"]


def post(client, csrf, **changes):
    content = {
        "source": "ashby", "job_id": "demo42", "person_id": "recruiter42",
        "subject": "Applying for Junior Python Developer",
        "body": "Hello, I would like to apply for the Python role.",
        "confirm_send": True,
    }
    content.update(changes)
    return client.post(
        "/internal/owner/mail/send", json=content,
        headers={"origin": "https://testserver", "x-csrf-token": csrf},
    )


def test_owner_only_no_public_outbound_endpoint(owner_mail_client):
    client = owner_mail_client
    assert client.get("/internal/owner/mail/status").status_code == 401
    assert client.get("/internal/owner/mail/csrf").status_code == 401
    assert post(client, "bogus").status_code == 401


def test_send_fails_closed_without_scope_or_ledger(owner_mail_client, monkeypatch):
    client = owner_mail_client
    csrf = auth(client)
    status = client.get("/internal/owner/mail/status")
    assert status.status_code == 200
    assert status.json()["status"] == "blocked"
    assert status.json()["approved_contact_count"] == 1
    assert status.json()["automatic_dispatch_enabled"] is False
    assert post(client, csrf).status_code == 503
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_ENABLED", "true")
    assert post(client, csrf).status_code == 503
    monkeypatch.setenv("GMAIL_SEND_REFRESH_TOKEN", "fake")
    assert post(client, csrf).status_code == 503


def test_mail_status_does_not_claim_ready_without_approved_contacts(owner_mail_client,
                                                                     monkeypatch):
    client = owner_mail_client
    auth(client)
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_ENABLED", "true")
    monkeypatch.setenv("GMAIL_SEND_REFRESH_TOKEN", "fake")
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "postgresql://example")
    monkeypatch.setattr("careerhunter.private_site._repo",
                        lambda: type("EmptyRepo", (), {"list_contacts": lambda self, limit: []})())
    status = client.get("/internal/owner/mail/status")
    assert status.status_code == 200
    assert status.json()["status"] == "blocked"
    assert status.json()["approved_contact_count"] == 0


def test_csrf_origin_explicit_approval_required(owner_mail_client, monkeypatch):
    client = owner_mail_client
    csrf = auth(client)
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_ENABLED", "true")
    monkeypatch.setenv("GMAIL_SEND_REFRESH_TOKEN", "fake")
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "sqlite:///mock")
    assert post(client, "bad").status_code == 403
    assert client.post("/internal/owner/mail/send", json={
        "source": "ashby", "job_id": "demo42", "person_id": "recruiter42",
        "subject": "Hello", "body": "Hello", "confirm_send": True,
    }, headers={"origin": "https://attacker.example", "x-csrf-token": csrf}).status_code == 403
    assert post(client, csrf, confirm_send=False).status_code == 422


def test_only_private_approved_matching_contact_can_be_used(
    owner_mail_client, monkeypatch,
):
    client = owner_mail_client
    csrf = auth(client)
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_ENABLED", "true")
    monkeypatch.setenv("GMAIL_SEND_REFRESH_TOKEN", "fixture")
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "sqlite:///mock")
    sent = []

    def fake_send(mail, *, database_url):
        sent.append((mail, database_url))
        return "gmailMessage42"

    monkeypatch.setattr(outbound, "send_approved_once", fake_send)
    assert post(client, csrf, person_id="not-known").status_code == 422
    assert post(client, csrf, job_id="unknown").status_code == 404
    response = post(client, csrf, person_id="recruiter42")
    assert response.status_code == 200
    assert response.json()["gmail_message_id"] == "gmailMessage42"
    assert response.json()["status"] == "sent"
    assert len(sent) == 1
    mail = sent[0][0]
    assert mail.recipient == "jobs@example.org"
    assert mail.contact_evidence_url == "https://example.org/careers"
    assert mail.approved_by_owner is True
    assert len(mail.approval_id) == 40
    assert sent[0][1] == "sqlite:///mock"


def test_unsafe_contact_or_do_not_contact_never_sends(
    owner_mail_client, monkeypatch,
):
    client = owner_mail_client
    csrf = auth(client)
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_ENABLED", "true")
    monkeypatch.setenv("GMAIL_SEND_REFRESH_TOKEN", "fixture")
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "sqlite:///mock")
    from careerhunter.private_site import _repo
    repo = _repo()
    contact = repo.list_contacts()[0]
    # Simulate a personal contact explicitly marked do-not-contact:
    modified = contact.model_copy(update={"do_not_contact": True})
    from sqlalchemy import update as sql_update
    from careerhunter.database import contacts
    with repo.engine.begin() as conn:
        conn.execute(sql_update(contacts).where(
            contacts.c.person_id == contact.person_id
        ).values(payload=modified.model_dump_json()))
    assert post(client, csrf).status_code == 422
