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
from .database import DatabaseRepository, create_repository
from .intelligence.company import build_company_signals
from .intelligence.people import discover_public_contacts
from .models import RunStats, utc_now
from .notifications.ntfy import publish_run
from .llm.provider import create_provider
from .reporting.daily import render_jobs, write_report
from .reporting.network import render_network, write_network_report


class Orchestrator:
    def __init__(self, db_path: Path | None = None, repo: DatabaseRepository | None = None):
        default_path = db_path or os.getenv(
            "CAREERHUNTER_DB", project_path("data", "careerhunter.db")
        )
        self.repo = repo or create_repository(default_path)

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
        return stats, report_path

    def _jobs(self, stats: RunStats, dry_run: bool) -> tuple[RunStats, Path]:
        source_cfg = load_yaml("sources.yaml")
        companies = load_yaml("companies.yaml").get("companies", [])
        matcher = RuleBasedMatcher(load_yaml("profile.yaml"), load_yaml("keywords.yaml"))
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
                    found = [matcher.score(job) for job in source.fetch(company["name"], slug)]
                    jobs.extend(found)
                    if not dry_run:
                        stats.jobs_new += self.repo.upsert_jobs(found)
                        stats.jobs_closed += self.repo.mark_closed(source_name, company["name"], {j.job_id for j in found})
                    successful += 1
                except Exception as exc:
                    errors.append(f"{company['name']}/{source_name}: {exc}")
        if attempted == 0:
            raise RuntimeError('No ATS job sources configured; refusing empty success')
        if successful == 0:
            raise RuntimeError(f'All {attempted} ATS job sources failed; refusing false success')
        stats.jobs_processed = len(jobs)
        if errors:
            stats.error = f'{len(errors)}/{attempted} ATS sources failed (partial result); see report'
        if not dry_run:
            for signal in build_company_signals(jobs):
                self.repo.upsert_company_signal(signal)
        provider = create_provider()
        if provider:
            ai_matcher = AIJobMatcher(provider, load_yaml("profile.yaml"))
            candidates = sorted(
                (job for job in jobs if (job.match_score or 0) >= 65),
                key=lambda job: job.match_score or 0,
                reverse=True,
            )[:10]
            for job in candidates:
                ai_matcher.enrich(job)
            budget = getattr(provider, "budget", None)
            stats.llm_calls = budget.calls if budget else 0
            stats.llm_tokens = budget.tokens if budget else 0
            stats.llm_cost_usd = budget.cost_usd if budget else 0
        content = render_jobs(jobs, stats)
        if errors:
            content += "\n## Kaynak hataları\n\n" + "\n".join(f"- {e}" for e in errors) + "\n"
        timestamp = datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%Y%m%d-%H%M%S")
        path = project_path("reports", f"jobs-{timestamp}.md")
        return stats, write_report(path, content)

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
