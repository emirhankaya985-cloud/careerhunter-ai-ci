from __future__ import annotations

import logging

from careerhunter.models import Job
from careerhunter.security.validation import validate_slug

from .base import JobSource, SourceError
from .common import clean_html, infer_remote, parse_datetime


class AshbySource(JobSource):
    name = "ashby"

    logger = logging.getLogger(__name__)

    def fetch(self, company: str, slug: str) -> list[Job]:
        slug = validate_slug(slug)
        source_url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        payload = self.get_json(source_url)
        items = payload.get("jobs", [])
        if not isinstance(items, list):
            raise SourceError(f"{self.name}: invalid_jobs_payload")
        jobs = []
        skipped = 0
        for item in items:
            # Ashby occasionally publishes an incomplete posting. One blank
            # title must not discard the rest of a valid company board.
            if not isinstance(item, dict) or not str(item.get("title") or "").strip():
                skipped += 1
                continue
            jobs.append(self.normalize(company, item, source_url))
        if skipped:
            self.logger.warning("Ashby %s: skipped %d postings with empty titles", slug, skipped)
        if items and not jobs:
            raise SourceError(f"{self.name}: no_valid_jobs")
        return jobs

    @staticmethod
    def normalize(company: str, item: dict, source_url: str) -> Job:
        location = item.get("location") or "unknown"
        description = clean_html(item.get("descriptionHtml") or item.get("descriptionPlain"))
        remote = "remote" if item.get("isRemote") else infer_remote(location, description)
        job_url = item.get("jobUrl") or item.get("applyUrl")
        return Job(job_id=str(item.get("id") or job_url.rsplit("/", 1)[-1]), source="ashby",
                   company=company, title=item["title"], location=location,
                   description=description, remote_type=remote,
                   employment_type=item.get("employmentType") or "unknown",
                   published_at=parse_datetime(item.get("publishedAt")),
                   job_url=job_url, source_url=source_url)
