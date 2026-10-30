"""Deterministic recovery behavior tests; never hit GitHub or Telegram."""
from datetime import datetime, timedelta, timezone

import pytest

from careerhunter.daily_recovery_guard import REPOSITORY, decision, run


NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)


def scan(*, hour=7, status="completed", conclusion="failure",
         event="schedule", branch="main"):
    return {
        "created_at": NOW.replace(hour=hour, minute=0).isoformat(),
        "status": status,
        "conclusion": conclusion,
        "event": event,
        "head_branch": branch,
    }


@pytest.mark.parametrize(("history", "expected"), [
    ([scan(conclusion="success")], "healthy"),
    ([scan(status="in_progress", conclusion=None)], "running"),
    ([scan(status="queued", conclusion=None)], "running"),
    ([scan(event="workflow_dispatch")], "already_retried"),
    ([scan()], "dispatch"),
    ([], "dispatch"),
    ([scan(conclusion="success", branch="untrusted-branch")], "dispatch"),
    ([scan(event="workflow_dispatch", conclusion="success")], "healthy"),
    ([scan(), scan(hour=8, conclusion="success")], "healthy"),
])
def test_recovery_decisions(history, expected):
    assert decision(history, NOW) == expected


def test_pre_scheduled_window_never_dispatches():
    assert decision([], NOW.replace(hour=5)) == "too_early"


def test_yesterdays_success_does_not_mask_missing_daily_run():
    previous = scan(conclusion="success")
    previous["created_at"] = (NOW - timedelta(days=1)).isoformat()
    assert decision([previous], NOW) == "dispatch"


def test_invalid_created_at_cannot_claim_success():
    record = scan(conclusion="success")
    record["created_at"] = "not a timestamp"
    assert decision([record], NOW) == "dispatch"


def test_guard_dispatches_exactly_once_when_missing():
    seen = []

    def fetch(url, token, body=None):
        assert token == "unit-test-token"
        seen.append((url, body))
        if body is None:
            return {"workflow_runs": [scan(conclusion="failure")]}
        assert body == b'{"ref":"main"}'
        return None

    result = run(token="unit-test-token", repo=REPOSITORY,
                 ref="refs/heads/main", event="schedule",
                 now=NOW, fetch=fetch)
    assert result == "recovery_dispatched"
    assert len(seen) == 2
    assert seen[0][1] is None and seen[1][1] is not None
    assert seen[1][0].endswith("/actions/workflows/daily.yml/dispatches")


def test_guard_never_dispatches_when_successful_or_already_retried():
    for current in [scan(conclusion="success"), scan(event="workflow_dispatch")]:
        seen = []

        def fetch(url, token, body=None):
            seen.append((url, body))
            assert body is None
            return {"workflow_runs": [current]}

        result = run(token="unit-test-token", repo=REPOSITORY,
                     ref="refs/heads/main", event="schedule",
                     now=NOW, fetch=fetch)
        assert result in {"healthy", "already_retried"}
        assert len(seen) == 1


@pytest.mark.parametrize(("repo", "ref", "event", "token"), [
    ("other/repo", "refs/heads/main", "schedule", "test"),
    (REPOSITORY, "refs/heads/feature", "schedule", "test"),
    (REPOSITORY, "refs/heads/main", "pull_request", "test"),
    (REPOSITORY, "refs/heads/main", "schedule", ""),
])
def test_untrusted_context_cannot_dispatch(repo, ref, event, token):
    def no_network(*args, **kwargs):
        raise AssertionError("Network must not be called")

    with pytest.raises(RuntimeError):
        run(token=token, repo=repo, ref=ref, event=event,
            now=NOW, fetch=no_network)


def test_missing_or_invalid_api_response_aborts_without_dispatch():
    for payload in [{}, {"workflow_runs": None}, []]:
        calls = []

        def fetch(url, token, body=None):
            calls.append(body)
            return payload

        with pytest.raises(RuntimeError):
            run(token="test", repo=REPOSITORY, ref="refs/heads/main",
                event="schedule", now=NOW, fetch=fetch)
        assert calls == [None]
