"""Transient Render GET failures may retry, writes must not replay."""
import io
import json
from urllib.error import HTTPError, URLError

import pytest

from careerhunter import render_scan_client as cli


class Response(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_transient_get_is_bounded_and_recovers(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr(cli, "token", lambda: "safe-fixture")
    monkeypatch.setattr(cli.time, "sleep", sleeps.append)

    def network(request, timeout):
        calls.append((request.get_method(), timeout))
        if len(calls) < 3:
            raise HTTPError(request.full_url, 503, "service sleeping", {}, None)
        return Response({"status": "ready"})

    monkeypatch.setattr(cli, "urlopen", network)
    assert cli.call("/internal/scan/status") == {"status": "ready"}
    assert calls == [("GET", 100)] * 3
    assert sleeps == [1, 2]


def test_post_is_never_automatically_replayed(monkeypatch):
    requests = []
    monkeypatch.setattr(cli, "token", lambda: "safe-fixture")
    monkeypatch.setattr(cli.time, "sleep", lambda _: pytest.fail("POST retried"))

    def failed(request, timeout):
        requests.append(request.get_method())
        raise HTTPError(request.full_url, 503, "unknown completion", {}, None)

    monkeypatch.setattr(cli, "urlopen", failed)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        cli.call("/internal/scan", method="POST")
    assert requests == ["POST"]


def test_transport_error_fails_closed_after_three_gets(monkeypatch):
    requests = []
    monkeypatch.setattr(cli, "token", lambda: "safe-fixture")
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)

    def failed(request, timeout):
        requests.append(request.get_method())
        raise URLError("network unavailable")

    monkeypatch.setattr(cli, "urlopen", failed)
    with pytest.raises(RuntimeError, match="transport unavailable"):
        cli.call("/internal/scan/status")
    assert requests == ["GET"] * 3
