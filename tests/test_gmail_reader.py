"""Read-only Gmail OAuth transport and privacy tests, all offline."""
import base64
from email.message import EmailMessage

import httpx
import pytest

from careerhunter import gmail_reader


def mail(subject="Interview invitation", body="Can you schedule an interview?"):
    msg = EmailMessage()
    msg["Message-ID"] = "<example@example.org>"
    msg["Subject"] = subject
    msg["From"] = "secret-recruiter@example.org"
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii").rstrip("=")


def secrets(monkeypatch):
    monkeypatch.setenv("GMAIL_READONLY_CLIENT_ID", "local-fixture-id")
    monkeypatch.setenv("GMAIL_READONLY_CLIENT_SECRET", "local-fixture-secret")
    monkeypatch.setenv("GMAIL_READONLY_REFRESH_TOKEN", "local-fixture-refresh")


def test_unconfigured_mail_reader_never_uses_network(monkeypatch):
    for key in ("GMAIL_READONLY_CLIENT_ID", "GMAIL_READONLY_CLIENT_SECRET",
                "GMAIL_READONLY_REFRESH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    assert not gmail_reader.configured()
    with pytest.raises(RuntimeError, match="not configured"):
        gmail_reader.read_readonly()


def test_bounded_api_only_reads_and_summarizes(monkeypatch):
    secrets(monkeypatch)
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.host == "oauth2.googleapis.com":
            assert request.method == "POST" and request.url.path == "/token"
            return httpx.Response(200, json={"access_token": "private-ephemeral"})
        assert request.url.host == "gmail.googleapis.com"
        assert request.method == "GET"
        assert request.headers.get("authorization") == "Bearer private-ephemeral"
        if request.url.path.endswith("/messages"):
            assert request.url.params.get("maxResults") == "5"
            return httpx.Response(200, json={"messages": [
                {"id": "aaa1111"}, {"id": "bbb2222"}]})
        return httpx.Response(200, json={"raw": mail()})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = gmail_reader.read_readonly(max_results=5, client=client)
    assert result.scanned == 1
    assert result.categories == {"interview": 1}
    assert result.review_required == 1
    assert result.as_dict()["automatic_replies_sent"] == 0
    assert len(calls) == 4
    assert calls.count(("POST", "/token")) == 1


def test_invalid_message_id_prevents_unbounded_url_and_network(monkeypatch):
    secrets(monkeypatch)
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "private"})
        return httpx.Response(200, json={"messages": [{"id": "../../../bad"}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="identifier"):
            gmail_reader.read_readonly(client=client)
    assert len(calls) == 2


def test_invalid_raw_payload_is_safe_failure(monkeypatch):
    secrets(monkeypatch)
    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "private"})
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "aaa1111"}]})
        return httpx.Response(200, json={"raw": "*bad-base64"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError):
            gmail_reader.read_readonly(client=client)


def test_max_results_is_bounded(monkeypatch):
    secrets(monkeypatch)
    with pytest.raises(ValueError, match="1..30"):
        gmail_reader.read_readonly(max_results=1000)
