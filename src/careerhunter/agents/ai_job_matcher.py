from __future__ import annotations

from careerhunter.llm.provider import LLMProvider
from careerhunter.models import Job


class AIJobMatcher:
    def __init__(self, provider: LLMProvider, profile: dict):
        self.provider = provider
        self.profile = profile

    def enrich(self, job: Job) -> Job:
        """Optional generative AI second pass; never fabricate eligibility."""
        try:
            result = self.provider.analyze_job(
                self.profile,
                f"title={job.title}\nlocation={job.location}\ndescription={job.description[:12000]}",
            )
        except Exception:
            return job
        score = result.total
        # A model must not override verified geographical restrictions.
        if (job.turkey_eligibility == "ineligible" or
                result.turkey_eligibility == "ineligible"):
            score = 0
        if job.experience_level == "senior":
            score = min(score, 20)
        job.match_score = max(0, min(100, score))
        # Eligibility can only be improved by the explicit evidence-based pass.
        if result.turkey_eligibility == "ineligible":
            job.turkey_eligibility = "ineligible"
            job.eligibility_status = "ineligible"
        job.score_reasons = result.reasons[:8] + [
            "AI değerlendirmesi; çalışma izni ayrıca doğrulanmalıdır."
        ]
        job.gaps = result.gaps[:8]
        job.match_method = "llm"
        return job
