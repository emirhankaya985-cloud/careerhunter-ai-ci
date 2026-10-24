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
