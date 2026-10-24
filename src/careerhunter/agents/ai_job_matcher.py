from __future__ import annotations

from careerhunter.llm.provider import LLMProvider
from careerhunter.models import Job


class AIJobMatcher:
    def __init__(self, provider: LLMProvider, profile: dict):
        self.provider = provider
        self.profile = profile

    def enrich(self, job: Job) -> Job:
        """Enrich only pre-filtered jobs; safe failure keeps the rule-based result."""
        try:
            result = self.provider.analyze_job(
                self.profile,
                f"title={job.title}\nlocation={job.location}\ndescription={job.description[:12000]}",
            )
        except Exception:
            return job
        job.match_score = result.total
        job.turkey_eligibility = result.turkey_eligibility
        job.eligibility_status = (
            "eligible" if result.turkey_eligibility == "verified"
            else "ineligible" if result.turkey_eligibility == "ineligible"
            else "needs_review"
        )
        job.score_reasons = result.reasons
        job.gaps = result.gaps
        return job
