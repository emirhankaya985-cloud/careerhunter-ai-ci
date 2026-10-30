"""Owner-operated v2 workflow regression tests with isolated local SQLite."""
import hashlib
import json

import pytest

from careerhunter.database import SQLiteRepository
from careerhunter.models import Job
from careerhunter.v2_workflow import (
    _private_file, main, record_manual_application,
)
from careerhunter.agents.job_hunter import SOURCE_CLASSES


def sample_job():
    return Job(job_id="job42", source="ashby", company="OpenAI",
               title="Junior Python Backend Developer",
               job_url="https://jobs.ashbyhq.com/openai/job42",
               source_url="https://api.ashbyhq.com/posting-api/job-board/openai",
               description="Python FastAPI PostgreSQL")


def seeded_repo(tmp_path):
    db = tmp_path / "local.sqlite"
    repo = SQLiteRepository(db)
    repo.upsert_jobs([sample_job()])
    return db, repo


def test_exact_job_lookup_and_verification_update(tmp_path):
    _, repo = seeded_repo(tmp_path)
    job = repo.get_job("ashby", "job42")
    assert job is not None and job.company == "OpenAI"
    assert repo.get_job("lever", "job42") is None
    job.verification_status = "SOURCE_ERROR"
    assert repo.update_job_evidence(job)
    assert repo.get_job("ashby", "job42").verification_status == "SOURCE_ERROR"


def test_no_application_without_real_event_confirmation(tmp_path):
    _, repo = seeded_repo(tmp_path)
    with pytest.raises(ValueError, match="Confirm"):
        record_manual_application(repo, sample_job(), "applied")
    assert repo.list_opportunities() == []


def test_applied_is_idempotent_with_one_followup(tmp_path):
    _, repo = seeded_repo(tmp_path)
    draft = tmp_path / "private-cv.md"
    draft.write_text("# Example Candidate\nPython\n", encoding="utf-8")
    first = record_manual_application(
        repo, sample_job(), "applied", confirmed=True, cv_file=draft,
        proof_url="https://example.org/confirmation/123",
    )
    assert first.status == "applied"
    assert first.cv_sha256 == hashlib.sha256(draft.read_bytes()).hexdigest()
    assert first.applied_at is not None
    assert repo.get_opportunity("ashby:job42").status == "applied"
    assert len(repo.list_followups()) == 1
    second = record_manual_application(repo, sample_job(), "applied", confirmed=True)
    assert second.applied_at == first.applied_at
    assert len(repo.list_followups()) == 1


def test_cannot_downgrade_recorded_application_to_reviewed(tmp_path):
    _, repo = seeded_repo(tmp_path)
    record_manual_application(repo, sample_job(), "applied", confirmed=True)
    with pytest.raises(ValueError, match="Cannot overwrite"):
        record_manual_application(repo, sample_job(), "reviewed")


def test_cv_cli_uses_local_profile_without_outreach(tmp_path, capsys):
    db, _ = seeded_repo(tmp_path)
    profile = tmp_path / "private.json"
    profile.write_text(json.dumps({"name": "Test Applicant",
                                  "skills": ["SQL", "FastAPI", "Python"],
                                  "education": "Engineering student"}), encoding="utf-8")
    out = tmp_path / "tailored.md"
    assert main(["--db", str(db), "cv", "--source", "ashby", "--job-id", "job42",
                 "--profile", str(profile), "--output", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Test Applicant")
    assert "FastAPI, Python, SQL" in text
    assert "PostgreSQL" not in text
    assert "CV draft written (not submitted)" in capsys.readouterr().out


def test_private_files_cannot_live_inside_repo():
    from careerhunter.v2_workflow import ROOT
    with pytest.raises(ValueError, match="cannot be stored"):
        _private_file(ROOT / "config" / "private-profile.json")


def test_verify_cli_uses_configured_source_and_persists_evidence(tmp_path, monkeypatch, capsys):
    db, repo = seeded_repo(tmp_path)
    class Source:
        def __init__(self, **kwargs):
            pass
        def fetch(self, company, slug):
            assert (company, slug) == ("OpenAI", "openai")
            return [sample_job()]
    monkeypatch.setitem(SOURCE_CLASSES, "ashby", Source)
    assert main(["--db", str(db), "verify", "--source", "ashby", "--job-id", "job42"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ATS_LISTED"
    assert repo.get_job("ashby", "job42").verification_status == "ATS_LISTED"


def test_verify_error_is_not_reported_as_success(tmp_path, monkeypatch, capsys):
    db, repo = seeded_repo(tmp_path)
    class Source:
        def __init__(self, **kwargs):
            pass
        def fetch(self, company, slug):
            raise TimeoutError("test timeout")
    monkeypatch.setitem(SOURCE_CLASSES, "ashby", Source)
    assert main(["--db", str(db), "verify", "--source", "ashby", "--job-id", "job42"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "SOURCE_ERROR"
    assert repo.get_job("ashby", "job42").status != "closed"



def test_employer_corrob_requires_second_page_success(tmp_path, monkeypatch, capsys):
    from careerhunter.employer_corroboration import EmployerEvidence
    db, repo = seeded_repo(tmp_path)
    class Source:
        def __init__(self, **kwargs):
            pass
        def fetch(self, company, slug):
            return [sample_job()]
    monkeypatch.setitem(SOURCE_CLASSES, "ashby", Source)
    monkeypatch.setattr(
        "careerhunter.v2_workflow.check_employer_page",
        lambda page, posting: EmployerEvidence(
            True, "exact_posting_link_on_configured_employer_page", page
        ),
    )
    result = main(["--db", str(db), "verify", "--source", "ashby",
                   "--job-id", "job42", "--employer-check"])
    assert result == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["status"] == "EMPLOYER_CONFIRMED"
    assert repo.get_job("ashby", "job42").verification_status == "EMPLOYER_CONFIRMED"
