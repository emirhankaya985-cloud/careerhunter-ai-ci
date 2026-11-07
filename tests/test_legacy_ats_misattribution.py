"""A verified replacement ATS must archive only provably unrelated legacy rows."""
import hashlib

from sqlalchemy import select

from careerhunter.database import DatabaseRepository, jobs
from careerhunter.models import Job, RunStats, utc_now
from careerhunter import orchestrator as orchestration


def example(ident, source, company, url):
    return Job(
        job_id=ident, source=source, company=company,
        title="Junior Python Developer", location="Istanbul",
        description="Python FastAPI role", job_url=url,
        source_url=("https://api.lever.co/v0/postings/insiderone?mode=json"
                    if source == "lever" else
                    "https://boards-api.greenhouse.io/v1/boards/peak/jobs"),
    )


def legacy_data():
    return [
        example("bi-1", "greenhouse", "Insider",
                "https://www.businessinsider.com/work-at-business-insider?gh_jid=123"),
        example("pt-1", "greenhouse", "Peak",
                "https://job-boards.greenhouse.io/peak/jobs/123"),
        example("not-legacy", "greenhouse", "Peak",
                "https://job-boards.greenhouse.io/peaklabs/jobs/321"),
        example("new-1", "lever", "Insider",
                "https://jobs.lever.co/insiderone/new-1"),
        example("new-2", "lever", "Peak",
                "https://jobs.lever.co/peakgames/new-2"),
    ]


def test_quarantine_is_precise_non_destructive_and_idempotent(tmp_path):
    repo = DatabaseRepository("sqlite:///" + str(tmp_path / "legacy.db"))
    assert repo.upsert_jobs(legacy_data()) == 5
    originals = {j.job_id: (j.first_seen_at, j.last_verified_at)
                 for j in repo.list_jobs(active_only=False, limit=20)}

    assert repo.quarantine_legacy_board_mismatch("Insider") == 1
    assert repo.quarantine_legacy_board_mismatch("Peak") == 1
    assert repo.quarantine_legacy_board_mismatch("Unknown") == 0
    assert repo.quarantine_legacy_board_mismatch("Peak") == 0

    remaining = {j.job_id for j in repo.list_jobs(active_only=True, limit=20)}
    assert remaining == {"not-legacy", "new-1", "new-2"}
    stored = {j.job_id: j for j in repo.list_jobs(active_only=False, limit=20)}
    assert len(stored) == 5
    for ident in ("bi-1", "pt-1"):
        assert stored[ident].status == "closed"
        assert (stored[ident].first_seen_at, stored[ident].last_verified_at) == originals[ident]
    with repo.engine.connect() as conn:
        rows = conn.execute(select(jobs)).mappings().all()
    for row in rows:
        assert row["content_hash"] == hashlib.sha256(
            __import__("json").dumps(
                Job.model_validate_json(row["payload"]).model_dump(mode="json"),
                sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    repo.engine.dispose()


def test_replacement_lever_success_retires_wrong_greenhouse_without_deleting(
    tmp_path, monkeypatch
):
    repo = DatabaseRepository("sqlite:///" + str(tmp_path / "collector.db"))
    legacy = legacy_data()[0]
    repo.upsert_jobs([legacy])

    class Lever:
        def __init__(self, **kwargs):
            pass

        def fetch(self, company, slug):
            assert company == "Insider" and slug == "insiderone"
            return [example("brand-new", "lever", "Insider",
                            "https://jobs.lever.co/insiderone/brand-new")]

    def yaml(name):
        return {
            "companies.yaml": {"companies": [{"name": "Insider", "lever": "insiderone"}]},
            "sources.yaml": {},
            "keywords.yaml": {"junior": ["junior"]},
        }[name]

    monkeypatch.setattr(orchestration, "SOURCE_CLASSES", {"lever": Lever})
    monkeypatch.setattr(orchestration, "load_yaml", yaml)
    monkeypatch.setattr(orchestration, "load_match_profile",
                        lambda: {"skills": ["Python"], "target_roles": ["Junior Python Developer"],
                                 "target_countries": ["Türkiye"]})
    monkeypatch.setattr(orchestration, "attest_collected", lambda job: job)
    monkeypatch.setattr(orchestration, "build_company_signals", lambda jobs: [])
    monkeypatch.setattr(orchestration, "create_provider", lambda: None)
    monkeypatch.setattr(orchestration, "project_path", lambda *parts: tmp_path / "report.md")
    monkeypatch.setattr(orchestration, "write_report", lambda path, body: path)
    worker = orchestration.Orchestrator(repo=repo)
    stats, path = worker._jobs(RunStats(slot="jobs", started_at=utc_now()), False)
    assert stats.jobs_new == 1
    assert stats.jobs_closed == 1
    assert repo.get_job("greenhouse", "bi-1").status == "closed"
    assert repo.get_job("lever", "brand-new").status == "new"
    assert len(repo.list_jobs(active_only=False, limit=20)) == 2
    repo.engine.dispose()
