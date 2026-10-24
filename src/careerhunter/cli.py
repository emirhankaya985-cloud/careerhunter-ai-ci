from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import project_path
from .database import create_repository, import_legacy_sqlite
from .models import Contact
from .orchestrator import Orchestrator


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="careerhunter")
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--slot", required=True, choices=["jobs", "network", "future", "weekly"])
    run.add_argument("--dry-run", action="store_true")
    commands.add_parser("status")
    report = commands.add_parser("report")
    report.add_argument("--latest", action="store_true", required=True)
    commands.add_parser("doctor")
    migrate = commands.add_parser("migrate-sqlite")
    migrate.add_argument("--source", required=True, type=Path)
    contact = commands.add_parser("contact")
    contact_commands = contact.add_subparsers(dest="contact_command", required=True)
    contact_import = contact_commands.add_parser("import")
    contact_import.add_argument("--file", required=True, type=Path)
    contact_update = contact_commands.add_parser("update")
    contact_update.add_argument("--id", required=True)
    contact_update.add_argument("--status", required=True)
    contact_commands.add_parser("list")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    db_path = Path(os.getenv("CAREERHUNTER_DB", project_path("data", "careerhunter.db")))
    if args.command == "run":
        try:
            stats, report = Orchestrator(db_path).run(args.slot, args.dry_run)
            print(
                f"status={stats.status} processed={stats.jobs_processed} new={stats.jobs_new} "
                f"llm_calls={stats.llm_calls} llm_tokens={stats.llm_tokens} report={report}"
            )
            return 0
        except Exception as exc:
            print(f"run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    if args.command == "status":
        row = create_repository(db_path).latest_run()
        print(row if row else "No runs recorded")
        return 0
    if args.command == "contact":
        repo = create_repository(db_path)
        if args.contact_command == "import":
            raw = json.loads(args.file.read_text(encoding="utf-8"))
            contacts = raw if isinstance(raw, list) else [raw]
            for item in contacts:
                repo.upsert_contact(Contact.model_validate(item))
            print(f"Imported {len(contacts)} contact(s)")
            return 0
        if args.contact_command == "update":
            try:
                updated = repo.update_contact_status(args.id, args.status)
            except (KeyError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(f"{updated.person_id}: {updated.status}")
            return 0
        for contact in repo.list_contacts():
            print(f"{contact.person_id}\t{contact.status}\t{contact.name}\t{contact.company}")
        return 0
    if args.command == "migrate-sqlite":
        counts = import_legacy_sqlite(args.source, create_repository(db_path))
        print(json.dumps(counts, sort_keys=True))
        return 0
    if args.command == "report":
        reports = sorted(project_path("reports").glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not reports:
            print("No reports found", file=sys.stderr)
            return 1
        print(reports[0].read_text(encoding="utf-8"))
        return 0
    checks = {
        "python": sys.version_info >= (3, 11),
        "config/profile.yaml": project_path("config", "profile.yaml").exists(),
        "config/companies.yaml": project_path("config", "companies.yaml").exists(),
        "database_configured": bool(os.getenv("DATABASE_URL")) or os.access(db_path.parent, os.W_OK),
        "llm_mode": bool(os.getenv("LLM_API_KEY")) or os.getenv("LLM_PROVIDER", "rules") == "rules",
    }
    for name, ok in checks.items():
        print(f"{'OK' if ok else 'FAIL'} {name}")
    return 0 if all(checks.values()) else 1

