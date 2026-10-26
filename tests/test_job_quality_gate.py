"""Regression cases for the CareerHunter user-facing Telegram alert gate."""
import pytest

from careerhunter.job_quality import evaluate
from careerhunter.telegram_only_report import make_messages


def candidate(title, location="Remote", score=76, **changes):
    job = {
        "title": title,
        "location": location,
        "score": score,
        "level": "junior",
        "eligibility": "needs_review",
        "description": "Python FastAPI PostgreSQL with junior team.",
        "skills": ["Python", "FastAPI", "PostgreSQL"],
    }
    job.update(changes)
    return job


@pytest.mark.parametrize(("title", "location", "score"), [
    ("Software Engineer", "Taiwan", 20),
    ("Applied AI Architect, OpenAI for Government", "Munich, Germany", 20),
    ("Operations Program Manager", "Bengaluru", 17),
    ("Head of Marketing, Japan", "Tokyo", 12),
    ("Account Executive, Money Management", "Singapore", 12),
])
def test_five_real_bad_alerts_are_all_filtered(title, location, score):
    allowed, reason = evaluate(candidate(title, location, score=score))
    assert not allowed, reason


@pytest.mark.parametrize("title", [
    "Junior Python Backend Developer",
    "Backend Engineer",
    "Machine Learning Intern",
    "AI Engineer",
    "QA Automation Engineer",
    "Computer Vision Engineer",
    "Data Science Intern",
    "Software Engineering Intern",
])
def test_relevant_early_career_roles_are_eligible(title):
    assert evaluate(candidate(title, "Remote")) == (True, "potential_match")


@pytest.mark.parametrize("title", [
    "Head of AI",
    "Principal Python Developer",
    "Senior Machine Learning Engineer",
    "Operations Program Manager",
    "Software Engineering Manager",
    "Software Architect",
    "QA Manual Tester",
    "Marketing Automation Manager",
])
def test_non_junior_and_unrelated_positions_are_rejected(title):
    assert not evaluate(candidate(title))[0]


def test_non_target_country_is_not_reported_without_global_eligibility():
    assert not evaluate(candidate("Junior Python Developer", "Taiwan"))[0]
    assert not evaluate(candidate("Junior Python Developer", "Remote, Singapore"))[0]
    assert not evaluate(candidate("Junior Python Developer", "Munich, Germany"))[0]
    assert evaluate(candidate("Junior Python Developer", "Munich, Germany",
                              eligibility="eligible"))[0]


def test_python_stack_is_needed_for_generic_software_roles():
    assert not evaluate(candidate(
        "Software Engineer", "London",
        skills=[], description="Frontend only JavaScript React and CSS"))[0]
    assert evaluate(candidate(
        "Software Engineer", "London",
        skills=["Python"], description="Backend FastAPI APIs"))[0]


def test_ineligible_or_below_minimum_is_rejected_even_if_title_matches():
    assert not evaluate(candidate(
        "Junior Python Developer", eligibility="ineligible"))[0]
    assert not evaluate(candidate(
        "Junior Python Developer", score=20))[0]
    assert not evaluate(candidate(
        "Junior Python Developer", level="senior"))[0]


def test_zero_good_jobs_message_reports_filtered_count_without_wrong_links():
    payload = {"status": "ready", "jobs_new": 5,
               "items": [], "listed_count": 0, "quality_rejected": 5}
    results = make_messages(payload)
    assert len(results) == 1
    text, buttons = results[0]
    assert "5" in text and "Sana uygun yeni ilan: <b>0</b>" in text
    assert "filtrelendi" in text
    assert buttons == []


def test_live_digest_can_show_one_good_job_without_all_the_bad_ones():
    payload = {
        "status": "ready", "jobs_new": 5, "listed_count": 1,
        "quality_rejected": 4, "strong_count": 1,
        "items": [{
            "title": "Junior Python Developer",
            "company": "Example",
            "location": "Remote",
            "url": "https://example.org/jobs/junior-python",
            "score": 84,
            "level": "junior",
            "eligibility": "needs_review",
        }],
    }
    rendered = make_messages(payload)
    assert len(rendered) == 1
    assert len(rendered[0][1]) == 1
    assert "Junior Python Developer" in rendered[0][0]
    assert "Uygun: <b>1</b>" in rendered[0][0]
