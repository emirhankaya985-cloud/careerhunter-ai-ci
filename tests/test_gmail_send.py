"""Gmail-send contract: no outbound before explicit consent and safe dedup."""
import base64
import json
from dataclasses import replace

import httpx
import pytest

from careerhunter.gmail_send import ApprovedMail, GmailSendError, send_approved_once

BASE = ApprovedMail(
    recipient="jobs@example.org",
    subject="Application — Backend Python",
    body="Hello, I am interested in this role. Regards.",
    contact_evidence_url="https://example.org/careers/backend-python",
    approval_id="candidate-job-001",
    approved_by_owner=True,
)


def credentials(monkeypatch):
    monkeypatch.setenv("GMAIL_SEND_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("GMAIL_SEND_CLIENT_SECRET", "fixture-secret")
    monkeypatch.setenv("GMAIL_SEND_REFRESH_TOKEN", "fixture-refresh")
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_ENABLED", "true")


def test_unapproved_or_unverified_mail_never_sends(tmp_path, monkeypatch):
    credentials(monkeypatch)
    db = "sqlite:///" + str(tmp_path / "ledger.db")
    for mail in (
        replace(BASE, approved_by_owner=False),
        replace(BASE, recipient="no-address"),
        replace(BASE, contact_evidence_url="http://example.org/unverified"),
        replace(BASE, subject="Hi\nBcc: intruder@example.org"),
    ):
        with pytest.raises(GmailSendError):
            send_approved_once(mail, database_url=db, allow_sqlite_tests=True)
    assert not (tmp_path / "ledger.db").exists()


def test_feature_is_disabled_by_default(tmp_path, monkeypatch):
    credentials(monkeypatch)
    monkeypatch.delenv("CAREERHUNTER_GMAIL_SEND_ENABLED")
    with pytest.raises(GmailSendError, match="gmail_send_disabled"):
        send_approved_once(BASE, database_url="sqlite:///" + str(tmp_path / "ledger.db"),
                           allow_sqlite_tests=True)


def test_real_sender_scope_is_separate_from_readonly(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_ENABLED", "true")
    monkeypatch.delenv("GMAIL_SEND_CLIENT_ID", raising=False)
    monkeypatch.setenv("GMAIL_READONLY_CLIENT_ID", "not-send")
    monkeypatch.setenv("GMAIL_READONLY_CLIENT_SECRET", "not-send")
    monkeypatch.setenv("GMAIL_READONLY_REFRESH_TOKEN", "not-send")
    with pytest.raises(GmailSendError, match="gmail_send_oauth_missing"):
        send_approved_once(BASE, database_url="sqlite:///" + str(tmp_path / "ledger.db"),
                           allow_sqlite_tests=True)


def test_one_time_gmail_send_has_positive_receipt(tmp_path, monkeypatch):
    credentials(monkeypatch)
    sent = []

    def transport(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "fake-test-token"})
        assert request.url.path.endswith("/messages/send")
        assert request.headers["Authorization"] == "Bearer fake-test-token"
        encoded = json.loads(request.content)["raw"]
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        assert b"jobs@example.org" in raw
        assert b"Backend Python" in raw
        sent.append(raw)
        return httpx.Response(200, json={"id": "providerMessage999"})

    db = "sqlite:///" + str(tmp_path / "ledger.db")
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        assert send_approved_once(BASE, database_url=db, client=client,
                                  allow_sqlite_tests=True) == "providerMessage999"
        with pytest.raises(GmailSendError, match="duplicate_or_previous_attempt"):
            send_approved_once(BASE, database_url=db, client=client,
                               allow_sqlite_tests=True)
    assert len(sent) == 1


def test_ambiguous_provider_failure_cannot_retry(tmp_path, monkeypatch):
    credentials(monkeypatch)
    calls = []

    def transport(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "fake-test-token"})
        calls.append(True)
        return httpx.Response(503, json={"error": "not inspected"})

    db = "sqlite:///" + str(tmp_path / "ledger.db")
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(GmailSendError, match="provider_result_unconfirmed"):
            send_approved_once(BASE, database_url=db, client=client,
                               allow_sqlite_tests=True)
        with pytest.raises(GmailSendError, match="duplicate_or_previous_attempt"):
            send_approved_once(BASE, database_url=db, client=client,
                               allow_sqlite_tests=True)
    assert len(calls) == 1


def test_live_mode_requires_postgresql(tmp_path, monkeypatch):
    credentials(monkeypatch)
    with pytest.raises(GmailSendError, match="postgresql_ledger_required"):
        send_approved_once(BASE, database_url="sqlite:///" + str(tmp_path / "x.db"))


def test_changing_mail_body_does_not_bypass_one_application_per_job_contact():
    from dataclasses import replace
    assert BASE.key() == replace(BASE, subject="Revised subject",
                                 body="Updated text").key()
    assert BASE.key() != replace(BASE, approval_id="candidate-job-002").key()


def test_existing_oauth_client_can_be_reused_but_readonly_token_cannot(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("CAREERHUNTER_GMAIL_SEND_ENABLED", "true")
    monkeypatch.delenv("GMAIL_SEND_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_SEND_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("GMAIL_READONLY_CLIENT_ID", "same-client-id")
    monkeypatch.setenv("GMAIL_READONLY_CLIENT_SECRET", "same-client-secret")
    monkeypatch.setenv("GMAIL_READONLY_REFRESH_TOKEN", "old-readonly-refresh")
    monkeypatch.setenv("GMAIL_SEND_REFRESH_TOKEN", "new-send-refresh")
    seen = []

    def reply(request):
        if request.url.host == "oauth2.googleapis.com":
            seen.append(request.content.decode())
            assert "refresh_token=new-send-refresh" in request.content.decode()
            assert "old-readonly-refresh" not in request.content.decode()
            return httpx.Response(200, json={"access_token": "fake-token"})
        return httpx.Response(200, json={"id": "providerMessage123"})

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        assert send_approved_once(
            BASE, database_url="sqlite:///" + str(tmp_path / "ledger.db"),
            client=client, allow_sqlite_tests=True,
        ) == "providerMessage123"
    assert len(seen) == 1
