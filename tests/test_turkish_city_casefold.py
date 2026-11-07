"""Unicode casefold must not discard Turkish city eligibility signals."""
import pytest

from careerhunter.agents.job_matcher import RuleBasedMatcher
from careerhunter.models import Job


@pytest.mark.parametrize("city", [
    "İstanbul", "Istanbul", "Ankara", "İzmir", "Izmir",
])
def test_turkish_city_eligibility_without_country_suffix(city):
    job = Job(
        job_id="local-100", source="greenhouse", company="Example",
        title="Junior Python Developer", location=city,
        description="Entry-level Python FastAPI role in the named city.",
        remote_type="onsite", job_url="https://example.org/jobs/local-100",
        source_url="https://example.org/jobs",
    )
    profile = {
        "skills": ["Python", "FastAPI"],
        "target_roles": ["Junior Python Developer"],
        "target_countries": ["Türkiye"],
    }
    scored = RuleBasedMatcher(profile, {"junior": ["junior"]}).score(job)
    assert scored.experience_level == "junior"
    assert scored.eligibility_status == "eligible"
    assert scored.match_score >= 65
