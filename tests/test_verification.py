"""Conservative vacancy evidence classification — never fake a second source."""
from careerhunter.models import Job
from careerhunter.verification import (
    apply_evidence, attest_collected, verify_from_config,
)
from careerhunter.agents.job_hunter import SOURCE_CLASSES


def job(job_id="job42", company="Example"):
    return Job(job_id=job_id, source="ashby", company=company,
               title="Junior Python Engineer",
               job_url="https://jobs.ashbyhq.com/example/job42",
               source_url="https://api.ashbyhq.com/posting-api/job-board/example")


CONFIG = [{"name": "Example", "ashby": "example"}]


def test_successful_collection_proves_only_ats_listing():
    item = attest_collected(job())
    assert item.verification_status == "ATS_LISTED"
    assert str(item.verification_evidence_url) == str(item.source_url)
    assert item.verification_observed_at is not None


def test_same_id_in_configured_board(monkeypatch):
    class Source:
        def __init__(self, **kwargs):
            pass

        def fetch(self, company, slug):
            assert (company, slug) == ("Example", "example")
            return [job()]

    monkeypatch.setitem(SOURCE_CLASSES, "ashby", Source)
    result = verify_from_config(job(), CONFIG)
    assert result.status == "ATS_LISTED"
    assert "same_source_and_job_id" in result.reason
    assert "EMPLOYER_CONFIRMED" != result.status
    assert apply_evidence(job(), result).verification_status == "ATS_LISTED"


def test_absence_does_not_imply_fraud_or_confirm_closure(monkeypatch):
    class Source:
        def __init__(self, **kwargs):
            pass

        def fetch(self, company, slug):
            return [job("different")]

    monkeypatch.setitem(SOURCE_CLASSES, "ashby", Source)
    result = verify_from_config(job(), CONFIG)
    assert result.status == "NOT_FOUND_AT_LAST_CHECK"
    assert "not_proof_of_fraud" in result.reason


def test_outage_is_source_error_not_missing(monkeypatch):
    class Source:
        def __init__(self, **kwargs):
            pass

        def fetch(self, company, slug):
            raise TimeoutError("do not reveal internal URLs")

    monkeypatch.setitem(SOURCE_CLASSES, "ashby", Source)
    result = verify_from_config(job(), CONFIG)
    assert result.status == "SOURCE_ERROR"
    assert "internal URLs" not in result.reason


def test_unconfigured_board_never_claims_verified(monkeypatch):
    class Source:
        def __init__(self, **kwargs):
            raise AssertionError("must not be invoked")

    monkeypatch.setitem(SOURCE_CLASSES, "ashby", Source)
    assert verify_from_config(job(), []).status == "REVIEW_REQUIRED"
    assert verify_from_config(job(), CONFIG + CONFIG).status == "REVIEW_REQUIRED"


def test_wrong_company_cannot_verify_matching_id(monkeypatch):
    class Source:
        def __init__(self, **kwargs):
            pass

        def fetch(self, company, slug):
            return [job(company="Different")]

    monkeypatch.setitem(SOURCE_CLASSES, "ashby", Source)
    assert verify_from_config(job(), CONFIG).status == "NOT_FOUND_AT_LAST_CHECK"
