"""No network, credential leakage, or duplicate Gmail raw fetches."""
import base64
from email.message import EmailMessage

import httpx
import pytest

from careerhunter.gmail_reader import GmailReadError, read_readonly


@pytest.fixture(autouse=True)
def oauth(monkeypatch):
    monkeypatch.setenv("GMAIL_READONLY_CLIENT_ID", "test-client")
    monkeypatch.setenv("GMAIL_READONLY_CLIENT_SECRET", "PRIVATE-SECRET")
    monkeypatch.setenv("GMAIL_READONLY_REFRESH_TOKEN", "PRIVATE-REFRESH")


@pytest.mark.parametrize(("host", "status", "reason"), [
    ("oauth2.googleapis.com", 400, "oauth_exchange_rejected"),
    ("oauth2.googleapis.com", 429, "oauth_rate_limited"),
    ("gmail.googleapis.com", 401, "gmail_token_rejected"),
    ("gmail.googleapis.com", 403, "gmail_access_forbidden"),
    ("gmail.googleapis.com", 429, "gmail_rate_limited"),
    ("gmail.googleapis.com", 503, "gmail_provider_unavailable"),
])
def test_http_failure_is_fixed_code_and_never_exposes_private_body(host, status, reason):
    def handler(request):
        if request.url.host == "oauth2.googleapis.com" and host != request.url.host:
            return httpx.Response(200, json={"access_token": "PRIVATE-ACCESS"})
        if request.url.host == "gmail.googleapis.com" and host == request.url.host:
            return httpx.Response(status, text="PRIVATE-SENDER PRIVATE-SECRET")
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(status, text="PRIVATE-REFRESH")
        raise AssertionError("Unexpected mail read")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GmailReadError) as exc:
            read_readonly(client=client)
    assert exc.value.reason == reason
    assert "PRIVATE" not in str(exc.value)


def test_duplicate_gmail_message_id_fetched_once():
    message = EmailMessage()
    message["Message-ID"] = "<only-once@example.org>"
    message["Subject"] = "Interview invitation"
    message.set_content("Would you join a technical interview?")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
    reads = []

    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "PRIVATE-ACCESS"})
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "unique123"},
                                                          {"id": "unique123"}]})
        reads.append(request.url.path)
        return httpx.Response(200, json={"raw": raw})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = read_readonly(max_results=5, client=client)
    assert result.scanned == 1
    assert len(reads) == 1
