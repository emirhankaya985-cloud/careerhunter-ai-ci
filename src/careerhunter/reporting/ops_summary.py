"""Operational status and ntfy report for the scheduled production workflow.

Never substitutes the dashboard page length for full-database aggregates.
The source dashboard is one export; this module only reads its JSON data.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from ..notifications.ntfy import publish

COUNTRIES = {"US": "United States", "GB": "United Kingdom",
             "AU": "Australia", "TR": "Türkiye"}


def build_summary(data: dict[str, Any] | None, *, outcomes: dict[str, str],
                  event: str, sha: str) -> dict[str, Any]:
    """Summarize an existing export, with explicit failure instead of fake zeros."""
    scheduled = event in {"schedule", "push"}
    must_succeed = ["database", "collection", "export"]
    if scheduled:
        must_succeed.append("network")
    failed = [name for name in must_succeed if outcomes.get(name) != "success"]
    summary: dict[str, Any] = {
        "status": "failed" if failed else "success",
        "event": event, "commit_sha": sha, "stages": outcomes,
        "failed_stages": failed, "mode": "production_collection",
        "notification_delivery": "transport HTTP only; phone receipt unverified",
    }
    if data is None:
        summary["status"] = "failed"
        summary["error"] = "dashboard.json missing or unreadable"
        return summary
    agg = data.get("aggregates")
    if not isinstance(agg, dict) or not all(k in agg for k in ("total", "new_24h", "countries")):
        summary["status"] = "failed"
        summary["error"] = "full-database aggregates missing"
        return summary
    if not 0 <= agg["new_24h"] <= agg["total"]:
        summary["status"] = "failed"
        summary["error"] = "global new count exceeds total"
    grouped = {}
    for code, name in COUNTRIES.items():
        row = agg["countries"].get(name)
        if not isinstance(row, dict) or not all(k in row for k in ("total", "new_24h")):
            summary["status"] = "failed"
            summary["error"] = f"missing {code} country aggregate"
            continue
        total, new = row["total"], row["new_24h"]
        if not 0 <= new <= total:
            summary["status"] = "failed"
            summary["error"] = f"invalid {code} subset count"
        grouped[code] = {"total": total, "new_24h": new}
    contacts = data.get("contacts", [])
    summary.update({
        "snapshot_id": data.get("snapshot_id"),
        "snapshot_at": data.get("snapshot_at"),
        "total_jobs": agg["total"],
        "new_jobs_24h": agg["new_24h"],
        "displayed_jobs": len(data.get("jobs", [])),
        "people": len(contacts),
        "drafts": sum(bool(c.get("message_variant_a") or c.get("message_variant_a_tr"))
                      for c in contacts),
        "countries": grouped,
    })
    latest = data.get("latest_run") or {}
    if latest.get("error"):
        summary["source_warnings"] = "Some sources had errors; see job report and latest_run"
    return summary


def notify(summary: dict[str, Any]) -> bool:
    ok = summary.get("status") == "success"
    countries = summary.get("countries") or {}
    rows = [
        f"{code}: {counts['total']} toplam / {counts['new_24h']} yeni"
        for code, counts in countries.items()
    ]
    message = "\n".join([
        "✅ CareerHunter günlük raporu" if ok else "🚨 CareerHunter günlük çalışma hatası",
        f"Durum: {summary.get('status', 'unknown')}",
        f"Toplam ilan: {summary.get('total_jobs', 'N/A')}",
        f"Son 24 saat yeni: {summary.get('new_jobs_24h', 'N/A')}",
        f"Kişi: {summary.get('people', 'N/A')} | Taslak: {summary.get('drafts', 'N/A')}",
        *rows,
        f"Hatalı adımlar: {', '.join(summary.get('failed_stages', [])) or 'yok'}",
        f"Commit: {str(summary.get('commit_sha', 'unknown'))[:12]}",
    ])
    return publish(message, title="CareerHunter günlük sonuç" if ok
                   else "CareerHunter otomasyon hatası", priority=3 if ok else 4)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=Path("reports/daily-run.json"))
    p.add_argument("--snapshot", type=Path, default=Path("reports/dashboard.json"))
    p.add_argument("--notify", action="store_true")
    args = p.parse_args()
    if args.notify:
        if not args.output.is_file():
            print("Cannot notify: daily summary missing")
            return 1
        summary = json.loads(args.output.read_text(encoding="utf-8"))
        sent = notify(summary)
        print("Notification transport accepted" if sent else "Notification unavailable or rejected")
        return 0 if sent else 1
    data = None
    if args.snapshot.is_file():
        try:
            data = json.loads(args.snapshot.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    outcomes = {
        "database": os.getenv("DB_RESULT", "unknown"),
        "collection": os.getenv("COLLECT_RESULT", "unknown"),
        "network": os.getenv("NETWORK_RESULT", "unknown"),
        "export": os.getenv("EXPORT_RESULT", "unknown"),
    }
    summary = build_summary(data, outcomes=outcomes,
                            event=os.getenv("EVENT_NAME", ""),
                            sha=os.getenv("GITHUB_SHA", "unknown"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
