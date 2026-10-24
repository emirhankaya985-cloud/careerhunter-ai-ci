from __future__ import annotations

import hashlib
from collections import defaultdict

from ..models import CompanySignal, Job


def build_company_signals(jobs: list[Job]) -> list[CompanySignal]:
    """Derive conservative signals solely from observed ATS records.

    This deliberately does not infer funding, growth, or hiring intent beyond the
    number of currently observed listings and their source URLs.
    """
    grouped: dict[str, list[Job]] = defaultdict(list)
    for job in jobs:
        grouped[job.company.strip()].append(job)
    signals: list[CompanySignal] = []
    for company, company_jobs in grouped.items():
        company_id = hashlib.sha256(company.casefold().encode("utf-8")).hexdigest()[:24]
        urls = list(dict.fromkeys(str(job.job_url) for job in company_jobs))
        evidence = [job.job_url for job in company_jobs[:10]]
        count = len(company_jobs)
        confidence = "high" if count >= 3 else "medium"
        signals.append(CompanySignal(
            company_id=company_id,
            company=company,
            signal_type="hiring_activity",
            claim=f"Observed {count} open ATS listing(s) in the current scan; this does not establish broader expansion.",
            evidence_urls=evidence,
            evidence_count=len(urls),
            confidence=confidence,
        ))
        remote_jobs = [job for job in company_jobs if job.remote_type == "remote"]
        if remote_jobs:
            signals.append(CompanySignal(
                company_id=company_id,
                company=company,
                signal_type="remote_activity",
                claim=f"Observed {len(remote_jobs)} listing(s) explicitly marked remote; Türkiye eligibility remains separate.",
                evidence_urls=[job.job_url for job in remote_jobs[:10]],
                evidence_count=len(remote_jobs),
                confidence="medium",
            ))
    return signals
