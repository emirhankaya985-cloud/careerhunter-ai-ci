"""Suppress duplicate Telegram on retried parent workflow attempts.

A failed first scan may be retried successfully and should send one
fresh daily digest. A run that already succeeded must never send twice.
GitHub workflow_run events are not presumed idempotent.
"""
from __future__ import annotations

import json
import os
import sys
from urllib.request import Request, urlopen

REPO = "emirhankaya985-cloud/careerhunter-ai-ci"


def should_notify(current: str, earlier: list[str]) -> bool:
    if "success" in earlier:
        return False
    if current == "success":
        return True
    return not earlier


def previous_conclusions(*, token: str, run_id: int, attempt: int) -> list[str]:
    results = []
    for previous in range(1, attempt):
        url = (
            f"https://api.github.com/repos/{REPO}/actions/runs/"
            f"{run_id}/attempts/{previous}"
        )
        req = Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urlopen(req, timeout=18) as response:
            info = json.load(response)
        if info.get("status") != "completed" or not isinstance(info.get("conclusion"), str):
            raise RuntimeError("Prior workflow attempt has no verified conclusion")
        results.append(info["conclusion"])
    return results


def run() -> bool:
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise RuntimeError("Unexpected repository")
    run_id = int(os.environ["PARENT_RUN_ID"])
    attempt = int(os.environ["PARENT_RUN_ATTEMPT"])
    if run_id < 1 or not 1 <= attempt <= 20:
        raise ValueError("Invalid parent run ID or attempt")
    conclusion = os.environ["PARENT_CONCLUSION"]
    if conclusion not in {"success", "failure", "cancelled", "timed_out"}:
        raise ValueError("Unrecognized parent conclusion")
    # No network needed for the first run; GitHub API is read-only for reruns.
    earlier = (previous_conclusions(
        token=os.environ["GITHUB_TOKEN"], run_id=run_id, attempt=attempt)
        if attempt > 1 else [])
    allowed = should_notify(conclusion, earlier)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"notify={'true' if allowed else 'false'}\n")
    print("Eligible first confirmed result" if allowed else "SKIP: previously reported or repeated failure")
    return allowed


if __name__ == "__main__":
    try:
        run()
    except (RuntimeError, ValueError, KeyError, OSError, TypeError) as exc:
        print(f"FAIL CLOSED: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
