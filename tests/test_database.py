import os
from datetime import timedelta

import pytest
from sqlalchemy import event

from careerhunter.database import DatabaseRepository, SQLiteRepository, import_legacy_sqlite
from careerhunter.models import CompanySignal, Contact, FollowUp, Interaction, Opportunity
from careerhunter.models import Job, RunStats, utc_now


def job(job_id="1"):
    return Job(job_id=job_id, source="greenhouse", company="Acme", title="Python Dev", job_url=f"https://boards.greenhouse.io/acme/jobs/{job_id}", source_url="https://boards-api.greenhouse.io/v1/boards/acme/jobs")


def test_dedup_and_close(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.db")
    assert repo.upsert_jobs([job()]) == 1
    assert repo.upsert_jobs([job()]) == 0
    assert len(repo.list_jobs()) == 1
    assert repo.mark_closed("greenhouse", "Acme", set()) == 1
    assert repo.list_jobs() == []
    assert repo.list_jobs(active_only=False)[0].status == "closed"


def test_recent_new_jobs_use_source_and_job_id_key(tmp_path):
    repo = SQLiteRepository(tmp_path / "recent.db")
    first = job("same")
    second = job("same")
    assert repo.upsert_jobs([first, second]) == 1
    assert repo.count_new_jobs_since(utc_now() - timedelta(hours=24)) == 1


def test_aggregate_job_counts_cover_full_table(tmp_path):
    repo = SQLiteRepository(tmp_path / "aggregate.db")
    repo.upsert_jobs([job("us-1").model_copy(update={"location": "US"})])
    row = job("tr-1").model_copy(update={"location": "Istanbul, Türkiye"})
    repo.upsert_jobs([row])
    counts = repo.aggregate_job_counts(utc_now() - timedelta(hours=24))
    assert counts["total"] == 2
    assert counts["new_24h"] == 2
    assert counts["country_us"] == 1
    assert counts["country_tr"] == 1


def test_country_new_counts_are_subset_of_totals(tmp_path):
    repo = SQLiteRepository(tmp_path / "country.db")
    item = job("country-1").model_copy(update={"location": "US"})
    repo.upsert_jobs([item])
    repo.upsert_country_assessment("greenhouse", "country-1", "United States", {
        "dimensions": {"physical_location": "mentioned", "remote_from_turkey": "unknown"}
    })
    counts = repo.aggregate_country_counts(utc_now() - timedelta(hours=24))
    assert 0 <= counts["United States"]["new_24h"] <= counts["United States"]["total"]



def test_country_scopes_use_full_database_and_same_new_subset(tmp_path):
    repo = SQLiteRepository(tmp_path / "scopes.db")
    old = utc_now() - timedelta(days=3)
    examples = [
        ("us", "US", "greenhouse", None),
        ("multi", "US / UK", "greenhouse", None),
        ("au", "Sydney, Australia", "greenhouse", None),
        ("old-us", "New York", "greenhouse", old),
        ("same", "UK", "greenhouse", None),
        ("same", "Australia", "lever", None),
        ("remote", "Remote - Worldwide", "greenhouse", None),
        ("body-only", "Remote", "greenhouse", None),
        ("tr", "Istanbul, Türkiye", "greenhouse", None),
    ]
    for identifier, location, source, seen_at in examples:
        item = job(identifier).model_copy(update={
            "source": source,
            "location": location,
            "description": "Work from USA and Türkiye" if identifier == "body-only" else "",
            "job_url": f"https://jobs.example/{source}/{identifier}",
            **({"first_seen_at": seen_at} if seen_at else {}),
        })
        repo.upsert_jobs([item])
    counts = repo.aggregate_country_counts(utc_now() - timedelta(days=1))
    assert counts == {
        "United States": {"total": 3, "new_24h": 2},
        "United Kingdom": {"total": 2, "new_24h": 2},
        "Australia": {"total": 2, "new_24h": 2},
        "Türkiye": {"total": 1, "new_24h": 1},
    }
    assert all(0 <= row["new_24h"] <= row["total"] for row in counts.values())
    assert repo.aggregate_job_counts(utc_now() - timedelta(days=1))["total"] == 9


def test_country_scopes_do_not_depend_on_persisted_assessments(tmp_path):
    repo = SQLiteRepository(tmp_path / "unassessed.db")
    repo.upsert_jobs([job("london").model_copy(update={"location": "London"})])
    assert repo.list_country_assessments() == []
    assert repo.aggregate_country_counts(utc_now() - timedelta(hours=24))[
        "United Kingdom"
    ] == {"total": 1, "new_24h": 1}


def test_large_job_upsert_uses_bounded_queries(tmp_path):
    repo = SQLiteRepository(tmp_path / "bulk.db")
    records = [job(f"bulk-{index}") for index in range(250)]
    calls = []

    def count_queries(conn, cursor, statement, parameters, context, executemany):
        calls.append(statement)

    event.listen(repo.engine, "before_cursor_execute", count_queries)
    try:
        assert repo.upsert_jobs(records) == 250
        first_queries = len(calls)
        calls.clear()
        assert repo.upsert_jobs(records) == 0
        second_queries = len(calls)
    finally:
        event.remove(repo.engine, "before_cursor_execute", count_queries)

    assert first_queries <= 6
    assert second_queries <= 6
    assert repo.aggregate_job_counts(utc_now() - timedelta(hours=24))["total"] == 250
    assert all(item.status == "seen" for item in repo.list_jobs(active_only=False, limit=250))


def test_bulk_upsert_deduplicates_scan_and_preserves_first_seen(tmp_path):
    repo = SQLiteRepository(tmp_path / "bulk-duplicate.db")
    original = job("same")
    assert repo.upsert_jobs([original]) == 1
    first = repo.list_jobs()[0].first_seen_at
    repeated = job("same")
    repeated.title = "Revised title"
    assert repo.upsert_jobs([repeated, repeated.model_copy()]) == 0
    stored = repo.list_jobs()[0]
    assert stored.title == "Revised title"
    assert stored.first_seen_at == first


def test_run_usage_is_persisted(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.db")
    stats = RunStats(slot="jobs", started_at=utc_now(), status="success", llm_calls=1, llm_tokens=123)
    repo.record_run(stats)
    row = repo.latest_run()
    assert row["llm_calls"] == 1
    assert row["llm_tokens"] == 123


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured")
def test_postgresql_batched_upsert_preserves_first_seen():
    # TEST_DATABASE_URL must be an isolated disposable test PostgreSQL database.
    repo = DatabaseRepository(os.environ["TEST_DATABASE_URL"])
    repo.clear_all()
    items = [job(f"postgres-batch-{index}") for index in range(135)]
    assert repo.upsert_jobs(items) == 135
    stored_first = {item.job_id: item.first_seen_at for item in
                    repo.list_jobs(active_only=False, limit=200)}
    assert repo.upsert_jobs(items) == 0
    stored_after = {item.job_id: item for item in
                    repo.list_jobs(active_only=False, limit=200)}
    assert len(stored_after) == 135
    assert all(row.status == "seen" for row in stored_after.values())
    assert all(row.first_seen_at == stored_first[id] for id, row in stored_after.items())


def test_independent_repository_instances_preserve_and_update_jobs(tmp_path):
    path = tmp_path / "persistent.db"
    first = SQLiteRepository(path)
    assert first.upsert_jobs([job()]) == 1

    changed = job()
    changed.title = "Python Platform Developer"
    second = SQLiteRepository(path)
    assert second.upsert_jobs([changed]) == 0
    stored = second.list_jobs()[0]
    assert stored.title == "Python Platform Developer"
    assert stored.status == "seen"


def test_legacy_sqlite_import_is_idempotent(tmp_path):
    legacy = SQLiteRepository(tmp_path / "legacy.db")
    legacy.upsert_jobs([job("legacy-1")])
    target = SQLiteRepository(tmp_path / "target.db")
    first = import_legacy_sqlite(legacy.path, target)
    second = import_legacy_sqlite(legacy.path, target)
    assert first == {"jobs_read": 1, "jobs_new": 1, "contacts_read": 0}
    assert second == {"jobs_read": 1, "jobs_new": 0, "contacts_read": 0}
    assert len(target.list_jobs()) == 1


def test_company_signal_upsert_is_deduplicated(tmp_path):
    repo = SQLiteRepository(tmp_path / "signals.db")
    signal = CompanySignal(
        company_id="acme", company="Acme", signal_type="hiring_activity",
        claim="Observed one listing", evidence_urls=[job().job_url], evidence_count=1,
    )
    repo.upsert_company_signal(signal)
    repo.upsert_company_signal(signal.model_copy(update={"claim": "Observed two listings"}))
    stored = repo.list_company_signals()
    assert len(stored) == 1
    assert stored[0].claim == "Observed two listings"


def test_crm_records_are_persistent_and_idempotent(tmp_path):
    repo = SQLiteRepository(tmp_path / "crm.db")
    opportunity = Opportunity(opportunity_id="opp-1", title="Data Intern", company="Acme")
    repo.upsert_opportunity(opportunity)
    repo.upsert_opportunity(opportunity.model_copy(update={"status": "reviewed"}))
    assert len(repo.list_opportunities()) == 1
    assert repo.list_opportunities()[0].status == "reviewed"

    interaction = Interaction(interaction_id="int-1", person_id="p-1", interaction_type="message")
    repo.record_interaction(interaction)
    repo.record_interaction(interaction)
    assert len(repo.list_interactions(person_id="p-1")) == 1

    followup = FollowUp(followup_id="fu-1", person_id="p-1", due_at=utc_now(), note="Check reply")
    repo.upsert_followup(followup)
    assert len(repo.list_followups(pending_only=True)) == 1
    assert repo.update_followup_status("fu-1", "completed").status == "completed"
    assert not repo.list_followups(pending_only=True)


def test_assessments_and_critics_are_persistent_and_idempotent(tmp_path):
    repo = SQLiteRepository(tmp_path / "evidence.db")
    payload = {"status": "needs_review", "confidence": "medium", "evidence": ["remote - us"]}
    repo.upsert_country_assessment("greenhouse", "job-1", "United States", payload)
    repo.upsert_country_assessment("greenhouse", "job-1", "United States", {**payload, "confidence": "high"})
    rows = repo.list_country_assessments("job-1")
    assert len(rows) == 1
    assert rows[0]["payload"] and "high" in rows[0]["payload"]
    repo.upsert_critic_result("p-1", {"ok": True, "issues": []})
    repo.upsert_critic_result("p-1", {"ok": False, "issues": ["too long"]})
    assert len(repo.list_critic_results()) == 1
    assert "too long" in repo.list_critic_results()[0]["payload"]


def test_contact_refresh_preserves_manual_history(tmp_path):
    repo = SQLiteRepository(tmp_path / "contacts.db")
    original = Contact(person_id="p-1", name="A", company="Acme", role="Engineer", category="employee",
                       status="contacted_manually", notes="sent email")
    repo.upsert_contact(original)
    refreshed = original.model_copy(update={"status": "research_needed", "notes": None, "role": "Senior Engineer"})
    repo.upsert_contact(refreshed)
    stored = repo.list_contacts()[0]
    assert stored.status == "contacted_manually"
    assert stored.notes == "sent email"
    assert stored.role == "Senior Engineer"


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured")
def test_postgresql_round_trip():
    repo = DatabaseRepository(os.environ["TEST_DATABASE_URL"])
    repo.clear_all()
    assert repo.upsert_jobs([job("postgres-round-trip")]) == 1
    assert repo.upsert_jobs([job("postgres-round-trip")]) == 0
    assert repo.list_jobs()[0].job_id == "postgres-round-trip"

