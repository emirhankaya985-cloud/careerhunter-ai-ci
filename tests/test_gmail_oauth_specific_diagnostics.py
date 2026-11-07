"""OAuth refresh failure classifications expose only safe fixed error codes."""
import httpx
import pytest

from careerhunter.gmail_reader import GmailReadError, read_readonly


@pytest.mark.parametrize(("code", "expected"), [
    ("invalid_grant", "oauth_refresh_invalid"),
    ("invalid_client", "oauth_client_rejected"),
    ("unknown_provider_code", "oauth_exchange_rejected"),
])
def test_oauth_refresh_failure_has_only_allowlisted_diagnostic(monkeypatch, code, expected):
    monkeypatch.setenv("GMAIL_READONLY_CLIENT_ID", "test-id")
    monkeypatch.setenv("GMAIL_READONLY_CLIENT_SECRET", "PRIVATE-SECRET")
    monkeypatch.setenv("GMAIL_READONLY_REFRESH_TOKEN", "PRIVATE-REFRESH")

    def respond(request):
        assert request.url.host == "oauth2.googleapis.com"
        return httpx.Response(400, json={
            "error": code,
            "error_description": "PRIVATE-SECRET PRIVATE-REFRESH",
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(GmailReadError) as err:
            read_readonly(client=client, max_results=1)
    assert err.value.reason == expected
    assert "PRIVATE" not in str(err.value)


def test_oauth_large_or_malformed_response_falls_back_safely(monkeypatch):
    for key in ("GMAIL_READONLY_CLIENT_ID", "GMAIL_READONLY_CLIENT_SECRET",
                "GMAIL_READONLY_REFRESH_TOKEN"):
        monkeypatch.setenv(key, "PRIVATE-VALUE")

    def respond(request):
        return httpx.Response(400, text="PRIVATE-SECRET" * 400)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(GmailReadError) as err:
            read_readonly(client=client)
    assert err.value.reason == "oauth_exchange_rejected"
    assert "PRIVATE" not in str(err.value)
