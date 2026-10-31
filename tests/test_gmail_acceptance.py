"""Gmail production acceptance is signed, safe and disabled by default."""
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from careerhunter import gmail_acceptance, scheduled_scan as scan, gmail_reader
from careerhunter.database import SQLiteRepository
from careerhunter.private_site import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "fixture.db")
    repo.engine.dispose()
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-password-very-long-for-owner")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "test-session-secret-very-long-000000")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", f"sqlite:///{tmp_path / 'fixture.db'}")
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("CAREERHUNTER_OIDC_COLLECTOR", "true")
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def token(monkeypatch, workflow=None):
    monkeypatch.setattr(scan._jwks, "get_signing_key_from_jwt",
                        lambda t: SimpleNamespace(key="fixture"))
    claims = {"sub": "repo:" + scan.REPO, "repository": scan.REPO,
              "repository_id": scan.REPO_ID,
              "workflow_ref": workflow or gmail_acceptance.WORKFLOW,
              "ref": "refs/heads/main", "event_name": "push"}
    monkeypatch.setattr(scan.jwt, "decode", lambda *a, **kw: claims)
    return {"Authorization": "Bearer one.two.three"}


def test_anonymous_and_wrong_workflow_cannot_read(client, monkeypatch):
    assert client.get("/internal/gmail/acceptance").status_code == 401
    h = token(monkeypatch, workflow=scan.WORKFLOW)
    assert client.get("/internal/gmail/acceptance", headers=h).status_code == 403


def test_off_by_default_even_with_valid_token(client, monkeypatch):
    h = token(monkeypatch)
    monkeypatch.delenv("CAREERHUNTER_GMAIL_READONLY_ENABLED", raising=False)
    r = client.get("/internal/gmail/acceptance", headers=h)
    assert r.json() == {"status": "disabled", "read_only": True}


def test_missing_oauth_returns_only_safe_status(client, monkeypatch):
    h = token(monkeypatch)
    monkeypatch.setenv("CAREERHUNTER_GMAIL_READONLY_ENABLED", "true")
    monkeypatch.setattr(gmail_reader, "configured", lambda: False)
    r = client.get("/internal/gmail/acceptance", headers=h)
    assert r.json() == {"status": "missing_render_oauth", "read_only": True}


def test_read_only_acceptance_never_exposes_message_contents(client, monkeypatch):
    h = token(monkeypatch)
    monkeypatch.setenv("CAREERHUNTER_GMAIL_READONLY_ENABLED", "true")
    monkeypatch.setattr(gmail_reader, "configured", lambda: True)
    monkeypatch.setattr(gmail_reader, "read_readonly",
                        lambda max_results: SimpleNamespace(scanned=max_results, review_required=1))
    r = client.get("/internal/gmail/acceptance", headers=h)
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "scanned": 3, "review_required": 1,
                        "read_only": True, "messages_sent": 0, "messages_modified": 0}
    assert "subject" not in r.text and "email" not in r.text
