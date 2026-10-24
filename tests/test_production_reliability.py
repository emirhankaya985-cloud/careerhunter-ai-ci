from pathlib import Path

import pytest

from careerhunter.models import RunStats, utc_now
from careerhunter.orchestrator import Orchestrator
from careerhunter.reporting.ops_summary import build_summary, notify
from careerhunter.database import SQLiteRepository


def sample_dashboard():
    return {
        "snapshot_id": "snap123", "snapshot_at": "2026-10-20T00:00:00+00:00",
        "jobs": [{"source": "alpha", "job_id": "1"}],
        "contacts": [{"message_variant_a": "manual draft"}, {}],
        "aggregates": {
            "total": 2000, "new_24h": 120,
            "countries": {
                "United States": {"total": 400, "new_24h": 60},
                "United Kingdom": {"total": 80, "new_24h": 10},
                "Australia": {"total": 40, "new_24h": 5},
                "Türkiye": {"total": 2, "new_24h": 0},
            },
        },
    }


def stages(**overrides):
    result = {"database": "success", "collection": "success",
              "network": "success", "export": "success"}
    result.update(overrides)
    return result


def test_daily_summary_uses_full_database_aggregates():
    result = build_summary(sample_dashboard(), outcomes=stages(),
                           event="schedule", sha="c0ffee")
    assert result["status"] == "success"
    assert result["total_jobs"] == 2000
    assert result["new_jobs_24h"] == 120
    assert result["displayed_jobs"] == 1
    assert result["people"] == 2 and result["drafts"] == 1
    assert result["countries"]["US"] == {"total": 400, "new_24h": 60}


def test_daily_summary_never_hides_a_failed_step():
    result = build_summary(sample_dashboard(), outcomes=stages(network="failure"),
                           event="schedule", sha="abcd")
    assert result["status"] == "failed"
    assert result["failed_stages"] == ["network"]


def test_daily_summary_missing_export_does_not_claim_zero_jobs():
    result = build_summary(None, outcomes=stages(export="failure"),
                           event="schedule", sha="abcd")
    assert result["status"] == "failed"
    assert "total_jobs" not in result


def test_daily_summary_rejects_country_new_greater_than_total():
    data = sample_dashboard()
    data["aggregates"]["countries"]["Australia"]["new_24h"] = 100
    result = build_summary(data, outcomes=stages(), event="schedule", sha="abcd")
    assert result["status"] == "failed"


def test_manual_network_slot_does_not_require_daily_network_step():
    result = build_summary(sample_dashboard(), outcomes=stages(network="skipped"),
                           event="workflow_dispatch", sha="abcd")
    assert result["status"] == "success"


def test_ntfy_report_contains_four_countries(monkeypatch):
    captured = {}
    monkeypatch.setattr("careerhunter.reporting.ops_summary.publish",
                        lambda message, **kwargs: captured.update(message=message, **kwargs) or True)
    summary = build_summary(sample_dashboard(), outcomes=stages(),
                            event="schedule", sha="abcd")
    assert notify(summary)
    assert "US: 400 toplam / 60 yeni" in captured["message"]
    assert "GB: 80 toplam / 10 yeni" in captured["message"]
    assert "AU: 40 toplam / 5 yeni" in captured["message"]
    assert "TR: 2 toplam / 0 yeni" in captured["message"]


def test_job_collection_refuses_success_when_all_sources_fail(tmp_path, monkeypatch):
    from careerhunter import orchestrator

    class UnavailableSource:
        def __init__(self, **kwargs):
            pass

        def fetch(self, company, slug):
            raise RuntimeError("ATS unavailable")

    def config(name):
        return {
            "companies.yaml": {"companies": [{"name": "Acme", "greenhouse": "acme"}]},
            "sources.yaml": {}, "profile.yaml": {}, "keywords.yaml": {},
        }[name]

    monkeypatch.setattr(orchestrator, "SOURCE_CLASSES", {"greenhouse": UnavailableSource})
    monkeypatch.setattr(orchestrator, "load_yaml", config)
    repo = SQLiteRepository(tmp_path / "test.db")
    with pytest.raises(RuntimeError, match="All 1 ATS job sources failed"):
        Orchestrator(repo=repo)._jobs(
            RunStats(slot="jobs", started_at=utc_now()), dry_run=True
        )
    assert repo.list_jobs(active_only=False) == []



def test_daily_workflow_runs_in_render_and_rejects_unauthenticated_requests():
    daily = (Path(__file__).parents[1] / ".github/workflows/daily.yml").read_text()
    runner = (Path(__file__).parents[1] /
              "src/careerhunter/render_scan_client.py").read_text()
    assert "id-token: write" in daily
    assert "DATABASE_URL" not in daily
    assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" in runner
    assert '"/internal/scan/status"' in runner
    assert '"/readyz"' in runner
    assert "Production collector returned zero jobs" in runner
    assert "sys.exit(1)" in runner
