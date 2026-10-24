"""One-time re-ranking of existing private PostgreSQL records.

No ATS API calls, no job freshness changes, and no personal profile exports.
"""
from __future__ import annotations

from .agents.job_matcher import RuleBasedMatcher
from .config import load_yaml
from .database import DatabaseRepository
from .personal_profile import load_match_profile


def rescore_existing(url: str, *, batch_size: int = 100) -> int:
    profile = load_match_profile()
    matcher = RuleBasedMatcher(profile, load_yaml("keywords.yaml"))
    repo = DatabaseRepository(url)
    try:
        existing = repo.list_jobs(active_only=False, limit=200000)
        total = 0
        for start in range(0, len(existing), batch_size):
            jobs = existing[start:start + batch_size]
            scored = [matcher.score(job) for job in jobs]
            total += repo.update_job_scores(scored)
        return total
    finally:
        repo.engine.dispose()


def enrich_best_existing(url: str, *, limit: int = 8) -> int:
    """Add NVIDIA semantic analysis to a tiny, bounded set of top-ranked jobs.

    Only use explicitly configured provider credentials. Never submit all
    historic jobs to the public trial endpoint; rule scores remain the fallback.
    """
    from .agents.ai_job_matcher import AIJobMatcher
    from .llm.provider import create_provider, configured_provider

    if configured_provider() != "nvidia":
        raise RuntimeError("NVIDIA Build API key is not configured in Render")
    provider = create_provider()
    if provider is None:
        raise RuntimeError("NVIDIA provider unavailable")
    repo = DatabaseRepository(url)
    try:
        jobs = repo.list_jobs(active_only=True, limit=10000)
        eligible = [
            j for j in jobs
            if (j.match_score or 0) >= 65
            and j.eligibility_status != "ineligible"
            and j.match_method != "llm"
        ]
        eligible.sort(key=lambda job: job.match_score or 0, reverse=True)
        from os import getenv
        max_calls = max(0, int(getenv("MAX_DAILY_LLM_CALLS", "8")))
        selected = eligible[:min(limit, max_calls)]
        matcher = AIJobMatcher(provider, load_match_profile())
        updated = []
        for job in selected:
            matcher.enrich(job)
            if job.match_method == "llm":
                updated.append(job)
        if not updated:
            raise RuntimeError("NVIDIA returned no valid AI analyses")
        return repo.update_job_scores(updated)
    finally:
        repo.engine.dispose()
