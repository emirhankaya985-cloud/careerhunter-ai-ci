import json

from careerhunter import live_verify


def test_live_verification_is_repeatable_and_never_sends(tmp_path, monkeypatch):
    monkeypatch.setattr(live_verify, "fetch_public", lambda url: '<script type="application/ld+json">{"@type":"JobPosting","identifier":{"value":"fixture-1"},"title":"Data Engineer","hiringOrganization":{"name":"Example"},"jobLocation":"Remote - US","description":"Build reliable data pipelines and systems for customers. This full-time engineering role owns production automation, testing, documentation, and operational reliability. Remote - US."}</script>')
    monkeypatch.setattr(live_verify, "fetch_team_page", lambda url, **kwargs: "<article><h2>Kim</h2><p>Software Engineer</p></article>")
    db, out, dashboard = tmp_path / "proof.sqlite", tmp_path / "proof.json", tmp_path / "dashboard.html"
    first = live_verify.run(db_path=db, output=out, dashboard_output=dashboard,
                            job_url="https://jobs.example/1", team_url="https://example/team")
    second = live_verify.run(db_path=db, output=out, job_url="https://jobs.example/1", team_url="https://example/team")
    assert first["job"]["new_records"] == 1
    assert second["job"]["new_records"] == 0
    assert second["safety"]["automatic_send"] is False
    assert second["people_source"]["hiring_manager"] == "unknown_not_inferred"
    assert set(first["country_assessments"]) == {"United States", "United Kingdom", "Türkiye", "Australia"}
    assert first["critics"] and first["dashboard"] == str(dashboard.resolve())
    html = dashboard.read_text(encoding="utf-8")
    assert "Kim" in html and "Message critic findings" in html
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "ok"


def test_live_verification_rejects_empty_job_page(tmp_path, monkeypatch):
    monkeypatch.setattr(live_verify, "fetch_public", lambda url: "<html></html>")
    proof = live_verify.run(db_path=tmp_path / "proof.sqlite", output=tmp_path / "proof.json",
                            job_url="https://jobs.example/nope", team_url="https://example/team")
    assert proof["status"] == "error"
    assert proof["errors"]


def test_greenhouse_api_payload_is_accepted_without_jsonld(tmp_path, monkeypatch):
    payload = {
        "id": 9281,
        "title": "Data Platform Engineer",
        "company": {"name": "Example Labs"},
        "location": {"name": "Remote - United States"},
        "content": "Build and operate production data platforms with Python, SQL, testing, and observability. "
                    "Collaborate with engineers and customers on reliable systems.",
        "absolute_url": "https://boards.greenhouse.io/example/jobs/9281",
    }
    monkeypatch.setattr(live_verify, "fetch_json", lambda url: payload)
    monkeypatch.setattr(live_verify, "fetch_team_page", lambda url, **kwargs: "<article><h2>Kim</h2><p>Engineer</p></article>")
    db = tmp_path / "api.sqlite"
    proof = live_verify.run(db_path=db, output=tmp_path / "api.json",
                            job_url="https://boards-api.greenhouse.io/v1/boards/example/jobs/9281",
                            team_url="https://example.test/team")
    assert proof["status"] == "ok"
    assert proof["job"]["source_kind"] == "greenhouse_api"
    assert proof["job"]["title"] == "Data Platform Engineer"


def test_greenhouse_api_payload_rejects_missing_company(tmp_path, monkeypatch):
    monkeypatch.setattr(live_verify, "fetch_json", lambda url: {
        "id": 1, "title": "Engineer", "location": {"name": "Remote"},
        "content": "A sufficiently long description that still has no company field and must be rejected."
    })
    proof = live_verify.run(db_path=tmp_path / "bad.sqlite", output=tmp_path / "bad.json",
                            job_url="https://boards-api.greenhouse.io/v1/boards/example/jobs/1",
                            team_url="https://example.test/team")
    assert proof["status"] == "error"
    assert proof["failed_stage"] == "job_source"
