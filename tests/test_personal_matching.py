"""Privacy, ranking, persistence and repeatability regression tests."""
import json

import pytest
from sqlalchemy import select

from careerhunter.agents.job_matcher import RuleBasedMatcher
from careerhunter.database import DatabaseRepository, jobs
from careerhunter.models import Job
from careerhunter.personal_profile import load_match_profile
from careerhunter.personal_rescore import rescore_existing


def sample():
    return {
        "skills": ["Python", "FastAPI", "SQL", "PostgreSQL", "PyTorch"],
        "target_roles": ["Junior Python Developer", "AI Automation Engineer"],
        "target_countries": ["Türkiye", "United Kingdom"],
        "career_stage": "early_career",
    }


def example_job(title="Junior Python Developer", description="Python FastAPI SQL"):
    return Job(
        job_id="101", source="greenhouse", company="Example", title=title,
        location="Remote", description=description,
        remote_type="remote",
        job_url="https://boards.greenhouse.io/example/jobs/101",
        source_url="https://boards-api.greenhouse.io/v1/boards/example/jobs",
    )


def test_private_profile_overrides_public_example(monkeypatch):
    monkeypatch.setenv("CAREERHUNTER_PROFILE_JSON", json.dumps(sample()))
    assert load_match_profile()["target_roles"] == sample()["target_roles"]
    monkeypatch.setenv("CAREERHUNTER_PROFILE_JSON", '{"skills": 10}')
    with pytest.raises(ValueError, match="list"):
        load_match_profile()


def test_private_profile_fail_closed_in_render(monkeypatch):
    monkeypatch.delenv("CAREERHUNTER_PROFILE_JSON", raising=False)
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        load_match_profile()


def test_remote_title_skill_and_experience_priority():
    m = RuleBasedMatcher(sample(), {
        "junior": ["junior"], "senior": ["senior", "staff"],
    })
    junior = m.score(example_job(description="Python FastAPI SQL. Remote worldwide."))
    senior = m.score(example_job(
        title="Senior Python Engineer", description="Python FastAPI SQL 8 years experience"
    ))
    assert junior.match_score > senior.match_score
    assert junior.match_score >= 65
    assert senior.match_score <= 20
    assert junior.match_method == "rules"


def test_ineligible_remote_never_becomes_high_match():
    m = RuleBasedMatcher(sample(), {"junior": ["junior"]})
    result = m.score(example_job(description="Python FastAPI SQL. US only remote."))
    assert result.eligibility_status == "ineligible"
    assert result.match_score == 0


def test_rescore_preserves_first_seen_and_verification_time(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "match.db")
    monkeypatch.setenv("CAREERHUNTER_PROFILE_JSON", json.dumps(sample()))
    repo = DatabaseRepository(url)
    job = example_job(description="Python FastAPI SQL. Remote worldwide.")
    assert repo.upsert_jobs([job]) == 1
    with repo.engine.connect() as conn:
        before = conn.execute(select(jobs)).mappings().one()
        first_seen, verified = before["first_seen_at"], before["last_verified_at"]
    assert rescore_existing(url) == 1
    assert rescore_existing(url) == 1
    with repo.engine.connect() as conn:
        after = conn.execute(select(jobs)).mappings().one()
    enriched = Job.model_validate_json(after["payload"])
    assert enriched.match_score >= 65
    assert enriched.match_method == "rules"
    assert after["first_seen_at"] == first_seen
    assert after["last_verified_at"] == verified
    assert after["status"] == before["status"]
    repo.engine.dispose()


def test_historical_ai_pass_only_enriches_selected_jobs(tmp_path, monkeypatch):
    from careerhunter.llm.provider import JobAnalysis
    from careerhunter.personal_rescore import enrich_best_existing

    url = "sqlite:///" + str(tmp_path / "ai.db")
    monkeypatch.setenv("CAREERHUNTER_PROFILE_JSON", json.dumps(sample()))
    monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "fake-test-api-key")
    monkeypatch.setenv("MAX_DAILY_LLM_CALLS", "1")
    repo = DatabaseRepository(url)
    job = example_job(description="Python FastAPI SQL. Remote worldwide.")
    job = RuleBasedMatcher(sample(), {"junior": ["junior"]}).score(job)
    assert repo.upsert_jobs([job]) == 1

    class FakeNvidia:
        def analyze_job(self, profile, text):
            assert "Python" in profile["skills"]
            assert "Python" in text
            return JobAnalysis(
                technical_fit=30, experience_fit=20, career_fit=17,
                remote_fit=8, freshness=10, turkey_eligibility="unknown",
                reasons=["Technical match"], gaps=[]
            )

    monkeypatch.setattr("careerhunter.llm.provider.create_provider", lambda: FakeNvidia())
    assert enrich_best_existing(url, limit=20) == 1
    saved = repo.list_jobs()[0]
    assert saved.match_method == "llm"
    assert saved.match_score == 85
    # Never re-call a free model for an already LLM-enriched job.
    with pytest.raises(RuntimeError, match="no valid AI analyses"):
        enrich_best_existing(url, limit=20)
    repo.engine.dispose()


def test_intern_title_gets_junior_scoring_not_unknown_experience():
    matcher = RuleBasedMatcher(sample(), {"junior": ["junior", "internship"]})
    intern = matcher.score(example_job(
        title="Machine Learning Intern", description="Python FastAPI. Remote worldwide."
    ))
    assert intern.experience_level == "junior"
    assert intern.match_score >= 65


def test_ats_remote_worldwide_location_counts_even_when_type_unknown():
    matcher = RuleBasedMatcher(sample(), {"junior": ["internship", "junior"]})
    role = example_job(
        title="Python Intern", description="Python FastAPI trainee position."
    ).model_copy(update={"location": "Remote Worldwide", "remote_type": "unknown"})
    scored = matcher.score(role)
    assert scored.experience_level == "junior"
    assert scored.eligibility_status == "eligible"
    assert scored.match_score >= 75


def test_remote_us_only_hyphen_overrides_any_worldwide_claim():
    matcher = RuleBasedMatcher(sample(), {"junior": ["internship", "junior"]})
    role = example_job(
        title="Python Intern",
        description="Python FastAPI. Remote worldwide opportunities at this firm."
    ).model_copy(update={"location": "Remote US-only", "remote_type": "unknown"})
    scored = matcher.score(role)
    assert scored.eligibility_status == "ineligible"
    assert scored.match_score == 0


def test_domestic_ankara_without_country_name_is_eligible():
    matcher = RuleBasedMatcher(sample(), {"junior": ["internship", "junior"]})
    role = example_job(
        title="Junior Python Developer", description="Python backend work."
    ).model_copy(update={"location": "Ankara", "remote_type": "onsite"})
    scored = matcher.score(role)
    assert scored.eligibility_status == "eligible"
