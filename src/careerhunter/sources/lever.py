from __future__ import annotations

from careerhunter.models import Job
from careerhunter.security.validation import validate_slug

from .base import JobSource
from .common import clean_html, infer_remote, parse_datetime


class LeverSource(JobSource):
    name = "lever"

    def fetch(self, company: str, slug: str) -> list[Job]:
        slug = validate_slug(slug)
        source_url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        payload = self.get_json(source_url)
        return [self.normalize(company, item, source_url) for item in payload]

    @staticmethod
    def normalize(company: str, item: dict, source_url: str) -> Job:
        categories = item.get("categories") or {}
        location = categories.get("location") or "unknown"
        description = clean_html(" ".join(filter(None, [item.get("description"), item.get("additional")])))
        return Job(job_id=str(item["id"]), source="lever", company=company,
                   title=item["text"], location=location, description=description,
                   remote_type=infer_remote(location, description),
                   employment_type=categories.get("commitment") or "unknown",
                   published_at=parse_datetime(item.get("createdAt")),
                   job_url=item.get("hostedUrl") or item.get("applyUrl"), source_url=source_url)

