from careerhunter.sources.ashby import AshbySource
from careerhunter.sources.greenhouse import GreenhouseSource
from careerhunter.sources.lever import LeverSource


def test_greenhouse_normalizes_html_and_unknown_eligibility():
    job = GreenhouseSource.normalize("Acme", {"id": 1, "title": "Junior Python Developer", "location": {"name": "Remote"}, "content": "<p>Python &amp; SQL</p>", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "updated_at": "2026-10-01T10:00:00Z"}, "https://boards-api.greenhouse.io/v1/boards/acme/jobs")
    assert job.description == "Python & SQL"
    assert job.remote_type == "remote"
    assert job.turkey_eligibility == "unknown"


def test_lever_normalizes_milliseconds():
    job = LeverSource.normalize("Acme", {"id": "abc", "text": "Backend Engineer", "categories": {"location": "Remote", "commitment": "Full-time"}, "description": "Python", "createdAt": 1_760_000_000_000, "hostedUrl": "https://jobs.lever.co/acme/abc"}, "https://api.lever.co/v0/postings/acme?mode=json")
    assert job.job_id == "abc"
    assert job.published_at is not None
    assert job.employment_type == "Full-time"


def test_ashby_respects_remote_boolean():
    job = AshbySource.normalize("Acme", {"id": "xyz", "title": "ML Engineer", "location": "Berlin", "isRemote": True, "descriptionPlain": "Models", "jobUrl": "https://jobs.ashbyhq.com/acme/xyz", "publishedAt": "2026-10-01T10:00:00Z"}, "https://api.ashbyhq.com/posting-api/job-board/acme")
    assert job.remote_type == "remote"


def test_empty_job_lists(httpx_mock):
    httpx_mock.add_response(url="https://api.lever.co/v0/postings/empty?mode=json", json=[])
    assert LeverSource(retries=1).fetch("Empty", "empty") == []


def test_429_is_retried(httpx_mock, monkeypatch):
    monkeypatch.setattr("careerhunter.sources.base.time.sleep", lambda _: None)
    url = "https://api.lever.co/v0/postings/acme?mode=json"
    httpx_mock.add_response(url=url, status_code=429)
    httpx_mock.add_response(url=url, json=[])
    assert LeverSource(retries=2).fetch("Acme", "acme") == []


def test_500_eventually_raises(httpx_mock, monkeypatch):
    from careerhunter.sources.base import SourceError

    monkeypatch.setattr("careerhunter.sources.base.time.sleep", lambda _: None)
    url = "https://api.lever.co/v0/postings/acme?mode=json"
    httpx_mock.add_response(url=url, status_code=500)
    httpx_mock.add_response(url=url, status_code=503)
    try:
        LeverSource(retries=2).fetch("Acme", "acme")
    except SourceError as exc:
        assert "503" in str(exc)
    else:
        raise AssertionError("SourceError was not raised")

