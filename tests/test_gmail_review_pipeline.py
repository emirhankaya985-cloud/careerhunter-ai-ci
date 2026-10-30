"""Private Gmail summary endpoint and Telegram digest must remain read-only."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from careerhunter import scheduled_scan as scan, telegram_mail_review as sender
from careerhunter.gmail_reader import InboxSummary
from careerhunter.private_site import app, _get_engine
from careerhunter.database import SQLiteRepository


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "private.db"
    repo = SQLiteRepository(db)
    repo.engine.dispose()
    monkeypatch.setenv("DASHBOARD_PASSWORD", "fake-test-dashboard-password-123")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "fake-test-session-key-123456789012345")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", "sqlite:///" + str(db))
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("CAREERHUNTER_OIDC_COLLECTOR", "true")
    _get_engine.cache_clear()
    claims = {
        "sub": "repo:" + scan.REPO + ":ref:refs/heads/main",
        "repository": scan.REPO,
        "repository_id": scan.REPO_ID,
        "workflow_ref": scan.MAIL_REVIEW_WORKFLOW,
        "ref": "refs/heads/main",
        "event_name": "schedule",
    }
    monkeypatch.setattr(scan._jwks, "get_signing_key_from_jwt",
                        lambda token: SimpleNamespace(key="fake-test-key"))
    monkeypatch.setattr(scan.jwt, "decode", lambda *args, **kwargs: dict(claims))
    try:
        with TestClient(app, base_url="https://testserver") as c:
            yield c, claims
    finally:
        _get_engine.cache_clear()


def test_gmail_endpoint_requires_signed_exact_workflow(client, monkeypatch):
    c, claims = client
    headers = {"Authorization": "Bearer a.b.c"}
    path = "/internal/gmail/review-summary"
    assert c.get(path).status_code == 401
    claims["workflow_ref"] = scan.WORKFLOW
    assert c.get(path, headers=headers).status_code == 403
    claims["workflow_ref"] = scan.MAIL_REVIEW_WORKFLOW
    assert c.get(path, headers=headers).json()["status"] == "disabled"
    monkeypatch.setenv("CAREERHUNTER_GMAIL_READONLY_ENABLED", "true")
    from careerhunter import gmail_reader
    monkeypatch.setattr(gmail_reader, "configured", lambda: False)
    assert c.get(path, headers=headers).json()["status"] == "not_configured"
    monkeypatch.setattr(gmail_reader, "configured", lambda: True)
    monkeypatch.setattr(gmail_reader, "read_readonly",
                        lambda max_results: InboxSummary(
                            scanned=2, categories={"interview": 1, "needs_review": 1},
                            review_required=2))
    r = c.get(path, headers=headers)
    assert r.status_code == 200 and r.json()["scanned"] == 2
    assert "gmail.com" not in r.text and "token" not in r.text
    assert "crm_statuses_changed" in r.text
    claims["event_name"] = "pull_request"
    assert c.get(path, headers=headers).status_code == 403


def test_gmail_telegram_aggregate_only():
    msg = sender.prepare({
        "status": "ready", "scanned": 2, "review_required": 2,
        "categories": {"interview": 1, "needs_review": 1},
    })
    assert "Mülakat olasılığı" in msg and "insan incelemesi" in msg
    assert "gmail.com" not in msg


def test_not_configured_gmail_fails_transparently(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(sender, "configured", lambda: True)
    monkeypatch.setattr(sender, "call", lambda path: {"status": "not_configured"})
    monkeypatch.setattr(sender, "send", lambda message: pytest.fail("no send"))
    assert sender.main() == 1


def test_retry_does_not_duplicate_telegram(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setattr(sender, "configured", lambda: True)
    monkeypatch.setattr(sender, "call", lambda path: pytest.fail("no fetch"))
    assert sender.main() == 0
