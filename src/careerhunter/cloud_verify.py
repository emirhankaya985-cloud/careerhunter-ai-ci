"""Non-destructive, repeatable PostgreSQL persistence smoke test.

The workflow uses a deterministic synthetic job.  It never truncates or deletes
rows, and only reports aggregate counts; connection strings are intentionally
never printed.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import func, select

from .database import DatabaseRepository, database_url, jobs
from .models import Job

TEST_SOURCE = "greenhouse"
TEST_JOB_ID = "careerhunter-cloud-verification-v1"


def verify(default_path: Path = Path("data/careerhunter.db")) -> tuple[int, int, int]:
    repo = DatabaseRepository(database_url(default_path))
    job = Job(
        job_id=TEST_JOB_ID,
        source=TEST_SOURCE,
        company="CareerHunter Cloud Verification",
        title="Controlled persistence smoke test (not a real vacancy)",
        location="Remote",
        remote_type="remote",
        job_url="https://example.invalid/careerhunter/cloud-verification",
        source_url="https://example.invalid/careerhunter/cloud-verification",
    )
    with repo.engine.connect() as connection:
        before = connection.execute(select(func.count()).select_from(jobs)).scalar_one()
    inserted = repo.upsert_jobs([job])
    with repo.engine.connect() as connection:
        after = connection.execute(select(func.count()).select_from(jobs)).scalar_one()
    print(f"controlled_record_id={TEST_JOB_ID}")
    print(f"jobs_before={before} jobs_after={after} jobs_new={inserted}")
    if inserted not in (0, 1):
        raise RuntimeError("unexpected upsert count")
    return int(before), int(after), inserted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/careerhunter.db"))
    args = parser.parse_args()
    verify(args.db)


if __name__ == "__main__":
    main()
