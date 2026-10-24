"""Deterministic, isolated end-to-end workflow proof.

This test intentionally uses a temporary SQLite database and fixture records. It
proves the product workflow without contacting real people or external APIs.
"""

from datetime import timedelta

from careerhunter.agents.hook_writer import prepare_drafts
from careerhunter.country_rules import assess_country
from careerhunter.database import SQLiteRepository
from careerhunter.intelligence.company import build_company_signals
from careerhunter.llm.fallback import critique_message
from careerhunter.models import Contact, FollowUp, Interaction, Job, Opportunity, utc_now


def test_job_to_network_to_manual_followup_is_persistent(tmp_path):
    repo = SQLiteRepository(tmp_path / "e2e.db")
    job = Job(
        job_id="fixture-ml-001",
        source="greenhouse",
        company="North Star Robotics",
        title="Junior Machine Learning Engineer",
        location="Remote - Türkiye / United States",
        description="Remote from Turkey; international contractor or EOR supported. Python and machine learning.",
        remote_type="remote",
        employment_type="contractor",
        job_url="https://jobs.example.test/north-star/fixture-ml-001",
        source_url="https://jobs.example.test/north-star",
    )

    # 1) Persist the job and prove a repeat scan is deduplicated.
    assert repo.upsert_jobs([job]) == 1
    assert repo.upsert_jobs([job]) == 0
    stored_job = repo.list_jobs()[0]
    assert stored_job.job_id == job.job_id

    # 2) Country gate is evidence-based; remote alone is not enough.
    assessment = assess_country(
        f"{job.location}. {job.description}", "Türkiye", source_url=str(job.source_url)
    )
    assert assessment.status in {"eligible", "sponsorship_or_rights_evidence"}
    assert "remote_from_turkey" in assessment.dimensions

    # 3) Derive and persist a company signal with job evidence.
    signals = build_company_signals([stored_job])
    assert {signal.signal_type for signal in signals} == {"hiring_activity", "remote_activity"}
    for signal in signals:
        repo.upsert_company_signal(signal)
    assert len(repo.list_company_signals()) == 2

    # 4) Add a sourced, public professional contact (fixture only).
    contact = Contact(
        person_id="fixture-person-001",
        name="Jordan Example",
        company=job.company,
        role="ML Engineering Lead",
        category="hiring_manager",
        primary_source_url="https://people.example.test/north-star/jordan-example",
        research_sources=["https://people.example.test/north-star/jordan-example"],
        verified_context="North Star Robotics' public machine-learning engineering work",
        research_confidence="high",
    )
    contact = prepare_drafts(contact)
    assert contact.status == "draft_ready"
    repo.upsert_contact(contact)

    # 5) Critic gates the draft; no automatic send is possible.
    critique = critique_message(
        contact.message_variant_a,
        verified_context=contact.verified_context,
        source_count=len(contact.research_sources),
    )
    assert critique["ok"] is True
    assert critique["send_allowed_automatically"] is False

    # 6) Link the job/person in CRM and record a manual send only.
    opportunity = Opportunity(
        opportunity_id="fixture-opportunity-001",
        title=job.title,
        company=job.company,
        job_id=job.job_id,
        job_url=job.job_url,
        status="reviewed",
        fit_score=88,
    )
    repo.upsert_opportunity(opportunity)
    interaction = Interaction(
        interaction_id="fixture-interaction-001",
        person_id=contact.person_id,
        interaction_type="message",
        channel="linkedin",
        direction="outbound",
        content=contact.message_variant_a,
        outcome="sent_manually_by_user",
    )
    repo.record_interaction(interaction)
    repo.update_contact_status(contact.person_id, "contacted_manually")

    # 7) Schedule and complete a follow-up without sending anything.
    followup = FollowUp(
        followup_id="fixture-followup-001",
        person_id=contact.person_id,
        opportunity_id=opportunity.opportunity_id,
        due_at=utc_now() + timedelta(days=7),
        note="Review reply and follow up manually if appropriate.",
    )
    repo.upsert_followup(followup)
    assert repo.list_followups(pending_only=True)[0].followup_id == followup.followup_id
    completed = repo.update_followup_status(followup.followup_id, "completed")
    assert completed.status == "completed"
    assert repo.list_interactions(contact.person_id)[0].outcome == "sent_manually_by_user"
