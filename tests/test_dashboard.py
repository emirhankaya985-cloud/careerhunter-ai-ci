from pathlib import Path

from careerhunter.dashboard import DashboardFilters, _html_page, export_snapshot, snapshot
from careerhunter.database import DatabaseRepository
from careerhunter.models import CompanySignal, Contact, Job


def test_dashboard_filters_and_exports(tmp_path: Path):
    repo = DatabaseRepository(f"sqlite:///{tmp_path / 'dashboard.db'}")
    job = Job(job_id="1", source="greenhouse", company="Acme", title="Python Engineer",
              location="United States", description="Visa sponsorship available",
              remote_type="remote", job_url="https://example.com/j/1",
              source_url="https://example.com")
    repo.upsert_jobs([job])
    data = snapshot(repo, DashboardFilters(country="usa", role="python", sponsorship="yes"))
    assert len(data["jobs"]) == 1
    target = export_snapshot(data, tmp_path / "out.csv", "csv")
    assert target.read_text(encoding="utf-8").splitlines()[1].startswith("1,Acme,Python Engineer")


def test_dashboard_has_no_demo_records(tmp_path: Path):
    repo = DatabaseRepository(f"sqlite:///{tmp_path / 'empty.db'}")
    data = snapshot(repo)
    assert data["jobs"] == []
    assert data["contacts"] == []


def test_browser_dashboard_is_read_only_and_contains_sections(tmp_path: Path):
    repo = DatabaseRepository(f"sqlite:///{tmp_path / 'browser.db'}")
    data = snapshot(repo)
    html = _html_page(data)
    assert "Jobs and evidence" in html
    assert "People and source evidence" in html
    assert "Message drafts (manual sending only)" in html
    assert "Follow-ups" in html
    assert "method=\"post\"" not in html


def test_browser_dashboard_renders_real_fixture_details(tmp_path: Path):
    repo = DatabaseRepository(f"sqlite:///{tmp_path / 'fixture.db'}")
    job = Job(job_id="fixture-1", source="greenhouse", company="Northstar",
              title="Data Engineer", location="United States",
              description="Remote - US. International contractor. Salary USD 100k.",
              remote_type="remote", job_url="https://jobs.example/fixture-1",
              source_url="https://jobs.example/fixture-1")
    repo.upsert_jobs([job])
    contact = Contact(person_id="person-1", name="Jordan Lee", company="Northstar",
                      role="Engineering Manager", category="hiring_manager",
                      verified_context="Northstar public engineering article",
                      evidence_text="Public team page lists Jordan Lee as Engineering Manager.",
                      relationship_type="employee", hiring_manager_unknown=True,
                      observed_at="2026-10-19T09:00:00Z",
                      proof_artifact_url="https://jobs.example/proofs/person-1.json",
                      research_sources=["https://northstar.example/team"],
                      message_variant_a="Hi Jordan, I read the Northstar public engineering article.")
    repo.upsert_contact(contact)
    repo.upsert_company_signal(CompanySignal(company_id="northstar", company="Northstar",
        signal_type="hiring_activity", claim="Observed hiring activity", evidence_urls=["https://jobs.example/fixture-1"],
        evidence_count=1, confidence="medium"))
    html = _html_page(snapshot(repo))
    assert "United States" in html
    assert "International contractor" in html
    assert "Message critic findings" in html
    assert "Northstar public engineering article" in html
    assert "Public team page lists Jordan Lee" in html
    assert "Hiring manager" in html
    assert "https://jobs.example/proofs/person-1.json" in html
    assert "Company signals and evidence" in html
    assert "careerhunter.json" in html
    assert "careerhunter.csv" in html
