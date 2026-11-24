"""Security tests for GitHub OIDC Telegram approval delivery and callbacks."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from careerhunter.private_site import app
from careerhunter import scheduled_scan, telegram_mail_approval as approval
from careerhunter import telegram_mail_worker as worker


@pytest.fixture
def mail_client(tmp_path, monkeypatch):
    db_path = tmp_path / "telegram-approval.sqlite"
    url = "sqlite:///" + str(db_path)
    monkeypatch.setattr(approval, "_writer_url", lambda: url)
    monkeypatch.setenv("DASHBOARD_PASSWORD", "approval-test-password-123456")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "approval-test-session-secret-123456789")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", url)
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "a" * 40)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    engine = create_engine(url)
    approval.approval_requests.create(engine)
    engine.dispose()
    with TestClient(app, base_url="https://testserver") as client:
        yield client, db_path


def enqueue(monkeypatch):
    monkeypatch.setattr(approval.secrets, "token_urlsafe", lambda _size: "r" * 24)
    contact = SimpleNamespace(
        person_id="person-1", name="Recruiter One", email_public="jobs@example.org",
        primary_source_url="https://example.org/team",
    )
    job = SimpleNamespace(
        source="ashby", job_id="job-1", company="Example Ltd", title="Engineer",
        job_url="https://example.org/jobs/1",
    )
    assert approval.queue_owner_approval(
        contact=contact, job=job, subject="Interest in Engineer", body="Hello recruiter",
    )


def test_queue_needs_only_webhook_secret_and_persists_without_bot_credentials(
    mail_client, monkeypatch,
):
    _, db_path = mail_client
    enqueue(monkeypatch)
    engine = create_engine("sqlite:///" + str(db_path))
    try:
        with engine.connect() as connection:
            row = connection.execute(select(approval.approval_requests)).mappings().one()
        assert row["status"] == "queued"
        payload = json.loads(row["payload"])
        assert payload["body"] == "Hello recruiter"
        assert payload["recipient_address"] == "jobs@example.org"
        assert payload["contact_evidence_url"] == "https://example.org/team"
    finally:
        engine.dispose()


def test_oidc_worker_claim_is_one_shot_and_delivery_binds_owner_chat(mail_client, monkeypatch):
    client, _ = mail_client
    enqueue(monkeypatch)
    monkeypatch.setattr(approval, "_require_mail_worker", lambda _request: None)
    first = client.post("/internal/telegram/mail-approval/claim", json={"chat_id": "123456789"})
    assert first.status_code == 200 and first.json()["status"] == "claimed"
    data = first.json()
    assert data["draft"]["owner_chat_id"] == "123456789"
    second = client.post("/internal/telegram/mail-approval/claim", json={"chat_id": "123456789"})
    assert second.json() == {"status": "empty"}
    receipt = client.post("/internal/telegram/mail-approval/delivery", json={
        "request_id": data["request_id"], "outcome": "delivered", "message_id": 55,
    })
    assert receipt.json()["status"] == "pending"
    assert client.post("/internal/telegram/mail-approval/delivery", json={
        "request_id": data["request_id"], "outcome": "delivered", "message_id": 56,
    }).json()["status"] == "already_final"


def test_config_is_bound_to_exact_workflow_identity(mail_client, monkeypatch):
    client, _ = mail_client
    seen = {}

    def require(request, *, workflow, events):
        seen["workflow"] = workflow
        seen["events"] = events
        assert workflow == scheduled_scan.TELEGRAM_MAIL_WORKFLOW

    monkeypatch.setattr(scheduled_scan, "_require_github_oidc", require)
    response = client.get("/internal/telegram/mail-approval/config")
    assert response.status_code == 200
    assert response.json()["url"].endswith("/internal/telegram/mail-approval")
    assert response.json()["secret"] == "a" * 40
    assert "pull_request" not in seen["events"]


def test_callback_uses_webhook_response_without_render_bot_token(mail_client, monkeypatch):
    client, _ = mail_client
    enqueue(monkeypatch)
    monkeypatch.setattr(approval, "_require_mail_worker", lambda _request: None)
    claim = client.post("/internal/telegram/mail-approval/claim", json={"chat_id": "123456789"}).json()
    request_id = claim["request_id"]
    client.post("/internal/telegram/mail-approval/delivery", json={
        "request_id": request_id, "outcome": "delivered", "message_id": 55,
    })
    called = []

    def dispatch(request, chat_id, message_id):
        pending = approval._load_and_claim(request, chat_id, message_id)
        called.append(pending)
        if pending:
            approval._set_status(request, "sent")
            return "sent"
        return "expired_or_already_used"

    monkeypatch.setattr(approval, "_dispatch", dispatch)
    payload = {"callback_query": {
        "id": "callback-1", "data": "chmail:" + request_id,
        "from": {"id": 123456789},
        "message": {"message_id": 55, "chat": {"id": 123456789, "type": "private"}},
    }}
    response = client.post("/internal/telegram/mail-approval", json=payload, headers={
        "x-telegram-bot-api-secret-token": "a" * 40,
    })
    assert response.status_code == 200
    assert response.json()["method"] == "answerCallbackQuery"
    assert response.json()["text"].startswith("✅")
    assert called and called[0]["body"] == "Hello recruiter"
    assert not hasattr(approval, "_api")
    again = client.post("/internal/telegram/mail-approval", json=payload, headers={
        "x-telegram-bot-api-secret-token": "a" * 40,
    })
    assert again.status_code == 200
    assert len(called) == 2 and called[1] is None


def test_worker_formats_exact_draft_and_escapes_untrusted_html():
    formatted = worker._format_message("r" * 24, {
        "recipient_name": "<Hiring>", "recipient_address": "jobs@example.org",
        "contact_evidence_url": "https://example.org/team", "company": "Example & Co",
        "job_title": "<Engineer>", "job_url": "https://example.org/jobs/1",
        "subject": "Interest <role>", "body": "Hello & welcome",
    })
    assert "&lt;Hiring&gt;" in formatted["text"]
    assert "Example &amp; Co" in formatted["text"]
    assert "Hello &amp; welcome" in formatted["text"]
    assert "<Engineer>" not in formatted["text"]
    assert formatted["reply_markup"]["inline_keyboard"][1][0]["callback_data"] == "chmail:" + "r" * 24
    assert "TELEGRAM_BOT_TOKEN" not in formatted["text"]


def test_worker_refuses_to_replace_another_webhook(monkeypatch):
    calls = []

    def telegram(_token, method, _data):
        calls.append(method)
        return {"ok": True, "result": {"url": "https://another.example/webhook"}}

    monkeypatch.setattr(worker, "_telegram", telegram)
    with pytest.raises(worker.WorkerError, match="Another Telegram webhook"):
        worker._configure_webhook(
            "123456789:" + "x" * 35,
            url=worker._BASE_URL + "/internal/telegram/mail-approval",
            secret="s" * 40,
        )
    assert calls == ["getWebhookInfo"]


def test_callback_requires_telegram_webhook_secret(mail_client, monkeypatch):
    client, _ = mail_client
    monkeypatch.setattr(approval, "_dispatch", lambda *_args: pytest.fail("must not dispatch"))
    response = client.post("/internal/telegram/mail-approval", json={"callback_query": {}}, headers={
        "x-telegram-bot-api-secret-token": "wrong-secret",
    })
    assert response.status_code == 403


def test_callback_rejects_other_private_chat(mail_client, monkeypatch):
    client, _ = mail_client
    enqueue(monkeypatch)
    monkeypatch.setattr(approval, "_require_mail_worker", lambda _request: None)
    claim = client.post("/internal/telegram/mail-approval/claim", json={"chat_id": "123456789"}).json()
    client.post("/internal/telegram/mail-approval/delivery", json={
        "request_id": claim["request_id"], "outcome": "delivered", "message_id": 55,
    })

    def dispatch(request, chat_id, message_id):
        return ("blocked" if approval._load_and_claim(request, chat_id, message_id)
                else "expired_or_already_used")

    monkeypatch.setattr(approval, "_dispatch", dispatch)
    payload = {"callback_query": {
        "id": "callback-1", "data": "chmail:" + claim["request_id"],
        "from": {"id": 987654321},
        "message": {"message_id": 55, "chat": {"id": 987654321, "type": "private"}},
    }}
    response = client.post("/internal/telegram/mail-approval", json=payload, headers={
        "x-telegram-bot-api-secret-token": "a" * 40,
    })
    assert response.status_code == 200
    assert response.json()["method"] == "answerCallbackQuery"
    assert response.json()["show_alert"] is True


def test_workflow_polls_telegram_callbacks_from_github_and_keeps_secrets_in_actions():
    from pathlib import Path

    workflow = (Path(__file__).parents[1] / ".github/workflows/telegram-mail-approvals.yml")
    content = workflow.read_text(encoding="utf-8")
    assert "id-token: write" not in content
    assert "secrets.TELEGRAM_BOT_TOKEN" in content
    assert "secrets.TELEGRAM_CHAT_ID" in content
    assert "schedule:" in content and "*/5 * * * *" in content
    assert "getUpdates" in (Path(__file__).parents[1] / "src/careerhunter/telegram_mail_worker.py").read_text()
    assert "TELEGRAM_MAIL_WORKFLOW = REPO + \"/.github/workflows/telegram-mail-approvals.yml@refs/heads/main\"" in (
        (Path(__file__).parents[1] / "src/careerhunter/scheduled_scan.py").read_text(encoding="utf-8")
    )
