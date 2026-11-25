import httpx

from careerhunter.models import RunStats, utc_now
from careerhunter.notifications.ntfy import publish_run


def test_ntfy_is_disabled_without_topic(monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    assert publish_run(RunStats(slot="jobs", started_at=utc_now(), status="success")) is False


def test_ntfy_publishes_aggregate_run_summary(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "careerhunter-test-topic")
    captured = {}

    def fake_post(url, *, json, headers, timeout):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("careerhunter.notifications.ntfy.httpx.post", fake_post)
    stats = RunStats(
        slot="jobs", started_at=utc_now(), status="success", jobs_processed=12, jobs_new=2
    )
    assert publish_run(stats) is True
    assert captured["url"] == "https://ntfy.sh/"
    assert "İşlenen ilan: 12" in captured["json"]["message"]
    assert "Yeni ilan: 2" in captured["json"]["message"]
    assert len(captured["headers"]["X-Sequence-ID"]) == 64


def test_ntfy_marks_partial_scan_and_keeps_sequence_stable(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "careerhunter-test-topic")
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append((json, headers))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("careerhunter.notifications.ntfy.httpx.post", fake_post)
    stats = RunStats(
        slot="jobs", started_at=utc_now(), status="success", jobs_processed=5,
        error="2/7 ATS sources failed (partial result): source timeout",
    )
    assert publish_run(stats) is True
    assert "kısmi" in calls[0][0]["title"]
    assert "2/7 ATS sources failed" in calls[0][0]["message"]
    first_id = calls[0][1]["X-Sequence-ID"]
    assert publish_run(stats) is True
    assert calls[1][1]["X-Sequence-ID"] == first_id


def test_ntfy_retries_and_redacts_failure(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "careerhunter-test-topic")
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append(json)
        if len(calls) < 3:
            raise httpx.ConnectError("password=super-secret", request=httpx.Request("POST", url))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("careerhunter.notifications.ntfy.httpx.post", fake_post)
    monkeypatch.setattr("careerhunter.notifications.ntfy.time.sleep", lambda _: None)
    assert publish_run(RunStats(slot="jobs", started_at=utc_now(), status="failed",
                                error="DATABASE_URL=postgresql://user:secret@host/db")) is True
    assert len(calls) == 3
    assert "postgresql://" not in calls[-1]["message"]
