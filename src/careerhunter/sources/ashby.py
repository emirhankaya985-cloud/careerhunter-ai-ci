from __future__ import annotations

from careerhunter.models import Job
from careerhunter.security.validation import validate_slug

from .base import JobSource
from .common import clean_html, infer_remote, parse_datetime


class AshbySource(JobSource):
    name = "ashby"

    def fetch(self, company: str, slug: str) -> list[Job]:
        slug = validate_slug(slug)
        source_url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        payload = self.get_json(source_url)
        return [self.normalize(company, item, source_url) for item in payload.get("jobs", [])]

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
