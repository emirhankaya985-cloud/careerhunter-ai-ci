"""Idempotent, zero-secret GitHub recovery guard for the daily CareerHunter scan.

Run after the normal collection window. One recovery dispatch at most per UTC
day; never restart an in-flight scan or duplicate a successful collection.
This agent cannot access production DB credentials, the private CV, or Telegram.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPOSITORY = "emirhankaya985-cloud/careerhunter-ai-ci"
WORKFLOW = "daily.yml"
API_ROOT = "https://api.github.com/repos/" + REPOSITORY
USER_AGENT = "CareerHunter-Recovery-Guard/1.0"


def _created_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None


def decision(runs: list[dict], now: datetime) -> str:
    """Choose one of: too_early, healthy, running, already_retried, dispatch.

    A 06:00 UTC window prevents yesterday's successful scheduled scan from
    suppressing today's recovery. We only run this guard after 08:40 UTC.
    """
    now = now.astimezone(timezone.utc)
    window_start = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now < window_start:
        return "too_early"
    current = []
    for run in runs:
        if not isinstance(run, dict) or run.get("head_branch") != "main":
            continue
        started = _created_at(run.get("created_at"))
        if started is not None and window_start <= started <= now:
            current.append(run)

    if any(run.get("status") == "completed" and
           run.get("conclusion") == "success" for run in current):
        return "healthy"
    if any(run.get("status") in {"queued", "in_progress", "requested",
                                 "waiting", "pending"} for run in current):
        return "running"
    # A manual run OR a previous watchdog dispatch counts as this day's
    # single recovery. This guard must never create a retry loop.
    if any(run.get("event") == "workflow_dispatch" for run in current):
        return "already_retried"
    return "dispatch"


def _request(url: str, token: str, body: bytes | None = None) -> dict | None:
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, method="POST" if body is not None else "GET",
                      headers=headers)
    with urlopen(request, timeout=25) as response:
        if body is not None:
            if response.status != 204:
                raise RuntimeError("GitHub did not accept dispatch")
            return None
        if response.status != 200:
            raise RuntimeError("GitHub workflow history unavailable")
        parsed = json.load(response)
        if not isinstance(parsed, dict):
            raise RuntimeError("GitHub workflow history invalid")
        return parsed


def run(*, token: str, repo: str, ref: str, event: str,
        now: datetime | None = None, fetch=_request) -> str:
    # Production guard cannot be repurposed by fork PRs or arbitrary branches.
    if repo != REPOSITORY or ref != "refs/heads/main":
        raise RuntimeError("Recovery limited to the exact production main branch")
    if event not in {"schedule", "workflow_dispatch"}:
        raise RuntimeError("Recovery requires a scheduled or owner-triggered run")
    if not token:
        raise RuntimeError("GitHub Actions recovery token is missing")
    now = now or datetime.now(timezone.utc)
    history_url = (API_ROOT + "/actions/workflows/" + WORKFLOW
                   + "/runs?branch=main&per_page=50")
    result = fetch(history_url, token)
    if not isinstance(result, dict) or not isinstance(result.get("workflow_runs"), list):
        raise RuntimeError("GitHub did not return the expected workflow list")
    choice = decision(result["workflow_runs"], now)
    if choice != "dispatch":
        return choice

    # A dispatch is permissible only when no scan has succeeded, is running,
    # or has already been manually retried since 06:00 UTC today.
    body = json.dumps({"ref": "main"}, separators=(",", ":")).encode("utf-8")
    fetch(API_ROOT + "/actions/workflows/" + WORKFLOW + "/dispatches", token, body)
    return "recovery_dispatched"


def main() -> int:
    try:
        result = run(token=os.getenv("GH_TOKEN", ""),
                     repo=os.getenv("GITHUB_REPOSITORY", ""),
                     ref=os.getenv("GITHUB_REF", ""),
                     event=os.getenv("GITHUB_EVENT_NAME", ""))
    except (RuntimeError, HTTPError, URLError, TimeoutError, ValueError, OSError):
        # Avoid showing token-bearing HTTP exception URLs in runner logs.
        print("FAIL: CareerHunter daily recovery guard could not verify/dispatch")
        return 1
    print("CareerHunter daily recovery guard:", result)
    output = os.getenv("GITHUB_STEP_SUMMARY")
    if output:
        with open(output, "a", encoding="utf-8") as file:
            file.write("### Daily recovery guard\n\nResult: " + result + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
