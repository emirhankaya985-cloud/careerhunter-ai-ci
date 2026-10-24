"""Run a deterministic, isolated proof of the human-in-the-loop workflow.

This is deliberately a controlled fixture, not a claim about a real vacancy.
It uses a temporary SQLite database and never contacts a person or sends a
message.  The JSON report is suitable for a CI artifact and records each gate.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from .agents.hook_writer import prepare_drafts
from .country_rules import assess_country
from .database import SQLiteRepository
from .intelligence.company import build_company_signals
from .llm.fallback import critique_message
from .models import Contact, FollowUp, Interaction, Job, Opportunity, utc_now


def run(output: Path | None = None) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="careerhunter-e2e-") as directory:
        repo = SQLiteRepository(Path(directory) / "workflow.db")
        job = Job(
            job_id="controlled-e2e-ml-001", source="greenhouse",
            company="CareerHunter Controlled Fixture",
            title="Junior Machine Learning Engineer",
            location="Remote - Türkiye / United States",
            description="Remote from Turkey; international contractor or EOR supported. Python and machine learning.",
            remote_type="remote", employment_type="contractor",
            job_url="https://example.invalid/controlled-e2e/job",
            source_url="https://example.invalid/controlled-e2e/company",
        )
        first = repo.upsert_jobs([job])
        second = repo.upsert_jobs([job])
        country = assess_country(f"{job.location}. {job.description}", "Türkiye", source_url=str(job.source_url))
        signals = build_company_signals([job])
        for signal in signals:
            repo.upsert_company_signal(signal)
        contact = prepare_drafts(Contact(
            person_id="controlled-e2e-person-001", name="Jordan Example",
            company=job.company, role="ML Engineering Lead", category="hiring_manager",
            primary_source_url="https://example.invalid/controlled-e2e/person",
            research_sources=["https://example.invalid/controlled-e2e/person"],
            verified_context="Public machine-learning work at the controlled fixture company.",
            research_confidence="high",
        ))
        repo.upsert_contact(contact)
        critique = critique_message(contact.message_variant_a, verified_context=contact.verified_context,
                                    source_count=len(contact.research_sources))
        opportunity = Opportunity(opportunity_id="controlled-e2e-opportunity-001", title=job.title,
                                  company=job.company, job_id=job.job_id, job_url=job.job_url,
                                  status="reviewed", fit_score=88)
        repo.upsert_opportunity(opportunity)
        repo.record_interaction(Interaction(
            interaction_id="controlled-e2e-interaction-001", person_id=contact.person_id,
            interaction_type="message", channel="linkedin", content=contact.message_variant_a,
            outcome="sent_manually_by_user"))
        repo.update_contact_status(contact.person_id, "contacted_manually")
        followup = FollowUp(followup_id="controlled-e2e-followup-001", person_id=contact.person_id,
                            opportunity_id=opportunity.opportunity_id, due_at=utc_now() + timedelta(days=7),
                            note="Review reply and follow up manually if appropriate.")
        repo.upsert_followup(followup)
        report = {
            "fixture": True, "external_message_sent": False,
            "gates": {"job_persisted": first == 1, "dedup_second_scan": second == 0,
                      "country_evidence": "remote_from_turkey" in country.dimensions,
                      "company_signals": len(signals), "contact_source_evidence": bool(contact.research_sources),
                      "draft_ready": contact.status == "draft_ready", "critic_ok": critique["ok"],
                      "automatic_send_blocked": critique["send_allowed_automatically"] is False,
                      "manual_interaction_recorded": len(repo.list_interactions(contact.person_id)) == 1,
                      "followup_pending": len(repo.list_followups(pending_only=True)) == 1},
            "counts": {"jobs_new_first": first, "jobs_new_second": second},
        }
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        # Windows keeps SQLite files locked until the SQLAlchemy pool is
        # explicitly disposed; dispose before TemporaryDirectory cleanup.
        repo.engine.dispose()
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reports/e2e-verification.json"))
    args = parser.parse_args()
    report = run(args.output)
    print(json.dumps(report, indent=2))
    if not all(report["gates"].values()):
        raise SystemExit("controlled e2e verification failed")


if __name__ == "__main__":
    main()
