"""Notification gating after GitHub Actions retry, no real API calls."""
import json
from io import BytesIO
from types import SimpleNamespace

import pytest

from careerhunter import telegram_attempt_guard as guard


@pytest.mark.parametrize(("conclusion", "earlier", "expected"), [
    ("success", [], True),
    ("failure", [], True),
    ("success", ["failure"], True),
    ("success", ["failure", "failure", "failure"], True),
    ("failure", ["failure"], False),
    ("cancelled", ["failure"], False),
    ("success", ["success"], False),
    ("success", ["failure", "success"], False),
])
def test_retried_workflow_only_reports_first_success(conclusion, earlier, expected):
    assert guard.should_notify(conclusion, earlier) is expected


def test_read_previous_attempts_readonly(monkeypatch):
    seen = []

    def fake_open(request, timeout):
        seen.append((request.full_url, request.get_header("Authorization"), timeout))
        return SimpleNamespace(
            __enter__=lambda self: self,
            __exit__=lambda self, *args: None,
        )

    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def api(request, timeout):
        seen.append(request.full_url)
        number = len(seen)
        return Response(json.dumps({"status": "completed",
                                    "conclusion": "failure" if number < 3 else "success"}).encode())

    monkeypatch.setattr(guard, "urlopen", api)
    result = guard.previous_conclusions(token="test-only-token", run_id=123, attempt=4)
    assert result == ["failure", "failure", "success"]
    assert all("attempts/" in url for url in seen)


def test_run_outputs_duplicate_safe_flag(tmp_path, monkeypatch):
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_REPOSITORY", guard.REPO)
    monkeypatch.setenv("PARENT_RUN_ID", "41178548813")
    monkeypatch.setenv("PARENT_RUN_ATTEMPT", "4")
    monkeypatch.setenv("PARENT_CONCLUSION", "success")
    monkeypatch.setenv("GITHUB_TOKEN", "fixture")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(guard, "previous_conclusions",
                        lambda **kwargs: ["failure", "failure", "failure"])
    assert guard.run() is True
    assert output.read_text() == "notify=true\n"

    output.write_text("")
    monkeypatch.setattr(guard, "previous_conclusions", lambda **kwargs: ["success"])
    assert guard.run() is False
    assert output.read_text() == "notify=false\n"
