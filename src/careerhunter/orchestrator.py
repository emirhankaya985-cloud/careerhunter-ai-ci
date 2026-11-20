from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .agents.job_hunter import SOURCE_CLASSES
from .agents.ai_job_matcher import AIJobMatcher
from .agents.hook_writer import prepare_drafts
from .agents.job_matcher import RuleBasedMatcher
from .config import load_yaml, project_path
from .country_rotation import (
    COUNTRIES, country_batch, discovery_companies, location_countries, rotation_report,
)
from .personal_profile import load_match_profile
from .database import DatabaseRepository, create_repository
from .intelligence.company import build_company_signals
from .intelligence.people import discover_public_contacts
from .models import FollowUp, Opportunity, RunStats, utc_now
from .verification import attest_collected
from .notifications.ntfy import publish_run
from .notifications.telegram import publish_daily_digest, publish_failure
from .llm.provider import create_provider
from .reporting.daily import render_jobs, write_report
from .reporting.network import render_network, write_network_report


class Orchestrator:
    def __init__(self, db_path: Path | None = None, repo: DatabaseRepository | None = None):
        default_path = db_path or os.getenv(
            "CAREERHUNTER_DB", project_path("data", "careerhunter.db")
        )
        self.repo = repo or create_repository(default_path)
        self._telegram_candidates = []

    def run(self, slot: str, dry_run: bool = False) -> tuple[RunStats, Path | None]:
        stats = RunStats(slot=slot, started_at=utc_now())
        report_path = None
        try:
            if slot == "jobs":
                stats, report_path = self._jobs(stats, dry_run)
            elif slot == "network":
                report_path = self._network(dry_run)
            elif slot in {"future", "weekly"}:
                report_path = self._placeholder_report(slot)
            else:
                raise ValueError(f"Unknown slot: {slot}")
            stats.status = "success"
        except Exception as exc:
            stats.status = "failed"
            stats.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            stats.finished_at = utc_now()
            if not dry_run:
                self.repo.record_run(stats)
                publish_run(stats)
                if slot == "jobs" and os.getenv("TELEGRAM_DELIVERY_MODE", "render") != "github":
                    if stats.status == "success":
                        publish_daily_digest(stats, self._telegram_candidates)
                    else:
                        publish_failure(stats)
        return stats, report_path

    def _jobs(self, stats: RunStats, dry_run: bool) -> tuple[RunStats, Path]:
        source_cfg = load_yaml("sources.yaml")
        companies = load_yaml("companies.yaml").get("companies", [])
        # Existing sources remain enabled. Full snapshots preserve closure safety.
        known = {c["name"] for c in companies}
        companies = companies + [c for c in discovery_companies(stats.started_at)
                                 if c["name"] not in known]
        profile = load_match_profile()
        profile = dict(profile)
        focus = set(country_batch(stats.started_at))
        profile["target_countries"] = [COUNTRIES[code][0]
                                       for code in country_batch(stats.started_at)]
        matcher = RuleBasedMatcher(profile, load_yaml("keywords.yaml"))
        jobs = []
        errors = []
        attempted = successful = 0
        for company in companies:
            for source_name, source_cls in SOURCE_CLASSES.items():
                slug = company.get(source_name)
                if not slug:
                    continue
                attempted += 1
                source = source_cls(timeout=source_cfg.get("timeout_seconds", 20),
                                    retries=source_cfg.get("max_retries", 3),
                                    user_agent=source_cfg.get("user_agent", "CareerHunterAI/0.1"))
                try:
                    found = [matcher.score(attest_collected(job))
                             for job in source.fetch(company["name"], slug)]
                    jobs.extend(found)
                    if not dry_run:
                        stats.jobs_new += self.repo.upsert_jobs(found)
                        stats.jobs_closed += self.repo.mark_closed(
                            source_name, company["name"], {j.job_id for j in found}
                        )
                        # Official Turkey boards moved from unrelated Greenhouse
                        # tenants to Lever. Retire *only* the provably misattributed
                        # old rows and only after that replacement Lever board
                        # returned a successful source response.
                        corrected = {"Insider": "insiderone", "Peak": "peakgames"}
                        if (source_name == "lever"
                                and corrected.get(company["name"]) == slug):
                            stats.jobs_closed += self.repo.quarantine_legacy_board_mismatch(
                                company["name"]
                            )
                    successful += 1
                except Exception as exc:
                    errors.append(f"{company['name']}/{source_name}: {exc}")
        if attempted == 0:
            raise RuntimeError('No ATS job sources configured; refusing empty success')
        if successful == 0:
            raise RuntimeError(f'All {attempted} ATS job sources failed; refusing false success')
        stats.jobs_processed = len(jobs)
        if errors:
            stats.error = f'{len(errors)}/{attempted} ATS sources failed (partial result): ' + '; '.join(errors)
        if not dry_run:
            for signal in build_company_signals(jobs):
                self.repo.upsert_company_signal(signal)
        provider = create_provider()
        if provider:
            ai_matcher = AIJobMatcher(provider, profile)
            candidates = sorted(
                (job for job in jobs if (job.match_score or 0) >= 65),
                key=lambda job: job.match_score or 0,
                reverse=True,
            )[:10]
            updated = []
            for job in candidates:
                ai_matcher.enrich(job)
                if job.match_method == "llm":
                    updated.append(job)
            if not dry_run and updated:
                self.repo.update_job_scores(updated)
            budget = getattr(provider, "budget", None)
            stats.llm_calls = budget.calls if budget else 0
            stats.llm_tokens = budget.tokens if budget else 0
            stats.llm_cost_usd = budget.cost_usd if budget else 0
        archived = 0
        if not dry_run:
            archived = self._archive_remote_fit_jobs(jobs)
        # Capture only genuinely new records after database upsert mutates
        # existing jobs to "seen"; LLM may have enriched the same objects.
        if not dry_run:
            self._telegram_candidates = [job for job in jobs if job.status == "new"]
        # Focus affects the shortlist, never the full-board persistence/closure set.
        focused_jobs = [job for job in jobs
                        if location_countries(job.location) & focus
                        or (job.remote_type == "remote"
                            and not location_countries(job.location))]
        content = render_jobs(focused_jobs, stats)
        content += rotation_report(jobs, stats.started_at)
        if archived:
            content += f"\n## Otomatik arşiv\n\n- Güçlü, Türkiye'den çalışmaya uygun uzaktan eşleşme: {archived}\n"
        if errors:
            content += "\n## Kaynak hataları\n\n" + "\n".join(f"- {e}" for e in errors) + "\n"
        timestamp = datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%Y%m%d-%H%M%S")
        path = project_path("reports", f"jobs-{timestamp}.md")
        return stats, write_report(path, content)

    def _archive_remote_fit_jobs(self, jobs) -> int:
        """Save strong verified remote matches as discovered CRM opportunities."""
        from .job_quality import is_remote_fit

        try:
            minimum = max(75, min(100, int(os.getenv("TELEGRAM_MIN_SCORE", "75"))))
        except ValueError:
            minimum = 75
        saved = 0
        followup_ids = {item.followup_id for item in self.repo.list_followups(limit=10000)}
        for job in jobs:
            if not is_remote_fit(job, minimum=minimum):
                continue
            opportunity_id = f"{job.source}:{job.job_id}"
            existing = self.repo.get_opportunity(opportunity_id)
            # Preserve any human-reviewed/application state and notes.
            if existing and existing.status != "discovered":
                continue
            self.repo.upsert_opportunity(Opportunity(
                opportunity_id=opportunity_id,
                title=job.title,
                company=job.company,
                job_id=job.job_id,
                job_url=job.job_url,
                status="discovered",
                fit_score=job.match_score,
                notes=(existing.notes if existing else
                       "Otomatik arşiv: güçlü profil eşleşmeli uzaktan ilan; ülke ve çalışma izni "
                       f"koşullarını ayrıca kontrol et ({job.match_score}/100)."),
                applied_at=existing.applied_at if existing else None,
                cv_sha256=existing.cv_sha256 if existing else None,
                submission_evidence_url=(existing.submission_evidence_url if existing else None),
                updated_at=utc_now(),
            ))
            deadline_followup_id = f"application-deadline:{opportunity_id}"
            if (job.application_deadline and job.application_deadline > utc_now()
                    and deadline_followup_id not in followup_ids):
                self.repo.upsert_followup(FollowUp(
                    followup_id=deadline_followup_id,
                    opportunity_id=opportunity_id,
                    due_at=job.application_deadline,
                    note="Son başvuru günü için Telegram hatırlatması",
                ))
                followup_ids.add(deadline_followup_id)
            saved += 1
        return saved

    def _network(self, dry_run: bool) -> Path:
        companies = load_yaml("companies.yaml").get("companies", [])
        discovered, errors = discover_public_contacts(
            companies,
            timeout=10,
            retries=2,
        )
        # Persist discoveries in the same configured repository used by jobs.
        # Upsert is evidence-bound and therefore idempotent across schedules.
        if not dry_run:
            for contact in discovered:
                self.repo.upsert_contact(contact)
        contacts = self.repo.list_contacts()
        prepared = []
        for contact in contacts:
            # Never reset a human's CRM state merely because a source was
            # refreshed. Drafts are generated only for new/research-needed
            # contacts and preserve contacted/replied/follow-up states.
            prepared.append(
                prepare_drafts(contact)
                if contact.status in {"discovered", "research_needed"}
                else contact
            )
        if not dry_run:
            for contact in prepared:
                self.repo.upsert_contact(contact)
        timestamp = datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%Y%m%d-%H%M%S")
        report = render_network(prepared)
        report += f"\n## Günlük keşif özeti\n\n- Yeni kaynak keşfi: {len(discovered)}\n- Kayıtlı toplam kişi: {len(prepared)}\n"
        if errors:
            report += "\n### Kaynak sonuçları\n\n" + "\n".join(f"- {error}" for error in errors) + "\n"
        return write_network_report(
            project_path("reports", f"network-{timestamp}.md"), report
        )

    def _placeholder_report(self, slot: str) -> Path:
        timestamp = datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%Y%m%d-%H%M%S")
        content = f"# {slot.title()} Intelligence\n\nBu slot Phase 1'de güvenli iskelet olarak hazırdır; doğrulanmamış kişi veya şirket verisi üretmez.\n"
        return write_report(project_path("reports", f"{slot}-{timestamp}.md"), content)
