"""GitHub OIDC-only reporter for actual Postgres archive recovery."""
from __future__ import annotations

import sys
import time

from .render_scan_client import call, wait_ready


def main() -> int:
    wait_ready()
    tools = call("/internal/pg-restore/tooling")
    if tools.get("installed") is not True:
        raise RuntimeError("pg_dump/pg_restore are absent from the Render runtime")
    if tools.get("enabled") is not True:
        raise RuntimeError("Restore acceptance is not enabled in Render")
    starting = call("/internal/pg-restore/start", method="POST")
    if starting.get("status") != "running":
        raise RuntimeError("Restore acceptance cannot start")
    for _ in range(60):
        state = call("/internal/pg-restore/status")
        if state.get("status") == "success":
            if not (state.get("pg_dump") is True
                    and state.get("pg_restore") is True
                    and state.get("tables") == 10
                    and state.get("render_source_untouched") is True):
                raise RuntimeError("Incomplete real restore evidence")
            print("PASS: real PostgreSQL pg_dump and pg_restore")
            print("Verified tables:", state.get("tables"))
            print("Verified jobs:", state.get("jobs"))
            print("Verified runs:", state.get("runs"))
            return 0
        if state.get("status") in {"failed", "idle"}:
            raise RuntimeError("Real recovery test failed")
        time.sleep(15)
    raise RuntimeError("Real recovery test timed out")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
