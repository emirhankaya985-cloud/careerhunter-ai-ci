"""Local, owner-operated CareerHunter v2 commands — NO automated outreach.

This entrypoint operates on an explicitly chosen *local* SQLite database.
Private profiles and generated CVs must stay outside the public repository.
Production PostgreSQL and deployment are separate, approval-gated tasks.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path

from .config import load_yaml
from .cv_tailor import tailor_cv
from .database import SQLiteRepository
from .employer_corroboration import check_employer_page
from .models import FollowUp, Job, Opportunity, utc_now
from .verification import apply_evidence, verify_from_config


SOURCES = ("greenhouse", "lever", "ashby")
EVENTS = ("reviewed", "applied", "interview", "offer", "rejected", "closed")
ROOT = Path(__file__).resolve().parents[2]


def _private_file(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT):
        raise ValueError("Private candidate data / CV files cannot be stored in the public repo")
    return resolved


def _load_job(repo: SQLiteRepository, source: str, job_id: str) -> Job:
    job = repo.get_job(source, job_id)
    if job is None:
        raise ValueError("Requested source/job_id does not exist in the chosen database")
    return job


def record_manual_application(
    repo: SQLiteRepository, job: Job, status: str, *,
    confirmed: bool = False, cv_file: Path | None = None,
    proof_url: str | None = None, notes: str = "",
) -> Opportunity:
    """A state transition is local bookkeeping, never an external submission."""
    if status not in EVENTS:
        raise ValueError("Invalid tracking status")
    if status != "reviewed" and not confirmed:
        raise ValueError("Confirm the real external event with --confirm-manual-event")
    if len(notes) > 600:
        raise ValueError("Notes too long")
    opportunity_id = f"{job.source}:{job.job_id}"
    existing = repo.get_opportunity(opportunity_id)
    if existing and existing.status == status and not cv_file and not proof_url and not notes:
        return existing  # idempotent re-runs do not move dates or follow-up.
    if existing and status == "reviewed" and existing.status != "reviewed":
        raise ValueError("Cannot overwrite an existing application with reviewed")
    if cv_file:
        local_cv = _private_file(cv_file)
        if not local_cv.is_file() or local_cv.suffix.lower() != ".md":
            raise ValueError("Only an existing private Markdown CV can be fingerprinted")
        cv_sha = hashlib.sha256(local_cv.read_bytes()).hexdigest()
    else:
        cv_sha = existing.cv_sha256 if existing else None
    data = {
        "opportunity_id": opportunity_id, "title": job.title, "company": job.company,
        "job_id": job.job_id, "job_url": job.job_url, "status": status,
        "fit_score": job.match_score,
        "cv_sha256": cv_sha,
        "submission_evidence_url": proof_url or (
            str(existing.submission_evidence_url) if existing and existing.submission_evidence_url
            else None),
        "notes": notes or (existing.notes if existing else None),
        "applied_at": (existing.applied_at if existing else None)
                      or (utc_now() if status == "applied" else None),
    }
    result = Opportunity.model_validate(data)
    repo.upsert_opportunity(result)
    if status == "applied":
        followup_id = f"manual-followup:{opportunity_id}"
        if not any(f.followup_id == followup_id for f in repo.list_followups(limit=10000)):
            repo.upsert_followup(FollowUp(
                followup_id=followup_id, opportunity_id=opportunity_id,
                due_at=result.applied_at + timedelta(days=7),
                note="Check application response and follow up only if appropriate",
            ))
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m careerhunter.v2_workflow")
    root.add_argument("--db", type=Path, required=True, help="Existing LOCAL SQLite file")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("verify", "cv", "track"):
        p = commands.add_parser(name)
        p.add_argument("--source", choices=SOURCES, required=True)
        p.add_argument("--job-id", required=True)
        if name == "verify":
            p.add_argument("--employer-check", action="store_true",
                           help="Optional bounded exact-link check on configured careers page")
        if name == "cv":
            p.add_argument("--profile", type=Path, required=True)
            p.add_argument("--output", type=Path, required=True)
        if name == "track":
            p.add_argument("--status", choices=EVENTS, required=True)
            p.add_argument("--confirm-manual-event", action="store_true")
            p.add_argument("--cv-file", type=Path)
            p.add_argument("--proof-url")
            p.add_argument("--notes", default="")
    commands.add_parser("list")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if not args.db.is_file():
            raise ValueError("Database file must exist; use a private local database")
        repo = SQLiteRepository(args.db)
        if args.command == "list":
            for item in repo.list_opportunities(limit=500):
                print(f"{item.opportunity_id}\t{item.status}\t{item.title}")
            return 0
        job = _load_job(repo, args.source, args.job_id)
        if args.command == "verify":
            companies = load_yaml("companies.yaml").get("companies", [])
            result = verify_from_config(job, companies)
            if result.status == "ATS_LISTED" and args.employer_check:
                pages = [
                    str(c["team_url"]) for c in companies
                    if str(c.get("name", "")).casefold() == job.company.casefold()
                    and c.get("team_url")
                ]
                if len(pages) == 1:
                    corroboration = check_employer_page(pages[0], result.job_url)
                    if corroboration.verified:
                        result = replace(
                            result, status="EMPLOYER_CONFIRMED",
                            feed_url=corroboration.page_url,
                            reason=corroboration.reason,
                        )
            repo.update_job_evidence(apply_evidence(job, result))
            print(json.dumps(result.to_dict(), sort_keys=True))
            return 0 if result.status in {"ATS_LISTED", "EMPLOYER_CONFIRMED"} else 2
        if args.command == "cv":
            private_profile = _private_file(args.profile)
            private_output = _private_file(args.output)
            if private_output.suffix.lower() != ".md" or not private_output.parent.is_dir():
                raise ValueError("Output must be .md in an existing private directory")
            profile = json.loads(private_profile.read_text(encoding="utf-8"))
            if not isinstance(profile, dict):
                raise ValueError("Profile JSON must be an object")
            draft = tailor_cv(profile, {"title": job.title,
                                         "company": job.company,
                                         "description": job.description})
            private_output.write_text(draft.markdown, encoding="utf-8")
            print(f"CV draft written (not submitted); matched skills: {len(draft.matched_skills)}")
            return 0
        item = record_manual_application(repo, job, args.status,
            confirmed=args.confirm_manual_event, cv_file=args.cv_file,
            proof_url=args.proof_url, notes=args.notes)
        print(f"Local tracking record: {item.opportunity_id} status={item.status} (no send)")
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        # Never print profile contents, tokens or external response bodies.
        print(f"CareerHunter v2: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
