"""OIDC workflow isolation, Telegram privacy and retry regressions."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from careerhunter.database import SQLiteRepository
from careerhunter.models import FollowUp, Opportunity, utc_now
from careerhunter.private_site import app, _get_engine
from careerhunter import scheduled_scan as scan, telegram_followups as sender


@pytest.fixture
def secured_client(tmp_path, monkeypatch):
    db = tmp_path / "private.db"
    repo = SQLiteRepository(db)
    repo.upsert_opportunity(Opportunity(
        opportunity_id="greenhouse:demo", company="Example Employer",
        title="Junior Python Engineer", status="applied",
        job_url="https://example.org/jobs/demo", notes="PRIVATE APPLICATION NOTES"
    ))
    repo.upsert_followup(FollowUp(
        followup_id="due:1", opportunity_id="greenhouse:demo",
        due_at=utc_now() - timedelta(days=2),
        note="PRIVATE NOTE: DO NOT EXPOSE", person_id="private-person-id"
    ))
    repo.upsert_followup(FollowUp(
        followup_id="later:2", opportunity_id="greenhouse:demo",
        due_at=utc_now() + timedelta(days=2), note="NOT DUE"
    ))
    repo.engine.dispose()
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-owner-passphrase-123456")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "test-private-session-secret-123456789000")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", "sqlite:///" + str(db))
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("CAREERHUNTER_OIDC_COLLECTOR", "true")
    _get_engine.cache_clear()
    claims = {
        "sub": "repo:" + scan.REPO + ":ref:refs/heads/main",
        "repository": scan.REPO, "repository_id": scan.REPO_ID,
        "workflow_ref": scan.FOLLOWUP_WORKFLOW,
        "ref": "refs/heads/main", "event_name": "schedule",
    }
    monkeypatch.setattr(scan._jwks, "get_signing_key_from_jwt",
                        lambda token: SimpleNamespace(key="fake-testing-key"))
    monkeypatch.setattr(scan.jwt, "decode", lambda *args, **kwargs: dict(claims))
    try:
        with TestClient(app, base_url="https://testserver") as client:
            yield client, claims
    finally:
        _get_engine.cache_clear()


def test_due_reminders_oidc_and_no_private_notes(secured_client):
    client, claims = secured_client
    url = "/internal/followups/due"
    headers = {"Authorization": "Bearer a.b.c"}
    assert client.get(url).status_code == 401
    claims["workflow_ref"] = scan.WORKFLOW
    assert client.get(url, headers=headers).status_code == 403
    claims["workflow_ref"] = scan.FOLLOWUP_WORKFLOW
    result = client.get(url, headers=headers)
    assert result.status_code == 200
    payload = result.json()
    assert payload["status"] == "ready" and payload["due_count"] == 1
    assert payload["items"][0]["title"] == "Junior Python Engineer"
    assert "PRIVATE" not in result.text
    assert "private-person-id" not in result.text
    assert "NOT DUE" not in result.text
    claims["event_name"] = "pull_request"
    assert client.get(url, headers=headers).status_code == 403


def test_sender_private_message_escapes_untrusted_text():
    msg, buttons = sender.prepare({
        "status": "ready", "due_count": 1,
        "items": [{"title": "Junior <script> Python", "company": "A & B",
                   "job_url": "https://example.org/jobs/demo", "due_at": "2026-10-30"}]
    })
    assert "&lt;script&gt;" in msg and "A &amp; B" in msg
    assert "<script>" not in msg
    assert any(x["url"].endswith("view=applications") for x in buttons)
    assert "gönderilmedi" in msg


def test_zero_due_does_not_send(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(sender, "configured", lambda: True)
    monkeypatch.setattr(sender, "call", lambda url: {"status": "ready", "due_count": 0, "items": []})
    monkeypatch.setattr(sender, "send", lambda *args: pytest.fail("must not send"))
    assert sender.main() == 0


def test_retried_job_never_sends(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setattr(sender, "configured", lambda: True)
    monkeypatch.setattr(sender, "call", lambda url: pytest.fail("must not query"))
    assert sender.main() == 0


def test_no_unverified_snapshot():
    with pytest.raises(ValueError):
        sender.prepare({"status": "error", "due_count": 4, "items": []})
