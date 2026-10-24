"""No-secret regression tests for the private Telegram daily digest."""
from datetime import datetime, timezone

import pytest

from careerhunter.models import Job, RunStats
from careerhunter.notifications import telegram


TOKEN = "123456789:" + "a" * 35
CHAT = "123456789"


def job(i, *, score=90, status="new", senior=False, eligibility="needs_review"):
    return Job(
        job_id=str(i), source="greenhouse", company=f"ACME <{i}>",
        title="Junior Python & AI Developer",
        location="Worldwide remote", description="Python FastAPI",
        job_url=f"https://boards.greenhouse.io/example/jobs/{i}",
        source_url="https://boards-api.greenhouse.io/v1/boards/example/jobs",
        match_score=score,
        status=status,
        experience_level="senior" if senior else "junior",
        eligibility_status=eligibility,
        match_method="llm" if i % 2 else "rules",
    )


def stats(*, status="success"):
    return RunStats(
        slot="jobs", started_at=datetime.now(timezone.utc),
        status=status, jobs_new=9, jobs_processed=1900, llm_calls=8,
    )


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.delenv("TELEGRAM_MIN_SCORE", raising=False)


def test_disabled_without_credentials_or_partial_configuration(monkeypatch, httpx_mock):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert not telegram.publish_daily_digest(stats(), [job(1)])
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    assert not telegram.publish_daily_digest(stats(), [job(1)])
    assert httpx_mock.get_requests() == []


def test_only_one_short_digest_with_three_links_and_safe_html(configured, httpx_mock):
    httpx_mock.add_response(
        url=f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"ok": True, "result": {"message_id": 121}},
    )
    examples = [job(1), job(2), job(3), job(4), job(1),
                job(8, score=45), job(9, status="seen"),
                job(10, senior=True), job(11, eligibility="ineligible")]
    assert telegram.publish_daily_digest(stats(), examples)
    assert len(httpx_mock.get_requests()) == 1
    payload = __import__("json").loads(httpx_mock.get_request().content)
    assert payload["chat_id"] == CHAT
    assert payload["parse_mode"] == "HTML"
    assert payload["protect_content"] is True
    assert "&lt;1&gt;" in payload["text"]
    assert "<1>" not in payload["text"]
    assert "NVIDIA AI" in payload["text"]
    assert len(payload["text"]) < 4000
    keys = payload["reply_markup"]["inline_keyboard"]
    assert len(keys) == 4
    assert all("url" in row[0] and "callback_data" not in row[0] for row in keys)
    assert all("/jobs/" in row[0]["url"] for row in keys[:3])


def test_already_seen_low_score_and_remote_block_are_silent(configured, httpx_mock):
    assert not telegram.publish_daily_digest(
        stats(), [job(1, status="seen"), job(2, score=60),
                  job(3, eligibility="ineligible"), job(4, senior=True)])
    assert not telegram.publish_daily_digest(stats(status="failed"), [job(5)])
    assert httpx_mock.get_requests() == []


def test_transport_success_requires_positive_message_id(configured, httpx_mock):
    httpx_mock.add_response(
        url=f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"ok": True, "result": {"message_id": 0}},
    )
    assert not telegram.publish_connection_test()


def test_send_failure_is_nonfatal_and_leaks_no_raw_exception(configured, httpx_mock):
    httpx_mock.add_response(url=f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                            status_code=401, json={"ok": False})
    assert not telegram.publish_daily_digest(stats(), [job(1)])


def test_telegram_error_never_includes_exception_or_database_url(configured, httpx_mock):
    httpx_mock.add_response(
        url=f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"ok": True, "result": {"message_id": 97}},
    )
    result = stats(status="failed")
    result.error = "password=secret postgres://user:secret@host/data"
    assert telegram.publish_failure(result)
    body = httpx_mock.get_request().content.decode()
    assert "password=secret" not in body
    assert "postgres://" not in body


def test_invalid_chat_and_token_are_rejected(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bad-secret")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    assert not telegram.is_configured()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "not-a-chat")
    assert not telegram.is_configured()
