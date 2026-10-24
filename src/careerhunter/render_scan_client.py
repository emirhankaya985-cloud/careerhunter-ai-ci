"""CI-facing client for the Render collector. No database secrets are read here."""
from __future__ import annotations

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE = "https://careerhunter-private-dashboard.onrender.com"
AUDIENCE = "careerhunter-ai-render-collector"
_token: str | None = None
_token_timestamp = 0.0


def token() -> str:
    global _token, _token_timestamp
    if _token and time.monotonic() - _token_timestamp < 110:
        return _token
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    bearer = os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
    separator = "&" if "?" in url else "?"
    request = Request(
        url + separator + "audience=" + quote(AUDIENCE, safe=""),
        headers={"Authorization": "bearer " + bearer, "Accept": "application/json"},
    )
    with urlopen(request, timeout=25) as response:
        data = json.load(response)
    _token = data["value"]
    _token_timestamp = time.monotonic()
    return _token


def call(path: str, method: str = "GET") -> dict:
    request = Request(
        BASE + path,
        method=method,
        headers={"Authorization": "Bearer " + token(), "User-Agent": "CareerHunter-GHA/1.0"},
    )
    try:
        with urlopen(request, timeout=100) as response:
            return json.load(response)
    except HTTPError as exc:
        # Intentionally never print JWT or response bodies from unexpected failures.
        raise RuntimeError(f"Render endpoint {path} returned HTTP {exc.code}") from None


def wait_ready() -> None:
    for attempt in range(8):
        try:
            with urlopen(BASE + "/readyz", timeout=65) as response:
                if response.status == 200 and response.read(64).strip() == b"ready":
                    print("Render PostgreSQL is ready")
                    return
        except (URLError, TimeoutError):
            pass
        if attempt < 7:
            time.sleep(20)
    raise RuntimeError("Render dashboard or PostgreSQL readiness unavailable")


def main() -> int:
    wait_ready()  # Wakes a free Render instance before requesting the short-lived OIDC JWT.
    is_rescore = "--rescore" in sys.argv[1:]
    endpoint = "/internal/rescore" if is_rescore else "/internal/scan"
    started = call(endpoint, method="POST")
    if started.get("status") != "running":
        raise RuntimeError("Collector did not start: " + str(started.get("status")))
    if is_rescore and started.get("mode") != "rescore":
        raise RuntimeError("Another production task is running; retry rescore later")
    print("Authenticated Render task accepted")

    deadline = time.monotonic() + 26 * 60
    last_status = None
    while time.monotonic() < deadline:
        state = call("/internal/scan/status")
        status = state.get("status")
        if status != last_status:
            print("Collector state:", status)
            last_status = status
        if status == "success":
            if is_rescore and state.get("mode") != "rescore":
                raise RuntimeError("Rescore task was replaced by another task")
            processed = int(state.get("jobs_processed", 0))
            added = int(state.get("jobs_new", 0))
            if processed <= 0:
                raise RuntimeError("Production collector returned zero jobs")
            summary = (f"Rescored {processed} stored jobs" if is_rescore
                       else f"Collected {processed} job rows; {added} newly stored.")
            print("PASS:", summary)
            print("Partial ATS source failures:", bool(state.get("sources_partial")))
            with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a", encoding="utf-8") as out:
                out.write("### CareerHunter Render collection\n\n")
                out.write(f"- Processed: {processed}\n- New: {added}\n")
                out.write("- Target: protected Render PostgreSQL (no CI database credentials)\n")
                out.write("- Outreach: disabled\n")
            return 0
        if status in {"failed", "empty", "idle"}:
            raise RuntimeError("Collector ended without confirmed new snapshot: " + str(status))
        time.sleep(15)
    raise RuntimeError("Collector exceeded 26-minute polling limit")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, HTTPError, URLError, KeyError, ValueError) as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
