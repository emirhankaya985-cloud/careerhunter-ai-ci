from careerhunter.agents.job_matcher import RuleBasedMatcher
from careerhunter.models import Job


PROFILE = {"skills": ["Python", "SQL", "AI", "automation"], "target_roles": ["Python Developer", "AI Automation Engineer"]}
KEYWORDS = {"junior": ["junior"], "senior": ["senior", "staff"], "turkey_positive": ["worldwide", "turkey", "türkiye"], "turkey_negative": ["us only", "eu only"]}


def make_job(title="Junior Python Developer", description="Python SQL worldwide remote"):
    return Job(job_id="1", source="greenhouse", company="Acme", title=title, description=description, location="Remote", remote_type="remote", job_url="https://boards.greenhouse.io/acme/jobs/1", source_url="https://boards-api.greenhouse.io/v1/boards/acme/jobs")


def test_junior_worldwide_scores_and_verifies():
    job = RuleBasedMatcher(PROFILE, KEYWORDS).score(make_job())
    assert job.match_score >= 65
    assert job.turkey_eligibility == "verified"


def test_us_only_is_hard_rejection():
    job = RuleBasedMatcher(PROFILE, KEYWORDS).score(make_job(description="Python, remote, US only"))
    assert job.match_score == 0
    assert job.eligibility_status == "ineligible"


def test_seven_years_is_not_high_score():
    job = RuleBasedMatcher(PROFILE, KEYWORDS).score(make_job("Python Engineer", "Python, at least 7 years, worldwide"))
    assert job.match_score <= 20


def test_remote_without_country_evidence_stays_unknown():
    job = RuleBasedMatcher(PROFILE, KEYWORDS).score(make_job(description="Python remote"))
    assert job.turkey_eligibility == "unknown"
    assert job.eligibility_status == "needs_review"

