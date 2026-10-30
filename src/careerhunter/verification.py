"""Conservative vacancy verification against configured first-party ATS feeds.

The ATS feed is one source, NOT independent employer-site corroboration.
Never equate 403/429/timeouts with a removed or fraudulent listing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping

from .agents.job_hunter import SOURCE_CLASSES
from .models import Job, utc_now


@dataclass(frozen=True)
class Verification:
    status: str
    source: str
    job_id: str
    company: str
    observed_at: str
    feed_url: str
    job_url: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def attest_collected(job: Job) -> Job:
    """Mark a job returned by a successfully parsed configured ATS response."""
    job.verification_status = "ATS_LISTED"
    job.verification_observed_at = utc_now()
    job.verification_evidence_url = job.source_url
    return job


def verify_from_config(
    job: Job, companies: list[Mapping[str, Any]], *, timeout: float = 12.0, retries: int = 2
) -> Verification:
    """Refetch the relevant configured ATS board; classify result without overclaiming."""
    now = utc_now().isoformat()
    base = {
        "source": job.source, "job_id": job.job_id, "company": job.company,
        "observed_at": now, "feed_url": str(job.source_url), "job_url": str(job.job_url),
    }
    boards = [
        entry for entry in companies
        if str(entry.get("name", "")).casefold() == job.company.casefold()
        and entry.get(job.source)
    ]
    if len(boards) != 1 or job.source not in SOURCE_CLASSES:
        return Verification(status="REVIEW_REQUIRED", reason="no_unique_configured_ats_board", **base)
    source = SOURCE_CLASSES[job.source](timeout=timeout, retries=retries)
    try:
        candidates = source.fetch(job.company, str(boards[0][job.source]))
    except Exception:
        # Intentionally no exception text: upstream exceptions may contain URLs/secrets.
        return Verification(status="SOURCE_ERROR", reason="ats_fetch_failed", **base)
    matched = next((item for item in candidates if item.job_id == job.job_id
                    and item.company.casefold() == job.company.casefold()), None)
    if matched is None:
        return Verification(
            status="NOT_FOUND_AT_LAST_CHECK",
            reason="id_absent_in_successfully_fetched_board_not_proof_of_fraud",
            **base,
        )
    return Verification(
        status="ATS_LISTED", reason="same_source_and_job_id_present_in_configured_ats_board",
        source=job.source, job_id=job.job_id, company=job.company,
        observed_at=now, feed_url=str(matched.source_url), job_url=str(matched.job_url),
    )


def apply_evidence(job: Job, result: Verification) -> Job:
    """Update JSON-only model fields; never invent second-source confirmation."""
    job.verification_status = result.status
    job.verification_observed_at = datetime.fromisoformat(result.observed_at)
    job.verification_evidence_url = result.feed_url
    return job
