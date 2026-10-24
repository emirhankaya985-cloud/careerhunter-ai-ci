from __future__ import annotations

from careerhunter.models import Job
from careerhunter.security.validation import validate_slug

from .base import JobSource
from .common import clean_html, infer_remote, parse_datetime


class GreenhouseSource(JobSource):
    name = "greenhouse"

    def fetch(self, company: str, slug: str) -> list[Job]:
        slug = validate_slug(slug)
        source_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        payload = self.get_json(source_url)
        return [self.normalize(company, item, source_url) for item in payload.get("jobs", [])]

    @staticmethod
    def normalize(company: str, item: dict, source_url: str) -> Job:
        location = (item.get("location") or {}).get("name") or "unknown"
        description = clean_html(item.get("content"))
        return Job(job_id=str(item["id"]), source="greenhouse", company=company,
                   title=item["title"], location=location, description=description,
                   remote_type=infer_remote(location, description),
                   published_at=parse_datetime(item.get("updated_at")),
                   job_url=item["absolute_url"], source_url=source_url)

