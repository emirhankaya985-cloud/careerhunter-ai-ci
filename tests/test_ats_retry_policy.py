"""ATS HTTP retry behavior: permanent failures never spam provider APIs."""
import httpx
import pytest

from careerhunter.sources import base
from careerhunter.sources.base import SourceError
from careerhunter.sources.lever import LeverSource


@pytest.mark.parametrize("code", [301, 400, 401, 403, 404, 410, 422])
def test_permanent_responses_are_not_retried(monkeypatch, code):
    count = []
    def handler(request):
        count.append(request.url.path)
        return httpx.Response(code, text="PRIVATE-RESPONSE-DATA")

    monkeypatch.setattr(base.httpx, "Client",
                        client_factory(httpx.MockTransport(handler)))
    monkeypatch.setattr(base.time, "sleep", lambda _: pytest.fail("should not retry"))
    with pytest.raises(SourceError, match=f"HTTP {code}") as exc:
        LeverSource(retries=3).fetch("Example", "example")
    assert len(count) == 1
    assert "PRIVATE" not in str(exc.value)


def client_factory(transport):
    original = httpx.Client
    return lambda *args, **kwargs: original(*args, transport=transport, **kwargs)


def test_retry_after_is_capped(monkeypatch):
    delays = []
    statuses = iter([429, 200])

    def handler(request):
        code = next(statuses)
        return httpx.Response(code, json=[] if code == 200 else None,
                              headers={"Retry-After": "9999999"})

    factory = client_factory(httpx.MockTransport(handler))
    monkeypatch.setattr(base.httpx, "Client", factory)
    monkeypatch.setattr(base.time, "sleep", delays.append)
    assert LeverSource(retries=2).fetch("Example", "example") == []
    assert delays == [8.0]


def test_http_503_retries_then_recovers(monkeypatch):
    responses = iter([503, 200])
    seen = []

    def handler(request):
        code = next(responses)
        seen.append(code)
        return httpx.Response(code, json=[] if code == 200 else None)

    factory = client_factory(httpx.MockTransport(handler))
    monkeypatch.setattr(base.httpx, "Client", factory)
    monkeypatch.setattr(base.time, "sleep", lambda _: None)
    assert LeverSource(retries=2).fetch("Example", "example") == []
    assert seen == [503, 200]
