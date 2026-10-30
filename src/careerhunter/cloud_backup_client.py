"""GitHub OIDC client: a *one-time* cloud backup, never production cutover."""
from __future__ import annotations

import json
import sys
import time

from render_scan_client import call, wait_ready


def main() -> int:
    wait_ready()
    try:
        # Render may deploy the reviewed main commit after GitHub's push
        # workflow starts. Retry 404 only; credentials/configuration failures
        # are not treated as deployment warmup.
        status = None
        for attempt in range(30):
            try:
                status = call("/internal/cloud-backup/preflight")
                break
            except RuntimeError as exc:
                if "returned HTTP 404" not in str(exc) or attempt == 29:
                    raise
                time.sleep(20)
        if status is None:
            raise RuntimeError("Cloud backup preflight was not deployed")
        if status.get("mode") != "preflight" or not status.get("target_empty"):
            raise RuntimeError("No safe empty Neon backup target")
        print("PASS: Render source is readable; Neon backup target is empty")
        started = call("/internal/cloud-backup/start", method="POST")
        if started.get("status") not in {"running", "success"}:
            raise RuntimeError("Cloud backup did not start")
        deadline = time.monotonic() + 28 * 60
        while time.monotonic() < deadline:
            state = call("/internal/cloud-backup/status")
            if state.get("status") == "success":
                if state.get("cutover") is not False or not state.get("source_unchanged"):
                    raise RuntimeError("Backup safety evidence missing")
                if state.get("source_counts") != state.get("copied_counts"):
                    raise RuntimeError("Backup row-count evidence differs")
                print("PASS: Neon cloud backup copied and verified; Render remains primary")
                print(json.dumps({"copied_counts": state["copied_counts"],
                                  "production_cutover_performed": False},
                                 sort_keys=True))
                return 0
            if state.get("status") == "failed":
                raise RuntimeError("Cloud backup transaction failed; Render remains primary")
            time.sleep(12)
        raise RuntimeError("Cloud backup timeout; no production cutover attempted")
    except (RuntimeError, ValueError, KeyError, TypeError):
        print("FAIL: cloud backup not verified; production Render unchanged", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
